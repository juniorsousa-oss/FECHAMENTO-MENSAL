from __future__ import annotations

import io
import re
import unicodedata
from collections import defaultdict
from datetime import date, datetime
from email import policy
from email.parser import BytesParser
from typing import Any

import openpyxl
from bs4 import BeautifulSoup


INITIAL_CONFIRMED_CODES = {
    "00110004","00110158","00110061","00110162","00110154","00110064",
    "00110065","00110114","00110161","00110001","00110160","00110003",
    "00110049","00110066","00110108","00110073","00110067","00110109",
    "00110176","00110157","00110178","00110159","00110172","00110171",
    "00110170","00110202","00110201","00110156","00110155","00110343",
    "00110341","00110340","06000005","06000031","06000014","06000167",
    "06000168","06000169","06000187","06000170","06000011","06000055",
    "06000178","06000179","06000189","06000188","06000186","06000210",
    "06000211",
}

INITIAL_CHAPA_MAP = {
    ("2500X1200", "#12 FINA FRIA"): "06000005",
    ("2500X1200", "#16 FINA FRIA"): "06000031",
    ("2500X1200", "#18 FINA FRIA"): "06000014",
    ("2500X1200", "#12 GALVANIZADA"): "06000167",
    ("2500X1200", "#14 GALVANIZADA"): "06000168",
    ("2500X1200", "#16 GALVANIZADA"): "06000169",
    ("2500X1200", "#18 GALVANIZADA"): "06000187",
    ("3000X1200", "#12 FINA FRIA"): "06000005",
    ("3000X1200", "#16 FINA FRIA"): "06000031",
    ("3000X1200", "#18 FINA FRIA"): "06000014",
    ("3000X1200", "#12 GALVANIZADA"): "06000167",
    ("3000X1200", "#14 GALVANIZADA"): "06000168",
    ("3000X1200", "#16 GALVANIZADA"): "06000169",
    ("3000X1200", "#18 GALVANIZADA"): "06000187",
    ("3000X1200", "3/16'' FINA QUENTE"): "06000170",
    ("3000X1200", '1/8" FINA QUENTE'): "06000011",
    ("3000X1200", '1/8" XADREZ'): "06000055",
    ("VARIADAS", "MAGNELIS 1,55"): "06000178",
    ("VARIADAS", "MAGNELIS 1,95"): "06000179",
    ("SIVACON", "#12 GALVANIZADA"): "06000167",
    ("SIVACON", "#14 GALVANIZADA"): "06000168",
    ("SIVACON", "#16 GALVANIZADA"): "06000169",
    ("SIVACON", "#20 GALVANIZADA"): "06000186",
    ("SIVACON", "5MM ALUMINIO"): "06000210",
    ("SIVACON", "3MM ALUMINIO"): "06000211",
}


