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
import pandas as pd
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
    "06000211","06000216","06000217","06000218","06000219",
}

CHAPA_EMAIL_BASE_MAP = {
    # 2500 x 1200
    ("2500X1200", "#12 FINA FRIA"): "06000005",
    ("2500X1200", "#16 FINA FRIA"): "06000031",
    ("2500X1200", "#18 FINA FRIA"): "06000014",
    ("2500X1200", "#12 GALVANIZADA"): "06000167",
    ("2500X1200", "#14 GALVANIZADA"): "06000168",
    ("2500X1200", "#16 GALVANIZADA"): "06000169",
    ("2500X1200", "#18 GALVANIZADA"): "06000187",

    # 3000 x 1200
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

    # Variadas
    ("VARIADAS", "MAGNELIS 1,55"): "06000178",
    ("VARIADAS", "MAGNELIS 1,95"): "06000179",

    # SIVACON
    ("SIVACON", "#12 GALVANIZADA"): "06000219",
    ("SIVACON", "#14 GALVANIZADA"): "06000218",
    ("SIVACON", "#16 GALVANIZADA"): "06000217",
    ("SIVACON", "#20 GALVANIZADA"): "06000216",
    ("SIVACON", "5MM ALUMINIO"): "06000210",
    ("SIVACON", "3MM ALUMINIO"): "06000211",
}

