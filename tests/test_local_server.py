import io
import json
import tempfile
import unittest
from http import HTTPStatus
from pathlib import Path
from unittest.mock import patch

import config_store
import local_server
import routes


def handler_for(path="/api/obsidian/status", host="127.0.0.1:4173", origin="", client="127.0.0.1"):
    handler = object.__new__(local_server.Handler)
    handler.path = path
    handler.client_address = (client, 49152)
    handler.headers = {"Host": host}
    if origin:
        handler.headers["Origin"] = origin
    return handler


class RequestGuardTests(unittest.TestCase):
    def test_same_origin_api_request_is_allowed(self):
        handler = handler_for(
            host="192.168.1.20:4173",
            origin="http://192.168.1.20:4173",
            client="192.168.1.50",
        )

        self.assertTrue(handler.request_allowed("/api/obsidian/status"))

    def test_cross_origin_api_request_is_blocked(self):
        handler = handler_for(
            host="192.168.1.20:4173",
            origin="https://example.test",
            client="192.168.1.50",
        )

        self.assertFalse(handler.request_allowed("/api/obsidian/status"))

    def test_extension_origin_is_limited_to_youtube_activity(self):
        handler = handler_for(origin="moz-extension://abc123")

        self.assertTrue(handler.request_allowed("/api/activity/youtube"))
        self.assertFalse(handler.request_allowed("/api/obsidian/task"))


class JsonBoundaryTests(unittest.TestCase):
    def test_read_json_requires_object_body(self):
        handler = handler_for()
        body = json.dumps(["not", "an", "object"]).encode()
        handler.headers["Content-Length"] = str(len(body))
        handler.rfile = io.BytesIO(body)

        with self.assertRaisesRegex(ValueError, "JSON object"):
            handler.read_json()

    def test_read_json_rejects_oversized_body(self):
        handler = handler_for()
        handler.headers["Content-Length"] = str(routes.MAX_JSON_BODY_BYTES + 1)
        handler.rfile = io.BytesIO(b"{}")

        with self.assertRaisesRegex(ValueError, "too large"):
            handler.read_json()


class RouteRegistryTests(unittest.TestCase):
    def test_api_routes_have_explicit_groups(self):
        grouped = local_server.API_ROUTES.groups()

        self.assertIn("/api/obsidian/status", [route.path for route in grouped["obsidian"]])
        self.assertIn("/api/google/calendar/today", [route.path for route in grouped["google"]])
        self.assertIn("/api/location/mobile/ingest", [route.path for route in grouped["location"]])

    def test_mobile_ingest_skips_browser_origin_guard_but_reads_json(self):
        route = local_server.API_ROUTES.get("POST", "/api/location/mobile/ingest")

        self.assertIsNotNone(route)
        self.assertFalse(route.auth_required)
        self.assertTrue(route.reads_json)

    def test_route_registry_rejects_duplicates(self):
        registry = routes.RouteRegistry()
        registry.add("GET", "/api/example", "example", "handle_example")

        with self.assertRaisesRegex(ValueError, "Duplicate route"):
            registry.add("GET", "/api/example", "example", "handle_example_again")

    def test_api_error_keeps_status_and_legacy_error_payload(self):
        error = routes.api_error("Nope.", HTTPStatus.CONFLICT)

        self.assertEqual(error.message, "Nope.")
        self.assertEqual(error.status, HTTPStatus.CONFLICT)


class RequestSchemaTests(unittest.TestCase):
    def test_validate_rejects_bad_task_line_before_handler(self):
        with self.assertRaisesRegex(routes.ApiError, "line"):
            routes.validate_json_body("/api/obsidian/task", {"line": "nope", "text": "Task"})

    def test_validate_rejects_unknown_habit_state(self):
        with self.assertRaisesRegex(routes.ApiError, "completed"):
            routes.validate_json_body("/api/habits/state", {"line": 1, "habit": "Walk", "state": "maybe"})

    def test_validate_accepts_mobile_location_batch_shape(self):
        routes.validate_json_body("/api/location/mobile/ingest", {"samples": [{"id": "1"}]})

    def test_validate_rejects_oversized_mobile_location_batch(self):
        with self.assertRaisesRegex(routes.ApiError, "too many"):
            routes.validate_json_body("/api/location/mobile/ingest", {"samples": [{}] * 501})


class ConfigTests(unittest.TestCase):
    def test_save_config_does_not_persist_secret_when_keychain_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "profile.json"
            with patch.object(config_store, "CONFIG", config_path), \
                 patch.object(config_store, "config", return_value={}), \
                 patch.object(config_store, "keychain_set", return_value=False):
                with self.assertRaisesRegex(ValueError, "Keychain"):
                    config_store.save_config({"notionToken": "secret-token"})

            self.assertFalse(config_path.exists())

    def test_profile_import_strips_nested_secrets(self):
        updates = local_server.clean_profile_import({
            "profile": {
                "preferences": {
                    "integrations": {
                        "google": {"clientId": "client", "clientSecret": "secret"},
                        "spotify": {"accessToken": "token", "clientId": "spotify"},
                    }
                }
            }
        })

        integrations = updates["profilePreferences"]["integrations"]
        self.assertEqual(integrations["google"], {"clientId": "client"})
        self.assertEqual(integrations["spotify"], {"clientId": "spotify"})


class MarkdownTests(unittest.TestCase):
    def test_archive_block_replaces_only_lifey_block(self):
        original = "# Daily\n\n---\n## Lifey · Today\nold\n---\n\n## Notes\nkeep\n"
        block = local_server.archive_block(original)

        self.assertIsNotNone(block)
        self.assertIn("## Notes\nkeep", block.sub("---\n## Lifey · Today\nnew\n---", original))

    def test_insert_task_creates_tasks_section_before_habits(self):
        with tempfile.TemporaryDirectory() as tmp:
            note = Path(tmp) / "2026-07-03.md"
            note.write_text("# Day\n\n## Habits::\n- [ ] Drink water\n")

            result = local_server.insert_task_under_tasks(note, "Write tests")

            self.assertEqual(result["line"], 5)
            self.assertEqual(
                note.read_text(),
                "# Day\n\n## Tasks::\n\n- [ ] Write tests\n\n## Habits::\n- [ ] Drink water\n",
            )


if __name__ == "__main__":
    unittest.main()
