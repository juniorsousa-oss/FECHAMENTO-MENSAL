"""Exportação operacional das divergências da conferência de chapas/barramentos.

O arquivo serve de apoio à tratativa manual no ERP. Não representa carga
automática do Protheus e nunca modifica saldos/contagens do fechamento.
"""
from __future__ import annotations

from datetime import date
from io import BytesIO
import math

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEADERS = [
    "Código", "Descrição", "Categoria", "U.M.", "Armazém(ns)",
    "Saldo fechamento", "Saldo atual", "Variação atual x fechamento",
    "Saldo base ajuste", "Base usada", "Quantidade física",
    "Diferença Qtd (físico - base)", "Ação indicativa",
    "Custo unitário (R$)", "Origem custo", "Diferença R$",
    "Consumo informado", "Fontes da contagem", "Status",
    "Atenção no ERP", "Tratativa / Observações",
]
NUMERIC_FIELDS = {
    "Saldo fechamento", "Saldo atual", "Variação atual x fechamento",
    "Saldo base ajuste", "Quantidade física",
    "Diferença Qtd (físico - base)", "Consumo informado",
}
MONEY_FIELDS = {"Custo unitário (R$)", "Diferença R$"}
FIELD_MAP = {
    "Código": "Código",
    "Descrição": "Descrição",
    "Categoria": "Categoria",
    "U.M.": "U.M.",
    "Armazém(ns)": "ARMZ",
    "Saldo fechamento": "Saldo fechamento",
    "Saldo atual": "Saldo atual",
    "Variação atual x fechamento": "Variação atual x fechamento",
    "Saldo base ajuste": "Saldo base ajuste",
    "Base usada": "Base usada",
    "Quantidade física": "Físico",
    "Diferença Qtd (físico - base)": "Diferença Qtd",
    "Custo unitário (R$)": "Custo unitário",
    "Origem custo": "Origem custo",
    "Diferença R$": "Diferença R$",
    "Consumo informado": "Consumo informado",
    "Fontes da contagem": "Fontes físicas",
    "Status": "Status",
}


def _excel_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    raw = str(value).strip()
    # Impede injeção de fórmula em descrições/origens de planilhas externas.
    return "'" + raw if raw.startswith(("=", "+", "-", "@")) else raw


def _number(value: object) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _action(diff: float | None) -> str:
    if diff is None:
        return "CONFERIR DADOS"
    if diff < -1e-9:
        return "REDUÇÃO DE SALDO"
    if diff > 1e-9:
        return "ACRÉSCIMO DE SALDO"
    return "CONFERIR DADOS"


def _caution(armazem: str, saldo_atual: float | None, base: float | None) -> str:
    notes = []
    # O sistema calcula por código e pode somar vários armazéns.
    if "," in armazem or ";" in armazem:
        notes.append("VALIDAR ARMAZÉM DE MOVIMENTAÇÃO")
    if saldo_atual is None:
        notes.append("SALDO ATUAL NÃO DISPONÍVEL")
    elif base is not None and abs(saldo_atual - base) > 1e-9:
        notes.append("BASE DE AJUSTE DIFERE DO SALDO ATUAL")
    return " | ".join(notes)


def divergent_records(reconciliation: pd.DataFrame) -> list[dict]:
    """Mesma seleção do KPI: somente status DIVERGÊNCIA já sem tolerados/excluídos."""
    if reconciliation is None or reconciliation.empty:
        return []
    if "Status" not in reconciliation.columns:
        raise ValueError("A base de conferência não possui a coluna Status.")
    result = []
    active = reconciliation.loc[
        reconciliation["Status"].astype(str).eq("DIVERGÊNCIA")
    ]
    for item in active.to_dict("records"):
        code = str(item.get("Código") or "").strip()
        # Evitar perda de zero à esquerda quando números chegam como texto.
        if code.isdecimal() and len(code) <= 8:
            code = code.zfill(8)
        diff = _number(item.get("Diferença Qtd"))
        stock_now = _number(item.get("Saldo atual"))
        stock_base = _number(item.get("Saldo base ajuste"))
        warehouse = _excel_text(item.get("ARMZ"))
        row = {}
        for label in HEADERS:
            if label == "Código":
                row[label] = code
            elif label == "Diferença Qtd (físico - base)":
                row[label] = diff
            elif label == "Ação indicativa":
                row[label] = _action(diff)
            elif label == "Atenção no ERP":
                row[label] = _caution(warehouse, stock_now, stock_base)
            elif label == "Tratativa / Observações":
                row[label] = ""
            elif label in NUMERIC_FIELDS or label in MONEY_FIELDS:
                row[label] = _number(item.get(FIELD_MAP[label]))
            else:
                row[label] = _excel_text(item.get(FIELD_MAP[label]))
        result.append(row)
    return sorted(result, key=lambda row: (row["Categoria"], row["Código"]))


