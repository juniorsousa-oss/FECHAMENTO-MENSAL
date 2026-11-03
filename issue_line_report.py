"""Conferência de Baixas: uma linha por registro ORIGINAL do Relatório Geral.

O Relatório Geral é a fonte exclusiva de OP/produto/lote e das quantidades
solicitadas, separadas e conferidas. Presença do CONFERENTE (responsável)
define conferência; sem conferente a atendida fica apenas separada.
O OPS informa exclusivamente a quantidade baixada da mesma chave,
independentemente da data de cada movimento.

Não consolida linhas do Geral por produto e não duplica a quantidade OPS
caso existam várias linhas com a mesma chave OP/produto/lote.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation

import ops_lot_source

COLUMNS = [
    "OP", "Produto", "Descrição", "Lote",
    "Qtd necessária", "Qtd separada", "Qtd conferida",
    "Qtd baixada", "Qtd pendente baixa", "Resultado",
]
ZERO = Decimal("0")
EPS = Decimal("0.000001")


def _amount(value) -> Decimal:
    if value is None or value == "":
        return ZERO
    try:
        number = Decimal(str(value))
        if not number.is_finite():
            raise ValueError(f"Quantidade não finita: {value}")
        return number
    except (InvalidOperation, TypeError) as exc:
        raise ValueError(f"Quantidade inválida: {value!r}") from exc


def _key(op: object, codigo: object, lote: object) -> tuple[str, str, str]:
    # Mesma normalização utilizada pelos leitores do Relatório Geral e OPS.
    return (
        str(op or "").strip(),
        str(codigo or "").strip(),
        ops_lot_source.lot(lote),
    )


def _is_confirmed(source: dict) -> bool:
    # Não inferir conferência pela data ou pela situação da OP.
    return bool(str(source.get("responsavel_conferencia") or "").strip())


def _sources_by_key(model: dict, selected_ops: set[str]):
    general = model.get("general") or []
    for index, source in enumerate(general):
        op, code, lot = _key(source.get("op"), source.get("codigo"),
                             source.get("lote"))
        if op not in selected_ops or not code:
            continue
        yield index, (op, code, lot), source


def _ops_by_key(model: dict) -> dict[tuple[str, str, str], Decimal]:
    if model.get("baixas_fonte") == "OPS" and not model.get("history_available"):
        raise ValueError(
            "O Relatório OPS não está disponível. Não é permitido "
            "apresentar baixa desconhecida como quantidade zero."
        )
    amounts = defaultdict(lambda: ZERO)
    for movement in model.get("movements") or []:
        if str(movement.get("natureza") or "") not in (
            "BAIXA / DEVOLUÇÃO", "CONSUMO DE OP"
        ):
            continue
        key = _key(movement.get("op"), movement.get("codigo"),
                   movement.get("lote"))
        if not key[0] or not key[1]:
            continue
        # Débito menos devolução, sem descartar o movimento de outra data.
        if movement.get("quantidade") is not None:
            delta = _amount(movement["quantidade"])
        else:
            delta = (_amount(movement.get("qtd_saida"))
                     - _amount(movement.get("qtd_entrada")))
        amounts[key] += delta
    return amounts


def _outcome(conferido: bool, separados: Decimal, conferidos: Decimal,
             baixados: Decimal, lote: str, *, pending_product: Decimal,
             lot_mismatch: bool) -> tuple[Decimal | None, str]:
    if not lote and (conferidos > EPS or baixados != ZERO):
        return None, "LOTE NÃO INFORMADO — CONFERIR ORIGEM"
    if baixados < -EPS:
        return None, "DEVOLUÇÃO SUPERIOR À BAIXA — CONFERIR"
    if conferido:
        if lot_mismatch:
            if pending_product > EPS:
                return pending_product, "BAIXA PENDENTE — DIVERGÊNCIA ENTRE LOTES"
            return ZERO, "DIVERGÊNCIA ENTRE LOTES — TOTAL BAIXADO CORRETO"
        if pending_product > EPS:
            return pending_product, "CONFERIDO — BAIXA PENDENTE"
        return ZERO, "CONFERIDO — BAIXA CORRESPONDENTE"
    if baixados > EPS:
        return None, "BAIXA SEM CONFERENTE — VERIFICAR"
    if separados > EPS:
        return None, "APENAS SEPARADO"
    return None, "AGUARDANDO SEPARAÇÃO"


def build_rows(model: dict, selected_ops: set[str],
               *, selected_codes: set[tuple[str, str]] | None = None
               ) -> list[list]:
    """Exporta cada linha do Geral, distribuindo a baixa OPS uma única vez.

    Quando o Geral tem duas linhas para a mesma chave, a baixa é atribuída
    na ordem original: primeiro às linhas com conferente e depois às outras.
    Excesso final é mantido na última linha, jamais omitido.
    """
    indexed = list(_sources_by_key(model, selected_ops))
    credits = _ops_by_key(model)
    allocated: dict[int, Decimal] = {}
    grouped = defaultdict(list)
    for index, key, row in indexed:
        grouped[key].append((index, row))
    for key, entries in grouped.items():
        # Sem lote não há prova de vínculo exato.
        available = credits.get(key, ZERO) if key[2] else ZERO
        ordered = sorted(entries, key=lambda entry: (
            not _is_confirmed(entry[1]), entry[0]
        ))
        for index, source in ordered:
            expected = _amount(source.get("atendida"))
            if available > ZERO:
                issued = min(available, expected)
                available -= issued
            else:
                issued = ZERO
            allocated[index] = issued
        if available:
            # Sobra/estorno: manter integralmente visível e contabilizado.
            last_index = ordered[-1][0]
            allocated[last_index] += available

    # Pendência de quantidade pertence à OP/produto, não à soma das
    # faltas positivas de cada lote. Excesso e falta de lotes diferentes
    # são uma DIVERGÊNCIA DE LOTE, não uma baixa faltante fictícia.
    products = defaultdict(list)
    for index, key, row in indexed:
        products[key[:2]].append((index, key, row))
    pending_by_line: dict[int, Decimal] = {}
    mismatches: set[tuple[str, str, str]] = set()
    for product, group in products.items():
        total_confirmed = sum(
            (_amount(row.get("atendida")) for _, _, row in group
             if _is_confirmed(row)), ZERO
        )
        issued_by_lot = {
            lot: qty for (op, code, lot), qty in credits.items()
            if (op, code) == product
        }
        total_issued = sum(issued_by_lot.values(), ZERO)
        remaining = max(total_confirmed - total_issued, ZERO)
        confirmed_by_lot = defaultdict(lambda: ZERO)
        for _, key, row in group:
            if _is_confirmed(row):
                confirmed_by_lot[key[2]] += _amount(row.get("atendida"))
        excess_lots = {
            lot for lot, issued in issued_by_lot.items()
            if issued > confirmed_by_lot[lot] + EPS
        }
        missing_lots = {
            lot for lot, confirmed_qty in confirmed_by_lot.items()
            if issued_by_lot.get(lot, ZERO) + EPS < confirmed_qty
        }
        if excess_lots:
            mismatches.update(
                key for _, key, _ in group
                if key[2] in excess_lots | missing_lots
            )
            # Baixas em lotes ausentes também precisam sinalizar as
            # linhas de origem, sem criar colunas extras.
            if excess_lots - set(confirmed_by_lot):
                mismatches.update(key for _, key, _ in group)
        pending_lines = [
            (index, key, row) for index, key, row in group if _is_confirmed(row)
        ]
        for index, key, row in pending_lines:
            deficit = max(_amount(row.get("atendida")) - allocated[index], ZERO)
            share = min(deficit, remaining)
            pending_by_line[index] = share
            remaining -= share
        if remaining > EPS and pending_lines:
            pending_by_line[pending_lines[-1][0]] += remaining

    output = []
    for index, key, source in indexed:
        op, code, lote = key
        if selected_codes is not None and (op, code) not in selected_codes:
            continue
        confirmed = _is_confirmed(source)
        attended = _amount(source.get("atendida"))
        requested = _amount(source.get("necessaria"))
        separated = ZERO if confirmed else attended
        conferred = attended if confirmed else ZERO
        issued = allocated[index]
        pending, result = _outcome(
            confirmed, separated, conferred, issued, lote,
            pending_product=pending_by_line.get(index, ZERO),
            lot_mismatch=key in mismatches,
        )
        output.append([
            op, code, source.get("descricao") or "", lote,
            float(requested), float(separated), float(conferred),
            float(issued), None if pending is None else float(pending), result,
        ])
    return output
