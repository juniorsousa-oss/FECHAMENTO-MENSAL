from __future__ import annotations

import io
import re
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from typing import Any


def _local(tag: str) -> str:
    return tag.split("}")[-1]


def _to_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip().replace("R$", "").replace(" ", "")
    if text in {"", "-"}:
        return 0.0

    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")

    try:
        return float(text)
    except Exception:
        return None


def _parse_rows(raw: bytes) -> tuple[str, list[dict[str, Any]]]:
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for si in root.iter():
                if _local(si.tag) != "si":
                    continue
                text_parts = [
                    node.text or ""
                    for node in si.iter()
                    if _local(node.tag) == "t"
                ]
                shared.append("".join(text_parts))

        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relations = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        relmap = {
            rel.attrib["Id"]: rel.attrib["Target"]
            for rel in relations
            if "Id" in rel.attrib and "Target" in rel.attrib
        }

        sheets_node = next(
            (node for node in workbook.iter() if _local(node.tag) == "sheets"),
            None,
        )
        if sheets_node is None:
            raise ValueError("Não foi possível identificar as abas do relatório.")

        sheets: list[tuple[str, str]] = []
        for sheet in list(sheets_node):
            if _local(sheet.tag) != "sheet":
                continue
            name = sheet.attrib.get("name", "")
            relation_id = next(
                (
                    value
                    for key, value in sheet.attrib.items()
                    if key.endswith("}id") or key == "id"
                ),
                None,
            )
            target = relmap.get(relation_id or "")
            if not target:
                continue
            if target.startswith("/"):
                target = target.lstrip("/")
            elif not target.startswith("xl/"):
                target = "xl/" + target
            sheets.append((name, target))

        if not sheets:
            raise ValueError("Nenhuma aba válida foi encontrada no arquivo.")

        selected = next(
            (
                item
                for item in sheets
                if "saldos em estoque" in item[0].lower()
            ),
            sheets[-1],
        )

        sheet_name, sheet_path = selected
        root = ET.fromstring(archive.read(sheet_path))

        rows: list[dict[str, Any]] = []
        for row in root.iter():
            if _local(row.tag) != "row":
                continue

            values: dict[str, Any] = {}
            for cell in list(row):
                if _local(cell.tag) != "c":
                    continue

                reference = cell.attrib.get("r", "")
                match = re.match(r"([A-Z]+)", reference)
                if not match:
                    continue
                column = match.group(1)

                cell_type = cell.attrib.get("t")
                value_node = next(
                    (node for node in cell if _local(node.tag) == "v"),
                    None,
                )
                inline_node = next(
                    (node for node in cell if _local(node.tag) == "is"),
                    None,
                )

                value: Any = None
                if cell_type == "s" and value_node is not None:
                    try:
                        value = shared[int(value_node.text or "0")]
                    except Exception:
                        value = value_node.text
                elif cell_type == "inlineStr" and inline_node is not None:
                    value = "".join(
                        node.text or ""
                        for node in inline_node.iter()
                        if _local(node.tag) == "t"
                    )
                elif cell_type == "str" and value_node is not None:
                    value = value_node.text
                elif value_node is not None:
                    text = value_node.text or ""
                    try:
                        number = float(text)
                        value = int(number) if number.is_integer() else number
                    except Exception:
                        value = text

                values[column] = value

            if values:
                rows.append(values)

        return sheet_name, rows


