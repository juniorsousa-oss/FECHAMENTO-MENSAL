from __future__ import annotations

import base64
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import requests

import inventory_db as db

CONSUMER_KEY = "fechamento_mensal"
TZ = ZoneInfo("America/Sao_Paulo")
SESSION = requests.Session()
SESSION.headers.update({"Connection": "keep-alive"})


def _headers() -> dict[str, str]:
    key = db.supabase_key()
    return {
        "Authorization": f"Bearer {key}",
        "apikey": key,
        "Content-Type": "application/json",
    }


def api_call(action: str, payload: dict | None = None, timeout: int = 45) -> dict:
    response = SESSION.post(
        f"{db.supabase_url().rstrip('/')}/functions/v1/setta-data-api",
        headers=_headers(),
        json={"action": action, "payload": payload or {}},
        timeout=timeout,
    )
    try:
        data = response.json()
    except Exception:
        data = {"ok": False, "error": response.text or f"HTTP {response.status_code}"}
    if not response.ok or not data.get("ok"):
        raise RuntimeError(data.get("error") or f"HTTP {response.status_code}")
    return data


def source_state() -> dict:
    payload = api_call(
        "bundle_state",
        {"source_keys": ["analitico"], "derived_keys": []},
        timeout=30,
    ).get("data") or {}
    rows = payload.get("sources") or []
    for row in rows:
        if isinstance(row, dict) and str(row.get("source_key")) == "analitico":
            return row
    return {}


def source_token(meta: dict) -> str:
    return f"v{int(meta.get('version') or 0)}|{meta.get('last_update_at') or ''}"


def download_analitico() -> tuple[bytes, dict]:
    meta = api_call(
        "source_download",
        {"source_key": "analitico"},
        timeout=30,
    ).get("data") or {}
    signed_url = str(meta.get("signed_url") or "")
    if not signed_url:
        raise RuntimeError("ANALÍTICO sem URL de leitura.")
    response = SESSION.get(signed_url, timeout=120)
    response.raise_for_status()
    return response.content, meta


def load_visual_config() -> dict:
    row = api_call(
        "visual_get",
        {"app_key": "setta_global"},
        timeout=30,
    ).get("data") or {}
    return {
        "logo_data": row.get("logo_data") or "",
        "logo_mime": row.get("logo_mime") or "image/png",
        "favicon_data": row.get("favicon_data") or "",
        "favicon_mime": row.get("favicon_mime") or "image/png",
    }


def favicon_bytes(config: dict | None = None) -> bytes:
    cfg = config or load_visual_config()
    data = str(cfg.get("favicon_data") or "").strip()
    if not data:
        return b""
    try:
        return base64.b64decode(data, validate=True)
    except Exception:
        return b""


def sync_state() -> dict:
    rows = api_call(
        "consumer_sync_status",
        {"consumer_key": CONSUMER_KEY},
        timeout=30,
    ).get("data") or []
    for row in rows:
        if isinstance(row, dict) and str(row.get("source_key")) == "analitico":
            return row
    return {}


def commit_sync(
    version_token: str,
    source_updated_at: Any,
    rows_count: int,
    *,
    status: str = "ATUALIZADO",
    error_message: str | None = None,
) -> dict:
    return api_call(
        "consumer_sync_commit",
        {
            "consumer_key": CONSUMER_KEY,
            "source_key": "analitico",
            "version_token": version_token,
            "source_updated_at": source_updated_at,
            "rows_count": int(rows_count or 0),
            "status": status,
            "error_message": error_message,
        },
        timeout=30,
    ).get("data") or {}


def format_dt(value: Any) -> str:
    if not value:
        return "—"
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        return dt.astimezone(TZ).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return str(value)
