"""Consulta leve do tipo de material na fonte CADASTROS, sem afetar chapas/barramentos."""
from __future__ import annotations

from io import BytesIO
import re
import unicodedata

import openpyxl
import pandas as pd


def _norm(value) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return re.sub(r"[^A-Z0-9]", "", "".join(c for c in text if not unicodedata.combining(c)).upper())


def _code(value) -> str:
    if value is None or bool(pd.isna(value)):
        return ""
    raw = str(value).strip()
    if re.fullmatch(r"\d+\.0+", raw):
        raw = raw.split(".")[0]
    if isinstance(value, (float, int)) and not isinstance(value, bool):
        raw = str(int(value)) if float(value).is_integer() else raw
    if not re.fullmatch(r"\d{1,8}", raw):
        return ""
    return raw.zfill(8)


def parse_rows(rows) -> dict[str, str]:
    """Busca CODIGO e TIPO/TP no cabeçalho, inclusive se estiver na linha 2."""
    mapping = {}
    for position, cells in enumerate(rows):
        if position > 12:
            break
        headers = {_norm(value): i for i, value in enumerate(cells)}
        code_idx = next((headers[h] for h in ("CODIGO", "CODMATERIAL", "CODPRODUTO") if h in headers), None)
        type_idx = next((headers[h] for h in ("TIPO", "TP", "TIPOMATERIAL") if h in headers), None)
        if code_idx is not None and type_idx is not None:
            mapping = {"header": position, "code": code_idx, "type": type_idx}
            break
    if not mapping:
        raise ValueError("A fonte CADASTROS não possui cabeçalho CODIGO e TIPO/TP.")
    result: dict[str, str] = {}
    for cells in rows[mapping["header"] + 1:]:
        if mapping["code"] >= len(cells) or mapping["type"] >= len(cells):
            continue
        code = _code(cells[mapping["code"]])
        tipo = _norm(cells[mapping["type"]])
        if code and tipo and tipo not in ("NI", "NAN", "NONE"):
            result[code] = tipo
    return result


def parse_frame(frame: pd.DataFrame) -> dict[str, str]:
    if frame is None or frame.empty:
        return {}
    return parse_rows([list(row) for row in frame.itertuples(index=False, name=None)])


def parse_raw(raw: bytes) -> dict[str, str]:
    workbook = openpyxl.load_workbook(BytesIO(raw), data_only=True, read_only=True)
    try:
        for sheet in workbook.worksheets:
            rows = [list(values) for values in sheet.iter_rows(values_only=True)]
            try:
                return parse_rows(rows)
            except ValueError:
                continue
    finally:
        workbook.close()
    raise ValueError("A fonte CADASTROS não possui aba com CODIGO e TIPO/TP.")
