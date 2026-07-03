from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import secrets
import ssl
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import quote, urlencode

from config_store import config, save_config


SSL_CONTEXT = ssl.create_default_context(cafile="/etc/ssl/cert.pem")
GOOGLE_SCOPES = "openid email https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/gmail.readonly"
GOOGLE_REDIRECT_URI = "http://127.0.0.1:4173/api/google/auth/callback"


def quote_path(value: str) -> str:
    return quote(value, safe="")


def base64url_bytes(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def google_oauth_status(settings: dict | None = None) -> dict:
    settings = settings or config()
    return {
        "configured": bool(google_client_id(settings)),
        "hasClientSecret": bool(google_client_secret(settings)),
        "connected": bool(settings.get("googleRefreshToken")),
        "email": settings.get("googleAccountEmail", ""),
        "calendar": google_calendar_id(settings),
        "gmailQuery": google_gmail_query(settings),
        "clientId": google_client_id(settings),
    }


def google_client_id(settings: dict | None = None) -> str:
    settings = settings or config()
    return str(settings.get("googleClientId") or settings.get("profilePreferences", {}).get("integrations", {}).get("google", {}).get("clientId") or "").strip()


def google_client_secret(settings: dict | None = None) -> str:
    return str((settings or config()).get("googleClientSecret", "")).strip()


def google_calendar_id(settings: dict | None = None) -> str:
    settings = settings or config()
    return str(settings.get("googleCalendarId") or settings.get("profilePreferences", {}).get("integrations", {}).get("google", {}).get("calendar") or "primary").strip() or "primary"


def google_gmail_query(settings: dict | None = None) -> str:
    settings = settings or config()
    return str(settings.get("gmailQuery") or settings.get("profilePreferences", {}).get("integrations", {}).get("gmail", {}).get("query") or "newer_than:14d (medium OR newsletter)").strip()


def google_oauth_request(payload: dict) -> dict:
    body = urlencode(payload).encode()
    req = urlrequest.Request("https://oauth2.googleapis.com/token", data=body, method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urlrequest.urlopen(req, context=SSL_CONTEXT, timeout=12) as response:
            return json.loads(response.read())
    except urlerror.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise ValueError(f"Google OAuth failed ({error.code}): {detail}")


def google_api_request(method: str, url: str, token: str, payload: dict | None = None) -> dict:
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    req = urlrequest.Request(url, data=body, method=method, headers=headers)
    try:
        with urlrequest.urlopen(req, context=SSL_CONTEXT, timeout=15) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except urlerror.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        if error.code == 401:
            raise ValueError("Google authorization expired. Reconnect Google on this Mac.")
        raise ValueError(f"Google API failed ({error.code}): {detail}")


def google_access_token() -> str:
    settings = config()
    client_id = google_client_id(settings)
    refresh_token = str(settings.get("googleRefreshToken", "")).strip()
    if not client_id:
        raise ValueError("Add a Google Desktop OAuth Client ID first.")
    if not refresh_token:
        raise ValueError("Connect Google on this Mac first.")
    payload = {"client_id": client_id, "refresh_token": refresh_token, "grant_type": "refresh_token"}
    if google_client_secret(settings):
        payload["client_secret"] = google_client_secret(settings)
    token = google_oauth_request(payload)
    access_token = token.get("access_token")
    if not access_token:
        raise ValueError("Google did not return an access token. Reconnect Google on this Mac.")
    return access_token


def google_auth_url() -> str:
    settings = config()
    client_id = google_client_id(settings)
    if not client_id:
        raise ValueError("Add a Google Desktop OAuth Client ID first.")
    if not google_client_secret(settings):
        raise ValueError("Add and save the Google Desktop OAuth Client Secret first.")
    verifier = base64url_bytes(secrets.token_bytes(64))
    challenge = base64url_bytes(hashlib.sha256(verifier.encode()).digest())
    state = secrets.token_urlsafe(24)
    save_config({"googleOAuthState": state, "googleCodeVerifier": verifier, "googleRedirectUri": GOOGLE_REDIRECT_URI})
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "client_id": client_id,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": GOOGLE_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })


def google_finish_auth(query: dict[str, list[str]]) -> str:
    settings = config()
    if query.get("error"):
        raise ValueError(f"Google authorization failed: {query.get('error', ['unknown'])[0]}")
    state = query.get("state", [""])[0]
    code = query.get("code", [""])[0]
    if not state or not secrets.compare_digest(state, str(settings.get("googleOAuthState", ""))):
        save_config({"googleOAuthState": "", "googleCodeVerifier": ""})
        raise ValueError("Google authorization state did not match. That usually means this was an old Google tab or Lifey was restarted mid-login. Start the connection again from Lifey.")
    if not code:
        raise ValueError("Google did not return an authorization code.")
    payload = {
        "client_id": google_client_id(settings),
        "code": code,
        "code_verifier": str(settings.get("googleCodeVerifier", "")),
        "redirect_uri": str(settings.get("googleRedirectUri") or GOOGLE_REDIRECT_URI),
        "grant_type": "authorization_code",
    }
    if google_client_secret(settings):
        payload["client_secret"] = google_client_secret(settings)
    token = google_oauth_request(payload)
    refresh_token = token.get("refresh_token") or settings.get("googleRefreshToken")
    if not refresh_token:
        raise ValueError("Google did not return a refresh token. Reconnect and approve offline access.")
    access_token = token.get("access_token")
    email = ""
    if access_token:
        try:
            email = google_api_request("GET", "https://openidconnect.googleapis.com/v1/userinfo", access_token).get("email", "")
        except ValueError:
            email = ""
    save_config({"googleRefreshToken": refresh_token, "googleAccountEmail": email, "googleOAuthState": "", "googleCodeVerifier": "", "googleRedirectUri": GOOGLE_REDIRECT_URI})
    return email


def google_calendar_today() -> dict:
    settings = config()
    token = google_access_token()
    start = dt.datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + dt.timedelta(days=1)
    query = urlencode({"singleEvents": "true", "orderBy": "startTime", "timeMin": start.isoformat(), "timeMax": end.isoformat()})
    return google_api_request("GET", f"https://www.googleapis.com/calendar/v3/calendars/{quote_path(google_calendar_id(settings))}/events?{query}", token)


def google_calendar_create(body: dict) -> dict:
    token = google_access_token()
    return google_api_request("POST", f"https://www.googleapis.com/calendar/v3/calendars/{quote_path(google_calendar_id())}/events", token, body)


def google_calendar_update(event_id: str, body: dict) -> dict:
    token = google_access_token()
    return google_api_request("PATCH", f"https://www.googleapis.com/calendar/v3/calendars/{quote_path(google_calendar_id())}/events/{quote_path(event_id)}", token, body)


def google_calendar_delete(event_id: str) -> dict:
    token = google_access_token()
    return google_api_request("DELETE", f"https://www.googleapis.com/calendar/v3/calendars/{quote_path(google_calendar_id())}/events/{quote_path(event_id)}", token)


def google_gmail_suggestions() -> dict:
    token = google_access_token()
    result = google_api_request("GET", f"https://gmail.googleapis.com/gmail/v1/users/me/messages?{urlencode({'q': google_gmail_query(), 'maxResults': '6'})}", token)
    messages = []
    for item in result.get("messages", [])[:6]:
        message_id = item.get("id", "")
        if not message_id:
            continue
        detail = google_api_request("GET", f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{quote_path(message_id)}?format=metadata&metadataHeaders=Subject&metadataHeaders=From", token)
        headers = {header.get("name"): header.get("value", "") for header in detail.get("payload", {}).get("headers", [])}
        messages.append({"id": message_id, "subject": headers.get("Subject", "(No subject)"), "from": headers.get("From", "Gmail"), "snippet": detail.get("snippet", "")})
    return {"messages": messages}
