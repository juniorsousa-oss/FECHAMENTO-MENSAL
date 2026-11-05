"""Confirmação auditável de ajustes reais de estoque no relatório Kardex.

A classificação residual de TES não é autorização de ajuste. Apenas registros
de inventário expressamente confirmados podem compor o indicador de acurácia.
Os documentos originais não são alterados.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
import io
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pandas as pd

REGISTRY_KEY = "fm_kardex_ajustes_confirmados_v1"
STOCK_ADJUSTMENT = "AJUSTE DE ESTOQUE"
CONSUMPTION = "MATERIAL DE CONSUMO"
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
EXCEL_DATE_BASE = datetime(1899, 12, 30)
ALLOWED_ORANGE_RGB = {
    "FFFFC000", "FFFFA500", "FFFF9900", "FFFFCC99",
    "FFF4B183", "FFED7D31", "FFFFB347",
}


def empty_registry() -> dict:
    return {"versao": 1, "meses": {}}


def _day(raw) -> str:
    if hasattr(raw, "strftime"):
        return raw.strftime("%Y-%m-%d")
    text = str(raw or "").strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        value = EXCEL_DATE_BASE + timedelta(days=float(text))
        return value.strftime("%Y-%m-%d")
    if re.fullmatch(r"\d{2}/\d{2}/\d{4}", text):
        return datetime.strptime(text, "%d/%m/%Y").strftime("%Y-%m-%d")
    if re.match(r"\d{4}-\d{2}-\d{2}", text):
        return text[:10]
    return ""


def row_key(date_value, code, warehouse, tes, document) -> str:
    date_iso = _day(date_value)
    code = re.sub(r"\.0+$", "", str(code or "").strip())
    if code.isdigit():
        code = code.zfill(8)
    warehouse = str(warehouse or "").strip().upper()
    tes = str(tes or "").strip()
    if tes.isdigit():
        tes = tes.zfill(3)
    document = str(document or "").strip().upper()
    if not date_iso or not re.fullmatch(r"\d{8}", code) or not warehouse or not tes or not document:
        return ""
    return "|".join((date_iso, warehouse, tes, code, document))


def normalize_registry(data: dict | None) -> dict:
    payload = data or {}
    if not isinstance(payload, dict):
        raise ValueError("Registro dos ajustes inválido.")
    months = payload.get("meses") or {}
    if not isinstance(months, dict):
        raise ValueError("Competências de ajustes inválidas.")
    result = {}
    for month, keys in months.items():
        month = str(month)
        if not re.fullmatch(r"\d{4}-\d{2}", month) or not isinstance(keys, list):
            raise ValueError("Competência ou lista de ajustes inválida.")
        unique = set()
        for item in keys:
            item = str(item or "")
            if not item.startswith(month + "-") or len(item) > 200 or len(item.split("|")) != 5:
                raise ValueError("Identificador de ajuste incompatível com a competência.")
            if row_key(*(
                item.split("|")[0], item.split("|")[3],
                item.split("|")[1], item.split("|")[2], item.split("|")[4],
            )) != item:
                raise ValueError("Identificador de ajuste inválido.")
            unique.add(item)
        if len(unique) > 100000:
            raise ValueError("Quantidade excessiva de ajustes confirmados.")
        result[month] = sorted(unique)
    return {"versao": 1, "meses": result}


def load_registry() -> dict:
    import requests
    import inventory_db as db
    response = requests.get(
        f"{db.supabase_url()}/rest/v1/fm_configuracoes",
        headers=db._headers(),
        params={"select": "valor", "chave": f"eq.{REGISTRY_KEY}", "limit": "1"},
        timeout=20,
    )
    db._raise(response)
    rows = response.json() or []
    return normalize_registry(rows[0].get("valor") if rows else None)


def save_registry(changes: dict[str, list[str]]) -> dict:
    """Sobrescreve apenas as competências importadas; preserva as demais."""
    import inventory_db as db
    current = load_registry()
    for month, keys in changes.items():
        current["meses"][month] = list(keys)
    valid = normalize_registry(current)
    db.rpc("fm_salvar_configuracao", {"p_chave": REGISTRY_KEY, "p_valor": valid}, timeout=45)
    verified = load_registry()
    if verified != valid:
        raise RuntimeError("Os ajustes confirmados não foram persistidos integralmente.")
    return verified


def apply_confirmed(frame: pd.DataFrame, registry: dict | None) -> pd.DataFrame:
    """O residual sem confirmação é MATERIAL DE CONSUMO, nunca ajuste real."""
    out = frame.copy()
    out["ajuste_confirmado"] = False
    out["ajuste_reclassificado_consumo"] = False
    if out.empty:
        return out
    approved = normalize_registry(registry)["meses"]
    residual = out["subgrupo_usuario"].eq(STOCK_ADJUSTMENT)
    if not residual.any():
        return out
    keys = out.loc[residual].apply(
        lambda r: row_key(r.get("data"), r.get("codigo"), r.get("armazem"),
                          r.get("tes"), r.get("documento")),
        axis=1,
    )
    allowed = set().union(*(set(values) for values in approved.values())) if approved else set()
    confirmed = keys.isin(allowed)
    confirmed_indexes = confirmed.index[confirmed]
    rejected_indexes = confirmed.index[~confirmed]
    out.loc[confirmed_indexes, "ajuste_confirmado"] = True
    out.loc[rejected_indexes, "ajuste_reclassificado_consumo"] = True
    out.loc[rejected_indexes, "subgrupo_usuario"] = CONSUMPTION
    out.loc[rejected_indexes, "condicao_id"] = "kardex_consumo_sem_ajuste_confirmado"
    return out


def _get_text(cell: ET.Element, strings: list[str]) -> str:
    t = cell.get("t")
    if t == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//m:t", NS))
    value = cell.find("m:v", NS)
    if value is None:
        return ""
    if t == "s":
        return strings[int(value.text)]
    return value.text or ""


def parse_orange_marked_excel(content: bytes) -> list[dict]:
    """Lê apenas células G laranja da aba Movimentações (sem dados presumidos)."""
    if len(content) > 25_000_000:
        raise ValueError("Arquivo de marcações maior que 25 MB.")
    with ZipFile(io.BytesIO(content)) as archive:
        names = archive.namelist()
        styles_root = ET.fromstring(archive.read("xl/styles.xml"))
        fills = list(styles_root.find("m:fills", NS) or [])
        xfs = list(styles_root.find("m:cellXfs", NS) or [])
        strings = []
        if "xl/sharedStrings.xml" in names:
            shared = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            strings = [
                "".join(t.text or "" for t in value.findall(".//m:t", NS))
                for value in shared.findall("m:si", NS)
            ]
        match = None
        for sheet_name in names:
            if not re.fullmatch(r"xl/worksheets/sheet\d+\.xml", sheet_name):
                continue
            if archive.getinfo(sheet_name).file_size > 75_000_000:
                raise ValueError("Planilha descompactada acima do limite de segurança.")
            root = ET.fromstring(archive.read(sheet_name))
            rows = root.findall("m:sheetData/m:row", NS)
            if not rows:
                continue
            header = {
                re.match(r"[A-Z]+", c.attrib["r"]).group(): _get_text(c, strings)
                for c in rows[0].findall("m:c", NS)
            }
            if (
                header.get("G", "").strip().upper() == "SUBGRUPO"
                and header.get("M", "").strip().upper() == "DOCUMENTO"
                and header.get("B", "").strip().upper() in ("CÓDIGO", "CODIGO")
            ):
                match = rows
                break
        if match is None:
            raise ValueError("Aba Movimentações sem o layout A:M esperado (Subgrupo na coluna G).")
        found = {}
        for row in match[1:]:
            cells = {
                re.match(r"[A-Z]+", c.attrib["r"]).group(): c
                for c in row.findall("m:c", NS)
            }
            g = cells.get("G")
            if g is None or _get_text(g, strings).strip().upper() != STOCK_ADJUSTMENT:
                continue
            style_id = int(g.get("s", "0"))
            if style_id >= len(xfs):
                continue
            fill_id = int(xfs[style_id].get("fillId", "0"))
            if fill_id >= len(fills):
                continue
            fg = fills[fill_id].find("m:patternFill/m:fgColor", NS)
            if fg is None:
                continue
            rgb = str(fg.get("rgb") or "").upper()
            if fg.get("theme") != "9" and rgb not in ALLOWED_ORANGE_RGB:
                continue
            values = {key: _get_text(c, strings) for key, c in cells.items()}
            key = row_key(values.get("A"), values.get("B"), values.get("D"),
                          values.get("E"), values.get("M"))
            if not key:
                raise ValueError(f"Movimentação laranja na linha {row.get('r')} sem chave válida.")
            if key in found:
                raise ValueError("O relatório possui marcações repetidas para o mesmo movimento.")
            found[key] = {
                "chave": key, "data": key[:10], "codigo": values.get("B"),
                "armazem": values.get("D"), "tes": values.get("E"),
                "documento": values.get("M"),
                "entrada": float(values.get("H") or 0),
                "saida": float(values.get("I") or 0),
            }
        return list(found.values())


def group_by_month(marked: list[dict]) -> dict[str, list[str]]:
    groups = defaultdict(list)
    for item in marked:
        groups[str(item["data"])[:7]].append(str(item["chave"]))
    return {month: sorted(keys) for month, keys in groups.items()}
