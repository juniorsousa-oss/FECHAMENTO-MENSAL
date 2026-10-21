"""Read-only reconciliation of MES confirmations, address stock and OP issues."""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

import pandas as pd

import movements as mv

VERSION = "2026-10-21.3"
EPSILON = Decimal("0.000001")
ZERO = Decimal(0)
MISSING = "CONFERIDO SEM SALDO E SEM BAIXA SUFICIENTE"
PROD_PENDING = "SALDO EM G9-PROD PENDENTE DE BAIXA"
SHARED = "DEMANDA COMPARTILHADA MAIOR QUE O SALDO"
NO_QUANTITY = "CONFERÊNCIA SEM QUANTIDADE ATENDIDA"
NO_LOT = "CONFERÊNCIA COM LOTE NÃO INFORMADO"
NO_CODE = "MATERIAL SEM CÓDIGO NO RELATÓRIO GERAL"

GENERAL_FIELDS = {
    "PROJETO": "op", "P.A.": "pa", "DESCRICAO P.A.": "descricao_pa",
    "CODIGO": "codigo", "LOTE": "lote", "DESCRICAO": "descricao",
    "QTD. NECESSARIA": "necessaria", "QTD. ATENDIDA": "atendida",
    "QTD. PENDENCIAS": "pendencia_mes", "RESP. SEPARACAO": "responsavel_separacao",
    "DATA DE SEPARACAO": "separacao", "RESP. CONFERENCIA": "responsavel_conferencia",
    "DATA DE CONFERENCIA": "conferencia", "REPORTADO": "reportado",
    "DATA DE REPORTE": "reporte", "REFERENCIA": "referencia", "COD. FORNECEDOR": "fornecedor",
}
STOCK_FIELDS = {"PRODUTO": "codigo", "ARMAZEM": "armazem", "ENDERECO": "endereco",
                "LOTE": "lote", "QUANTIDADE": "saldo", "EMPENHO": "empenho"}
GENERAL_REQUIRED = {"op", "codigo", "lote", "necessaria", "atendida", "separacao", "conferencia"}
STOCK_REQUIRED = {"codigo", "armazem", "endereco", "lote", "saldo"}


def text(value) -> str:
    if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
        return ""
    return str(value).strip()


def normalized_header(value) -> str:
    return re.sub(r"[^A-Z0-9]", "", mv.normalized(text(value)))


def op_number(value, *, require_prefix=False) -> str:
    value = text(value)
    # Aceita espaços, dois-pontos, barras ou hífens usuais do vínculo da OP,
    # sem aceitar número parcial ou números extras no campo AE.
    expression = r"OP[\s:/-]*(\d+)(?:\.0+)?" if require_prefix else r"(?:OP[\s:/-]*)?(\d+)(?:\.0+)?"
    match = re.fullmatch(expression, value, re.I)
    return match.group(1) if match else ""


