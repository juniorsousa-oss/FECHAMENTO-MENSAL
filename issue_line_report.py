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
             baixados: Decimal, lote: str) -> tuple[Decimal | None, str]:
    if not lote and (conferidos > EPS or baixados != ZERO):
        return None, "LOTE NÃO INFORMADO — CONFERIR ORIGEM"
    if baixados < -EPS:
        return None, "DEVOLUÇÃO SUPERIOR À BAIXA — CONFERIR"
    if conferido:
        pending = max(conferidos - baixados, ZERO)
        if baixados > conferidos + EPS:
            return ZERO, "BAIXA SUPERIOR AO CONFERIDO"
        if pending > EPS:
            return pending, "CONFERIDO — BAIXA PENDENTE"
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
        pending, result = _outcome(confirmed, separated, conferred, issued, lote)
        output.append([
            op, code, source.get("descricao") or "", lote,
            float(requested), float(separated), float(conferred),
            float(issued), None if pending is None else float(pending), result,
        ])
    return output
