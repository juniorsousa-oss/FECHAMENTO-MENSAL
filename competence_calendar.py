"""Competências selecionáveis, independentes da gravação do fechamento.

O mês em andamento deve continuar acessível mesmo quando a fotografia
contábil ainda não foi persistida em fm_importacoes.
"""
from __future__ import annotations

from datetime import date


def selectable_months(
    imported_months: list[date],
    live_month: date,
    closing_month: date,
    *,
    first_month: date = date(2026, 1, 1),
) -> list[date]:
    """Retorna meses contínuos para operação, sem criar fechamentos fictícios."""
    first = date(first_month.year, first_month.month, 1)
    candidates = [live_month, closing_month, *imported_months]
    last = max(date(value.year, value.month, 1) for value in candidates)
    months: list[date] = []
    cursor = first
    while cursor <= last:
        months.append(cursor)
        cursor = (
            date(cursor.year + 1, 1, 1)
            if cursor.month == 12
            else date(cursor.year, cursor.month + 1, 1)
        )
    return months
