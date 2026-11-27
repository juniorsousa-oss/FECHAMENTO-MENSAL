"""Read-only transfer of compact OPS/KARDEX sources; historical commit stays explicit."""
from __future__ import annotations

import hashlib
import streamlit as st
import central_fechamento_data as central
import movements as mv
import ops_lot_source as ops

KARDEX_KEYS = ("kardex_s2", "kardex_ep", "kardex_e2")
SOURCE_KEYS = ("ops", *KARDEX_KEYS)
LABELS = {"ops": "OPS", "kardex_s2": "KARDEX S2",
          "kardex_ep": "KARDEX EP", "kardex_e2": "KARDEX E2"}


@st.cache_data(show_spinner=False, ttl=35, max_entries=2)
def feed_state():
    raw = central.api_call("bundle_state", {
        "source_keys": list(SOURCE_KEYS), "derived_keys": []
    }, timeout=20).get("data") or {}
    normal = central.api_call("source_normalized_status", {
        "keys": list(SOURCE_KEYS)
    }, timeout=20).get("data") or []
    sync = {r["source_key"]: r for r in central._consumer_status_rows()}
    norms = {r["source_key"]: r for r in normal}
    state = {}
    for r in raw.get("sources") or []:
        key = r["source_key"]
        if key not in SOURCE_KEYS:
            continue
        n = norms.get(key) or {}
        current = (bool(r.get("available")) and bool(n.get("available"))
                   and not n.get("stale")
                   and int(n.get("source_version") or 0) == int(r.get("version") or 0)
                   and n.get("profile") == "CLOSING_XML_VALUES_V1")
        last = sync.get(key) or {}
        version = central.source_token(r)
        applied = (current and last.get("version_token") == version
                   and last.get("status") == "ATUALIZADO")
        status = ("APLICADO" if applied else "PRONTO PARA CONFERÊNCIA" if current
                  else "AGUARDANDO NORMALIZAÇÃO" if r.get("available") else "SEM CARGA")
        if current and last.get("version_token") == version and last.get("status") == "ERRO":
            status = "ERRO"
        state[key] = {"meta": r, "token": version, "current": current,
                      "applied": applied, "status": status, "sync": last}
    return state


def state_or_empty():
    try:
        return feed_state()
    except Exception as exc:
        st.warning("CENTRAL INDISPONÍVEL · " + str(exc))
        return {}


def describe(key, entry):
    meta = entry.get("meta") or {}
    return (f"{LABELS[key]} · {entry.get('status', 'SEM CARGA')} · "
            f"V{meta.get('version') or 0} · {central.format_dt(meta.get('last_update_at'))}")


@st.cache_data(show_spinner=False, max_entries=5)
def load_parsed(key, token):
    if key not in SOURCE_KEYS:
        raise ValueError("Fonte desconhecida.")
    pack, meta = central.download_normalized_source(key)
    current = f"v{int(meta.get('source_version') or 0)}|{meta.get('last_update_at') or ''}"
    if current != token or pack.get("source_key") != key:
        raise ValueError("A versão da Central mudou. Atualize a tela.")
    name = str(pack.get("file_name") or meta.get("last_file_name") or "")
    if key == "ops":
        parsed = ops.parse(b"", name, source_pack=pack)
    else:
        parsed = mv.parse_report(b"", name, source_pack=pack)
        expected = key.removeprefix("kardex_").upper()
        if {r["armazem"] for r in parsed["rows"]} != {expected}:
            raise ValueError("O armazém do relatório não corresponde à fonte " + LABELS[key])
    return parsed


def verify_current(key, token):
    # Uncached verification immediately before the historical write.
    rows = central.api_call("source_normalized_status", {"keys": [key]}, timeout=20).get("data") or []
    current = central.api_call("bundle_state", {"source_keys": [key], "derived_keys": []},
                               timeout=20).get("data") or {}
    row = next((r for r in current.get("sources") or [] if r.get("source_key") == key), {})
    norm = next((r for r in rows if r.get("source_key") == key), {})
    if (central.source_token(row) != token or not norm.get("available")
            or norm.get("stale") or norm.get("profile") != "CLOSING_XML_VALUES_V1"
            or int(norm.get("source_version") or 0) != int(row.get("version") or 0)):
        raise ValueError("A fonte " + LABELS[key] + " mudou. Reabra a prévia antes de confirmar.")


def mark_applied(key, entry, rows):
    central.commit_source_sync(key, entry["token"], entry["meta"].get("last_update_at"),
                               rows, status="ATUALIZADO")
    feed_state.clear()


def mark_error(key, entry, exc):
    try:
        central.commit_source_sync(key, entry["token"], entry["meta"].get("last_update_at"),
                                   0, status="ERRO", error_message=str(exc)[:1000])
    except Exception:
        pass
    feed_state.clear()
