"""Configuração gerencial KARDEX separada dos lançamentos históricos.

Grupos usam associação exclusiva de TES. Condições executáveis classificam
subgrupos em fila, sem modificar registros nem valores físicos.
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
    from kardex_conditions import TEMPLATES
    return {"versao": 3, "grupos": [], "condicoes": [
        {"id": item["id"], "nome": item["nome"], "regra": item["regra"]}
        for item in TEMPLATES
    ]}


def _migrate_conditions(data: dict) -> dict:
    """Adiciona novas regras apenas uma vez sem modificar grupos nem condições excluídas.

    V1 -> V2: seis condições iniciais. V2 -> V3: quatro condições
    complementares na ordem definida. Versões V3 não são ressemeadas.
    """
    from kardex_conditions import TEMPLATES
    version = int(data.get("versao") or 1)
    if version >= 3:
        return data
    upgraded = copy.deepcopy(data)
    if version < 2:
        legacy = list(upgraded.get("condicoes") or [])
        known_names = {t["nome"].casefold() for t in TEMPLATES}
        original = [
            t for t in TEMPLATES
            if t["regra"] in (
                "producao_interna", "consumo_op", "acerto_gerencial",
                "material_consumo", "chapas_barras", "adequacao_custo"
            )
        ]
        upgraded["condicoes"] = [
            {"id":t["id"], "nome":t["nome"], "regra":t["regra"]}
            for t in original
        ] + [
            item for item in legacy
            if isinstance(item, dict)
            and str(item.get("nome") or "").casefold() not in known_names
        ]
    current = upgraded.get("condicoes") or []
    present = {x.get("id") for x in current if isinstance(x, dict)}
    additions = {t["regra"]:t for t in TEMPLATES if t["id"] not in present}
    for name, anchor in (
        ("consumo_epi", "consumo_op"),
        ("tc_tp_consumo", "consumo_epi"),
    ):
        template = additions.get(name)
        if not template:
            continue
        anchor_index = next(
            (i for i,x in enumerate(current) if x.get("regra") == anchor),
            None
        )
        insert_at = anchor_index+1 if anchor_index is not None else 0
        current.insert(insert_at, {
            "id":template["id"], "nome":template["nome"], "regra":template["regra"]
        })
    for name in ("ajuste_estoque", "retorno_producao"):
        template = additions.get(name)
        if template:
            current.append({
                "id":template["id"], "nome":template["nome"], "regra":template["regra"]
            })
    upgraded["condicoes"] = current
    upgraded["versao"] = 3
    return upgraded

def normalize_tes(value: object) -> str:
    code = str(value or "").strip()
    return code.zfill(3) if re.fullmatch(r"\d{1,3}", code) else ""

def validated(data: dict, known_tes: set[str] | None = None) -> dict:
    if not isinstance(data, dict):
        raise ValueError("Configuração de grupos inválida.")
    output = _migrate_conditions(copy.deepcopy(data))
    output.setdefault("grupos", [])
    output.setdefault("condicoes", [])
    output["versao"] = 3
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
    from kardex_conditions import TEMPLATE_BY_ID, TEMPLATE_BY_RULE
    condition_names = {}
    rule_names = set()
    for condition in output["condicoes"]:
        if not isinstance(condition, dict):
            raise ValueError("Condição inválida.")
        ident = str(condition.get("id") or "")
        title = str(condition.get("nome") or "").strip()
        if not ident or ident in ids or not 1 <= len(title) <= 120:
            raise ValueError("Identificador ou nome da condição inválido.")
        rule_id = str(condition.get("regra") or "")
        existing = condition_names.get(title.casefold())
        # MATERIAL DE CONSUMO possui duas verificações sequenciais, com
        # identificadores distintos, mas o mesmo subgrupo de destino.
        permitted_pair = {"tc_tp_consumo", "material_consumo"}
        if existing is not None and {existing, rule_id} != permitted_pair:
            raise ValueError("Já existe uma condição com esse nome.")
        if rule_id:
            template = TEMPLATE_BY_RULE.get(rule_id)
            if template is None or template["id"] != ident or template["nome"] != title:
                raise ValueError("Condição automática com regra ou identificador inválido.")
            if rule_id in rule_names:
                raise ValueError("Regra executável cadastrada mais de uma vez.")
            rule_names.add(rule_id)
        ids.add(ident); condition_names[title.casefold()] = rule_id or ident; condition["nome"] = title
    return {"versao": 3, "grupos": output["grupos"], "condicoes": output["condicoes"]}

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

def add_predefined_condition(data: dict, template_id: str, *, known_tes: set[str]) -> dict:
    """Reativa uma regra anteriormente excluída; mantém a prioridade da fila atual."""
    from kardex_conditions import TEMPLATE_BY_ID
    cfg = validated(data, known_tes)
    template = TEMPLATE_BY_ID.get(template_id)
    if template is None:
        raise ValueError("Regra predefinida desconhecida.")
    if any(item["id"] == template_id for item in cfg["condicoes"]):
        raise ValueError("Condição já cadastrada.")
    cfg["condicoes"].append({
        "id": template_id, "nome": template["nome"], "regra": template["regra"]
    })
    return validated(cfg, known_tes)


def move_condition(data: dict, ident: str, direction: int, *, known_tes: set[str]) -> dict:
    cfg = validated(data, known_tes)
    if direction not in (-1, 1):
        raise ValueError("Direção da prioridade inválida.")
    positions = [i for i, condition in enumerate(cfg["condicoes"])
                 if condition["id"] == ident]
    if not positions:
        raise ValueError("Condição não encontrada.")
    current = positions[0]
    destination = current + direction
    if 0 <= destination < len(cfg["condicoes"]):
        cfg["condicoes"][current], cfg["condicoes"][destination] = (
            cfg["condicoes"][destination], cfg["condicoes"][current]
        )
    return validated(cfg, known_tes)


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
    payload = records[0]["valor"] if records else empty()
    data = validated(payload)
    if records and int(payload.get("versao") or 1) < 3:
        # Migração única até V3; excluir regras depois não as recria.
        db.rpc("fm_salvar_configuracao", {"p_chave": CONFIG_KEY, "p_valor": data}, timeout=45)
    return data

def save(data: dict, *, known_tes: set[str]) -> dict:
    payload = validated(data, known_tes)
    db.rpc("fm_salvar_configuracao", {"p_chave":CONFIG_KEY, "p_valor":payload}, timeout=45)
    # Confirma leitura persistida antes de anunciar sucesso.
    persisted = load()
    if validated(persisted, known_tes) != payload:
        raise RuntimeError("Configuração não confirmada após gravação.")
    return persisted
