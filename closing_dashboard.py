"""Read-only presentation rules for Dashboard's distinct stock periods."""


def read_quality_rows(info, analysed_month, live_month, selected_context, central_context, historical_reader):
    """Look up errors in the same source as the displayed balance."""
    if info.get("manual_snapshot"):
        return list(selected_context.get("errors") or [])
    if info.get("preview") and analysed_month == live_month:
        return list(central_context.get("errors") or [])
    return list(historical_reader(analysed_month) or [])


def closing_status(*, saved, available, errors):
    if saved:
        return "Já encerrada"
    if not available:
        return "Sem base para fechar"
    if errors:
        return "Bloqueada por pendências"
    return "Pronta para conferência"
