"""Fonte persistente das baixas por OP, material e LOTE (Relatório OPS).

Substitui o uso do KARDEX apenas na Conferência de Baixas. Cada nova
importação representa uma fotografia histórica completa, nunca um
incremento adicionado à anterior. O KARDEX gerencial permanece intacto.
"""
from __future__ import annotations

import base64
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
import gzip
import hashlib
import io
import json
import re

import requests

import inventory_db as db
import movements as mv

KEY = "fm_conferencia_ops_lotes_v1"
FORMAT = "setta_ops_lotes_v1"
VERSION = "2026-11-03.1"
# Código de movimento em C e TES/TP em O: não confundir entrada de
# produto acabado PR0/010 nem transferência RE1/999 com consumo de OP.
ISSUES = {("RE0", "520"), ("RE0", "550"), ("RE6", "550")}
RETURNS = {("DE0", "020")}
REQUIRED = {"B": "ORDPRODUCAO", "D": "PRODUTO", "F": "QUANTIDADE",
            "K": "DTEMISSAO", "N": "LOTE"}


def lot(value) -> str:
    """Mantém zeros à esquerda e não confunde vazio com lote fictício."""
    raw = str(value or "").strip()
    if re.fullmatch(r"\d+\.0+", raw):
        raw = raw.split(".")[0]
    return raw


def _op(value) -> str:
    match = re.fullmatch(r"(?:OP[\s:/-]*)?(\d+)(?:\.0+)?",
                         str(value or "").strip(), re.IGNORECASE)
    return match.group(1) if match else ""


def parse(raw: bytes, file_name: str) -> dict:
    if not file_name.lower().endswith((".xlsx", ".xltx")):
        raise ValueError("Envie o relatório OPS em formato XLSX ou XLTX.")
    digest = hashlib.sha256(raw).hexdigest()
    seen_headers = set()
    grouped = defaultdict(Decimal)
    representative = {}
    stats = Counter()
    dates = set()
    errors = []
    for sheet, line, cells, epoch in mv._xml_rows(raw):
        headers = {col: re.sub(r"[^A-Z0-9]", "", mv.normalized(cells.get(col, "")))
                   for col in REQUIRED}
        if all(headers[k] == v for k, v in REQUIRED.items()):
            seen_headers.add(sheet)
            continue
        if sheet not in seen_headers:
            continue
        movement_type = str(cells.get("C") or "").strip().upper()
        tes = mv.identifier(cells.get("O"), 3)
        kind = (movement_type, tes)
        if kind not in ISSUES and kind not in RETURNS:
            stats["outros_movimentos_ignorados"] += 1
            continue
        try:
            op = _op(cells.get("B"))
            code = mv.identifier(cells.get("D"), 8)
            if not op or not re.fullmatch(r"\d{8}", code):
                raise ValueError("OP ou código de produto inválido")
            d = mv._date(cells.get("K"), epoch)
            quantity = mv.decimal(cells.get("F"))
            if kind in ISSUES and quantity < 0:
                raise ValueError("requisição com quantidade negativa")
            if kind in RETURNS and quantity > 0:
                raise ValueError("devolução com sinal positivo")
            if not quantity:
                stats["quantidade_zero"] += 1
                continue
            lote = lot(cells.get("N"))
            # O valor do tipo de movimento é mantido para auditoria.
            key = (op, code, lote, d, movement_type, tes)
            grouped[key] += quantity
            representative.setdefault(key, (str(cells.get("J") or ""), line))
            dates.add(d)
            stats["movimentos_validos"] += 1
            if not lote:
                stats["movimentos_sem_lote"] += 1
        except (ValueError, TypeError) as exc:
            errors.append(f"{sheet}, linha {line}: {exc}")
            if len(errors) >= 20:
                break

    if not seen_headers:
        raise ValueError(
            "Cabeçalho OPS não localizado. Esperado: B Ord Producao, "
            "D Produto, F Quantidade, K DT Emissao e N Lote."
        )
    if errors:
        raise ValueError(
            "O arquivo possui movimentações inconsistentes. Importação bloqueada: "
            + "; ".join(errors[:8])
        )
    if not grouped:
        raise ValueError("Não foram identificadas requisições/devoluções de OP válidas.")
    rows = []
    for key, qty in sorted(grouped.items()):
        if not qty:
            continue
        op, code, lote, day, movement_type, tes = key
        document, source_line = representative[key]
        rows.append({
            "op": op, "codigo": code, "lote": lote, "data": day,
            "tipo_movimento": movement_type, "tes": tes,
            "quantidade": str(qty), "documento": document,
            "linha_origem": source_line,
        })
    meta = {
        "arquivo_nome": file_name, "sha256": digest,
        "linhas_lidas": stats["movimentos_validos"] + stats["outros_movimentos_ignorados"]
                        + stats["quantidade_zero"],
        "movimentos_validos": stats["movimentos_validos"],
        "movimentos_sem_lote": stats["movimentos_sem_lote"],
        "outros_movimentos_ignorados": stats["outros_movimentos_ignorados"],
        "registros_consolidados_por_dia": len(rows),
        "periodo_inicio": min(dates), "periodo_fim": max(dates),
        "politica": "SUBSTITUIR_FOTOGRAFIA_COMPLETA",
        "versao": VERSION,
    }
    return {"meta": meta, "rows": rows}


