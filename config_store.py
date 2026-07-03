from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent
LEGACY_CONFIG = ROOT / ".local-dashboard.json"
CONFIG = Path.home() / "Library" / "Application Support" / "Lifey" / "profile.json"
SECRET_FIELDS = {"notionToken", "traccarToken", "googlePlacesKey", "lifeyLocationToken", "googleRefreshToken", "googleClientSecret"}
KEYCHAIN_SERVICE = "Lifey"
PROFILE_PREFERENCE_FIELDS = {"appearance", "visibility", "taskDisplay", "contentDisplay", "heroMetricOrder", "heroMetricVisibility", "cardOrder", "integrations", "habitSettings"}
PROFILE_SECRET_KEYS = {"token", "accessToken", "refreshToken", "notionToken", "traccarToken", "googlePlacesKey", "lifeyLocationToken", "googleClientSecret", "clientSecret", "password", "secret"}


def keychain_get(name: str) -> str:
    try:
        result = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", name, "-w"], capture_output=True, timeout=3, check=False)
        if result.returncode != 0:
            return ""
        raw = result.stdout.rstrip(b"\r\n")
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("latin-1")
    except (OSError, subprocess.SubprocessError):
        return ""


def keychain_set(name: str, value: str) -> bool:
    try:
        result = subprocess.run(["security", "add-generic-password", "-U", "-s", KEYCHAIN_SERVICE, "-a", name, "-w", value], capture_output=True, text=True, timeout=3, check=False)
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def keychain_delete(name: str) -> bool:
    try:
        subprocess.run(["security", "delete-generic-password", "-s", KEYCHAIN_SERVICE, "-a", name], capture_output=True, text=True, timeout=3, check=False)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def config() -> dict:
    try:
        settings = json.loads((CONFIG if CONFIG.exists() else LEGACY_CONFIG).read_text())
    except (OSError, json.JSONDecodeError):
        settings = {}
    for key in SECRET_FIELDS:
        secret = keychain_get(key)
        if secret:
            settings[key] = secret
    return settings


def save_config(values: dict) -> None:
    migrating_legacy = not CONFIG.exists() and LEGACY_CONFIG.exists()
    current = config()
    current.update(values)
    persisted = dict(current)
    for key in SECRET_FIELDS:
        value = str(current.get(key) or "")
        if key in values and not value:
            keychain_delete(key)
            persisted.pop(key, None)
        elif value:
            if not keychain_set(key, value):
                raise ValueError(f"Could not store {key} in the macOS Keychain. Nothing was saved.")
            persisted.pop(key, None)
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(persisted, indent=2))
    if migrating_legacy:
        try:
            legacy = json.loads(LEGACY_CONFIG.read_text())
            for key in SECRET_FIELDS:
                if keychain_get(key):
                    legacy.pop(key, None)
            LEGACY_CONFIG.write_text(json.dumps(legacy, indent=2))
        except (OSError, json.JSONDecodeError):
            pass


def strip_profile_secrets(value):
    if isinstance(value, dict):
        return {key: strip_profile_secrets(item) for key, item in value.items() if key not in PROFILE_SECRET_KEYS}
    if isinstance(value, list):
        return [strip_profile_secrets(item) for item in value]
    return value


def safe_profile_preferences(settings: dict) -> dict:
    preferences = settings.get("profilePreferences", {})
    if not isinstance(preferences, dict):
        preferences = {}
    clean = {key: preferences[key] for key in PROFILE_PREFERENCE_FIELDS if key in preferences}
    integrations = strip_profile_secrets(dict(clean.get("integrations", {}))) if isinstance(clean.get("integrations"), dict) else {}
    if settings.get("notionParentId"):
        notion = dict(integrations.get("notion", {})) if isinstance(integrations.get("notion"), dict) else {}
        notion.setdefault("database", settings.get("notionParentId", ""))
        notion.setdefault("dataSourceId", settings.get("notionDataSourceId", ""))
        notion.setdefault("property", settings.get("notionTitleProperty", "Name"))
        integrations["notion"] = strip_profile_secrets(notion)
    if settings.get("traccarServer") or settings.get("traccarDeviceId"):
        traccar = dict(integrations.get("traccar", {})) if isinstance(integrations.get("traccar"), dict) else {}
        traccar.setdefault("server", settings.get("traccarServer", ""))
        traccar.setdefault("deviceId", settings.get("traccarDeviceId", ""))
        integrations["traccar"] = strip_profile_secrets(traccar)
    if settings.get("googleClientId") or settings.get("googleCalendarId"):
        google = dict(integrations.get("google", {})) if isinstance(integrations.get("google"), dict) else {}
        google.setdefault("clientId", settings.get("googleClientId", ""))
        google.setdefault("calendar", settings.get("googleCalendarId", "primary"))
        integrations["google"] = strip_profile_secrets(google)
    if settings.get("gmailQuery"):
        gmail = dict(integrations.get("gmail", {})) if isinstance(integrations.get("gmail"), dict) else {}
        gmail.setdefault("query", settings.get("gmailQuery", ""))
        integrations["gmail"] = strip_profile_secrets(gmail)
    if integrations:
        clean["integrations"] = integrations
    return strip_profile_secrets(clean)
