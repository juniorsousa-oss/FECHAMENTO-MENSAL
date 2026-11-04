"""Cálculo auditável de compras financeiras a partir do KARDEX ativo.

Não equipara entradas a compras: CFOPs explícitos e TES inequívocas são
considerados. Lançamentos incertos deixam a baixa pendente de revisão.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
import re

from movements import decimal, normalized

PURCHASE_CFOPS = frozenset({"1101", "1102", "2101", "2102", "3101", "3102"})
EXCLUDE_TERMS = (
    "DEVOLU", "RETORNO", "TRANSFER", "AJUSTE", "ACERTO", "ESTORNO",
    "PRODUCAO INTERNA", "RECLASSIF", "REMESSA", "CONSIGNAC",
    "BONIFICAC", "SOBRA", "INVENTARIO", "ENTRE ARMAZ",
)
PURCHASE_TERMS = ("COMPRA", "AQUISICAO", "IMPORTACAO")


def _cfop(row: dict) -> str:
    value = str(row.get("cf") or "").strip().replace(".", "")
    if re.fullmatch(r"\d{4}(?:\.0+)?", value):
        return value.split(".")[0]
    return ""


def purchase_classification(row: dict) -> str:
    """Retorna compra, nao_compra ou revisar; sem presumir por sinal da entrada."""
    tes_description = normalized(row.get("descricao_tes"))
    cfop = _cfop(row)
    if any(term in tes_description for term in EXCLUDE_TERMS):
        return "nao_compra"
    if cfop in PURCHASE_CFOPS or any(term in tes_description for term in PURCHASE_TERMS):
        return "compra"
    if cfop and cfop[0] in "123":
        return "nao_compra"
    return "revisar"


def summarize_purchases(model: dict) -> dict[str, dict]:
    """Soma compras por competência; exige cobertura dos armazéns do histórico.

    Dados de cobertura correspondem a versões vigentes por mês e armazém,
    conforme o mecanismo de substituição KARDEX existente.
    """
    coverage = model.get("coverage_metas") or []
    all_warehouses = {
        str(scope.get("armazem") or "").strip()
        for scope in coverage if scope.get("armazem")
    }
    months = defaultdict(lambda: {
        "compras": Decimal("0"),
        "sem_classificacao": Decimal("0"),
        "registros_revisar": 0,
        "armazens": set(),
    })
    for scope in coverage:
        competencia = str(scope.get("competencia") or "")[:7]
        if competencia:
            months[competencia]["armazens"].add(str(scope.get("armazem") or "").strip())
    for row in model.get("rows") or []:
        month = str(row.get("data") or "")[:7]
        if month not in months:
            continue  # sem cobertura vigente: nunca inferir um período completo
        amount = decimal(row.get("valor_entrada"))
        if amount <= 0:
            continue
        classification = purchase_classification(row)
        if classification == "compra":
            months[month]["compras"] += amount
        elif classification == "revisar":
            months[month]["sem_classificacao"] += amount
            months[month]["registros_revisar"] += 1

    result = {}
    for month, values in months.items():
        missing = sorted(all_warehouses - values["armazens"])
        pending = bool(missing or values["registros_revisar"])
        result[month] = {
            "compras": float(values["compras"]),
            "sem_classificacao": float(values["sem_classificacao"]),
            "registros_revisar": values["registros_revisar"],
            "armazens": sorted(values["armazens"]),
            "armazens_pendentes": missing,
            "status": "PENDENTE" if pending else "VALIDADO",
        }
    return result


def closing_write_off(initial: float | None, final: float | None,
                      purchase_info: dict | None) -> float | None:
    """EI - (EF - compras). Ausência de fontes não pode ser interpretada como zero."""
    if initial is None or final is None or not purchase_info:
        return None
    if purchase_info.get("status") != "VALIDADO":
        return None
    return float(initial) - (float(final) - float(purchase_info["compras"]))
