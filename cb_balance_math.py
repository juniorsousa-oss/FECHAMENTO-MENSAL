"""Somatórios e apresentação determinística dos saldos da conferência.

Preserva os dados brutos do Analítico e a fotografia do fechamento.
Não utiliza float como acumulador para evitar diferenças no limite de
arredondamento (ex.: 5.070,093500 MT).
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Callable, Mapping, Iterable, Any


def saldo_categoria(
    rows: Iterable[Mapping[str, Any]],
    categoria: str,
    elegiveis: set[str],
    cadastro: Mapping[str, Mapping[str, Any]],
    normalizar_codigo: Callable[[Any], str],
) -> Decimal:
    """Soma os saldos positivos dos materiais confirmados da categoria."""
    total = Decimal("0")
    for row in rows:
        codigo = normalizar_codigo(row.get("codigo"))
        if codigo not in elegiveis:
            continue
        entry = cadastro.get(codigo) or {}
        if str(entry.get("categoria") or "").upper() != categoria:
            continue
        try:
            saldo = Decimal(str(row.get("saldo") or 0))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if saldo.is_finite() and saldo > 0:
            total += saldo
    return total


def numero_br(value: object, casas: int = 3) -> str:
    """Formata valores pt-BR com ROUND_HALF_UP, sem reconverter para float."""
    if value is None:
        return "—"
    try:
        number = Decimal(str(value))
        if not number.is_finite():
            return "—"
        places = max(0, min(9, int(casas)))
        rounded = number.quantize(
            Decimal("1").scaleb(-places), rounding=ROUND_HALF_UP
        )
    except (TypeError, ValueError, InvalidOperation):
        return "—"
    raw = f"{rounded:,.{places}f}"
    return raw.replace(",", "X").replace(".", ",").replace("X", ".")
