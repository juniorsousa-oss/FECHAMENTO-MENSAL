"""Relatórios gerenciais do fechamento SETTA.

Exporta uma única planilha por relatório escolhido, sem alterar bases,
regras de conferência ou lançamentos originais.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
import math

import pandas as pd
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


HEADER = "17243B"
LINE = "F2F6FB"
WARNING = "FDE8E8"
MONEY_FORMAT = '#,##0.00;[Red](#,##0.00)'
# "General" respeita a configuração regional do Excel e evita o
# separador decimal isolado que o formato #,##0.###### gerava no pt-BR.
QUANTITY_FORMAT = "General"
QUANTITY_INTEGER_FORMAT = "General"
EXPORT_SCHEMA_VERSION = "2026-11-04.5-OPS-LOT-DETAIL-R12"
PERCENT_FORMAT = '0.00%;[Red](0.00%)'

# Formato homologado: cabeçalho da OP repetido e, à direita, a mesma
# tabela de materiais que aparece ao expandir a OP na Conferência de Baixas.
# Cada linha representa um produto da OP, com lotes já consolidados pelo MES.
# A base Geral, suas linhas e a conciliação por lote NÃO são alteradas aqui.
OP_FIELDS = [
    ("OP", "op"),
    ("Produtos totais", "itens"),
    ("Produtos separados", "separados"),
    ("Produtos conferidos", "conferidos"),
    ("Produtos baixados", "baixados"),
    ("Produtos com alerta", "divergencias"),
    ("Cliente", "cliente"),
    ("Condição", "condicao"),
    ("Nota fiscal", "nota_fiscal"),
    ("Faturamento", "data_faturamento"),
    ("Pátio", "dias_patio"),
    ("Status da OP", "status_op"),
]
ISSUE_ITEM_FIELDS = [
    ("Produto", "codigo"),
    ("Descrição", "descricao"),
    ("Lotes", "lotes"),
    ("Qtd necessária", "necessaria"),
    ("Qtd separada", "separada"),
    ("Qtd conferida", "conferida"),
    ("Qtd baixada", "baixada"),
    ("Qtd pendente baixa", "pendente"),
    ("Valor previsto da baixa (R$)", "valor_previsto_baixa"),
    ("Saldo no lote conferido", "saldo"),
    ("Saldo G9-PROD", "saldo_g9_prod"),
    ("Outros endereços", "outros_enderecos"),
    ("Resultado", "status"),
]
OP_COLUMNS = [name for name, _ in OP_FIELDS + ISSUE_ITEM_FIELDS]
ISSUE_QUANTITY_NAMES = {
    "Qtd necessária", "Qtd separada", "Qtd conferida", "Qtd baixada",
    "Qtd pendente baixa", "Saldo no lote conferido", "Saldo G9-PROD",
}
ISSUE_COUNT_NAMES = {
    "Produtos totais", "Produtos separados", "Produtos conferidos",
    "Produtos baixados", "Produtos com alerta",
}
ISSUE_MONEY_NAMES = {"Valor previsto da baixa (R$)"}

def _cell(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()[:10]
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(x) for x in value)
    if isinstance(value, dict):
        return str(value)
    if isinstance(value, str):
        if value.startswith(("=", "+", "-", "@")):
            return "'" + value
        return value
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _date(value) -> date | None:
    if value is None or str(value).strip() in ("", "NI", "None"):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value).strip()
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        for fmt in ("%d/%m/%Y", "%d/%m/%y"):
            try:
                return datetime.strptime(raw[:10], fmt).date()
            except ValueError:
                pass
    return None


def _period(start: date | None, end: date | None):
    if start is not None and end is not None and start > end:
        raise ValueError("A data inicial não pode ser maior que a final.")


def _between(value, start: date | None, end: date | None) -> bool:
    parsed = _date(value)
    return parsed is not None and (start is None or parsed >= start) and (end is None or parsed <= end)


def activity_evidence(model: dict, start: date | None, end: date | None) -> dict[str, list[tuple[date, str]]]:
    """Eventos rastreáveis que justificam inclusão; respeita o corte MES."""
    _period(start, end)
    reference = _date(model.get("as_of"))
    effective_end = min(end, reference) if end and reference else end or reference
    if start and effective_end and start > effective_end:
        return {}
    events: dict[str, list[tuple[date, str]]] = {}
    def add(op: str, value: object, kind: str):
        when = _date(value)
        if not when or (start and when < start) or (effective_end and when > effective_end):
            return
        events.setdefault(str(op), []).append((when, kind))
    for item in model.get("general") or []:
        add(item["op"], item.get("separacao"), "SEPARAÇÃO")
        add(item["op"], item.get("conferencia"), "CONFERÊNCIA")
    for movement in model.get("movements") or []:
        if movement.get("natureza") not in ("BAIXA / DEVOLUÇÃO", "CONSUMO DE OP"):
            continue
        if (abs(float(movement.get("qtd_saida") or 0)) == 0
                and abs(float(movement.get("qtd_entrada") or 0)) == 0):
            continue
        add(movement.get("op") or "", movement.get("data"), "BAIXA/DEVOLUÇÃO")
    return events


def selection_diagnostics(model: dict, start: date | None, end: date | None,
                          *, include_activity: bool = False) -> dict:
    """Por padrão, filtrar estritamente pelo FATURAMENTO na data selecionada.

    Incluir movimentações é opção expressa: adiciona OPs com separação,
    conferência ou baixa OPS no período (mesmo com faturamento NI, anterior
    ou posterior). A opção nunca restringe OPs efetivamente faturadas no mês.
    """
    _period(start, end)
    ops = {str(item["op"]): item for item in model["ops"].to_dict("records")}
    has_period = start is not None or end is not None
    if has_period:
        billed = {
            op for op, header in ops.items()
            if _between(header.get("data_faturamento"), start, end)
        }
    else:
        # Histórico completo continua mostrando todas as OPs da base.
        billed = set(ops)
    events = (
        activity_evidence(model, start, end)
        if include_activity and has_period else {}
    )
    added_by_activity = (set(events) & set(ops)) - billed
    selected = billed | added_by_activity
    excluded_missing_billing = []
    excluded_outside_billing = []
    excluded_prior_billing = {}
    for op, header in ops.items():
        if op in selected:
            continue
        billing = _date(header.get("data_faturamento"))
        if billing is None:
            excluded_missing_billing.append(op)
        else:
            excluded_outside_billing.append(op)
            if start and billing < start:
                excluded_prior_billing[op] = {
                    "faturamento": billing.isoformat(),
                    "motivo": "FATURAMENTO ANTERIOR AO PERÍODO",
                }
    unreadable_billing = sorted(
        op for op in selected
        if str(ops[op].get("data_faturamento") or "").strip().upper()
        not in ("", "NI", "N/I", "NONE", "NAN") and
        _date(ops[op].get("data_faturamento")) is None
    )
    return {
        "selected": selected,
        "billed_in_period": billed,
        "added_by_activity": added_by_activity,
        "excluded_missing_billing": sorted(excluded_missing_billing),
        "excluded_outside_billing": sorted(excluded_outside_billing),
        "excluded_prior_billing": excluded_prior_billing,
        "events": events,
        "unreadable_billing": unreadable_billing,
    }


def ops_with_activity(model: dict, start: date | None, end: date | None,
                      *, include_activity: bool = False) -> set[str]:
    """Compatibilidade: seleção fiscal padrão, com atividade opcional."""
    return selection_diagnostics(
        model, start, end, include_activity=include_activity,
    )["selected"]


class _Excel:
    """Escrita streaming com cabeçalho fixo, autofiltro e formatação de colunas."""
    def __init__(self):
        self.workbook = Workbook(write_only=True)
        self.sheets = {}

    def sheet(self, name, headers, *, money=(), quantity=(), percent=(), alert_column=None):
        ws = self.workbook.create_sheet(name[:31])
        ws.sheet_view.showGridLines = False
        ws.freeze_panes = "A2"
        for i, header in enumerate(headers, 1):
            width = min(60, max(16, len(header) + 4))
            if header in ("Descrição", "Outros endereços", "Resultado"):
                width = 46
            ws.column_dimensions[get_column_letter(i)].width = width
        self.sheets[name] = (ws, list(headers), set(money), set(quantity),
                             set(percent), alert_column, 1)
        self.add(name, headers, header=True)
        return ws

    def add(self, name, values, *, header=False, alert=False):
        ws, headers, money, quantities, percents, alert_column, count = self.sheets[name]
        row = []
        for i, value in enumerate(values):
            value = _cell(value)
            c = WriteOnlyCell(ws, value)
            if isinstance(value, str):
                c.data_type = "s"
            if header:
                c.fill = PatternFill("solid", fgColor=HEADER)
                c.font = Font(name="Aptos", size=10, bold=True, color="FFFFFF")
                c.alignment = Alignment(vertical="center", wrap_text=True)
            else:
                c.font = Font(name="Aptos", size=10, color="17243B")
                if alert and (alert_column is None or alert_column == i):
                    c.fill = PatternFill("solid", fgColor=WARNING)
                    if alert_column == i:
                        c.font = Font(name="Aptos", size=10, color="991B1B", bold=True)
                elif count % 2 == 0 and i != alert_column:
                    # Na Conferência, Resultado sem alerta fica sem
                    # demarcação (inclusive nas linhas alternadas).
                    c.fill = PatternFill("solid", fgColor=LINE)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    if i in money:
                        c.number_format = MONEY_FORMAT
                    elif i in quantities:
                        # Excel reconhece o valor numérico e determina como
                        # exibir o separador decimal conforme o idioma local.
                        c.number_format = QUANTITY_FORMAT
                    elif i in percents:
                        c.number_format = PERCENT_FORMAT
            row.append(c)
        ws.append(row)
        self.sheets[name] = (ws, headers, money, quantities, percents, alert_column, count + 1)
        if header:
            ws.row_dimensions[1].height = 32

    def save(self) -> bytes:
        for name, (ws, headers, *_rest) in self.sheets.items():
            ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{self.sheets[name][-1] - 1}"
        output = BytesIO()
        self.workbook.save(output)
        return output.getvalue()


STOCK_HEADERS = ["Competência", "Estoque inicial (R$)", "Estoque final (R$)",
                 "Resumo (R$)", "Variação (%)", "Validação", "Fonte"]


def stock_data(summaries: list[dict], imports: list[dict],
               start: date | None = None, end: date | None = None) -> dict:
    """Reusa o valor_total mensal do Dashboard; não soma meses como saldo."""
    _period(start, end)
    imports_map = {str(x.get("competencia") or "")[:10]: x for x in imports}
    values = {
        (str(r.get("competencia") or "")[:10], str(r.get("dimensao") or ""), str(r.get("chave") or "")):
        float(r.get("valor_total") or 0)
        for r in summaries
    }
    months = sorted(d for key in imports_map if (d := _date(key)) is not None)
    months = [d for d in months if (start is None or d.year * 12 + d.month >= start.year * 12 + start.month)
              and (end is None or d.year * 12 + d.month <= end.year * 12 + end.month)]
    all_month_keys = set(imports_map)
    entries = []
    for month in months:
        key = month.isoformat()
        prev = date(month.year - (month.month == 1), month.month - 1 or 12, 1)
        prior_exists = prev.isoformat() in all_month_keys
        prior_key = prev.isoformat()
        final = values.get((key, "TOTAL", "TOTAL"))
        initial = values.get((prior_key, "TOTAL", "TOTAL")) if prior_exists else None
        if final is None:
            continue
        info = imports_map[key]
        summary = final - initial if initial is not None else None
        change = summary / abs(initial) if initial not in (None, 0) else None
        common = [month.strftime("%m/%Y"), initial, final, summary, change,
                  str(info.get("status") or "NI"), "PRÉVIA" if info.get("preview") else "FECHAMENTO"]
        entries.append((month, common))
    def dimension_rows(dim, prefix):
        results = []
        for month, common in entries:
            key = month.isoformat()
            prev = date(month.year - (month.month == 1), month.month - 1 or 12, 1).isoformat()
            codes = {
                k[2][len(prefix):] for k in values
                if k[1] == dim and k[0] in (key, prev) and k[2].startswith(prefix)
            }
            for code in sorted(codes):
                final = values.get((key, dim, prefix + code), 0.0)
                initial = values.get((prev, dim, prefix + code), 0.0) if prev in all_month_keys else None
                change = final - initial if initial is not None else None
                percent = change / abs(initial) if initial not in (None, 0) else None
                results.append([common[0], code, initial, final, change, percent, common[5], common[6]])
        return results
    return {
        "Resumo Geral": [entries[-1][1]] if entries else [],
        "Por Armazém": dimension_rows("ARMZ", "ARMZ:"),
        "Por Tipo": dimension_rows("TP", "TP:"),
        "Evolução Mensal": [entry for _, entry in entries],
    }


def export_stock(summaries: list[dict], imports: list[dict],
                 start: date | None = None, end: date | None = None) -> bytes:
    data = stock_data(summaries, imports, start, end)
    wb = _Excel()
    for name, rows in data.items():
        headers = STOCK_HEADERS if name in ("Resumo Geral", "Evolução Mensal") else [
            "Competência", "Armazém" if name == "Por Armazém" else "Tipo de material",
            *STOCK_HEADERS[1:],
        ]
        offset = 1 if len(headers) == 8 else 0
        wb.sheet(name, headers, money={i + offset for i in (1, 2, 3)},
                 percent={4 + offset})
        for row in rows:
            wb.add(name, row)
    return wb.save()


def _valor_previsto_baixa(item: dict, prices: dict) -> float | None:
    """Previsão financeira operacional: quantidade ainda não baixada × custo.

    Aguardando separação/conferência: necessidade − baixa OPS, pois a
    pendência de conferência pode ser zero mesmo sem consumo realizado.
    Não consumido: mantém a pendência de baixa já calculada pelo MES/OPS.
    Demais alertas preservam a lógica prévia (pendência positiva).
    Falta de preço ou de quantidade/baixa conhecida não vira zero fictício.
    """
    import operational_status as stages

    status = str(item.get("status") or "").strip()
    awaiting = {
        stages.AGUARDANDO_SEPARACAO,
        stages.SEPARADO_SEM_CONFERENCIA,
    }
    not_consumed = {
        stages.NAO_CONSUMIDO_G9,
        stages.NAO_CONSUMIDO_SEM,
        stages.NAO_CONSUMIDO_OUTRO,
    }
    if status not in awaiting | not_consumed and not bool(item.get("divergente")):
        return None
    try:
        codigo = str(item.get("codigo") or "").strip()
        if not codigo:
            return None
        if codigo.isdecimal() and len(codigo) <= 8:
            codigo = codigo.zfill(8)
        price_raw = prices.get(codigo)
        if price_raw is None or str(price_raw).strip() == "":
            return None
        unit_price = Decimal(str(price_raw))
        if not unit_price.is_finite() or unit_price <= 0:
            return None

        if status in awaiting:
            # O OPS pode registrar baixas antes da separação/conferência.
            # Não assumir baixa zero quando a fonte não a informou.
            required_raw = item.get("necessaria")
            issued_raw = item.get("baixada")
            if required_raw is None or issued_raw is None:
                return None
            required = Decimal(str(required_raw))
            issued = Decimal(str(issued_raw))
            if not required.is_finite() or not issued.is_finite():
                return None
            remaining = max(required - issued, Decimal("0"))
        else:
            pending_raw = item.get("pendente")
            if pending_raw is None:
                return None
            remaining = Decimal(str(pending_raw))
            if not remaining.is_finite():
                return None
            remaining = max(remaining, Decimal("0"))
            # A classificação antiga de outros alertas só previa
            # dinheiro para pendências positivas.
            if status not in not_consumed and remaining <= 0:
                return None

        return float((remaining * unit_price).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP))
    except (ValueError, ArithmeticError, TypeError):
        return None


def _issue_selection(model: dict, start: date | None, end: date | None,
                     *, statuses: set[str] | None, alerts_only: bool,
                     material_types: set[str] | None,
                     include_activity: bool) -> tuple[set[str], set[tuple[str, str]] | None]:
    diagnostic = selection_diagnostics(
        model, start, end, include_activity=include_activity
    )
    selected_ops = set(diagnostic["selected"])
    ops = model.get("lot_ops") if model.get("lot_ops") is not None else model.get("ops")
    if ops is not None and not ops.empty:
        if statuses:
            selected_ops &= set(
                ops.loc[ops["status_op"].astype(str).isin(statuses), "op"].astype(str)
            )
        if alerts_only:
            selected_ops &= set(
                ops.loc[ops["divergencias"].fillna(0).gt(0), "op"].astype(str)
            )
    selected_codes = None
    if material_types:
        items = model.get("items")
        if items is None or items.empty or "tipo_material" not in items:
            return set(), set()
        kinds = items["tipo_material"].astype(str).str.upper().isin(material_types)
        selected_codes = set(zip(
            items.loc[kinds, "op"].astype(str),
            items.loc[kinds, "codigo"].astype(str),
        ))
    return selected_ops, selected_codes


def issue_detail_rows(model: dict, selected_ops: set[str],
                      *, selected_codes: set[tuple[str, str]] | None = None
                      ) -> list[tuple[list, bool]]:
    """OP + produto + lote em linha individual, igual à grade expandida.

    Usa os mesmos dados calculados da tela. Não soma lotes no Excel
    nem multiplica baixas OPS quando o Geral repete a mesma chave.
    """
    if not selected_ops:
        return []
    ops = model.get("lot_ops") if model.get("lot_ops") is not None else model.get("ops")
    items = model.get("lot_items") if model.get("lot_items") is not None else model.get("items")
    if ops is None or items is None or ops.empty or items.empty:
        return []
    if model.get("baixas_fonte") == "OPS" and not model.get("history_available"):
        raise ValueError("Relatório OPS indisponível: não exportar baixas desconhecidas.")
    op_map = ops.set_index("op").to_dict("index")
    prices = model.get("catalog_prices") or {}
    rows = []
    for item in items.to_dict("records"):
        op = str(item.get("op") or "")
        code = str(item.get("codigo") or "")
        if op not in selected_ops:
            continue
        if selected_codes is not None and (op, code) not in selected_codes:
            continue
        header = op_map.get(op)
        if header is None:
            continue
        full_op = {"op": op, **header}
        values = [
            full_op.get(key) for _, key in OP_FIELDS
        ] + [
            _valor_previsto_baixa(item, prices)
            if key == "valor_previsto_baixa"
            else item.get("resultado_lote", item.get("status"))
            if key == "status"
            else item.get(key)
            for _, key in ISSUE_ITEM_FIELDS
        ]
        # Não inferir alertas de texto, cores ou 'historico_incompleto'.
        # A mesma flag divergente utilizada no filtro e resumo da tela
        # é a única condição que destaca o Resultado no Excel.
        rows.append((values, bool(item.get("divergente", False))))
    return rows


def issue_rows(model: dict, start: date | None = None, end: date | None = None,
               *, statuses: set[str] | None = None, alerts_only: bool = False,
               material_types: set[str] | None = None,
               include_activity: bool = False) -> list[list]:
    selected_ops, selected_codes = _issue_selection(
        model, start, end, statuses=statuses, alerts_only=alerts_only,
        material_types=material_types,
        include_activity=include_activity,
    )
    return [
        values for values, _ in issue_detail_rows(
            model, selected_ops, selected_codes=selected_codes,
        )
    ]


def export_issues(model: dict, start: date | None = None, end: date | None = None,
                  *, statuses: set[str] | None = None, alerts_only: bool = False,
                  material_types: set[str] | None = None,
                  include_activity: bool = False) -> bytes:
    """Espelha cabeçalho da OP + campos validados do R3, inclusive previsão."""
    selected_ops, selected_codes = _issue_selection(
        model, start, end, statuses=statuses, alerts_only=alerts_only,
        material_types=material_types,
        include_activity=include_activity,
    )
    records = issue_detail_rows(model, selected_ops, selected_codes=selected_codes)
    wb = _Excel()
    wb.sheet(
        "Conferência de Baixas", OP_COLUMNS,
        quantity={OP_COLUMNS.index(name) for name in ISSUE_QUANTITY_NAMES | ISSUE_COUNT_NAMES},
        money={OP_COLUMNS.index(name) for name in ISSUE_MONEY_NAMES},
        alert_column=OP_COLUMNS.index("Resultado"),
    )
    for values, has_alert in records:
        wb.add("Conferência de Baixas", values, alert=has_alert)
    return wb.save()


def filtered_kardex(frame: pd.DataFrame, start: date | None = None, end: date | None = None,
                    warehouses: set[str] | None = None, types: set[str] | None = None,
                    groups: set[str] | None = None, group_names: set[str] | None = None,
                    group_config: dict | None = None) -> pd.DataFrame:
    _period(start, end)
    filtered = frame
    if start or end:
        dates = pd.to_datetime(frame["data"], errors="coerce").dt.date
        mask = pd.Series(True, index=frame.index)
        if start:
            mask &= dates >= start
        if end:
            mask &= dates <= end
        filtered = filtered.loc[mask]
    if warehouses:
        filtered = filtered.loc[filtered["armazem"].astype(str).isin(warehouses)]
    if types:
        filtered = filtered.loc[filtered["tipo"].astype(str).str.upper().isin(types)]
    if groups:
        filtered = filtered.loc[filtered["tes"].astype(str).str.zfill(3).isin(groups)]
    if group_names:
        if group_config is None:
            raise ValueError("O filtro de grupos exige o cadastro gerencial atualizado.")
        import kardex_group_config as gc
        owner = gc.group_owner(group_config)
        named = filtered["tes"].astype(str).str.zfill(3).map(owner).fillna(gc.UNASSIGNED)
        filtered = filtered.loc[named.isin(group_names)]
    return filtered.copy()


def export_kardex(frame: pd.DataFrame, group_config: dict, *,
                  summary_only: bool = False) -> bytes:
    import movements
    return movements.export_excel(frame, group_config=group_config, summary_only=summary_only)