def parse_inventory_report(raw: bytes, file_name: str) -> dict:
    sheet_name, rows = _parse_rows(raw)

    header_index = next(
        (
            index
            for index, row in enumerate(rows)
            if str(row.get("A") or "").strip().upper() == "CODIGO"
        ),
        None,
    )
    if header_index is None:
        raise ValueError("Cabeçalho CODIGO não encontrado no relatório.")

    header = rows[header_index]
    columns: dict[str, str] = {}
    for column, value in header.items():
        if value is None:
            continue
        normalized = re.sub(r"\s+", " ", str(value).strip().upper())
        columns[normalized] = column

    def find_column(*names: str) -> str | None:
        for name in names:
            normalized = re.sub(r"\s+", " ", name.strip().upper())
            if normalized in columns:
                return columns[normalized]
        return None

    mapping = {
        "codigo": find_column("CODIGO"),
        "tp": find_column("TP"),
        "armz": find_column("ARMZ"),
        "saldo": find_column("SALDO EM ESTOQUE"),
        "valor_estoque": find_column("VALOR EM ESTOQUE"),
        "descricao": find_column("DESCRICAO"),
        "descricao_armazem": find_column("DESCRICAO DO ARMAZEM"),
    }

    required = {
        "CODIGO": mapping["codigo"],
        "TP": mapping["tp"],
        "ARMZ": mapping["armz"],
        "SALDO EM ESTOQUE": mapping["saldo"],
        "VALOR EM ESTOQUE": mapping["valor_estoque"],
    }
    missing = [label for label, column in required.items() if not column]
    if missing:
        raise ValueError(
            "Colunas obrigatórias ausentes: " + ", ".join(missing)
        )

    parsed: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for row_number, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        code_value = row.get(mapping["codigo"])
        if code_value is None or str(code_value).strip() == "":
            continue

        item = {
            "linha": row_number,
            "codigo": str(code_value).strip(),
            "tp": str(row.get(mapping["tp"]) or "").strip(),
            "armz": str(row.get(mapping["armz"]) or "").strip(),
            "saldo": _to_number(row.get(mapping["saldo"])),
            "valor_estoque": _to_number(row.get(mapping["valor_estoque"])),
            "descricao": str(
                row.get(mapping["descricao"]) if mapping["descricao"] else ""
                or ""
            ).strip(),
            "descricao_armazem": str(
                row.get(mapping["descricao_armazem"])
                if mapping["descricao_armazem"]
                else ""
                or ""
            ).strip(),
        }

        reasons: list[str] = []
        if not item["tp"]:
            reasons.append("TP NÃO INFORMADO")
        if not item["armz"]:
            reasons.append("ARMZ NÃO INFORMADO")

        if item["saldo"] is None:
            reasons.append("SALDO INVÁLIDO")
        elif item["saldo"] <= 0:
            reasons.append("SEM SALDO OU SALDO NEGATIVO")

        if item["valor_estoque"] is None:
            reasons.append("VALOR EM ESTOQUE INVÁLIDO")
        elif item["valor_estoque"] <= 0:
            reasons.append("SEM CUSTO OU VALOR NEGATIVO")

        if reasons:
            errors.append({**item, "motivo": " / ".join(reasons)})
        else:
            parsed.append(
                {
                    key: value
                    for key, value in item.items()
                    if key != "linha"
                }
            )

    duplicate_counts = Counter(
        (item["codigo"], item["armz"]) for item in parsed
    )
    duplicates = [
        {"codigo": code, "armz": armz, "ocorrencias": count}
        for (code, armz), count in duplicate_counts.items()
        if count > 1
    ]

    if duplicates:
        for duplicate in duplicates:
            errors.append(
                {
                    "linha": None,
                    "codigo": duplicate["codigo"],
                    "tp": "",
                    "armz": duplicate["armz"],
                    "saldo": None,
                    "valor_estoque": None,
                    "descricao": "",
                    "descricao_armazem": "",
                    "motivo": (
                        "CÓDIGO DUPLICADO NO MESMO ARMAZÉM "
                        f"({duplicate['ocorrencias']} ocorrências)"
                    ),
                }
            )

    total_value = sum(
        float(item["valor_estoque"] or 0)
        for item in parsed
    )

    warehouses = sorted({item["armz"] for item in parsed})
    product_types = sorted({item["tp"] for item in parsed})

    return {
        "file_name": file_name,
        "sheet_name": sheet_name,
        "rows": parsed,
        "errors": errors,
        "total_rows": len(parsed) + len(errors),
        "valid_rows": len(parsed),
        "invalid_rows": len(errors),
        "total_value": total_value,
        "warehouses": warehouses,
        "product_types": product_types,
    }
