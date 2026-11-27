"""Build a read-only preview of the exact rows to be registered by Chapas."""
from __future__ import annotations

from hashlib import sha256

import pandas as pd


_EPS = 1e-9
ADJUSTMENT_COLUMNS = [
    "Categoria", "Código", "Descrição", "U.M.", "Saldo base ajuste",
    "Físico", "Diferença Qtd", "Diferença R$", "Contagem assumida zero",
]


def missing_zero_preview(reconciliation: pd.DataFrame) -> pd.DataFrame:
    """Preview what the existing zero-count rule would do for every pending row."""
    if reconciliation.empty:
        return pd.DataFrame(columns=ADJUSTMENT_COLUMNS)
    pending = reconciliation.loc[reconciliation["Status"].eq("SEM CONTAGEM")].copy()
    pending["Físico"] = 0.0
    pending["Contagem assumida zero"] = True
    pending["Diferença Qtd"] = -pd.to_numeric(
        pending["Saldo base ajuste"], errors="coerce"
    ).fillna(0.0)
    pending["Diferença R$"] = pending["Diferença Qtd"] * pd.to_numeric(
        pending["Custo unitário"], errors="coerce"
    ).fillna(0.0)
    pending["Status"] = "DIVERGÊNCIA"
    return pending


def finalization_rows(
    report_snapshot: pd.DataFrame, zero_preview: pd.DataFrame, assume_zero: bool,
) -> pd.DataFrame:
    """Keep all counted rows; infer zero only when opted in and with actual impact."""
    finalized = report_snapshot.copy()
    if not finalized.empty:
        confirmed = finalized["Status"].eq("CONFERIDO")
        finalized.loc[confirmed, ["Diferença Qtd", "Diferença R$"]] = 0.0
    if assume_zero and not zero_preview.empty:
        effective = zero_preview.loc[zero_preview["Diferença Qtd"].abs().gt(_EPS)]
        if not effective.empty:
            finalized = pd.concat([finalized, effective], ignore_index=True)
    return finalized


def effective_adjustments(snapshot: pd.DataFrame) -> pd.DataFrame:
    if snapshot.empty:
        return pd.DataFrame(columns=ADJUSTMENT_COLUMNS)
    has_qty = pd.to_numeric(snapshot["Diferença Qtd"], errors="coerce").fillna(0.0).abs().gt(_EPS)
    return snapshot.loc[has_qty].reindex(columns=ADJUSTMENT_COLUMNS)


def confirmation_key(competence: str, snapshot: pd.DataFrame, assume_zero: bool) -> str:
    """Expire approval when its records, competence, or zero-count choice change."""
    data = snapshot.to_json(date_format="iso", double_precision=15, orient="split")
    digest = sha256(f"{competence}|{assume_zero}|{data}".encode()).hexdigest()
    return f"cb_confirm_review_{digest}"
