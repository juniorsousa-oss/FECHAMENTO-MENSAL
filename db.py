from __future__ import annotations

from datetime import date
import os

import requests
import streamlit as st

DEFAULT_SUPABASE_URL = "https://cuixazpxkvniqldmmnth.supabase.co"
DEFAULT_SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImN1aXhhenB4a3ZuaXFsZG1tbnRoIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODc1MTYwNTMsImV4cCI6MjEwMzA5MjA1M30.jNFaIG1FcDYnMAoVaI23UYMuRL1BpZmuqu_LPEYb88E"


def _secret(*names: str) -> str:
    for name in names:
        try:
            value = st.secrets.get(name)
            if value:
                return str(value).strip()
        except Exception:
            pass
        value = os.getenv(name)
        if value:
            return str(value).strip()
    try:
        supa = st.secrets.get("supabase", {})
        for name in names:
            for key in (name, name.lower(), name.replace("SUPABASE_", "").lower()):
                value = supa.get(key)
                if value:
                    return str(value).strip()
    except Exception:
        pass
    return ""


def supabase_url() -> str:
    return _secret("SUPABASE_URL") or DEFAULT_SUPABASE_URL


def supabase_key() -> str:
    return (
        _secret("SUPABASE_ANON_KEY", "SUPABASE_KEY", "SUPABASE_PUBLISHABLE_KEY")
        or DEFAULT_SUPABASE_ANON_KEY
    )


def configured() -> bool:
    return bool(supabase_url() and supabase_key())


def _headers(prefer: str | None = None) -> dict[str, str]:
    key = supabase_key()
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def _raise(response: requests.Response) -> None:
    if response.ok:
        return
    try:
        payload = response.json()
        message = (
            payload.get("message")
            or payload.get("error")
            or payload.get("hint")
            or str(payload)
        )
    except Exception:
        message = response.text
    raise RuntimeError(f"Supabase HTTP {response.status_code}: {message}")


def rpc(name: str, payload: dict | None = None, timeout: int = 45):
    response = requests.post(
        f"{supabase_url()}/rest/v1/rpc/{name}",
        headers=_headers(),
        json=payload or {},
        timeout=timeout,
    )
    _raise(response)
    if not response.text.strip():
        return None
    return response.json()


def load_nfs_visual_config() -> dict:
    """Lê a identidade visual efetivamente salva pelo app NFS Setta."""
    response = requests.get(
        f"{supabase_url()}/rest/v1/nf_configuracoes",
        headers=_headers(),
        params={"select": "valor", "chave": "eq.app", "limit": "1"},
        timeout=20,
    )
    _raise(response)
    rows = response.json() or []
    if not rows:
        return {}
    value = rows[0].get("valor") or {}
    return value if isinstance(value, dict) else {}


def load_config() -> dict:
    response = requests.get(
        f"{supabase_url()}/rest/v1/fm_configuracoes",
        headers=_headers(),
        params={"select": "valor", "chave": "eq.app", "limit": "1"},
        timeout=20,
    )
    _raise(response)
    rows = response.json() or []
    if not rows:
        return {}
    value = rows[0].get("valor") or {}
    return value if isinstance(value, dict) else {}


def save_config(config: dict) -> None:
    rpc(
        "fm_salvar_configuracao",
        {"p_chave": "app", "p_valor": config},
        timeout=45,
    )


def list_months() -> list[dict]:
    response = requests.get(
        f"{supabase_url()}/rest/v1/fm_fechamentos_mensais",
        headers=_headers(),
        params={"select": "*", "order": "competencia.desc"},
        timeout=30,
    )
    _raise(response)
    return response.json() or []


def get_month(competencia: date) -> dict:
    month_key = competencia.replace(day=1).isoformat()
    response = requests.get(
        f"{supabase_url()}/rest/v1/fm_fechamentos_mensais",
        headers=_headers(),
        params={
            "select": "*",
            "competencia": f"eq.{month_key}",
            "limit": "1",
        },
        timeout=20,
    )
    _raise(response)
    rows = response.json() or []
    return rows[0] if rows else {}


def save_month(data: dict) -> None:
    competencia = data["competencia"]
    if isinstance(competencia, date):
        competencia = competencia.replace(day=1).isoformat()

    payload = {
        "p_competencia": competencia,
        "p_faturamento": float(data.get("faturamento") or 0),
        "p_ei_s2": float(data.get("ei_s2") or 0),
        "p_ef_s2": float(data.get("ef_s2") or 0),
        "p_baixa_op_s2": float(data.get("baixa_op_s2") or 0),
        "p_ajustes_s2": float(data.get("ajustes_s2") or 0),
        "p_compras_s2": float(data.get("compras_s2") or 0),
        "p_transferencias_s2": float(data.get("transferencias_s2") or 0),
        "p_vendas_s2": float(data.get("vendas_s2") or 0),
        "p_ei_ep": float(data.get("ei_ep") or 0),
        "p_ef_ep": float(data.get("ef_ep") or 0),
        "p_ei_pa": float(data.get("ei_pa") or 0),
        "p_ef_pa": float(data.get("ef_pa") or 0),
        "p_observacao": str(data.get("observacao") or ""),
    }
    rpc("fm_salvar_fechamento", payload, timeout=45)
