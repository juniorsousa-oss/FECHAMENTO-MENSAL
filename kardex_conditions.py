"""Avaliação sequencial e exclusiva das condições/subgrupos do KARDEX.

Uma linha só pode receber a primeira condição verdadeira. As regras
operam somente em uma cópia da visão, sem modificar registros persistidos.
"""
from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

import pandas as pd

PRODUCTION = "PRODUÇÃO INTERNA"
CONSUMPTION = "CONSUMO OP"
MANAGEMENT = "ACERTO GERÊNCIAL"
CONSUMABLE = "MATERIAL DE CONSUMO"
SHEET_BAR = "ADEQUAÇÃO DE CHAPAS E BARRAS"
COST = "ADEQUAÇÃO DE CUSTO"
EPI = "CONSUMO DE EPI"
STOCK_ADJUSTMENT = "AJUSTE DE ESTOQUE"
PRODUCTION_RETURN = "RETORNO DE PRODUÇÃO"

# Identificadores estáveis. A lista persistida define a ordem e pode ser
# reorganizada em Cadastros. Deletar uma regra remove sua aplicação.
TEMPLATES = [
    {"id": "kardex_cond_01_producao_interna", "regra": "producao_interna", "nome": PRODUCTION,
     "criterio": "TES 020/040 + tipo PA ou PI"},
    {"id": "kardex_cond_02_consumo_op", "regra": "consumo_op", "nome": CONSUMPTION,
     "criterio": "Qualquer saída com OP identificada na AE"},
    {"id": "kardex_cond_07_consumo_epi", "regra": "consumo_epi", "nome": EPI,
     "criterio": "TES 520/540 + CF 601401"},
    {"id": "kardex_cond_08_tc_tp_consumo", "regra": "tc_tp_consumo", "nome": CONSUMABLE,
     "criterio": "TES 520 + identificação explícita de MATERIAL USADO TC/TP (tipo considerado II para análise)"},
    {"id": "kardex_cond_03_acerto_gerencial", "regra": "acerto_gerencial", "nome": MANAGEMENT,
     "criterio": "TES 520/550 + CC informado diferente de 600307"},
    {"id": "kardex_cond_04_material_consumo", "regra": "material_consumo", "nome": CONSUMABLE,
     "criterio": "TES 520/550 + tipo II"},
    {"id": "kardex_cond_05_chapas_barras", "regra": "chapas_barras", "nome": SHEET_BAR,
     "criterio": "TES 020/030/040/520/540/550 + CC 600307 + material de chapa/barra"},
    {"id": "kardex_cond_06_adequacao_custo", "regra": "adequacao_custo", "nome": COST,
     "criterio": "TES 030/540 (quando não houver condição anterior)"},
    {"id": "kardex_cond_09_ajuste_estoque", "regra": "ajuste_estoque", "nome": STOCK_ADJUSTMENT,
     "criterio": "TES 020/520, grupo FLUXO DE ESTOQUE e sem condição anterior"},
    {"id": "kardex_cond_10_retorno_producao", "regra": "retorno_producao", "nome": PRODUCTION_RETURN,
     "criterio": "TES 040, grupo FLUXO DE ESTOQUE e sem condição anterior"},
]

TEMPLATE_BY_ID = {item["id"]: item for item in TEMPLATES}
TEMPLATE_BY_RULE = {item["regra"]: item for item in TEMPLATES}


@lru_cache(maxsize=1)
def sheet_bar_codes() -> frozenset[str]:
    source = Path(__file__).parent / "config" / "kardex_chapas_barras_codigos.json"
    payload = json.loads(source.read_text("utf-8"))
    return frozenset(payload["codigos"])


def _normalize_text(value) -> str:
    raw = unicodedata.normalize("NFKD", str(value or "").upper())
    return re.sub(r"[^A-Z0-9]+", " ", "".join(ch for ch in raw if not unicodedata.combining(ch))).strip()


def _tc_tp_designation(frame: pd.DataFrame) -> pd.Series:
    """Somente indicação explícita de 'MATERIAL USADO TC TP'; não inferir de 'TC' ou 'TP' soltos.

    Pode estar no grupo/categoria ou na descrição original do material.
    """
    expressions = []
    for key in ("grupo", "descricao"):
        if key not in frame.columns:
            continue
        text = frame[key].fillna("").astype(str).map(_normalize_text)
        expressions.append(text.str.contains(r"\bMATERIAL(?:\s+USADO)?\s+TC\s+TP\b", regex=True))
    if not expressions:
        return pd.Series(False, index=frame.index)
    result = expressions[0]
    for expression in expressions[1:]:
        result = result | expression
    return result


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
        out["tipo_analise"] = pd.Series(dtype="object")
        return out
    group = out["tes"].map(owners).fillna(groups.UNASSIGNED)
    out["grupo_usuario"] = group
    out["subgrupo_usuario"] = group.copy()
    out["condicao_id"] = ""
    out["condicao_ordem"] = pd.Series(pd.NA, index=out.index, dtype="Int64")

    tes = out["tes"].astype(str)
    kind = out["tipo"].fillna("").astype(str).str.strip().str.upper()
    tc_tp = tes.eq("520") & _tc_tp_designation(out)
    # Tipo para análise, mantendo a classificação original do KARDEX íntegra.
    out["tipo_analise"] = kind.where(~tc_tp, "II")
    cc = out["cc_identificado"].fillna("").astype(str).str.strip()
    cc = cc.str.lstrip("0").replace("", "0")
    cc_provided = out["cc_identificado"].fillna("").astype(str).str.strip().ne("")
    op = out["op_identificada"].fillna("").astype(str).str.strip().ne("")
    # Uma saída só é considerada existente quando quantidade OU valor sai.
    outgoing = (
        pd.to_numeric(out["qtd_saida"], errors="coerce").fillna(0).ne(0)
        | pd.to_numeric(out["valor_saida"], errors="coerce").fillna(0).ne(0)
    )
    cf = out.get("cf", pd.Series("", index=out.index)).fillna("").astype(str).str.replace(r"[^0-9]", "", regex=True)
    matches = {
        "producao_interna": tes.isin(["020", "040"]) & kind.isin(["PA", "PI"]),
        "consumo_op": outgoing & op,
        "consumo_epi": tes.isin(["520", "540"]) & cf.eq("601401"),
        "tc_tp_consumo": tc_tp,
        "acerto_gerencial": tes.isin(["520", "550"]) & cc_provided & cc.ne("600307"),
        "material_consumo": tes.isin(["520", "550"]) & kind.eq("II"),
        "chapas_barras": tes.isin(["020", "030", "040", "520", "540", "550"])
        & cc_provided & cc.eq("600307") & out["codigo"].isin(sheet_bar_codes()),
        "adequacao_custo": tes.isin(["030", "540"]),
        "ajuste_estoque": tes.isin(["020", "520"]) & group.eq("FLUXO DE ESTOQUE"),
        "retorno_producao": tes.eq("040") & group.eq("FLUXO DE ESTOQUE"),
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
