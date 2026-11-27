"""Competências selecionáveis, independentes da gravação do fechamento.

O mês em andamento deve continuar acessível mesmo quando a fotografia
contábil ainda não foi persistida em fm_importacoes.
"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo


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


def default_analysis_month(requested: str, options: list[date], live_month: date) -> date:
    """Honor a valid explicit historical link; otherwise keep the live month."""
    try:
        parsed = date.fromisoformat(requested.strip() + "-01") if len(requested.strip()) == 7 else None
    except (AttributeError, ValueError):
        parsed = None
    return parsed if parsed in options else live_month


def latest_closed_month(saved_keys: set[str], live_month: date) -> date | None:
    """Find the newest persisted historical month without inferring a close."""
    months = []
    for key in saved_keys:
        try:
            month = date.fromisoformat(key[:10]).replace(day=1)
        except (TypeError, ValueError):
            continue
        if month < live_month:
            months.append(month)
    return max(months, default=None)

def snapshot_is_current(meta: dict, live_month: date) -> bool:
    """A Central snapshot from a previous month cannot stand in for the live month."""
    try:
        timestamp = datetime.fromisoformat(str(meta.get("last_update_at") or "").replace("Z", "+00:00"))
    except ValueError:
        return False
    local_tz = ZoneInfo("America/Sao_Paulo")
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=local_tz)
    return timestamp.astimezone(local_tz).date().replace(day=1) == live_month
