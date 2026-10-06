import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import routes
import spotify_service as spotify


def recent_track(track_id, played_at):
    return {"track": {"id": track_id, "name": "Song " + track_id, "type": "track", "duration_ms": 180000,
                      "artists": [{"id": "artist", "name": "Artist"}], "album": {"images": []}}, "played_at": played_at}


class SpotifyOriginTests(unittest.TestCase):
    def test_callback_uses_only_allowlisted_origins(self):
        with patch.dict("os.environ", {"LIFEY_PUBLIC_ORIGIN": "https://lifey.jeremymarino.com"}):
            self.assertEqual(spotify.callback_origin("localhost:4173"), spotify.LOCAL_ORIGIN)
            self.assertEqual(spotify.callback_origin("lifey.jeremymarino.com"), "https://lifey.jeremymarino.com")
            with self.assertRaises(spotify.SpotifyError):
                spotify.callback_origin("other.example.com")

    def test_public_post_requires_exact_origin_or_referer(self):
        with patch.dict("os.environ", {"LIFEY_PUBLIC_ORIGIN": "https://lifey.jeremymarino.com"}):
            base = {"Host": "lifey.jeremymarino.com"}
            self.assertFalse(routes.request_allowed(base, ("127.0.0.1", 5000), "/api/spotify/config", "POST"))
            self.assertFalse(routes.request_allowed({**base, "Origin": "http://lifey.jeremymarino.com"}, ("127.0.0.1", 5000), "/api/spotify/config", "POST"))
            self.assertTrue(routes.request_allowed({**base, "Referer": "https://lifey.jeremymarino.com/settings"}, ("127.0.0.1", 5000), "/api/spotify/config", "POST"))


class SpotifyAuthTests(unittest.TestCase):
    def setUp(self):
        spotify.PENDING.clear()
        spotify.ACCESS.clear()

    def test_pkce_state_and_callback_address(self):
        with patch.object(spotify, "config", return_value={"spotifyClientId": "client"}), patch.dict("os.environ", {"LIFEY_PUBLIC_ORIGIN": "https://lifey.jeremymarino.com"}):
            url = spotify.auth_url("lifey.jeremymarino.com")
            params = parse_qs(urlparse(url).query)
            state = params["state"][0]
            self.assertEqual(params["redirect_uri"], ["https://lifey.jeremymarino.com/api/spotify/auth/callback"])
            with self.assertRaises(spotify.SpotifyError):
                spotify.finish_auth({"state": [state], "code": ["code"]}, "localhost:4173")
            self.assertNotIn(state, spotify.PENDING)

    def test_keychain_failure_does_not_connect(self):
        with patch.object(spotify, "config", return_value={"spotifyClientId": "client"}), patch.object(spotify, "_token_request", return_value={"access_token": "access", "refresh_token": "refresh", "expires_in": 3600}), patch.object(spotify, "_request", return_value=(200, {"id": "person"}, {})), patch.object(spotify, "save_config", side_effect=ValueError("Keychain failed")):
            state = parse_qs(urlparse(spotify.auth_url("localhost:4173")).query)["state"][0]
            with self.assertRaisesRegex(ValueError, "Keychain"):
                spotify.finish_auth({"state": [state], "code": ["code"]}, "127.0.0.1:4173")
            self.assertFalse(spotify.ACCESS)

    def test_refresh_and_retry_after_401(self):
        with patch.object(spotify, "config", return_value={"spotifyClientId": "client", "spotifyRefreshToken": "refresh"}), patch.object(spotify, "_token_request", side_effect=[{"access_token": "first", "expires_in": 3600}, {"access_token": "second", "expires_in": 3600}]), patch.object(spotify, "_request", side_effect=[(401, {}, {}), (200, {"id": "person"}, {})]) as request:
            self.assertEqual(spotify._api("/me"), {"id": "person"})
            self.assertEqual(request.call_args_list[-1].kwargs["token"], "second")

    def test_invalid_refresh_clears_saved_authorization(self):
        with patch.object(spotify, "config", return_value={"spotifyClientId": "client", "spotifyRefreshToken": "refresh"}), patch.object(spotify, "_token_request", side_effect=spotify.SpotifyError("expired", 401, "expired")), patch.object(spotify, "save_config") as save:
            with self.assertRaises(spotify.SpotifyError):
                spotify._access_token()
            save.assert_called_once_with({"spotifyRefreshToken": ""})

    def test_forbidden_and_rate_limit_have_distinct_status(self):
        forbidden = spotify._failure(403, {}, {})
        limited = spotify._failure(429, {}, {"Retry-After": "10"})
        self.assertEqual((forbidden.status, forbidden.kind), (403, "forbidden"))
        self.assertEqual((limited.status, limited.kind), (429, "rate_limited"))
        self.assertGreater(spotify.RUNTIME["retryAt"], 0)
        spotify.RUNTIME["retryAt"] = 0


class SpotifyHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "spotify-history.json"
        patcher = patch.object(spotify, "HISTORY_PATH", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)
        spotify.RUNTIME.update(activeAt=0, retryAt=0, syncError="", playbackError="")

    def test_backfill_deduplicates_and_shared_summary_counts_completed_plays(self):
        now = dt.datetime.now(dt.timezone.utc)
        latest = recent_track("one", (now - dt.timedelta(minutes=5)).isoformat())
        older = recent_track("two", (now - dt.timedelta(minutes=15)).isoformat())
        with patch.object(spotify, "config", return_value={"spotifyClientId": "client", "spotifyRefreshToken": "refresh"}), patch.object(spotify, "_api", side_effect=[{"items": [latest]}, {"items": [older]}]):
            result = spotify.sync_recent(force=True)
            self.assertEqual(result["added"], 2)
        with patch.object(spotify, "config", return_value={"spotifyClientId": "client", "spotifyRefreshToken": "refresh"}):
            summary = spotify.summary("today")
        self.assertEqual(summary["stats"]["playCount"], 2)
        self.assertEqual(summary["stats"]["minutes"], 6)
        self.assertTrue(summary["backfillComplete"])
        self.assertEqual(len(spotify._read_history()["plays"]), 2)

    def test_migration_excludes_live_capture_and_clear_blocks_old_plays(self):
        played = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)).isoformat()
        source = {"trackId": "one", "title": "Song", "playedAt": played, "durationMs": 180000,
                  "artists": [{"id": "artist", "name": "Artist"}], "source": "recently-played"}
        live = {**source, "source": "currently-playing", "trackId": "live"}
        self.assertEqual(spotify.import_legacy([source, live])["imported"], 1)
        self.assertEqual(spotify.import_legacy([source])["imported"], 0)
        spotify.clear_history()
        self.assertEqual(spotify.import_legacy([source])["imported"], 0)
        self.assertEqual(spotify._read_history()["plays"], [])

    def test_gap_after_more_than_one_page_is_resumed(self):
        now = dt.datetime.now(dt.timezone.utc)
        previous = recent_track("previous", (now - dt.timedelta(hours=3)).isoformat())
        spotify._write_history({"plays": [], "latestPlay": previous["played_at"], "backfillComplete": True})
        newest = [recent_track(str(index), (now - dt.timedelta(minutes=index + 1)).isoformat()) for index in range(50)]
        middle = [recent_track("middle-" + str(index), (now - dt.timedelta(minutes=index + 51)).isoformat()) for index in range(50)]
        with patch.object(spotify, "config", return_value={"spotifyClientId": "client", "spotifyRefreshToken": "refresh"}), patch.object(spotify, "_api", side_effect=[{"items": newest}, {"items": middle}, {"items": [previous]}]):
            spotify.sync_recent(force=True)
        history = spotify._read_history()
        self.assertEqual(len(history["plays"]), 101)
        self.assertFalse(history.get("catchupBefore"))
        self.assertFalse(spotify.summary("today")["historyGap"])

    def test_unavailable_gap_is_reported(self):
        now = dt.datetime.now(dt.timezone.utc)
        previous = (now - dt.timedelta(days=3)).isoformat()
        spotify._write_history({"plays": [], "latestPlay": previous, "backfillComplete": True})
        latest = recent_track("new", (now - dt.timedelta(minutes=5)).isoformat())
        missing = recent_track("older", (now - dt.timedelta(hours=1)).isoformat())
        with patch.object(spotify, "config", return_value={"spotifyClientId": "client", "spotifyRefreshToken": "refresh"}), patch.object(spotify, "_api", side_effect=[{"items": [latest]}, {"items": [missing], "next": None}]):
            spotify.sync_recent(force=True)
        with patch.object(spotify, "config", return_value={"spotifyClientId": "client", "spotifyRefreshToken": "refresh"}):
            summary = spotify.summary("today")
        self.assertTrue(summary["historyGapUnrecoverable"])


if __name__ == "__main__":
    unittest.main()
