"""Consulta de dados complementares do Plano Mestre de Produção (FOR001).

Leitura por OP completa, sem alterar a conferência MES/KARDEX.
Campos: A OP, C cliente, O condição, Q NF, R faturamento, T dias de pátio.
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta

import pandas as pd

import movements as mv

FIELDS = ("cliente", "condicao", "nota_fiscal", "data_faturamento", "dias_patio")
POSITIONS = {"op": 0, "cliente": 2, "condicao": 14, "nota_fiscal": 16,
             "data_faturamento": 17, "dias_patio": 19}
EMPTY = {"", "-", "NI", "N/I", "N.A.", "N/A", "#NAME?", "#N/A",
         "#REF!", "#VALUE!", "#DIV/0!", "NONE", "NULL", "NAN", "NAT"}


def _missing(value) -> bool:
    if value is None:
        return True
    try:
        if bool(pd.isna(value)):
            return True
    except (ValueError, TypeError):
        pass
    return str(value).strip().upper() in EMPTY


def op_key(value) -> str:
    if _missing(value):
        return ""
    value = str(value).strip()
    value = re.sub(r"^OP\s*[-:/]?\s*", "", value, flags=re.I)
    if re.fullmatch(r"\d+\.0+", value):
        value = value.split(".", 1)[0]
    return value if re.fullmatch(r"\d+", value) else ""


def _text(value) -> str:
    if _missing(value):
        return "NI"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, int):
        return str(value)
    return str(value).strip()


def _date(value) -> str:
    if _missing(value):
        return "NI"
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.strftime("%d/%m/%Y")
    s = str(value).strip()
    if re.fullmatch(r"\d+(?:\.0+)?", s):
        numeric = float(s)
        if 1 <= numeric <= 90000:
            return (datetime(1899, 12, 30) + timedelta(days=numeric)).strftime("%d/%m/%Y")
    try:
        return pd.to_datetime(s, dayfirst=True, errors="raise").strftime("%d/%m/%Y")
    except (TypeError, ValueError, OverflowError):
        return "NI"


def _days(value) -> str:
    if _missing(value):
        return "NI"
    if isinstance(value, (datetime, date, pd.Timestamp)):
        # Alguns modelos Excel formatam dias de pátio como data do sistema 1900.
        days = (value.date() if isinstance(value, datetime) else value) - date(1899, 12, 30)
        return str(days.days) if 0 <= days.days < 10000 else "NI"
    s = str(value).strip()
    if " ".join(s.upper().split()) == "FINALIZADO E ENTREGUE":
        return "FINALIZADO E ENTREGUE"
    try:
        n = float(s.replace(",", "."))
        if not math.isfinite(n) or n < 0:
            return "NI"
        return str(int(n)) if n.is_integer() else str(n).replace(".", ",")
    except ValueError:
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00")).date()
            days = (dt - date(1899, 12, 30)).days
            return str(days) if 0 <= days < 10000 else "NI"
        except ValueError:
            return "NI"


def _record(cells) -> tuple[str, dict] | None:
    def at(pos):
        return cells[pos] if pos < len(cells) else None

    op = op_key(at(POSITIONS["op"]))
    if not op:
        return None
    return op, {
        "cliente": _text(at(POSITIONS["cliente"])),
        "condicao": _text(at(POSITIONS["condicao"])),
        "nota_fiscal": _text(at(POSITIONS["nota_fiscal"])),
        "data_faturamento": _date(at(POSITIONS["data_faturamento"])),
        "dias_patio": _days(at(POSITIONS["dias_patio"])),
    }


def parse_frame(frame: pd.DataFrame) -> dict[str, dict]:
    """Aceita a aba PAINEL normalizada, com ou sem cabeçalho promovido."""
    if frame is None or frame.empty:
        return {}
    matrix = frame.itertuples(index=False, name=None)
    result: dict[str, dict] = {}
    found_header = False
    for pos, cells in enumerate(matrix):
        if pos < 30 and any("ORDEM PRODU" in mv.normalized(x) for x in cells[:1]):
            found_header = True
            continue
        # Quando os nomes das colunas já são o cabeçalho, a primeira linha é um dado.
        if not found_header and pos < 5 and not op_key(cells[0] if cells else None):
            continue
        parsed = _record(cells)
        if not parsed:
            continue
        op, incoming = parsed
        stored = result.setdefault(op, {key: "NI" for key in FIELDS})
        # Duplicidades da OP: mantém o último dado válido de cada campo,
        # sem apagar valores existentes com células vazias de outras linhas.
        for field, value in incoming.items():
            if value != "NI":
                stored[field] = value
    return result


def parse_raw(raw: bytes) -> dict[str, dict]:
    """Fallback para Excel bruto disponibilizado pelo Monitor de APIs."""
    result: dict[str, dict] = {}
    for sheet_name, row_number, cells, _epoch in mv._xml_rows(raw):
        if sheet_name.upper().strip() != "PAINEL" or row_number <= 5:
            continue
        row = [cells.get(chr(65 + i)) for i in range(20)]
        parsed = _record(row)
        if parsed:
            op, incoming = parsed
            stored = result.setdefault(op, {key: "NI" for key in FIELDS})
            for field, value in incoming.items():
                if value != "NI":
                    stored[field] = value
    return result


def enrich_ops(ops: pd.DataFrame, records: dict[str, dict]) -> pd.DataFrame:
    result = ops.copy()
    for field in FIELDS:
        result[field] = result["op"].map(
            lambda op: records.get(op_key(op), {}).get(field, "NI")
        )
    return result


def label_fields(info: dict) -> str:
    values = {key: info.get(key) or "NI" for key in FIELDS}
    patio = values["dias_patio"]
    values["dias_patio"] = patio if patio == "NI" else f"{patio} DIAS"
    return ("CLIENTE: {cliente} | CONDIÇÃO: {condicao} | NF: {nota_fiscal} | "
            "FATURAMENTO: {data_faturamento} | PÁTIO: {dias_patio}").format(**values)