def normalize_code(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text == "-":
        return ""

    if re.fullmatch(r"\d+(?:\.0+)?", text):
        return str(int(float(text))).zfill(8)

    compact = re.sub(r"\s+", "", text)
    digits = re.sub(r"\D", "", compact)
    if digits and len(digits) <= 8:
        return digits.zfill(8)
    return compact


def normalize_text(value: Any) -> str:
    text = str(value or "").strip().upper()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(
        char for char in text
        if not unicodedata.combining(char)
    )
    text = re.sub(r"\s+", " ", text)
    return text


def to_number(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip().replace("R$", "").replace(" ", "")
    if not text or text == "-":
        return 0.0

    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")

    try:
        return float(text)
    except Exception:
        return 0.0


def _find_header_row(
    ws,
    required_labels: set[str],
    max_rows: int = 30,
) -> tuple[int, dict[int, str]] | None:
    for row_index in range(1, min(ws.max_row, max_rows) + 1):
        values = {
            col: normalize_text(ws.cell(row_index, col).value)
            for col in range(1, ws.max_column + 1)
        }
        present = {value for value in values.values() if value}
        if required_labels.issubset(present):
            return row_index, values
    return None


def parse_cadastros(raw: bytes, file_name: str) -> dict:
    wb = openpyxl.load_workbook(
        io.BytesIO(raw),
        data_only=True,
        read_only=True,
    )
    ws = wb[wb.sheetnames[0]]

    header_info = _find_header_row(
        ws,
        {"GRUPO", "CODIGO", "DESCRICAO", "TIPO", "UNIDADE"},
        max_rows=10,
    )
    if not header_info:
        raise ValueError(
            "Não encontrei o cabeçalho esperado do relatório CADASTROS."
        )

    header_row, headers = header_info
    column_by_name = {
        value: col
        for col, value in headers.items()
        if value
    }

    code_col = column_by_name["CODIGO"]
    group_col = column_by_name["GRUPO"]
    desc_col = column_by_name["DESCRICAO"]
    type_col = column_by_name["TIPO"]
    unit_col = column_by_name["UNIDADE"]
    price_col = column_by_name.get("ULT. PRECO")

    candidates: list[dict] = []

    for row_index in range(header_row + 1, ws.max_row + 1):
        codigo = normalize_code(ws.cell(row_index, code_col).value)
        if not codigo:
            continue

        grupo = str(ws.cell(row_index, group_col).value or "").strip()
        descricao = str(
            ws.cell(row_index, desc_col).value or ""
        ).strip()
        tp = str(ws.cell(row_index, type_col).value or "").strip()
        unidade = str(
            ws.cell(row_index, unit_col).value or ""
        ).strip()
        ult_preco = (
            to_number(ws.cell(row_index, price_col).value)
            if price_col
            else 0.0
        )

        desc_norm = normalize_text(descricao)
        categoria = ""
        regra = ""

        if desc_norm.startswith("BARRA DE COBRE ELETROLITICO NU"):
            categoria = "BARRA_COBRE"
            regra = "DESCRICAO_BARRA_COBRE"
        elif (
            grupo == "0600"
            and tp.upper() == "MP"
            and desc_norm.startswith("CHAPA ")
        ):
            categoria = "CHAPA"
            regra = "GRUPO_0600_MP_DESCRICAO_CHAPA"

        if not categoria:
            continue

        candidates.append(
            {
                "codigo": codigo,
                "categoria": categoria,
                "descricao": descricao,
                "grupo": grupo,
                "tp": tp,
                "unidade": unidade,
                "ult_preco": ult_preco,
                "status": (
                    "CONFIRMADO"
                    if codigo in INITIAL_CONFIRMED_CODES
                    else "CANDIDATO"
                ),
                "origem": file_name,
                "regra_detectada": (
                    "BASE_INICIAL_VALIDADA"
                    if codigo in INITIAL_CONFIRMED_CODES
                    else regra
                ),
            }
        )

    return {
        "file_name": file_name,
        "candidates": candidates,
        "total_candidates": len(candidates),
        "chapas": sum(
            1 for row in candidates
            if row["categoria"] == "CHAPA"
        ),
        "barras": sum(
            1 for row in candidates
            if row["categoria"] == "BARRA_COBRE"
        ),
    }


def parse_chapas_eml(raw: bytes, file_name: str) -> dict:
    message = BytesParser(policy=policy.default).parsebytes(raw)

    html_parts: list[str] = []
    for part in message.walk():
        if part.get_content_type() != "text/html":
            continue
        try:
            html_parts.append(part.get_content())
        except Exception:
            continue

    if not html_parts:
        raise ValueError(
            "O e-mail não possui conteúdo HTML com a tabela de chapas."
        )

    soup = BeautifulSoup("\n".join(html_parts), "html.parser")
    valid_tables: list[dict] = []

    for table in soup.find_all("table"):
        raw_rows: list[list[str]] = []
        for tr in table.find_all("tr"):
            cells = [
                " ".join(cell.stripped_strings)
                for cell in tr.find_all(["td", "th"])
            ]
            if cells:
                raw_rows.append(cells)

        if len(raw_rows) < 3:
            continue

        header_index = None
        for index, row in enumerate(raw_rows[:5]):
            normalized = [normalize_text(cell) for cell in row]
            if (
                "DIMENSAO" in normalized
                and "DESCRICAO" in normalized
                and "CHAPAS" in normalized
                and "PESO TOTAL" in normalized
            ):
                header_index = index
                break

        if header_index is None:
            continue

        competencia_data = None
        if header_index > 0:
            for cell in raw_rows[header_index - 1]:
                match = re.search(
                    r"(\d{1,2}/\d{1,2}/\d{4})",
                    cell,
                )
                if match:
                    try:
                        competencia_data = datetime.strptime(
                            match.group(1),
                            "%d/%m/%Y",
                        ).date()
                    except Exception:
                        pass
                    break

        current_dimension = ""
        parsed_rows: list[dict] = []

        for row in raw_rows[header_index + 1 :]:
            if len(row) >= 4:
                dimension = str(row[0] or "").strip()
                descricao = str(row[1] or "").strip()
                chapas = row[2]
                peso = row[3]
                if dimension:
                    current_dimension = dimension
            elif len(row) == 3:
                dimension = current_dimension
                descricao = str(row[0] or "").strip()
                chapas = row[1]
                peso = row[2]
            else:
                continue

            if not descricao:
                continue

            if dimension:
                current_dimension = dimension

            parsed_rows.append(
                {
                    "dimensao": current_dimension,
                    "dimensao_norm": normalize_text(
                        current_dimension
                    ),
                    "descricao": descricao,
                    "descricao_norm": normalize_text(descricao),
                    "chapas": to_number(chapas),
                    "peso_total": to_number(peso),
                }
            )

        if parsed_rows:
            valid_tables.append(
                {
                    "data": competencia_data,
                    "rows": parsed_rows,
                }
            )

    if not valid_tables:
        raise ValueError(
            "Não encontrei tabela de chapas no padrão DIMENSÃO / "
            "DESCRIÇÃO / CHAPAS / PESO TOTAL."
        )

    valid_tables.sort(
        key=lambda item: item["data"] or date.min,
        reverse=True,
    )
    selected = valid_tables[0]
    table_date = selected["data"]
    competencia = (
        date(table_date.year, table_date.month, 1)
        if table_date
        else None
    )

    return {
        "file_name": file_name,
        "subject": str(message.get("subject") or ""),
        "sender": str(message.get("from") or ""),
        "competencia": competencia,
        "data_contagem": table_date,
        "rows": selected["rows"],
        "tables_found": len(valid_tables),
    }


def parse_barramentos_excel(raw: bytes, file_name: str) -> dict:
    wb = openpyxl.load_workbook(
        io.BytesIO(raw),
        data_only=True,
        read_only=True,
    )

    chosen = None
    for ws in wb.worksheets:
        for row_index in range(1, min(ws.max_row, 20) + 1):
            headers = {
                col: normalize_text(ws.cell(row_index, col).value)
                for col in range(1, ws.max_column + 1)
            }
            values = set(headers.values())
            has_code = "CODIGO" in values
            has_barras = any(
                value.startswith("BARRAS")
                for value in values
            )
            has_processado = any(
                "PROCESSADO" in value
                for value in values
            )
            if has_code and has_barras and has_processado:
                chosen = (ws, row_index, headers)
                break
        if chosen:
            break

    if not chosen:
        raise ValueError(
            "Não encontrei as colunas CODIGO, BARRAS e PROCESSADO "
            "na planilha de barramentos."
        )

    ws, header_row, headers = chosen
    code_col = next(
        col for col, value in headers.items()
        if value == "CODIGO"
    )
    bars_col = next(
        col for col, value in headers.items()
        if value.startswith("BARRAS")
    )
    processed_col = next(
        col for col, value in headers.items()
        if "PROCESSADO" in value
    )
    model_col = next(
        (
            col for col, value in headers.items()
            if "MODELO" in value
        ),
        None,
    )

    aggregated: dict[str, dict] = {}

    for row_index in range(header_row + 1, ws.max_row + 1):
        codigo = normalize_code(ws.cell(row_index, code_col).value)
        if not codigo:
            continue

        barras = to_number(ws.cell(row_index, bars_col).value)
        processado = to_number(
            ws.cell(row_index, processed_col).value
        )
        total = barras + processado
        modelo = (
            str(ws.cell(row_index, model_col).value or "").strip()
            if model_col
            else ""
        )

        current = aggregated.setdefault(
            codigo,
            {
                "codigo": codigo,
                "quantidade_fisica": 0.0,
                "barras": 0.0,
                "processado": 0.0,
                "modelo": modelo,
            },
        )
        current["quantidade_fisica"] += total
        current["barras"] += barras
        current["processado"] += processado
        if not current["modelo"]:
            current["modelo"] = modelo

    rows = list(aggregated.values())
    return {
        "file_name": file_name,
        "rows": rows,
        "total_rows": len(rows),
        "total_metros": sum(
            row["quantidade_fisica"] for row in rows
        ),
    }


def parse_interno_excel(raw: bytes, file_name: str) -> dict:
    wb = openpyxl.load_workbook(
        io.BytesIO(raw),
        data_only=True,
        read_only=True,
    )

    candidates: list[dict] = []
    quantity_names = {
        "MTS",
        "METROS",
        "QUANTIDADE",
        "QUANTIDADE FISICA",
        "QTD",
        "QNT",
        "SALDO CONTAGEM",
        "CONTAGEM",
    }

    for ws in wb.worksheets:
        for row_index in range(1, min(ws.max_row, 40) + 1):
            headers = {
                col: normalize_text(ws.cell(row_index, col).value)
                for col in range(1, ws.max_column + 1)
            }
            code_cols = [
                col for col, value in headers.items()
                if value == "CODIGO"
            ]

            for code_col in code_cols:
                quantity_col = None
                quantity_label = ""

                for offset in range(1, 6):
                    col = code_col + offset
                    value = headers.get(col, "")
                    if value in quantity_names:
                        quantity_col = col
                        quantity_label = value
                        break

                if quantity_col is None:
                    continue

                rows: list[dict] = []
                blank_streak = 0

                for data_row in range(
                    row_index + 1,
                    ws.max_row + 1,
                ):
                    codigo = normalize_code(
                        ws.cell(data_row, code_col).value
                    )
                    if not codigo:
                        blank_streak += 1
                        if blank_streak >= 12 and rows:
                            break
                        continue

                    blank_streak = 0
                    quantidade = to_number(
                        ws.cell(data_row, quantity_col).value
                    )
                    rows.append(
                        {
                            "codigo": codigo,
                            "quantidade_fisica": quantidade,
                        }
                    )

                if rows:
                    candidates.append(
                        {
                            "sheet": ws.title,
                            "header_row": row_index,
                            "quantity_label": quantity_label,
                            "rows": rows,
                        }
                    )

    if not candidates:
        raise ValueError(
            "Não encontrei uma estrutura com CODIGO e MTS/METROS/"
            "QUANTIDADE na planilha do setor interno."
        )

    candidates.sort(
        key=lambda item: len(item["rows"]),
        reverse=True,
    )
    selected = candidates[0]

    aggregated: dict[str, float] = defaultdict(float)
    for row in selected["rows"]:
        aggregated[row["codigo"]] += float(
            row["quantidade_fisica"] or 0
        )

    rows = [
        {
            "codigo": codigo,
            "quantidade_fisica": quantidade,
        }
        for codigo, quantidade in sorted(aggregated.items())
    ]

    return {
        "file_name": file_name,
        "sheet": selected["sheet"],
        "quantity_label": selected["quantity_label"],
        "rows": rows,
        "total_rows": len(rows),
        "total_quantidade": sum(
            row["quantidade_fisica"] for row in rows
        ),
    }


def resolve_chapa_rows(
    email_rows: list[dict],
    mappings: list[dict],
    catalog: list[dict],
) -> dict:
    mapping_exact: dict[tuple[str, str], dict] = {
        (normalize_text(dim), normalize_text(desc)): {
            "codigo": codigo
        }
        for (dim, desc), codigo in INITIAL_CHAPA_MAP.items()
    }
    mapping_fallback: dict[str, list[dict]] = defaultdict(list)

    for (dim, desc), codigo in INITIAL_CHAPA_MAP.items():
        mapping_fallback[normalize_text(desc)].append(
            {"codigo": codigo}
        )

    for row in mappings:
        if str(row.get("status") or "").upper() != "CONFIRMADO":
            continue
        dim = normalize_text(
            row.get("dimensao_norm")
            or row.get("dimensao_origem")
            or "*"
        )
        desc = normalize_text(
            row.get("descricao_norm")
            or row.get("descricao_origem")
        )
        if not desc:
            continue
        mapping_exact[(dim or "*", desc)] = row
        mapping_fallback[desc].append(row)

    catalog_map = {
        str(row.get("codigo") or "").strip(): row
        for row in catalog
        if str(row.get("status") or "").upper() == "CONFIRMADO"
    }

    resolved: list[dict] = []
    unresolved: list[dict] = []

    for source_row in email_rows:
        dim = normalize_text(source_row.get("dimensao_norm"))
        desc = normalize_text(source_row.get("descricao_norm"))

        mapping = mapping_exact.get((dim, desc))
        if mapping is None:
            unique_codes = {
                str(item.get("codigo") or "").strip()
                for item in mapping_fallback.get(desc, [])
                if str(item.get("codigo") or "").strip()
            }
            if len(unique_codes) == 1:
                only_code = next(iter(unique_codes))
                mapping = {"codigo": only_code}

        codigo = (
            str(mapping.get("codigo") or "").strip()
            if mapping
            else ""
        )
        catalog_item = catalog_map.get(codigo)

        if not codigo or not catalog_item:
            if (
                float(source_row.get("chapas") or 0) == 0
                and float(source_row.get("peso_total") or 0) == 0
            ):
                continue
            unresolved.append(source_row)
            continue

        unidade = normalize_text(catalog_item.get("unidade"))
        if unidade in {"KG", "KILO", "QUILOGRAMA"}:
            quantidade = float(source_row.get("peso_total") or 0)
            criterio = "PESO TOTAL"
        elif unidade in {"UN", "PC", "PÇ", "PCA"}:
            quantidade = float(source_row.get("chapas") or 0)
            criterio = "CHAPAS"
        else:
            unresolved.append(
                {
                    **source_row,
                    "motivo": (
                        "UNIDADE DO CADASTRO NÃO SUPORTADA "
                        f"PARA CHAPAS: {catalog_item.get('unidade') or '-'}"
                    ),
                }
            )
            continue

        resolved.append(
            {
                "codigo": codigo,
                "quantidade_fisica": quantidade,
                "observacao": (
                    f"{source_row.get('dimensao') or ''} · "
                    f"{source_row.get('descricao') or ''} · "
                    f"critério {criterio}"
                ).strip(" ·"),
            }
        )

    aggregated: dict[str, dict] = {}
    for row in resolved:
        codigo = row["codigo"]
        current = aggregated.setdefault(
            codigo,
            {
                "codigo": codigo,
                "quantidade_fisica": 0.0,
                "observacoes": [],
            },
        )
        current["quantidade_fisica"] += float(
            row["quantidade_fisica"] or 0
        )
        current["observacoes"].append(row["observacao"])

    final_rows = [
        {
            "codigo": item["codigo"],
            "quantidade_fisica": item["quantidade_fisica"],
            "observacao": " | ".join(item["observacoes"]),
        }
        for item in aggregated.values()
    ]

    return {
        "resolved": final_rows,
        "unresolved": unresolved,
    }
