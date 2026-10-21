"""Persistent KARDEX revisions; monthly replacement is atomic within each saved file."""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import requests

import inventory_db as db
import kardex_history as history
from movements import pack_import, unpack_import

PREFIX = "fm_movimentacoes_import_v1_"
HTTP = requests.Session()  # reaproveita conexões nas consultas do registro


def _key(digest: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError("Identificador de importação inválido.")
    return PREFIX + digest


def list_imports() -> list[dict]:
    result, offset = [], 0
    while True:
        response = HTTP.get(
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


@lru_cache(maxsize=48)
def load_import(key: str) -> dict:
    if not key.startswith(PREFIX) or _key(key[len(PREFIX):]) != key:
        raise ValueError("Chave de histórico inválida.")
    response = HTTP.get(
        f"{db.supabase_url()}/rest/v1/fm_configuracoes", headers=db._headers(),
        params={"select": "valor,atualizado_em", "chave": f"eq.{key}", "limit": "1"}, timeout=90,
    )
    db._raise(response)
    rows = response.json() or []
    if not rows:
        raise RuntimeError("Importação histórica não encontrada.")
    imported = unpack_import(rows[0]["valor"])
    imported.update(_key=key, _imported_at=str(rows[0].get("atualizado_em") or ""))
    return imported


def load_history(entries: list[dict]) -> list[dict]:
    """Read active payloads; superseded versions need only their saved metadata."""
    ordered = sorted(entries, key=lambda item: str(item.get("atualizado_em") or ""))
    owners = {}
    for item in ordered:
        meta = item.get("meta") or {}
        if meta.get("politica") == history.POLICY:
            for scope in history.validate_scopes(meta.get("escopos") or []):
                owners[scope["competencia"], scope["armazem"]] = item["chave"]
    active = []
    for item in ordered:
        meta = item.get("meta") or {}
        inactive = meta.get("politica") == history.POLICY and all(
            owners[scope["competencia"], scope["armazem"]] != item["chave"] for scope in meta["escopos"])
        if not inactive:
            active.append(item["chave"])

    # Ler arquivos KARDEX em paralelo reduz a soma da latência por armazém.
    url, key = db.supabase_url(), db.supabase_key()
    if len(active) > 1:
        with ThreadPoolExecutor(max_workers=min(4, len(active))) as pool:
            loaded = list(pool.map(
                lambda item_key: db.read_with_connection(lambda: load_import(item_key), url, key),
                active,
            ))
    else:
        loaded = [load_import(item_key) for item_key in active]

    by_key = dict(zip(active, loaded))
    packs = []
    for item in ordered:
        meta = item.get("meta") or {}
        imported = dict(by_key[item["chave"]]) if item["chave"] in by_key else {"meta": meta, "rows": []}
        imported.update(_key=item["chave"], _imported_at=str(item.get("atualizado_em") or ""))
        packs.append(imported)
    return packs


def save_import(parsed: dict, known: list[dict] | None = None) -> dict:
    digest = parsed["meta"]["sha256"]
    key = _key(parsed["meta"].get("import_id") or digest)
    existing = known if known is not None else list_imports()
    if parsed["meta"].get("politica") == history.POLICY:
        scopes = history.import_scopes(parsed)
        owners = {}
        for item in existing:
            meta = item.get("meta") or {}
            if meta.get("politica") == history.POLICY:
                for scope in history.validate_scopes(meta.get("escopos") or []):
                    owners[scope["competencia"], scope["armazem"]] = item["chave"]
        already_active = all(owners.get((s["competencia"], s["armazem"])) == key for s in scopes)
    else:
        already_active = any(item["chave"] == key for item in existing)
    if already_active:
        return {"saved": False, "key": key, "meta": parsed["meta"], "reactivated": False}
    reactivated = any(item["chave"] == key for item in existing)
    payload = pack_import(parsed)
    db.rpc("fm_salvar_configuracao", {"p_chave": key, "p_valor": payload}, timeout=120)
    # A verificação após gravação precisa reler a versão persistida.
    load_import.cache_clear()
    # Verify the committed import before reporting success; exact file hashes make retries idempotent.
    stored = load_import(key)
    if stored["meta"] != payload["meta"] or pack_import(stored)["payload"] != payload["payload"]:
        raise RuntimeError("A importação foi enviada, mas a conferência dos registros não corresponde ao arquivo.")
    return {"saved": True, "key": key, "meta": stored["meta"], "reactivated": reactivated}
