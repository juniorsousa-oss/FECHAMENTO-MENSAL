"""Conciliação assistida, SOMENTE LEITURA, de baixas manuais sem vínculo de OP.

O KARDEX possui data, documento, TES, centro de custo e produto, mas
não comprova vínculo de OP/lote na movimentação CC600307 sem OP.
Não altera MES, OPS, pendências, estoques ou estado de conferência.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
import re

import pandas as pd

import movements as mv

VERSION = "2026-11-04.1-CANDIDATOS-MANUAIS-SOMENTE-LEITURA"
TES_ELEGIVEIS = frozenset(("520", "550"))
CR_ELEGIVEL = "600307"
EPS = Decimal("0.000001")

COLUMNS = [
    ("Data da baixa", "data"),
    ("Documento KARDEX", "documento"),
    ("TES", "tes"),
    ("CR", "cr"),
    ("Produto", "codigo"),
    ("Descrição", "descricao"),
    ("Quantidade manual", "quantidade"),
    ("Armazém", "armazem"),
    ("OP candidata", "op"),
    ("Cliente", "cliente"),
    ("Faturamento", "faturamento"),
    ("Data separação MES", "separacao"),
    ("Data conferência MES", "conferencia"),
    ("Necessidade na OP", "necessaria"),
    ("Baixada comprovada OPS", "baixada_ops"),
    ("Falta de consumo na OP", "pendente_demanda"),
    ("Saldo atual G9-PROD", "saldo_g9_atual"),
    ("OPs compatíveis com a baixa", "qtd_ops_candidatas"),
    ("Situação", "situacao"),
    ("Justificativa / revisão", "justificativa"),
    ("Origem do KARDEX", "arquivo_origem"),
    ("Linha de origem", "linha_origem"),
    ("ID movimentação", "movimento_id"),
]
NUMERICS = frozenset({
    "quantidade", "necessaria", "baixada_ops",
    "pendente_demanda", "saldo_g9_atual", "qtd_ops_candidatas",
    "linha_origem",
})


def _date(value) -> date | None:
    if value is None or str(value).strip().upper() in (
        "", "NI", "N/I", "NAN", "NONE", "NAT",
    ):
        return None
    if isinstance(value, date):
        return value.date() if hasattr(value, "date") else value
    raw = str(value).strip()
    try:
        return mv._date(raw) and date.fromisoformat(mv._date(raw))
    except (ValueError, TypeError):
        return None


def _normalized_code(value) -> str:
    return mv.identifier(value, 8)


def _quantity(value) -> Decimal:
    return mv.decimal(value)


def _cc_without_op(row: dict) -> str:
    ae = str(row.get("ae_original") or "").strip().upper()
    # Só CC explícito; registros vazios, ambíguos, outros CRs e OP na AE
    # não podem ser inferidos como 600307.
    if re.fullmatch(r"CC[\s:.-]*0*600307(?:\.0+)?", ae):
        return CR_ELEGIVEL
    return ""


def _pending(required: Decimal, issued: Decimal) -> Decimal:
    return max(required - issued, Decimal("0"))


def _manual_rows(frame: pd.DataFrame, *, start: date, end: date) -> list[dict]:
    if frame is None or frame.empty:
        return []
    required = ("data", "tes", "codigo", "qtd_saida", "qtd_entrada", "ae_original")
    missing = [col for col in required if col not in frame.columns]
    if missing:
        raise ValueError("KARDEX sem campos obrigatórios: " + ", ".join(missing))
    matches = []
    for raw in frame.to_dict("records"):
        when = _date(raw.get("data"))
        if when is None or not start <= when <= end:
            continue
        tes = mv.identifier(raw.get("tes"), 3)
        if tes not in TES_ELEGIVEIS:
            continue
        cr = _cc_without_op(raw)
        if not cr:
            continue
        qty = _quantity(raw.get("qtd_saida"))
        if qty <= EPS or _quantity(raw.get("qtd_entrada")) != 0:
            continue
        code = _normalized_code(raw.get("codigo"))
        if not re.fullmatch(r"\d{8}", code):
            continue
        movement = dict(raw)
        movement.update(data=when.isoformat(), tes=tes, codigo=code,
                        quantidade=qty, cr=cr)
        # ID do snapshot deduplicado; não equivale à OP e não autoriza consumo.
        movement["movimento_id"] = str(
            raw.get("id_registro")
            or mv.fingerprint(raw)[:24]
        )
        matches.append(movement)
    return matches


def _op_products(model: dict) -> dict[str, list[dict]]:
    """Agrupar lotes na OP; o KARDEX sem OP não permite atribuir lote."""
    items = model.get("lot_items")
    if items is None:
        items = model.get("items")
    if items is None or items.empty:
        return {}
    summed = defaultdict(lambda: {"necessaria": Decimal("0"),
                                  "baixada_ops": Decimal("0"), "rows": []})
    for item in items.to_dict("records"):
        op, code = str(item.get("op") or ""), _normalized_code(item.get("codigo"))
        if not op or not code:
            continue
        entry = summed[(op, code)]
        entry["necessaria"] += _quantity(item.get("necessaria"))
        entry["baixada_ops"] += _quantity(item.get("baixada"))
        entry["rows"].append(item)

    op_meta = {}
    ops = model.get("lot_ops")
    if ops is None:
        ops = model.get("ops")
    if ops is not None and not ops.empty:
        op_meta = {
            str(row.get("op")): row for row in ops.to_dict("records")
        }
    mes_dates = defaultdict(lambda: {"separacao": [], "conferencia": []})
    for row in model.get("general") or []:
        key = str(row.get("op") or ""), _normalized_code(row.get("codigo"))
        for field in ("separacao", "conferencia"):
            day = _date(row.get(field))
            if day:
                mes_dates[key][field].append(day)

    by_code = defaultdict(list)
    for (op, code), data in summed.items():
        pending = _pending(data["necessaria"], data["baixada_ops"])
        if pending <= EPS:
            continue
        header = op_meta.get(op, {})
        dates = mes_dates[(op, code)]
        separated = min(dates["separacao"]) if dates["separacao"] else None
        confirmed = min(dates["conferencia"]) if dates["conferencia"] else None
        billing = _date(header.get("data_faturamento"))
        by_code[code].append({
            "op": op, "codigo": code,
            "necessaria": data["necessaria"],
            "baixada_ops": data["baixada_ops"],
            "pendente_demanda": pending,
            "faturamento_dt": billing,
            "separacao_dt": separated,
            "conferencia_dt": confirmed,
            "cliente": header.get("cliente") or "NI",
        })
    return by_code


def _balance_by_code(stock: list[dict], as_of: date) -> dict[str, Decimal]:
    """Fotografia ENDEREÇO atual (não retroprojetável para data da baixa)."""
    result = defaultdict(Decimal)
    for row in stock:
        if str(row.get("endereco") or "").strip().upper() != "G9-PROD":
            continue
        code = _normalized_code(row.get("codigo"))
        if code:
            result[code] += _quantity(row.get("saldo"))
    return result


def _window_reason(candidate: dict, when: date, *,
                   before_days: int, after_days: int) -> str | None:
    billing = candidate["faturamento_dt"]
    if billing is not None:
        delta = (billing - when).days
        if -after_days <= delta <= before_days:
            return (
                f"Data da baixa a {delta} dia(s) do faturamento "
                "(valor negativo = baixa posterior)."
            )
        return None
    # Sem faturamento, somente um evento MES próximo permite
    # apresentar a OP como candidata e SEM confiança de vínculo.
    events = [d for d in (candidate["separacao_dt"],
                         candidate["conferencia_dt"]) if d]
    if not events:
        return None
    gap = min(abs((when - d).days) for d in events)
    if gap > 30:
        return None
    return (
        "Faturamento NI; proximidade de "
        f"{gap} dia(s) com separação/conferência MES. "
        "Requer validação documental."
    )


def build(model: dict, kardex_frame: pd.DataFrame, *,
          start: date, end: date, before_days: int = 90,
          after_days: int = 7, require_insufficient_g9: bool = True) -> dict:
    """Retorna candidatos e diagnostico; NÃO retorna baixas conciliadas.

    1 movimentação pode aparecer em várias linhas quando várias OPs
    atendem ao critério. Essas linhas NUNCA são somadas como baixa.
    """
    if not isinstance(start, date) or not isinstance(end, date) or start > end:
        raise ValueError("Selecione datas inicial e final válidas.")
    if not 0 <= before_days <= 365 or not 0 <= after_days <= 60:
        raise ValueError("Janela temporal fora do limite permitido.")
    if not model.get("history_available"):
        raise ValueError("Fonte OPS não disponível; conciliação assistida indisponível.")
    cutoff = _date(model.get("as_of"))
    if cutoff is None:
        raise ValueError("Data de referência MES não identificada.")
    if start > cutoff:
        raise ValueError("Intervalo começa depois da referência MES.")
    period_end = min(end, cutoff)
    manual = _manual_rows(kardex_frame, start=start, end=period_end)
    index = _op_products(model)
    stock = _balance_by_code(model.get("stock") or [], cutoff)
    evidence = []
    summary = defaultdict(int)
    unique_ids = set()
    for movement in manual:
        movement_id = movement["movimento_id"]
        # Nunca usar um registro duas vezes em totais, mesmo se uma fonte
        # extraordinária passar pela política de importação.
        if movement_id in unique_ids:
            summary["duplicados_ignorados"] += 1
            continue
        unique_ids.add(movement_id)
        summary["movimentos_elegiveis"] += 1
        qty = movement["quantidade"]
        available = max(stock.get(movement["codigo"], Decimal("0")), Decimal("0"))
        considered = []
        for candidate in index.get(movement["codigo"], ()):
            why = _window_reason(candidate, _date(movement["data"]),
                                 before_days=before_days, after_days=after_days)
            if why is None:
                continue
            pending = candidate["pendente_demanda"]
            if require_insufficient_g9 and available >= pending - EPS:
                summary["sem_insuficiencia_atual_g9"] += 1
                continue
            considered.append((candidate, why))

        considered.sort(key=lambda entry: (
            entry[0]["faturamento_dt"] is None,
            abs(((entry[0]["faturamento_dt"] or entry[0]["conferencia_dt"]
                  or entry[0]["separacao_dt"] or cutoff)
                 - _date(movement["data"])).days),
            entry[0]["op"],
        ))
        number = len(considered)
        if number > 1:
            summary["movimentos_ambiguos"] += 1
        elif number == 1:
            summary["movimentos_com_op_unica"] += 1
        else:
            summary["movimentos_sem_correspondencia"] += 1

        for candidate, reason in considered or [(None, "")]:
            if candidate:
                qty_excess = qty > candidate["pendente_demanda"] + EPS
                situation = (
                    "MÚLTIPLAS OPS — VALIDAR"
                    if number > 1 else
                    "QUANTIDADE MAIOR QUE PENDÊNCIA — VALIDAR"
                    if qty_excess else
                    "CANDIDATO ÚNICO — VALIDAR"
                )
                if candidate["faturamento_dt"] is None:
                    situation = "FATURAMENTO NI — VALIDAR"
                reason += (
                    " Saldo atual em G9-PROD é apenas indicativo, "
                    "não comprova saldo na data histórica. "
                    "Lote do KARDEX não disponível; não atribuir lote."
                )
            else:
                situation = "SEM OP CANDIDATA"
                reason = (
                    "Não há OP com demanda pendente e janela temporal "
                    "compatíveis, ou o saldo atual G9-PROD não atende ao filtro. "
                    "Sem atribuição automática."
                )
            evidence.append({
                "data": movement["data"],
                "documento": str(movement.get("documento") or ""),
                "tes": movement["tes"], "cr": movement["cr"],
                "codigo": movement["codigo"],
                "descricao": str(movement.get("descricao") or ""),
                "quantidade": qty, "armazem": str(movement.get("armazem") or ""),
                "op": candidate["op"] if candidate else "",
                "cliente": candidate["cliente"] if candidate else "",
                "faturamento": (
                    candidate["faturamento_dt"].strftime("%d/%m/%Y")
                    if candidate and candidate["faturamento_dt"] else "NI"
                ),
                "separacao": (
                    candidate["separacao_dt"].strftime("%d/%m/%Y")
                    if candidate and candidate["separacao_dt"] else "NI"
                ),
                "conferencia": (
                    candidate["conferencia_dt"].strftime("%d/%m/%Y")
                    if candidate and candidate["conferencia_dt"] else "NI"
                ),
                "necessaria": candidate["necessaria"] if candidate else None,
                "baixada_ops": candidate["baixada_ops"] if candidate else None,
                "pendente_demanda": (
                    candidate["pendente_demanda"] if candidate else None
                ),
                "saldo_g9_atual": available,
                "qtd_ops_candidatas": number,
                "situacao": situation,
                "justificativa": reason,
                "arquivo_origem": str(movement.get("arquivo_origem") or ""),
                "linha_origem": int(movement.get("linha_origem") or 0),
                "movimento_id": movement_id,
            })
    summary["linhas_para_revisao"] = len(evidence)
    # Campos de métricas sempre presentes, inclusive quando nenhum
    # movimento no período passou pela triagem.
    for key in (
        "movimentos_elegiveis", "movimentos_ambiguos",
        "movimentos_com_op_unica", "movimentos_sem_correspondencia",
        "duplicados_ignorados", "sem_insuficiencia_atual_g9",
    ):
        summary[key] += 0
    summary["regras"] = VERSION
    summary["data_corte_mes"] = cutoff.isoformat()
    summary["filtro_g9"] = require_insufficient_g9
    return {"rows": evidence, "summary": dict(summary)}


def export_excel(result: dict) -> bytes:
    """Relatório independente, sem reproduzir valores em OPS nem no banco."""
    from reports import _Excel

    wb = _Excel()
    wb.sheet(
        "Baixas Manuais Candidatas",
        [label for label, key in COLUMNS],
        quantity={i for i, (_, key) in enumerate(COLUMNS) if key in NUMERICS},
    )
    for row in result.get("rows") or []:
        values = [
            float(row[key]) if isinstance(row.get(key), Decimal)
            else row.get(key)
            for _, key in COLUMNS
        ]
        wb.add("Baixas Manuais Candidatas", values)
    return wb.save()
