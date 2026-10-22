"""Avaliação sequencial e exclusiva das condições/subgrupos do KARDEX.

Uma linha só pode receber a primeira condição verdadeira. As regras
operam somente em uma cópia da visão, sem modificar registros persistidos.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pandas as pd

PRODUCTION = "PRODUÇÃO INTERNA"
CONSUMPTION = "CONSUMO OP"
MANAGEMENT = "ACERTO GERÊNCIAL"
CONSUMABLE = "MATERIAL DE CONSUMO"
SHEET_BAR = "ADEQUAÇÃO DE CHAPAS E BARRAS"
COST = "ADEQUAÇÃO DE CUSTO"

# Identificadores estáveis. A lista persistida define a ordem e pode ser
# reorganizada em Cadastros. Deletar uma regra remove sua aplicação.
TEMPLATES = [
    {"id": "kardex_cond_01_producao_interna", "regra": "producao_interna", "nome": PRODUCTION,
     "criterio": "TES 020/040 + tipo PA ou PI"},
    {"id": "kardex_cond_02_consumo_op", "regra": "consumo_op", "nome": CONSUMPTION,
     "criterio": "Qualquer saída registrada com AE vinculada a OP"},
    {"id": "kardex_cond_03_acerto_gerencial", "regra": "acerto_gerencial", "nome": MANAGEMENT,
     "criterio": "TES 520/550 + CC informado diferente de 600307"},
    {"id": "kardex_cond_04_material_consumo", "regra": "material_consumo", "nome": CONSUMABLE,
     "criterio": "TES 520/550 + tipo II"},
    {"id": "kardex_cond_05_chapas_barras", "regra": "chapas_barras", "nome": SHEET_BAR,
     "criterio": "TES 020/030/040/520/540/550 + CC 600307 + código no cadastro de chapa/barra"},
    {"id": "kardex_cond_06_adequacao_custo", "regra": "adequacao_custo", "nome": COST,
     "criterio": "TES 030/540"},
]
TEMPLATE_BY_ID = {item["id"]: item for item in TEMPLATES}
TEMPLATE_BY_RULE = {item["regra"]: item for item in TEMPLATES}


@lru_cache(maxsize=1)
def sheet_bar_codes() -> frozenset[str]:
    source = Path(__file__).parent / "config" / "kardex_chapas_barras_codigos.json"
    payload = json.loads(source.read_text("utf-8"))
    return frozenset(payload["codigos"])


def classify(frame: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Aplica a fila aos lançamentos, assegurando exclusão entre subgrupos."""
    import kardex_group_config as groups

    out = frame.copy()
    owners = groups.group_owner(config)
    if out.empty:
        out["grupo_usuario"] = pd.Series(dtype="object")
        out["subgrupo_usuario"] = pd.Series(dtype="object")
        out["condicao_id"] = pd.Series(dtype="object")
        out["condicao_ordem"] = pd.Series(dtype="Int64")
        return out
    group = out["tes"].map(owners).fillna(groups.UNASSIGNED)
    out["grupo_usuario"] = group
    out["subgrupo_usuario"] = group.copy()
    out["condicao_id"] = ""
    out["condicao_ordem"] = pd.Series(pd.NA, index=out.index, dtype="Int64")

    tes = out["tes"].astype(str)
    kind = out["tipo"].fillna("").astype(str).str.strip().str.upper()
    cc = out["cc_identificado"].fillna("").astype(str).str.strip()
    cc = cc.str.lstrip("0").replace("", "0")
    cc_provided = out["cc_identificado"].fillna("").astype(str).str.strip().ne("")
    op = out["op_identificada"].fillna("").astype(str).str.strip().ne("")
    # Uma saída só é considerada existente quando quantidade OU valor sai.
    outgoing = (
        pd.to_numeric(out["qtd_saida"], errors="coerce").fillna(0).ne(0)
        | pd.to_numeric(out["valor_saida"], errors="coerce").fillna(0).ne(0)
    )
    matches = {
        "producao_interna": tes.isin(["020", "040"]) & kind.isin(["PA", "PI"]),
        "consumo_op": outgoing & op,
        "acerto_gerencial": tes.isin(["520", "550"]) & cc_provided & cc.ne("600307"),
        "material_consumo": tes.isin(["520", "550"]) & kind.eq("II"),
        "chapas_barras": tes.isin(["020", "030", "040", "520", "540", "550"])
        & cc_provided & cc.eq("600307") & out["codigo"].isin(sheet_bar_codes()),
        "adequacao_custo": tes.isin(["030", "540"]),
    }

    pending = pd.Series(True, index=out.index)
    for priority, item in enumerate(config.get("condicoes", []), 1):
        rule = TEMPLATE_BY_RULE.get(item.get("regra", ""))
        if rule is None:
            continue  # Condições sem critério programado não classificam.
        mask = matches[rule["regra"]] & pending
        if not mask.any():
            continue
        out.loc[mask, "subgrupo_usuario"] = rule["nome"]
        out.loc[mask, "condicao_id"] = item["id"]
        out.loc[mask, "condicao_ordem"] = priority
        pending &= ~mask
    return out
