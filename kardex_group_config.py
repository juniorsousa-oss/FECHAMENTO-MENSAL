"""Configuração gerencial KARDEX separada dos lançamentos históricos.

Grupos usam associação exclusiva de TES: um lançamento só pode integrar um
grupo. Condições são cadastradas para definição futura e não alteram saldos.
"""
from __future__ import annotations

import copy
import re
import uuid

import requests

import inventory_db as db

CONFIG_KEY = "fm_kardex_grupos_v1"
UNASSIGNED = "SEM GRUPO"

def empty() -> dict:
    return {"versao": 1, "grupos": [], "condicoes": []}

def normalize_tes(value: object) -> str:
    code = str(value or "").strip()
    return code.zfill(3) if re.fullmatch(r"\d{1,3}", code) else ""

def validated(data: dict, known_tes: set[str] | None = None) -> dict:
    if not isinstance(data, dict):
        raise ValueError("Configuração de grupos inválida.")
    output = copy.deepcopy(data)
    output.setdefault("grupos", [])
    output.setdefault("condicoes", [])
    output["versao"] = 1
    if not isinstance(output["grupos"], list) or not isinstance(output["condicoes"], list):
        raise ValueError("Estrutura inválida de grupos ou condições.")
    names, owners, ids = set(), {}, set()
    for group in output["grupos"]:
        if not isinstance(group, dict):
            raise ValueError("Grupo inválido.")
        ident = str(group.get("id") or "")
        name = str(group.get("nome") or "").strip()
        if not ident or ident in ids or not 1 <= len(name) <= 80 or name.upper() == UNASSIGNED:
            raise ValueError("Identificador ou nome de grupo inválido.")
        if name.casefold() in names:
            raise ValueError("Já existe um grupo com esse nome.")
        ids.add(ident); names.add(name.casefold()); group["nome"] = name
        codes = group.get("tes", [])
        if not isinstance(codes, list):
            raise ValueError("As TES do grupo precisam ser uma lista.")
        unique_codes = []
        for raw in codes:
            code = normalize_tes(raw)
            if not code or (known_tes is not None and code not in known_tes):
                raise ValueError(f"TES inválida ou não cadastrada: {raw}")
            if code in owners and owners[code] != ident:
                raise ValueError(f"TES {code} está vinculada a mais de um grupo.")
            owners[code] = ident
            if code not in unique_codes:
                unique_codes.append(code)
        group["tes"] = unique_codes
    condition_names = set()
    for condition in output["condicoes"]:
        if not isinstance(condition, dict):
            raise ValueError("Condição inválida.")
        ident = str(condition.get("id") or "")
        title = str(condition.get("nome") or "").strip()
        if not ident or ident in ids or not 1 <= len(title) <= 120:
            raise ValueError("Identificador ou nome da condição inválido.")
        if title.casefold() in condition_names:
            raise ValueError("Já existe uma condição com esse nome.")
        ids.add(ident); condition_names.add(title.casefold()); condition["nome"] = title
    return {"versao": 1, "grupos": output["grupos"], "condicoes": output["condicoes"]}

def create_group(data: dict, name: str, *, known_tes: set[str]) -> dict:
    updated = validated(data, known_tes)
    updated["grupos"].append({"id":uuid.uuid4().hex, "nome":name, "tes":[]})
    return validated(updated, known_tes)

def assign_group(data: dict, ident: str, codes: list[str], *, known_tes: set[str], name: str | None = None) -> dict:
    updated = validated(data, known_tes)
    found = next((g for g in updated["grupos"] if g["id"] == ident), None)
    if found is None:
        raise ValueError("Grupo não encontrado.")
    found["tes"] = codes
    if name is not None:
        found["nome"] = name
    return validated(updated, known_tes)

def delete_group(data: dict, ident: str, *, known_tes: set[str]) -> dict:
    updated = validated(data, known_tes)
    if not any(g["id"] == ident for g in updated["grupos"]):
        raise ValueError("Grupo não encontrado.")
    updated["grupos"] = [g for g in updated["grupos"] if g["id"] != ident]
    return validated(updated, known_tes)

def create_condition(data: dict, name: str, *, known_tes: set[str]) -> dict:
    updated = validated(data, known_tes)
    updated["condicoes"].append({"id": uuid.uuid4().hex, "nome": name})
    return validated(updated, known_tes)

def delete_condition(data: dict, ident: str, *, known_tes: set[str]) -> dict:
    updated = validated(data, known_tes)
    if not any(c["id"] == ident for c in updated["condicoes"]):
        raise ValueError("Condição não encontrada.")
    updated["condicoes"] = [c for c in updated["condicoes"] if c["id"] != ident]
    return validated(updated, known_tes)

def group_owner(data: dict) -> dict[str, str]:
    return {code: group["nome"] for group in data["grupos"] for code in group["tes"]}

def summarize(frame, data: dict):
    """Uma movimentação por grupo; SEM GRUPO recebe todas as TES não vinculadas."""
    import movements as mv
    by_code = group_owner(data)
    work = frame.copy()
    work["grupo_usuario"] = work["tes"].map(by_code).fillna(UNASSIGNED)
    summary = mv.summarize(work, ["grupo_usuario"])
    summary["tes_distintas"] = work.groupby("grupo_usuario")["tes"].nunique().reindex(summary["grupo_usuario"]).to_numpy()
    return summary

def load() -> dict:
    response = requests.get(
        f"{db.supabase_url()}/rest/v1/fm_configuracoes",
        headers=db._headers(),
        params={"select":"valor", "chave":f"eq.{CONFIG_KEY}", "limit":"1"},
        timeout=20,
    )
    db._raise(response)
    records = response.json() or []
    return validated(records[0]["valor"] if records else empty())

def save(data: dict, *, known_tes: set[str]) -> dict:
    payload = validated(data, known_tes)
    db.rpc("fm_salvar_configuracao", {"p_chave":CONFIG_KEY, "p_valor":payload}, timeout=45)
    # Confirma leitura persistida antes de anunciar sucesso.
    persisted = load()
    if validated(persisted, known_tes) != payload:
        raise RuntimeError("Configuração não confirmada após gravação.")
    return persisted