def stamp(value) -> str:
    if not text(value):
        return ""
    if isinstance(value, (date, datetime, pd.Timestamp)):
        return value.isoformat()
    value = text(value)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
    except ValueError:
        pass
    for fmt in ("%d/%m/%y %H:%M", "%d/%m/%Y %H:%M", "%d/%m/%y %H:%M:%S",
                "%d/%m/%Y %H:%M:%S", "%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(value, fmt).isoformat()
        except ValueError:
            pass
    try:
        number = mv.decimal(value)
        if number <= 0:
            raise ValueError()
        return (datetime(1899, 12, 30) + timedelta(days=float(number))).isoformat()
    except Exception as exc:
        raise ValueError(f"Data inválida: {value!r}") from exc


def _table(frame: pd.DataFrame, fields: dict, required: set) -> list[dict]:
    aliases = {normalized_header(k): v for k, v in fields.items()}

    def mapping(values):
        return {i: aliases[normalized_header(v)] for i, v in enumerate(values)
                if normalized_header(v) in aliases}

    columns = mapping(frame.columns)
    header = -1
    if not required.issubset(columns.values()):
        for position, row in enumerate(frame.head(25).itertuples(index=False, name=None)):
            columns = mapping(row)
            if required.issubset(columns.values()):
                header = position
                break
        else:
            raise ValueError("Cabeçalho incompatível com o relatório: " + ", ".join(sorted(required)))
    physical = frame.attrs.get("source_rows") or []
    result = []
    # itertuples reduz a criação de Series pandas para cada linha do MES.
    for position, values in enumerate(frame.itertuples(index=False, name=None)):
        if position <= header:
            continue
        if not any(text(v) for v in values):
            continue
        current = {name: values[i] if i < len(values) else None for i, name in columns.items()}
        if normalized_header(current.get("codigo")) in ("CODIGO", "PRODUTO"):
            continue
        if not text(current.get("codigo")) and not text(current.get("op")):
            continue
        current["linha_origem"] = physical[position] if physical else position + (2 if header == -1 else 1)
        result.append(current)
    return result


def parse_general(frame: pd.DataFrame) -> list[dict]:
    rows = _table(frame, GENERAL_FIELDS, GENERAL_REQUIRED)
    for row in rows:
        row["op"] = op_number(row["op"])
        row["codigo"] = mv.identifier(row["codigo"], 8)
        if not row["op"] or (row["codigo"] and not re.fullmatch(r"\d{8}", row["codigo"])):
            raise ValueError(f"OP ou produto inválido na linha {row['linha_origem']} do Relatório Geral.")
        row["item_id"] = row["op"] + ":" + (row["codigo"] or f"SEM_CODIGO_{row['linha_origem']}")
        for key in ("lote", "pa", "descricao_pa", "descricao", "responsavel_separacao",
                    "responsavel_conferencia", "referencia", "fornecedor", "reportado"):
            row[key] = text(row.get(key))
        for key in ("necessaria", "atendida", "pendencia_mes"):
            if key in ("necessaria", "atendida") and not text(row.get(key)):
                raise ValueError(f"Quantidade ausente na linha {row['linha_origem']} do Relatório Geral.")
            row[key] = mv.decimal(row.get(key))
            if row[key] < 0:
                raise ValueError(f"Quantidade negativa na linha {row['linha_origem']} do Relatório Geral.")
        for key in ("separacao", "conferencia", "reporte"):
            row[key] = stamp(row.get(key))
    if not rows:
        raise ValueError("Relatório Geral sem registros de materiais.")
    return rows


def parse_stock(frame: pd.DataFrame) -> list[dict]:
    rows = _table(frame, STOCK_FIELDS, STOCK_REQUIRED)
    for row in rows:
        row["codigo"] = mv.identifier(row["codigo"], 8)
        for key in ("lote", "armazem", "endereco"):
            row[key] = text(row.get(key))
        row["endereco"] = row["endereco"].upper()
        if not re.fullmatch(r"\d{8}", row["codigo"]) or not row["armazem"] or not row["endereco"]:
            raise ValueError(f"Produto, armazém ou endereço inválido na linha {row['linha_origem']} de Endereço.")
        if not text(row.get("saldo")):
            raise ValueError(f"Saldo ausente na linha {row['linha_origem']} de Endereço.")
        row["saldo"] = mv.decimal(row["saldo"])
        row["empenho"] = mv.decimal(row.get("empenho"))
    if not rows:
        raise ValueError("Relatório de Endereço sem registros de estoque.")
    return rows


def parse_raw(raw: bytes, kind: str) -> list[dict]:
    """Legacy Excel fallback, with the same parser used for normalized source rows."""
    sheets = defaultdict(list)
    row_numbers = defaultdict(list)
    for name, number, cells, _epoch in mv._xml_rows(raw):
        width = max((_column_index(c) for c in cells), default=0) + 1
        values = [None] * width
        for col, value in cells.items():
            values[_column_index(col)] = value
        sheets[name].append(values)
        row_numbers[name].append(number)
    parser = parse_general if kind == "relatorio_geral" else parse_stock
    errors = []
    for name, rows in sheets.items():
        frame = pd.DataFrame(rows)
        frame.attrs["source_rows"] = row_numbers[name]
        try:
            return parser(frame)
        except ValueError as exc:
            errors.append(str(exc))
    raise ValueError("; ".join(errors) or "Arquivo sem planilha de dados.")


def _column_index(column: str) -> int:
    result = 0
    for char in column:
        result = result * 26 + ord(char) - ord("A") + 1
    return result - 1


def positive(value: Decimal) -> Decimal:
    return value if value > EPSILON else ZERO


def coverage(metas: list[dict], warehouses=None) -> dict:
    if warehouses and any(m.get("armazem") for m in metas):
        per_warehouse = {warehouse: coverage([m for m in metas if not m.get("armazem") or m["armazem"] == warehouse])
                         for warehouse in warehouses}
        common = next(iter(per_warehouse.values()))["intervalos"]
        for period in list(per_warehouse.values())[1:]:
            common = [[max(a, c), min(b, d)] for a, b in common for c, d in period["intervalos"]
                      if max(a, c) <= min(b, d)]
        return {"inicio": common[0][0] if common else "", "fim": common[-1][1] if common else "",
                "intervalos": common, "por_armazem": per_warehouse}
    intervals = sorted((str(m.get("periodo_inicio") or ""), str(m.get("periodo_fim") or ""))
                       for m in metas if m.get("periodo_inicio") and m.get("periodo_fim"))
    joined = []
    for start, end in intervals:
        date.fromisoformat(start); date.fromisoformat(end)
        if end < start:
            raise ValueError("Período inválido no histórico KARDEX.")
        if joined and start <= (date.fromisoformat(joined[-1][1]) + timedelta(days=1)).isoformat():
            joined[-1][1] = max(joined[-1][1], end)
        else:
            joined.append([start, end])
    return {"inicio": joined[0][0] if joined else "", "fim": joined[-1][1] if joined else "", "intervalos": joined}


def _covered(intervals: list[list[str]], start: str, end: str) -> bool:
    return start <= end and any(first <= start and last >= end for first, last in intervals)


def reconcile(general: list[dict], stock: list[dict], movements: list[dict], *,
              history_metas: list[dict], as_of: str, warehouses: tuple[str, ...] = ("S2",),
              sources_same_day: bool = True, accumulated_history: bool = False) -> dict:
    """Concilia baixas por OP/produto; não atribui consumo sem lote a um lote."""
    date.fromisoformat(as_of)
    warehouses = tuple(warehouses)
    if not warehouses:
        raise ValueError("Selecione ao menos um armazém para a conferência.")
    # A auditoria convencional usa interseção dos períodos dos armazéns.
    # A conferência acumulada aceita históricos independentes: é a UNIÃO
    # de todas as importações até a data de referência, sem exigir período
    # comum entre armazéns. A cobertura individual permanece rastreável.
    if accumulated_history:
        relevant = [m for m in history_metas if not m.get("armazem") or m.get("armazem") in warehouses]
        period = coverage(relevant)
        period["por_armazem"] = {
            warehouse: coverage([m for m in relevant if not m.get("armazem") or m.get("armazem") == warehouse])
            for warehouse in warehouses
        }
        period["modo"] = "ACUMULADO"
    else:
        period = coverage(history_metas, warehouses)
    has_history = any(not meta.get("armazem") or meta["armazem"] in warehouses for meta in history_metas)
    pool, prod_pool = defaultdict(Decimal), defaultdict(Decimal)
    address_pool = defaultdict(Decimal)
    stock_rows = [r for r in stock if r["armazem"] in warehouses]
    for row in stock_rows:
        key = (row["codigo"], row["lote"])
        pool[key] += row["saldo"]
        address_pool[(row["codigo"], row["lote"], row["armazem"], row["endereco"])] += row["saldo"]
        if row["endereco"] == "G9-PROD":
            prod_pool[key] += row["saldo"]
    # Índice por produto/lote elimina varredura de todos os endereços
    # a cada produto com falta de baixa.
    address_index = defaultdict(list)
    for (code, lot, wh, address), quantity in address_pool.items():
        if lot and address != "G9-PROD" and quantity > EPSILON:
            address_index[code, lot].append((wh, address, quantity))
    by_item = defaultdict(list)
    for row in general:
        by_item[row["op"], row["item_id"]].append(row)
    audit_movements, after_snapshot = [], 0
    outgoing_totals, incoming_totals = defaultdict(Decimal), defaultdict(Decimal)
    scoped_movements = []
    for idx, raw in enumerate(movements):
        if raw.get("armazem") not in warehouses:
            continue
        if str(raw.get("data") or "")[:10] > as_of:
            after_snapshot += 1
            continue
        row = dict(raw)
        # Identifica compensações com todo o KARDEX do armazém, inclusive o
        # par de entrada que pode não conter a OP na AE original.
        row.setdefault("id_registro", f"auditoria-{idx}")
        row.setdefault("enderecamento_compensado", False)
        for field in ("codigo", "armazem", "um", "documento", "data", "tes"):
            row.setdefault(field, "")
        scoped_movements.append(row)
    mv.match_addresses(scoped_movements)
    for row in scoped_movements:
        number = op_number(row.get("ae_original"), require_prefix=True)
        if not number:
            continue
        row["op"] = number
        tes = str(row.get("tes") or "").zfill(3)
        paired = bool(row.get("enderecamento_compensado"))
        row["natureza"] = (
            "ENDEREÇAMENTO COMPENSADO" if paired
            else "ENDEREÇAMENTO" if tes == "499"
            else "CONSUMO DE OP" if tes == "999"
            else "BAIXA / DEVOLUÇÃO"
        )
        audit_movements.append(row)
        if row["natureza"] in ("BAIXA / DEVOLUÇÃO", "CONSUMO DE OP"):
            outgoing_totals[number, row["codigo"]] += mv.decimal(row.get("qtd_saida"))
            incoming_totals[number, row["codigo"]] += mv.decimal(row.get("qtd_entrada"))
    ops_with_issues = {number for (number, code), amount in outgoing_totals.items()
                       if positive(amount - incoming_totals[number, code])}
    items, lot_rows = [], []
    min_pending, max_pending, pending_ops = defaultdict(Decimal), defaultdict(Decimal), defaultdict(set)
    for (number, item_id), rows in by_item.items():
        code = rows[0]["codigo"]
        confirmed = [r for r in rows if r["conferencia"]]
        confirmed_lots = defaultdict(Decimal)
        for row in confirmed:
            confirmed_lots[row["lote"]] += row["atendida"]
        c = sum(confirmed_lots.values(), ZERO)
        outgoing = outgoing_totals[number, code]
        incoming = incoming_totals[number, code]
        net = outgoing - incoming
        pending = positive(c - max(net, ZERO)) if has_history else None
        available = sum((min(amount, max(pool[code, lot], ZERO)) for lot, amount in confirmed_lots.items() if lot), ZERO)
        prod = sum((min(amount, max(prod_pool[code, lot], ZERO)) for lot, amount in confirmed_lots.items() if lot), ZERO)
        missing = positive(pending - available) if pending is not None else None
        in_prod = min(pending, prod) if pending is not None else None
        alerts = []
        if not code:
            alerts.append(NO_CODE)
            missing = None
            in_prod = None
        if any(not r["atendida"] for r in confirmed):
            alerts.append(NO_QUANTITY)
        if any(not r["lote"] and r["atendida"] > 0 for r in confirmed):
            alerts.append(NO_LOT)
            missing = None
        if missing is not None and missing > 0:
            alerts.append(MISSING)
        if (in_prod is not None and in_prod > EPSILON
                and pending is not None and pending > EPSILON
                and any(r["separacao"] for r in rows)
                and number in ops_with_issues):
            alerts.append(PROD_PENDING)
        # Endereços alternativos são sugestões de localização, não reservas:
        # prioriza saldos que cobrem a falta no G9-PROD, começando pelo mais
        # próximo da quantidade faltante. Nunca mistura lotes distintos.
        shortage_g9 = positive(pending - max(prod, ZERO)) if pending is not None else ZERO
        alternatives = []
        if confirmed and shortage_g9 > EPSILON:
            for lot in confirmed_lots:
                for wh, address, quantity in address_index.get((code, lot), ()):
                    alternatives.append({"armazem": wh, "endereco": address,
                                         "lote": lot, "saldo": quantity})
            alternatives.sort(key=lambda candidate: (
                candidate["saldo"] < shortage_g9,
                abs(candidate["saldo"] - shortage_g9),
                -candidate["saldo"], candidate["armazem"], candidate["endereco"]
            ))
        first_date = min((r["conferencia"][:10] for r in confirmed), default=as_of)
        # No modo acumulado não se exige cobertura ininterrupta até a data
        # atual. Ausência de histórico comprovado de um intervalo pode ser
        # consultada no detalhamento técnico, mas não impede somar as baixas.
        incomplete = (bool(confirmed) and not sources_same_day) if accumulated_history else (
            bool(confirmed) and (not sources_same_day or not _covered(period["intervalos"], first_date, as_of))
        )
        item = {"item_id": item_id, "op": number, "codigo": code, "descricao": rows[0]["descricao"],
                "itens": len(rows), "itens_separados": sum(bool(r["separacao"]) for r in rows),
                "itens_conferidos": len(confirmed), "op_possui_baixa": number in ops_with_issues,
                "necessaria": sum((r["necessaria"] for r in rows), ZERO),
                "atendida": sum((r["atendida"] for r in rows), ZERO),
                "separada": sum((r["atendida"] for r in rows if r["separacao"]), ZERO),
                "conferida": c,
                "saida_bruta": outgoing if has_history else None, "devolvida": incoming if has_history else None,
                "baixada": net if has_history else None, "pendente": pending,
                "saldo": sum((pool[code, lot] for lot in confirmed_lots if lot), ZERO),
                "saldo_g9_prod": sum((prod_pool[code, lot] for lot in confirmed_lots if lot), ZERO),
                "outros_enderecos": " | ".join(
                    f"{entry['armazem']}/{entry['endereco']} · lote {entry['lote']}: {entry['saldo']}"
                    for entry in alternatives
                ),
                "enderecos_alternativos": alternatives,
                "cobertura_saldo": available, "sem_saldo": missing, "em_g9_prod": in_prod,
                "lotes": ", ".join(sorted({r["lote"] or "(não informado)" for r in rows})),
                "alertas": alerts, "historico_incompleto": incomplete, "saldo_compartilhado": False,
                "conflito_saldo": False, "primeira_conferencia": first_date if confirmed else ""}
        items.append(item)
        for lot in sorted({r["lote"] for r in rows}):
            line = {"item_id": item_id, "op": number, "codigo": code, "lote": lot, "conferida": confirmed_lots.get(lot, ZERO),
                    "saldo": pool[code, lot], "saldo_g9_prod": prod_pool[code, lot]}
            # Bounds retain ambiguity when the same OP/product has multiple lots.
            line["pendente_minima"] = positive(line["conferida"] - max(net, ZERO)) if has_history else None
            line["pendente_maxima"] = min(line["conferida"], pending) if pending is not None else None
            lot_rows.append(line)
            if lot and line["pendente_maxima"] is not None and line["pendente_maxima"] > EPSILON:
                key = (code, lot)
                min_pending[key] += line["pendente_minima"]
                max_pending[key] += line["pendente_maxima"]
                pending_ops[key].add(number)
    lot_index = defaultdict(list)
    for row in lot_rows:
        lot_index[row["item_id"]].append(row)
    for item in items:
        for lot in lot_index[item["item_id"]]:
            key = (item["codigo"], lot["lote"])
            lot["ops_com_demanda"] = len(pending_ops[key])
            lot["demanda_compartilhada_minima"] = min_pending[key]
            lot["demanda_compartilhada_maxima"] = max_pending[key]
            lot["saldo_compartilhado"] = len(pending_ops[key]) > 1
            if lot["pendente_maxima"] is not None and lot["pendente_maxima"] > EPSILON and lot["saldo_compartilhado"]:
                item["saldo_compartilhado"] = True
                if positive(min_pending[key] - max(pool[key], ZERO)):
                    item["conflito_saldo"] = True
        if item["conflito_saldo"] and not item["sem_saldo"]:
            item["alertas"].append(SHARED)
        item["divergente"] = bool(item["alertas"])
        if item["alertas"]:
            item["status"] = " · ".join(item["alertas"])
        elif not item["itens_conferidos"]:
            item["status"] = "AGUARDANDO CONFERÊNCIA" if item["itens_separados"] else "AGUARDANDO SEPARAÇÃO"
        elif not has_history:
            item["status"] = "AGUARDANDO KARDEX"
        elif not item["pendente"]:
            item["status"] = "BAIXA IDENTIFICADA"
        elif item["em_g9_prod"] and not item["op_possui_baixa"]:
            item["status"] = "SALDO G9-PROD — OP SEM BAIXAS NO HISTÓRICO"
        else:
            item["status"] = "SALDO EM OUTROS ENDEREÇOS — BAIXA A CONFERIR"
    items_frame = pd.DataFrame(items)
    ops = []
    general_ops = defaultdict(list)
    item_ops = defaultdict(list)
    for row in general:
        general_ops[row["op"]].append(row)
    for item in items:
        item_ops[item["op"]].append(item)
    for number, rows in general_ops.items():
        group = item_ops[number]
        ops.append({"op": number, "pa": ", ".join(sorted({r["pa"] for r in rows if r["pa"]})),
                    "descricao_pa": " / ".join(dict.fromkeys(r["descricao_pa"] for r in rows if r["descricao_pa"])),
                    # Contadores do cabeçalho seguem a mesma unidade da
                    # tabela: código de produto por OP, não linhas duplicadas
                    # de lote/fonte no Relatório Geral.
                    "produtos": len(group), "itens": len(group),
                    "separados": sum(bool(item["itens_separados"]) for item in group),
                    "conferidos": sum(bool(item["itens_conferidos"]) for item in group),
                    "linhas_mes": len(rows),
                    "linhas_separadas_mes": sum(bool(r["separacao"]) for r in rows),
                    "linhas_conferidas_mes": sum(bool(r["conferencia"]) for r in rows),
                    "baixados": sum(
                        r["itens_conferidos"] for r in group
                        if r["conferida"] > EPSILON and r["baixada"] is not None
                        and r["pendente"] is not None and r["pendente"] <= EPSILON
                    ),
                    "divergencias": sum(r["divergente"] for r in group),
                    "incompletos": sum(r["historico_incompleto"] for r in group)})
    diagnostics = {
        "movimentos_no_periodo": len(scoped_movements),
        "movimentos_op_reconhecida": len(audit_movements),
        "consumos_vinculados": sum(
            row["natureza"] in ("BAIXA / DEVOLUÇÃO", "CONSUMO DE OP")
            and mv.decimal(row.get("qtd_saida")) > ZERO
            for row in audit_movements
        ),
        "tes_999_sem_compensacao": sum(
            str(row.get("tes") or "").zfill(3) == "999"
            and not row.get("enderecamento_compensado")
            for row in audit_movements
        ),
        "enderecamentos_compensados": sum(
            bool(row.get("enderecamento_compensado")) for row in scoped_movements
        ),
    }
    return {"items": items_frame, "ops": pd.DataFrame(ops), "lots": pd.DataFrame(lot_rows),
            "general": general, "stock": stock_rows, "movements": audit_movements,
            "coverage": period, "as_of": as_of, "warehouses": warehouses,
            "history_available": has_history, "movimentos_apos_base": after_snapshot,
            "diagnostico_baixas": diagnostics,
            "negative_stock_rows": sum(r["saldo"] < 0 for r in stock_rows),
            "accumulated_history": accumulated_history, "version": VERSION}
