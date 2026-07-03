from __future__ import annotations

import json
import ssl
from urllib import error as urlerror
from urllib import request as urlrequest


SSL_CONTEXT = ssl.create_default_context(cafile="/etc/ssl/cert.pem")
NOTION_VERSION = "2026-03-11"


def notion_request(method: str, path: str, token: str, payload: dict | None = None) -> dict:
    body = json.dumps(payload).encode() if payload is not None else None
    req = urlrequest.Request(
        f"https://api.notion.com/v1{path}",
        data=body,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION, "Content-Type": "application/json"},
    )
    try:
        with urlrequest.urlopen(req, timeout=15, context=SSL_CONTEXT) as response:
            return json.loads(response.read())
    except urlerror.HTTPError as error:
        detail = json.loads(error.read() or b"{}").get("message", error.reason)
        raise ValueError(f"Notion: {detail}") from error


def notion_data_source(settings: dict) -> str:
    token, parent = settings.get("notionToken", ""), settings.get("notionParentId", "")
    if not token or not parent:
        raise ValueError("Configure a Notion token and database/data source ID first.")
    try:
        notion_request("GET", f"/data_sources/{parent}", token)
        return parent
    except ValueError:
        database = notion_request("GET", f"/databases/{parent}", token)
        sources = database.get("data_sources", [])
        if not sources:
            raise ValueError("That Notion database has no data source.")
        return sources[0]["id"]


def notion_title(item: dict) -> str:
    title = item.get("title") or item.get("name") or []
    if isinstance(title, str):
        return title
    return "".join(part.get("plain_text") or part.get("text", {}).get("content", "") for part in title) or "Untitled"