# Chapas de alumínio SIVACON são controladas pelo ERP em peças.
# No e-mail, a coluna PESO TOTAL pode vir vazia; nesses casos a coluna
# CHAPAS é a contagem física válida e deve ser confrontada diretamente
# com o saldo do sistema.
CHAPA_EMAIL_PIECE_CODES = {
    "06000210",  # 5 mm alumínio · 3000x1250
    "06000211",  # 3 mm alumínio · 3000x1250
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


def normalize_bar_identifier(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""

    if re.fullmatch(r"\d+(?:\.0+)?", raw):
        return str(int(float(raw))).zfill(8)

    text = normalize_text(raw).replace(",", ".")
    text = re.sub(
        r"(?<!\d)(\d+)[ .]+(\d+\s*/\s*\d+)",
        lambda m: f"{m.group(1)}+{m.group(2)}",
        text,
    )
    text = re.sub(r"\s*[X×]\s*", "X", text)
    text = re.sub(r"\s*/\s*", "/", text)
    text = re.sub(r"\s+", "", text)
    text = text.replace("MM", "")
    return text


def parse_bar_quantity(
    value: Any,
    quantity_header: str = "",
) -> dict:
    raw = str(value or "").strip()
    header = normalize_text(quantity_header)

    if isinstance(value, (int, float)):
        number = float(value)
    else:
        match = re.search(
            r"[-+]?\d+(?:[.,]\d+)?",
            raw.replace(" ", ""),
        )
        number = (
            float(match.group(0).replace(",", "."))
            if match
            else 0.0
        )

    raw_norm = normalize_text(raw)
    explicit_meters = (
        header in {"MTS", "MT", "METROS", "METRO"}
        or bool(
            re.search(
                r"\b(?:M|MT|MTS|METRO|METROS)\b",
                raw_norm,
            )
        )
    )
    explicit_bars = bool(
        re.search(r"\bBARRA(?:S)?\b", raw_norm)
    )

    if explicit_meters and not explicit_bars:
        mode = "METROS"
        meters = number
    else:
        mode = "BARRAS"
        meters = number * 3.0

    return {
        "quantidade_informada": number,
        "modo_quantidade": mode,
        "quantidade_fisica": meters,
        "quantidade_origem": raw,
    }


def dimension_value_mm(token: str, is_inch: bool) -> float | None:
    raw = str(token or "").strip().replace(",", ".")
    if not raw:
        return None
    try:
        if "/" in raw:
            compact = raw.replace(" ", "")
            if "." in compact:
                whole, frac = compact.split(".", 1)
                num, den = frac.split("/", 1)
                value = float(whole) + float(num) / float(den)
            else:
                num, den = compact.split("/", 1)
                if num.isdigit() and len(num) == 2:
                    value = float(num[0]) + float(num[1]) / float(den)
                else:
                    value = float(num) / float(den)
        else:
            value = float(raw)
    except Exception:
        return None
    if is_inch:
        value *= 25.4
    return value


def bar_dimension_signature(value: Any) -> tuple[float, float] | None:
    text = normalize_text(value).replace(",", ".")
    if not text:
        return None

    largura = re.search(
        r"LARGURA\s+([^ ]+)\s*(MM|POL)",
        text,
    )
    espessura = re.search(
        r"ESPESSURA\s+([^ ]+)\s*(MM|POL)",
        text,
    )

    if largura and espessura:
        a = dimension_value_mm(
            largura.group(1),
            largura.group(2) == "POL",
        )
        b = dimension_value_mm(
            espessura.group(1),
            espessura.group(2) == "POL",
        )
    else:
        pair = re.search(
            r"([^ ]+)\s*[X×]\s*([^ ]+)",
            text,
        )
        if not pair:
            return None

        left = pair.group(1)
        right = pair.group(2)
        is_inch = (
            "/" in left
            or "/" in right
            or "POL" in text
        )
        a = dimension_value_mm(left, is_inch)
        b = dimension_value_mm(right, is_inch)

    if a is None or b is None:
        return None

    values = sorted(
        [float(a), float(b)],
        reverse=True,
    )
    return round(values[0], 3), round(values[1], 3)


def bar_dimension_similarity(
    wanted: tuple[float, float],
    candidate: tuple[float, float],
) -> float:
    """Percentual de proximidade entre duas dimensões já convertidas para mm."""
    errors = []
    for expected, found in zip(wanted, candidate):
        base = max(abs(expected), abs(found), 0.001)
        errors.append(abs(expected - found) / base)

    # O pior eixo governa a similaridade para evitar que uma dimensão
    # muito próxima esconda uma segunda dimensão incorreta.
    score = 100.0 * (1.0 - max(errors))
    return round(max(0.0, min(100.0, score)), 2)


def find_bar_catalog_matches(
    identifier: Any,
    catalog: list[dict],
) -> list[dict]:
    """Retorna candidatos ordenados do mais semelhante para o menos semelhante.

    Prioridades:
    1. código exato;
    2. referência exata;
    3. medida equivalente após conversão mm/polegada;
    4. medida dimensional mais próxima.
    """
    raw = str(identifier or "").strip()
    if not raw:
        return []

    normalized = normalize_bar_identifier(raw)

    exact = []
    for item in catalog:
        code = normalize_code(item.get("codigo"))
        reference = normalize_bar_identifier(
            item.get("referencia")
        )

        if normalized == code:
            match = dict(item)
            match["_match_similarity"] = 100.0
            match["_match_mode"] = "CÓDIGO EXATO"
            match["_match_dimension"] = ""
            return [match]

        if reference and normalized == reference:
            match = dict(item)
            match["_match_similarity"] = 100.0
            match["_match_mode"] = "REFERÊNCIA EXATA"
            match["_match_dimension"] = str(
                item.get("referencia") or ""
            )
            exact.append(match)

    if exact:
        return exact

    wanted = bar_dimension_signature(raw)
    if wanted is None:
        return []

    ranked = []
    for item in catalog:
        best_score = -1.0
        best_dimension = ""
        best_source = ""

        for source_name, source_value in (
            ("REFERÊNCIA", item.get("referencia")),
            ("DESCRIÇÃO", item.get("descricao")),
        ):
            signature = bar_dimension_signature(
                source_value
            )
            if signature is None:
                continue

            score = bar_dimension_similarity(
                wanted,
                signature,
            )
            if score > best_score:
                best_score = score
                best_dimension = (
                    f"{signature[0]:g} x "
                    f"{signature[1]:g} mm"
                )
                best_source = source_name

        if best_score >= 0:
            match = dict(item)
            match["_match_similarity"] = best_score
            match["_match_mode"] = (
                "MEDIDA EQUIVALENTE"
                if best_score >= 99.99
                else f"MEDIDA MAIS PRÓXIMA · {best_source}"
            )
            match["_match_dimension"] = best_dimension
            ranked.append(match)

    ranked.sort(
        key=lambda item: (
            -float(item.get("_match_similarity") or 0),
            str(item.get("codigo") or ""),
        )
    )
    return ranked

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
    """Lê o CADASTROS usando apenas os campos úteis para este módulo.

    Campos principais:
    - CODIGO
    - DESCRICAO
    Campos opcionais:
    - REFERENCIA
    - ULT. PRECO

    CHAPA é sempre tratada em KG e BARRA DE COBRE em MT,
    portanto GRUPO, TP e UNIDADE não participam da conferência.
    """
    wb = openpyxl.load_workbook(
        io.BytesIO(raw),
        data_only=True,
        read_only=True,
    )
    ws = wb[wb.sheetnames[0]]

    required_headers = {"CODIGO", "DESCRICAO"}

    header_row = None
    header_map: dict[str, int] = {}

    for row_index, values in enumerate(
        ws.iter_rows(
            min_row=1,
            max_row=10,
            values_only=True,
        ),
        start=1,
    ):
        current = {
            normalize_text(value): index
            for index, value in enumerate(values)
            if value is not None
            and normalize_text(value)
        }
        if required_headers.issubset(current.keys()):
            header_row = row_index
            header_map = current
            break

    if header_row is None:
        wb.close()
        raise ValueError(
            "Não encontrei as colunas CODIGO e DESCRICAO no CADASTROS."
        )

    code_idx = header_map["CODIGO"]
    desc_idx = header_map["DESCRICAO"]

    reference_idx = None
    for possible in (
        "REFERENCIA",
        "REF.",
        "REF",
        "REFERÊNCIA",
        "COD.REF. FOR",
        "COD REF FOR",
        "COD. REF. FOR",
    ):
        normalized = normalize_text(possible)
        if normalized in header_map:
            reference_idx = header_map[normalized]
            break

    price_idx = None
    for possible in (
        "ULT. PRECO",
        "ULT PRECO",
        "ULTIMO PRECO",
        "ULT. PREÇO",
    ):
        normalized = normalize_text(possible)
        if normalized in header_map:
            price_idx = header_map[normalized]
            break

    ativo_idx = header_map.get("ATIVO")

    indexes = [code_idx, desc_idx]
    if reference_idx is not None:
        indexes.append(reference_idx)
    if price_idx is not None:
        indexes.append(price_idx)
    if ativo_idx is not None:
        indexes.append(ativo_idx)

    max_col = max(indexes) + 1

    candidates: list[dict] = []
    master_lookup: dict[str, dict] = {}
    total_rows_read = 0
    rows_discarded = 0
    known_codes_found = 0
    new_candidates_found = 0
    blocked_rows = 0
    inconsistent_rows = 0
    ok_master_rows = 0

    def master_code(value: Any) -> str:
        if value is None:
            return ""

        if isinstance(value, (int, float)):
            if isinstance(value, float) and not value.is_integer():
                return str(value).strip()
            digits = str(int(value))
            return digits.zfill(8) if len(digits) <= 8 else digits

        return str(value).strip()

    for values in ws.iter_rows(
        min_row=header_row + 1,
        max_col=max_col,
        values_only=True,
    ):
        total_rows_read += 1

        codigo_raw = (
            values[code_idx]
            if code_idx < len(values)
            else None
        )
        if codigo_raw is None or str(codigo_raw).strip() == "":
            rows_discarded += 1
            continue

        codigo_master = master_code(codigo_raw)
        codigo_valido = bool(
            re.fullmatch(r"\d{8}", codigo_master)
        )

        ativo_value = (
            normalize_text(values[ativo_idx])
            if ativo_idx is not None
            and ativo_idx < len(values)
            else ""
        )

        if ativo_idx is not None:
            if ativo_value == "N":
                blocked_rows += 1
                rows_discarded += 1
                continue
            if ativo_value not in ("S", ""):
                inconsistent_rows += 1
                rows_discarded += 1
                continue

        if not codigo_valido:
            inconsistent_rows += 1
            rows_discarded += 1
            continue

        codigo = codigo_master
        ok_master_rows += 1

        descricao = str(
            values[desc_idx]
            if desc_idx < len(values)
            else ""
            or ""
        ).strip()

        referencia = (
            str(values[reference_idx] or "").strip()
            if reference_idx is not None
            and reference_idx < len(values)
            else ""
        )

        ult_preco = (
            to_number(values[price_idx])
            if price_idx is not None
            and price_idx < len(values)
            else 0.0
        )

        master_lookup[codigo] = {
            "codigo": codigo,
            "descricao": descricao,
            "referencia": referencia,
            "ult_preco": ult_preco,
            "ativo": ativo_value,
        }

        desc_norm = normalize_text(descricao)
        ref_norm = normalize_text(referencia)

        categoria = ""
        regra = ""
        status = "CANDIDATO"

        # A base inicial já conhecida permanece confirmada,
        # independentemente de mudanças de descrição no CADASTROS.
        if codigo in INITIAL_CONFIRMED_CODES:
            if codigo.startswith("0011"):
                categoria = "BARRA_COBRE"
            else:
                categoria = "CHAPA"
            regra = "BASE_INICIAL_VALIDADA"
            status = "CONFIRMADO"
            known_codes_found += 1

        # Novos códigos entram como candidato apenas quando a descrição
        # ou referência indicar claramente chapa ou barra de cobre.
        elif (
            "BARRA DE COBRE" in desc_norm
            or desc_norm.startswith("BARRAMENTO COBRE")
            or "BARRA DE COBRE" in ref_norm
        ):
            categoria = "BARRA_COBRE"
            regra = "DESCRICAO_OU_REFERENCIA_BARRA_COBRE"
            new_candidates_found += 1

        elif (
            desc_norm.startswith("CHAPA ")
            or ref_norm.startswith("CHAPA ")
        ):
            categoria = "CHAPA"
            regra = "DESCRICAO_OU_REFERENCIA_CHAPA"
            new_candidates_found += 1

        if not categoria:
            rows_discarded += 1
            continue

        candidates.append(
            {
                "codigo": codigo,
                "categoria": categoria,
                "descricao": descricao,
                "referencia": referencia,
                "grupo": "",
                "tp": "",
                "unidade": (
                    "KG"
                    if categoria == "CHAPA"
                    else "MT"
                ),
                "ult_preco": ult_preco,
                "status": status,
                "origem": file_name,
                "regra_detectada": regra,
            }
        )

    wb.close()

    return {
        "file_name": file_name,
        "candidates": candidates,
        "total_candidates": len(candidates),
        "chapas": sum(
            1
            for row in candidates
            if row["categoria"] == "CHAPA"
        ),
        "barras": sum(
            1
            for row in candidates
            if row["categoria"] == "BARRA_COBRE"
        ),
        "known_codes_found": known_codes_found,
        "new_candidates_found": new_candidates_found,
        "rows_read": total_rows_read,
        "rows_discarded": rows_discarded,
        "master_ok_rows": ok_master_rows,
        "master_blocked_rows": blocked_rows,
        "master_inconsistent_rows": inconsistent_rows,
        "master_lookup": master_lookup,
    }


def parse_cadastros_frame(frame: pd.DataFrame, file_name: str) -> dict:
    """Versão do parser de CADASTROS para SETTA_SOURCE_V1, sem reabrir Excel."""
    rows = [
        list(values)
        for values in frame.itertuples(index=False, name=None)
    ]
    required_headers = {"CODIGO", "DESCRICAO"}
    header_index = None
    header_map: dict[str, int] = {}

    for index, values in enumerate(rows[:10]):
        current = {
            normalize_text(value): col
            for col, value in enumerate(values)
            if value is not None and normalize_text(value)
        }
        if required_headers.issubset(current.keys()):
            header_index = index
            header_map = current
            break

    if header_index is None:
        raise ValueError(
            "Não encontrei as colunas CODIGO e DESCRICAO no CADASTROS."
        )

    code_idx = header_map["CODIGO"]
    desc_idx = header_map["DESCRICAO"]

    reference_idx = None
    for possible in (
        "REFERENCIA",
        "REF.",
        "REF",
        "REFERÊNCIA",
        "COD.REF. FOR",
        "COD REF FOR",
        "COD. REF. FOR",
    ):
        normalized = normalize_text(possible)
        if normalized in header_map:
            reference_idx = header_map[normalized]
            break

    price_idx = None
    for possible in (
        "ULT. PRECO",
        "ULT PRECO",
        "ULTIMO PRECO",
        "ULT. PREÇO",
    ):
        normalized = normalize_text(possible)
        if normalized in header_map:
            price_idx = header_map[normalized]
            break

    ativo_idx = header_map.get("ATIVO")
    candidates: list[dict] = []
    master_lookup: dict[str, dict] = {}
    total_rows_read = 0
    rows_discarded = 0
    known_codes_found = 0
    new_candidates_found = 0
    blocked_rows = 0
    inconsistent_rows = 0
    ok_master_rows = 0

    def master_code(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, (int, float)):
            try:
                if isinstance(value, float) and not float(value).is_integer():
                    return str(value).strip()
            except Exception:
                pass
            digits = str(int(value))
            return digits.zfill(8) if len(digits) <= 8 else digits
        text = str(value).strip()
        if re.fullmatch(r"\d+\.0", text):
            text = text[:-2]
        return text.zfill(8) if text.isdigit() and len(text) <= 8 else text

    for values in rows[header_index + 1 :]:
        total_rows_read += 1
        codigo_raw = values[code_idx] if code_idx < len(values) else None
        if codigo_raw is None or str(codigo_raw).strip() == "":
            rows_discarded += 1
            continue

        codigo_master = master_code(codigo_raw)
        codigo_valido = bool(re.fullmatch(r"\d{8}", codigo_master))

        ativo_value = (
            normalize_text(values[ativo_idx])
            if ativo_idx is not None and ativo_idx < len(values)
            else ""
        )
        if ativo_idx is not None:
            if ativo_value == "N":
                blocked_rows += 1
                rows_discarded += 1
                continue
            if ativo_value not in ("S", ""):
                inconsistent_rows += 1
                rows_discarded += 1
                continue

        if not codigo_valido:
            inconsistent_rows += 1
            rows_discarded += 1
            continue

        codigo = codigo_master
        ok_master_rows += 1
        descricao = str(
            values[desc_idx] if desc_idx < len(values) else ""
            or ""
        ).strip()
        referencia = (
            str(values[reference_idx] or "").strip()
            if reference_idx is not None and reference_idx < len(values)
            else ""
        )
        ult_preco = (
            to_number(values[price_idx])
            if price_idx is not None and price_idx < len(values)
            else 0.0
        )

        master_lookup[codigo] = {
            "codigo": codigo,
            "descricao": descricao,
            "referencia": referencia,
            "ult_preco": ult_preco,
            "ativo": ativo_value,
        }

        desc_norm = normalize_text(descricao)
        ref_norm = normalize_text(referencia)
        categoria = ""
        regra = ""
        status = "CANDIDATO"

        if codigo in INITIAL_CONFIRMED_CODES:
            categoria = "BARRA_COBRE" if codigo.startswith("0011") else "CHAPA"
            regra = "BASE_INICIAL_VALIDADA"
            status = "CONFIRMADO"
            known_codes_found += 1
        elif (
            "BARRA DE COBRE" in desc_norm
            or desc_norm.startswith("BARRAMENTO COBRE")
            or "BARRA DE COBRE" in ref_norm
        ):
            categoria = "BARRA_COBRE"
            regra = "DESCRICAO_OU_REFERENCIA_BARRA_COBRE"
            new_candidates_found += 1
        elif desc_norm.startswith("CHAPA ") or ref_norm.startswith("CHAPA "):
            categoria = "CHAPA"
            regra = "DESCRICAO_OU_REFERENCIA_CHAPA"
            new_candidates_found += 1

        if not categoria:
            rows_discarded += 1
            continue

        candidates.append(
            {
                "codigo": codigo,
                "categoria": categoria,
                "descricao": descricao,
                "referencia": referencia,
                "grupo": "",
                "tp": "",
                "unidade": "KG" if categoria == "CHAPA" else "MT",
                "ult_preco": ult_preco,
                "status": status,
                "origem": file_name,
                "regra_detectada": regra,
            }
        )

    return {
        "file_name": file_name,
        "candidates": candidates,
        "total_candidates": len(candidates),
        "chapas": sum(1 for row in candidates if row["categoria"] == "CHAPA"),
        "barras": sum(1 for row in candidates if row["categoria"] == "BARRA_COBRE"),
        "known_codes_found": known_codes_found,
        "new_candidates_found": new_candidates_found,
        "rows_read": total_rows_read,
        "rows_discarded": rows_discarded,
        "master_ok_rows": ok_master_rows,
        "master_blocked_rows": blocked_rows,
        "master_inconsistent_rows": inconsistent_rows,
        "master_lookup": master_lookup,
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
    # A contagem de chapas chega no início do mês seguinte e pertence
    # ao fechamento do mês imediatamente anterior, mesma regra do Analítico.
    if table_date:
        if table_date.month == 1:
            competencia = date(table_date.year - 1, 12, 1)
        else:
            competencia = date(table_date.year, table_date.month - 1, 1)
    else:
        competencia = None

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

            # Novo modelo: CODIGO + TOTAL FECHAMENTO <MÊS>
            total_col = next(
                (
                    col for col, value in headers.items()
                    if value.startswith("TOTAL FECHAMENTO")
                ),
                None,
            )

            # Modelo antigo: CODIGO + BARRAS + PROCESSADO
            bars_col = next(
                (
                    col for col, value in headers.items()
                    if value.startswith("BARRAS")
                ),
                None,
            )
            processed_col = next(
                (
                    col for col, value in headers.items()
                    if "PROCESSADO" in value
                ),
                None,
            )

            if has_code and (
                total_col is not None
                or (
                    bars_col is not None
                    and processed_col is not None
                )
            ):
                chosen = (
                    ws,
                    row_index,
                    headers,
                    total_col,
                    bars_col,
                    processed_col,
                )
                break

        if chosen:
            break

    if not chosen:
        raise ValueError(
            "Não encontrei uma estrutura válida de barramentos. "
            "É necessário CODIGO + TOTAL FECHAMENTO ou "
            "CODIGO + BARRAS + PROCESSADO."
        )

    (
        ws,
        header_row,
        headers,
        total_col,
        bars_col,
        processed_col,
    ) = chosen

    code_col = next(
        col for col, value in headers.items()
        if value == "CODIGO"
    )
    model_col = next(
        (
            col for col, value in headers.items()
            if "MODELO" in value
        ),
        None,
    )
    consumption_col = next(
        (
            col for col, value in headers.items()
            if value == "CONSUMO"
            or value.startswith("CONSUMO ")
        ),
        None,
    )

    aggregated: dict[str, dict] = {}

    for row_index in range(header_row + 1, ws.max_row + 1):
        codigo = normalize_code(
            ws.cell(row_index, code_col).value
        )
        if not codigo:
            continue

        modelo = (
            str(
                ws.cell(row_index, model_col).value
                or ""
            ).strip()
            if model_col
            else ""
        )

        consumo = (
            to_number(
                ws.cell(row_index, consumption_col).value
            )
            if consumption_col
            else 0.0
        )

        if total_col is not None:
            total = to_number(
                ws.cell(row_index, total_col).value
            )
            barras = 0.0
            processado = 0.0
            criterio = "TOTAL FECHAMENTO"
        else:
            barras = to_number(
                ws.cell(row_index, bars_col).value
            )
            processado = to_number(
                ws.cell(row_index, processed_col).value
            )
            total = barras + processado
            criterio = "BARRAS + PROCESSADO"

        current = aggregated.setdefault(
            codigo,
            {
                "codigo": codigo,
                "quantidade_fisica": 0.0,
                "consumo": 0.0,
                "barras": 0.0,
                "processado": 0.0,
                "modelo": modelo,
                "criterio": criterio,
            },
        )

        current["quantidade_fisica"] += float(
            total or 0
        )
        current["consumo"] += float(
            consumo or 0
        )
        current["barras"] += float(
            barras or 0
        )
        current["processado"] += float(
            processado or 0
        )

        if not current["modelo"]:
            current["modelo"] = modelo

    rows = list(aggregated.values())
    wb.close()

    return {
        "file_name": file_name,
        "rows": rows,
        "total_rows": len(rows),
        "total_metros": sum(
            float(row["quantidade_fisica"] or 0)
            for row in rows
        ),
        "total_consumo": sum(
            float(row["consumo"] or 0)
            for row in rows
        ),
        "consumo_disponivel": consumption_col is not None,
        "criterio": (
            "TOTAL FECHAMENTO"
            if total_col is not None
            else "BARRAS + PROCESSADO"
        ),
    }

def parse_interno_excel(raw: bytes, file_name: str) -> dict:
    wb = openpyxl.load_workbook(
        io.BytesIO(raw),
        data_only=True,
        read_only=True,
    )

    candidates: list[dict] = []
    identifier_names = {
        "CODIGO",
        "BARRAMENTO",
        "MATERIAL",
        "REFERENCIA",
        "REF",
    }
    quantity_names = {
        "MTS",
        "MT",
        "METROS",
        "METRO",
        "QUANTIDADE",
        "QUANTIDADE FISICA",
        "QTD",
        "QNT",
        "BARRAS",
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
                if value in identifier_names
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
                    identificador_raw = ws.cell(
                        data_row,
                        code_col,
                    ).value
                    identificador = str(
                        identificador_raw or ""
                    ).strip()
                    codigo = normalize_bar_identifier(
                        identificador_raw
                    )
                    if not codigo:
                        blank_streak += 1
                        if blank_streak >= 12 and rows:
                            break
                        continue

                    blank_streak = 0
                    quantidade = parse_bar_quantity(
                        ws.cell(data_row, quantity_col).value,
                        quantity_label,
                    )
                    rows.append(
                        {
                            "identificador": identificador,
                            "chave_origem": codigo,
                            "codigo_direto": (
                                codigo
                                if re.fullmatch(r"\d{8}", codigo)
                                else ""
                            ),
                            "quantidade_informada": float(
                                quantidade.get("quantidade_informada") or 0
                            ),
                            "modo_quantidade": str(
                                quantidade.get("modo_quantidade") or ""
                            ),
                            "quantidade_fisica": float(
                                quantidade.get("quantidade_fisica") or 0
                            ),
                            "quantidade_origem": str(
                                quantidade.get("quantidade_origem") or ""
                            ),
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
            "Não encontrei uma estrutura válida. Use preferencialmente "
            "BARRAMENTO + QUANTIDADE ou CODIGO + MTS."
        )

    candidates.sort(
        key=lambda item: len(item["rows"]),
        reverse=True,
    )
    selected = candidates[0]

    aggregated: dict[str, dict] = {}

    for row in selected["rows"]:
        key = str(row.get("chave_origem") or "").strip()
        if not key:
            continue

        current = aggregated.setdefault(
            key,
            {
                "identificador": row.get("identificador") or key,
                "chave_origem": key,
                "codigo_direto": row.get("codigo_direto") or "",
                "quantidade_informada": 0.0,
                "quantidade_fisica": 0.0,
                "modo_quantidade": row.get("modo_quantidade") or "",
                "quantidade_origem": [],
            },
        )
        current["quantidade_informada"] += float(
            row.get("quantidade_informada") or 0
        )
        current["quantidade_fisica"] += float(
            row.get("quantidade_fisica") or 0
        )
        current["quantidade_origem"].append(
            str(row.get("quantidade_origem") or "")
        )

        if (
            current["modo_quantidade"]
            != str(row.get("modo_quantidade") or "")
        ):
            current["modo_quantidade"] = "MISTO"

    rows = []
    for item in aggregated.values():
        item["quantidade_origem"] = " | ".join(
            value
            for value in item["quantidade_origem"]
            if value
        )
        rows.append(item)

    wb.close()

    return {
        "file_name": file_name,
        "sheet": selected["sheet"],
        "quantity_label": selected["quantity_label"],
        "rows": rows,
        "total_rows": len(rows),
        "total_quantidade": sum(
            row["quantidade_fisica"]
            for row in rows
        ),
    }


def resolve_chapa_rows(
    email_rows: list[dict],
    mappings: list[dict],
    catalog: list[dict],
) -> dict:
    # Nova lógica:
    # 1) a matriz DIMENSÃO + DESCRIÇÃO abaixo é a base oficial do e-mail;
    # 2) vínculos manuais persistidos só completam itens fora da matriz;
    # 3) não existe mais fallback automático apenas pela descrição.
    base_mapping: dict[tuple[str, str], dict] = {
        (normalize_text(dim), normalize_text(desc)): {"codigo": codigo}
        for (dim, desc), codigo in CHAPA_EMAIL_BASE_MAP.items()
    }

    manual_exact: dict[tuple[str, str], dict] = {}
    manual_wildcard: dict[str, dict] = {}

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

        if dim in {"", "*"}:
            manual_wildcard[desc] = row
        else:
            manual_exact[(dim, desc)] = row

    catalog_map = {
        str(row.get("codigo") or "").strip(): row
        for row in catalog
        if bool(row.get("ativo", True))
        and str(row.get("status") or "").upper() != "IGNORADO"
        and str(row.get("categoria") or "").upper() == "CHAPA"
    }

    resolved: list[dict] = []
    unresolved: list[dict] = []

    for source_row in email_rows:
        dim = normalize_text(source_row.get("dimensao_norm"))
        desc = normalize_text(source_row.get("descricao_norm"))

        mapping = base_mapping.get((dim, desc))
        if mapping is None:
            mapping = manual_exact.get((dim, desc))
        if mapping is None:
            mapping = manual_wildcard.get(desc)

        codigo = (
            str(mapping.get("codigo") or "").strip()
            if mapping
            else ""
        )
        catalog_item = catalog_map.get(codigo)

        if not codigo or not catalog_item:
            # Regra do fechamento: toda linha recebida precisa possuir
            # vínculo com um código do sistema, mesmo quando a contagem
            # física informada for zero.
            unresolved.append(source_row)
            continue

        peso_total = float(source_row.get("peso_total") or 0)
        chapas = float(source_row.get("chapas") or 0)

        if codigo in CHAPA_EMAIL_PIECE_CODES and peso_total <= 0 and chapas >= 0:
            quantidade = chapas
            criterio = "CHAPAS · PC"
        else:
            quantidade = peso_total
            criterio = "PESO TOTAL · KG"

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
