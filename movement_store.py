"""Append-only KARDEX imports in the application's existing Supabase store."""
from __future__ import annotations

import re

import requests

import inventory_db as db
from movements import pack_import, unpack_import

PREFIX = "fm_movimentacoes_import_v1_"


def _key(digest: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError("Identificador de importação inválido.")
    return PREFIX + digest


def list_imports() -> list[dict]:
    result, offset = [], 0
    while True:
        response = requests.get(
            f"{db.supabase_url()}/rest/v1/fm_configuracoes", headers=db._headers(),
            params={"select": "chave,meta:valor->meta,atualizado_em", "chave": f"like.{PREFIX}*",
                    "order": "atualizado_em.asc,chave.asc", "limit": "1000", "offset": str(offset)}, timeout=30,
        )
        db._raise(response)
        page = response.json() or []
        result.extend(page)
        if len(page) < 1000:
            return result
        offset += 1000


def load_import(key: str) -> dict:
    if not key.startswith(PREFIX) or _key(key[len(PREFIX):]) != key:
        raise ValueError("Chave de histórico inválida.")
    response = requests.get(
        f"{db.supabase_url()}/rest/v1/fm_configuracoes", headers=db._headers(),
        params={"select": "valor", "chave": f"eq.{key}", "limit": "1"}, timeout=90,
    )
    db._raise(response)
    rows = response.json() or []
    if not rows:
        raise RuntimeError("Importação histórica não encontrada.")
    return unpack_import(rows[0]["valor"])


def save_import(parsed: dict, known: list[dict] | None = None) -> dict:
    digest = parsed["meta"]["sha256"]
    key = _key(digest)
    existing = known if known is not None else list_imports()
    if any(item["chave"] == key for item in existing):
        return {"saved": False, "key": key, "meta": parsed["meta"]}
    payload = pack_import(parsed)
    db.rpc("fm_salvar_configuracao", {"p_chave": key, "p_valor": payload}, timeout=120)
    # Verify the committed import before reporting success; exact file hashes make retries idempotent.
    stored = load_import(key)
    if stored["meta"]["sha256"] != digest or len(stored["rows"]) != len(parsed["rows"]):
        raise RuntimeError("A importação foi enviada, mas a conferência dos registros não corresponde ao arquivo.")
    return {"saved": True, "key": key, "meta": stored["meta"]}