def export_divergences(reconciliation: pd.DataFrame, competencia: date) -> bytes:
    if not isinstance(competencia, date):
        raise ValueError("Competência inválida para exportar divergências.")
    rows = divergent_records(reconciliation)
    if not rows:
        raise ValueError("Nenhuma divergência ativa para exportação.")
    wb = Workbook()
    ws = wb.active
    ws.title = "Divergências"
    ws.sheet_view.showGridLines = False

    # Orientações no próprio arquivo evitam importar a diferença como ajuste
    # definitivo sem checar movimentos posteriores no Protheus.
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(HEADERS))
    ws["A1"] = f"SETTA | CONFERÊNCIA DE CHAPAS E BARRAMENTOS | {competencia:%m/%Y}"
    ws["A1"].font = Font(name="Aptos", size=14, color="FFFFFF", bold=True)
    ws["A1"].fill = PatternFill("solid", fgColor="17263D")
    ws["A1"].alignment = Alignment(vertical="center")
    ws.row_dimensions[1].height = 29

    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(HEADERS))
    ws["A2"] = (
        "PLANILHA DE APOIO À REGULARIZAÇÃO — NÃO É UMA CARGA PROTHEUS. "
        "Diferença = físico − menor saldo entre fechamento e atual. "
        "Validar saldo vigente, armazém e TES antes de lançar qualquer ajuste."
    )
    ws["A2"].font = Font(name="Aptos", size=10, color="7C3A10", bold=True)
    ws["A2"].fill = PatternFill("solid", fgColor="FFF2DC")
    ws["A2"].alignment = Alignment(vertical="center", wrap_text=True)
    ws.row_dimensions[2].height = 30

    ws.merge_cells(start_row=3, start_column=1, end_row=3, end_column=len(HEADERS))
    ws["A3"] = (
        f"{len(rows)} material(is) divergente(s). "
        "Redução: físico menor que base; acréscimo: físico maior que base. "
        "Itens tolerados ou removidos manualmente da análise não são exportados."
    )
    ws["A3"].font = Font(name="Aptos", size=10, color="354A67")
    ws.row_dimensions[3].height = 19

    header_row = 5
    for index, label in enumerate(HEADERS, start=1):
        cell = ws.cell(header_row, index, label)
        cell.font = Font(name="Aptos", size=10, color="FFFFFF", bold=True)
        cell.fill = PatternFill("solid", fgColor="223C60")
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        letter = get_column_letter(index)
        if label in {"Descrição", "Fontes da contagem", "Atenção no ERP", "Tratativa / Observações"}:
            ws.column_dimensions[letter].width = 42
        elif label in {"Código", "U.M.", "Base usada"}:
            ws.column_dimensions[letter].width = 16
        elif label in {"Ação indicativa", "Origem custo", "Armazém(ns)"}:
            ws.column_dimensions[letter].width = 25
        else:
            ws.column_dimensions[letter].width = min(25, max(18, len(label) + 2))
    ws.row_dimensions[header_row].height = 32
    for rindex, row in enumerate(rows, start=header_row + 1):
        for cindex, label in enumerate(HEADERS, start=1):
            value = row.get(label)
            cell = ws.cell(rindex, cindex, value)
            cell.font = Font(name="Aptos", size=10, color="21344A")
            if rindex % 2 == 0:
                cell.fill = PatternFill("solid", fgColor="F0F5FA")
            if label == "Código":
                cell.number_format = "@"
            elif label in NUMERIC_FIELDS:
                # Seis casas fixas: precisão original preservada, sem
                # separador decimal isolado em configurações pt-BR.
                cell.number_format = "#,##0.000000;[Red](#,##0.000000)"
            elif label in MONEY_FIELDS:
                cell.number_format = '"R$ " #,##0.00;[Red]("R$ " #,##0.00)'
            if label == "Ação indicativa" and value == "REDUÇÃO DE SALDO":
                cell.font = Font(name="Aptos", size=10, color="B42318", bold=True)
            if label == "Atenção no ERP" and value:
                cell.font = Font(name="Aptos", size=10, color="9A3412")
            cell.alignment = Alignment(vertical="center", wrap_text=label in {
                "Descrição", "Fontes da contagem", "Atenção no ERP", "Tratativa / Observações"
            })
        ws.row_dimensions[rindex].height = 22

    ws.freeze_panes = "C6"
    ws.auto_filter.ref = f"A5:{get_column_letter(len(HEADERS))}{header_row + len(rows)}"
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_options.horizontalCentered = True
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.print_title_rows = "1:5"
    out = BytesIO()
    wb.save(out)
    wb.close()
    return out.getvalue()