def _pack(imported: dict) -> dict:
    rows = imported["rows"]
    encoded = json.dumps([
        [r[k] for k in (
            "op", "codigo", "lote", "data", "tipo_movimento",
            "tes", "quantidade", "documento", "linha_origem",
        )] for r in rows
    ], ensure_ascii=False, separators=(",", ":")).encode()
    payload = base64.b64encode(gzip.compress(encoded, compresslevel=6, mtime=0)).decode()
    return {"formato": FORMAT, "meta": dict(imported["meta"]),
            "encoding": "gzip+base64", "payload": payload}


def _unpack(packed: dict) -> dict:
    if packed.get("formato") != FORMAT or packed.get("encoding") != "gzip+base64":
        raise ValueError("Fotografia OPS incompatível; faça uma nova importação.")
    data = json.loads(gzip.decompress(base64.b64decode(packed["payload"], validate=True)))
    keys = ("op", "codigo", "lote", "data", "tipo_movimento",
            "tes", "quantidade", "documento", "linha_origem")
    rows = [dict(zip(keys, row)) for row in data]
    if len(rows) != int(packed["meta"]["registros_consolidados_por_dia"]):
        raise ValueError("Fotografia OPS corrompida: quantidade de registros difere do manifesto.")
    return {"meta": packed["meta"], "rows": rows}


def read_meta() -> dict:
    response = requests.get(
        f"{db.supabase_url()}/rest/v1/fm_configuracoes",
        headers=db._headers(),
        params={"select": "meta:valor->meta,atualizado_em",
                "chave": f"eq.{KEY}", "limit": "1"},
        timeout=30,
    )
    db._raise(response)
    values = response.json() or []
    if not values:
        return {}
    return {**(values[0].get("meta") or {}),
            "atualizado_em": str(values[0].get("atualizado_em") or "")}


def load() -> dict:
    response = requests.get(
        f"{db.supabase_url()}/rest/v1/fm_configuracoes",
        headers=db._headers(),
        params={"select": "valor", "chave": f"eq.{KEY}", "limit": "1"},
        timeout=90,
    )
    db._raise(response)
    values = response.json() or []
    if not values:
        return {}
    return _unpack(values[0]["valor"])


def save(parsed: dict, *, current: dict | None = None) -> dict:
    old = current if current is not None else read_meta()
    if old.get("sha256") == parsed["meta"]["sha256"]:
        return {"saved": False, "meta": old}
    db.rpc("fm_salvar_configuracao",
           {"p_chave": KEY, "p_valor": _pack(parsed)}, timeout=120)
    actual = read_meta()
    if actual.get("sha256") != parsed["meta"]["sha256"]:
        raise RuntimeError("A gravação OPS não retornou a versão esperada.")
    return {"saved": True, "meta": actual}


def movements_as_of(records: list[dict], reference: str, *, ops: set[str]) -> tuple[list[dict], int]:
    """Evidências filtradas à data-base, sem filtrar por armazém inexistente no OPS."""
    result = []
    future = 0
    for row in records:
        if row["data"] > reference:
            future += 1
            continue
        if row["op"] not in ops:
            continue
        amount = mv.decimal(row["quantidade"])
        if not amount:
            continue
        result.append({
            "op": row["op"], "codigo": row["codigo"], "lote": lot(row["lote"]),
            "data": row["data"], "tes": row["tes"], "tipo_movimento": row["tipo_movimento"],
            "qtd_saida": str(max(amount, 0)), "qtd_entrada": str(max(-amount, 0)),
            "quantidade": str(amount), "natureza": "BAIXA / DEVOLUÇÃO",
            "ae_original": "OP" + row["op"], "documento": row.get("documento") or "",
            "armazem": "", "arquivo_origem": "RELATÓRIO OPS",
            "linha_origem": row.get("linha_origem", 0),
        })
    return result, future
