"""Linhas da Conferência de Baixas por OP + produto + lote (MES x OPS).

Preserva os dados do MES, separa as diferenças de lançamento de lote da
pendência QUANTITATIVA do produto e não atribui arbitrariamente uma falta
residual quando múltiplos lotes são candidatos.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

import pandas as pd

import movements as mv
import ops_lot_source as ops_source
import operational_status as status

ZERO = Decimal("0")
EPS = Decimal("0.000001")
VERSION = "2026-11-04.6-SEM-DEMANDA-NEUTRO-R2"

# As mesmas categorias recebem atenção âmbar na tela e na exportação.
# Não usar quantidade ou status de alerta para decidir a cor desses resultados.
ATTENTION_RESULTS = frozenset({
    status.AGUARDANDO_SEPARACAO,
    status.SEPARADO_SEM_CONFERENCIA,
    "BAIXA A MAIOR NESTE LOTE",
    "BAIXA A MENOR NESTE LOTE",
    "DIVERGÊNCIA DE LOTE",
})
LOT_RESULT_CATEGORIES = frozenset({
    "BAIXA A MAIOR NESTE LOTE",
    "BAIXA A MENOR NESTE LOTE",
    "DIVERGÊNCIA DE LOTE",
})


def is_attention_result(result: str) -> bool:
    return str(result or "").strip() in ATTENTION_RESULTS



def _positive(value: Decimal) -> Decimal:
    return max(value, ZERO)


def _lot(value) -> str:
    return ops_source.lot(value)


def _confirmed(row: dict) -> bool:
    return bool(str(row.get("responsavel_conferencia") or "").strip())


def _valid_qty(value) -> Decimal:
    return mv.decimal(value)


def _lot_status(*, material: dict, required: Decimal, separated: Decimal,
                confirmed: Decimal, issued: Decimal | None,
                missing: Decimal | None, gross_missing: Decimal,
                gross_excess: Decimal, wrong_lots: str, ambiguity: bool,
                saldo_prod: Decimal, saldo: Decimal) -> tuple[str, str, bool]:
    """Retorna status canônico, resultado explicativo por lote e alerta."""
    code_type = str(material.get("tipo_material") or "").strip().upper()
    if code_type == "II":
        return status.MATERIAL_CONSUMO, status.MATERIAL_CONSUMO, False
    if issued is None:
        return status.AGUARDANDO_OPS, status.AGUARDANDO_OPS, False

    # Linha do Geral sem demanda, separação, conferência ou baixa OPS não
    # pode herdar alerta do lote de outra linha do mesmo produto. A linha
    # permanece consultável para investigar sua origem, mas é neutra.
    if (required <= EPS and separated <= EPS and confirmed <= EPS
            and abs(issued) <= EPS):
        result = "SEM DEMANDA OU MOVIMENTAÇÃO NO LOTE"
        return result, result, False

    if ambiguity:
        return (
            status.BAIXA_LOTE_DIVERGENTE,
            "BAIXAS EM LOTES DIVERGENTES; HÁ PENDÊNCIA QUANTITATIVA REAL, "
            "MAS SUA DISTRIBUIÇÃO ENTRE LOTES NÃO PODE SER COMPROVADA. "
            f"FALTA BRUTA NESTE LOTE: {gross_missing}",
            True,
        )
    if wrong_lots:
        if gross_missing > EPS:
            if missing is not None and missing > EPS:
                return (status.BAIXA_LOTE_DIVERGENTE,
                        f"BAIXA A MENOR NESTE LOTE ({gross_missing}); "
                        f"PENDÊNCIA REAL {missing}; {wrong_lots}", True)
            return (status.BAIXA_LOTE_DIVERGENTE,
                    f"BAIXA A MENOR NESTE LOTE ({gross_missing}), "
                    f"COMPENSADA EM OUTRO LOTE; PENDÊNCIA TOTAL ZERO; {wrong_lots}", True)
        if gross_excess > EPS:
            return (status.BAIXA_LOTE_DIVERGENTE,
                    f"BAIXA A MAIOR NESTE LOTE ({gross_excess}); {wrong_lots}", True)
        return (status.BAIXA_LOTE_DIVERGENTE, wrong_lots, True)

    if gross_excess > EPS:
        return (status.BAIXA_ACIMA_NECESSIDADE,
                f"BAIXA A MAIOR NESTE LOTE ({gross_excess})", True)
    if missing is not None and missing > EPS:
        if confirmed <= EPS:
            return (status.SEPARADO_SEM_CONFERENCIA,
                    "BAIXA A CONFERIR — SEM CONFERENTE REGISTRADO", True)
        if saldo_prod > EPS:
            canonical = status.NAO_CONSUMIDO_G9
        elif saldo > EPS:
            canonical = status.NAO_CONSUMIDO_OUTRO
        else:
            canonical = status.NAO_CONSUMIDO_SEM
        return (canonical, f"{canonical} — FALTAM {missing} NESTE LOTE", True)
    if confirmed <= EPS:
        if issued > EPS:
            return (status.BAIXA_LOTE_DIVERGENTE,
                    "BAIXA SEM CONFERENTE REGISTRADO NESTE LOTE", True)
        if separated > EPS:
            return (status.SEPARADO_SEM_CONFERENCIA,
                    status.SEPARADO_SEM_CONFERENCIA, True)
        return status.AGUARDANDO_SEPARACAO, status.AGUARDANDO_SEPARACAO, False
    return status.PRODUTO_CONSUMIDO, status.PRODUTO_CONSUMIDO, False


def _result_category(canonical: str, detail: str, *,
                     gross_missing: Decimal, gross_excess: Decimal,
                     wrong_lots: str, ambiguity: bool) -> str:
    """Categoria fixa para tela e filtro do Excel, sem valores variáveis.

    Preserva a explicação completa separadamente em detalhe_resultado_lote
    para auditoria e evidência. A classificação e os cálculos não mudam.
    """
    if canonical == "SEM DEMANDA OU MOVIMENTAÇÃO NO LOTE":
        # Não sobrescrever a categoria neutra com uma divergência herdada
        # de outros lotes do mesmo produto.
        return canonical
    if ambiguity:
        return "DIVERGÊNCIA DE LOTES — PENDÊNCIA A APURAR"
    if gross_missing > EPS and wrong_lots:
        return "BAIXA A MENOR NESTE LOTE"
    if gross_excess > EPS:
        return "BAIXA A MAIOR NESTE LOTE"
    if wrong_lots:
        return "DIVERGÊNCIA DE LOTE"
    if canonical == status.BAIXA_LOTE_DIVERGENTE:
        if "SEM CONFERENTE" in detail:
            return "BAIXA SEM CONFERENTE REGISTRADO"
        return "DIVERGÊNCIA DE LOTE"
    return canonical


def build(model: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Gera grade de lotes e cabeçalhos coerentes, sem alterar o modelo original.

    REGRAS:
    - chave exata (OP, código, lote), consolidando linhas MES repetidas;
    - baixa líquida OPS agrupada por lote, somando todas as datas;
    - pendência de produto = max(conferido total - baixado total, 0);
    - faltas e excessos por lote continuam sinalizados;
    - compensações de lote só podem eliminar a *quantidade* pendente;
    - se faltam unidades e há vários lotes candidatos com compensação
      parcial, não é possível atribuir a falta real a um lote com certeza.
    """
    original = model.get("items")
    headers = model.get("ops")
    if original is None or headers is None:
        return pd.DataFrame(), pd.DataFrame()
    general = model.get("general") or []
    if not general:
        return original.copy(), headers.copy()

    parent = {(str(r["op"]), str(r["codigo"])): r
              for r in original.to_dict("records")}
    by_key = {}
    key_order = []
    for source in general:
        op = str(source.get("op") or "")
        code = str(source.get("codigo") or "")
        lot = _lot(source.get("lote"))
        if not op or not code:
            continue
        key = op, code, lot
        if key not in by_key:
            by_key[key] = {
                "necessaria": ZERO, "separada": ZERO,
                "conferida": ZERO, "descricao": source.get("descricao") or "",
            }
            key_order.append(key)
        info = by_key[key]
        info["necessaria"] += _valid_qty(source.get("necessaria"))
        info["separada"] += _valid_qty(source.get("atendida"))
        if _confirmed(source):
            info["conferida"] += _valid_qty(source.get("atendida"))

    stock_lots = {
        (str(r.get("op") or ""), str(r.get("codigo") or ""),
         _lot(r.get("lote"))): r
        for r in model.get("lots", pd.DataFrame()).to_dict("records")
    }
    known = bool(model.get("history_available"))
    by_issued = defaultdict(lambda: ZERO)
    if known:
        for movement in model.get("movements") or []:
            if movement.get("natureza") not in (
                "BAIXA / DEVOLUÇÃO", "CONSUMO DE OP",
            ):
                continue
            key = (str(movement.get("op") or ""),
                   str(movement.get("codigo") or ""),
                   _lot(movement.get("lote")))
            if key[0] and key[1]:
                by_issued[key] += (
                    _valid_qty(movement.get("qtd_saida"))
                    - _valid_qty(movement.get("qtd_entrada"))
                )

    grouped = defaultdict(list)
    for key in key_order:
        grouped[key[:2]].append(key)

    # Indexar OPS uma única vez por OP + produto. A implementação anterior
    # percorria TODAS as baixas a cada produto (O(produtos × baixas)),
    # congelando o Streamlit ao reprocessar >100 mil movimentos.
    issued_index = defaultdict(dict)
    for (op, code, lot), qty in by_issued.items():
        issued_index[(op, code)][lot] = qty

    view_rows = []
    for product, keys in grouped.items():
        op, code = product
        main = parent.get(product, {})
        if not main:
            continue

        confirmed_total = sum((by_key[k]["conferida"] for k in keys), ZERO)
        required_total = sum((by_key[k]["necessaria"] for k in keys), ZERO)
        issued_for_product = issued_index.get(product, {})
        issued_total = sum(issued_for_product.values(), ZERO)
        pending_total = _positive(confirmed_total - issued_total) if known else None
        # Alertas por LOTE dependem da demanda TOTAL da OP + produto,
        # não apenas do lote individual e nem só do conferido.
        remaining_demand = _positive(required_total - issued_total) if known else None

        raw_short = {}
        raw_excess = {}
        for key in keys:
            c = by_key[key]["conferida"]
            b = by_issued[key]
            raw_short[key] = _positive(c - b)
            raw_excess[key] = _positive(b - c)
        deficit_keys = [key for key in keys if raw_short[key] > EPS]
        shortage_sum = sum(raw_short.values(), ZERO)
        offset = _positive(shortage_sum - (pending_total or ZERO))
        # Se há um único lote com falta, o excesso de outro lote só
        # compensa essa falta; se há vários candidatos e crédito parcial,
        # a atribuição é indeterminada sem evidência do operador.
        ambiguity = (
            known and len(deficit_keys) > 1
            and EPS < offset < shortage_sum - EPS
        )

        real_pending = {key: ZERO for key in keys}
        if known and not ambiguity:
            if len(deficit_keys) == 1:
                only = deficit_keys[0]
                real_pending[only] = min(raw_short[only], pending_total)
            elif offset <= EPS:
                real_pending = {key: raw_short[key] for key in keys}
            elif offset >= shortage_sum - EPS:
                real_pending = {key: ZERO for key in keys}
        remaining_extras = [
            (lot, qty) for lot, qty in issued_for_product.items()
            if qty > EPS and (op, code, lot) not in by_key
        ]
        lot_note = " | ".join(
            f"BAIXA EM LOTE NÃO PREVISTO {lot or '(SEM LOTE)'}: {qty}"
            for lot, qty in remaining_extras
        )
        # FALTA sem qualquer lote com excesso é uma baixa realmente
        # pendente, não uma divergência de vínculo entre lotes.
        product_has_mismatch = bool(remaining_extras) or any(
            raw_excess[k] > EPS for k in keys
        )
        for key in keys:
            _, _, lot = key
            info = by_key[key]
            stock = stock_lots.get(key, {})
            qty_issued = by_issued[key] if known else None
            shortage = raw_short[key]
            excess = raw_excess[key]
            has_cross_lot = (
                product_has_mismatch and (
                    shortage > EPS or excess > EPS or bool(lot_note)
                )
            )
            if not known:
                note = ""
            elif has_cross_lot:
                note = "DIVERGÊNCIA DE LOTE"
                if lot_note:
                    note += "; " + lot_note
            else:
                note = ""

            pending = (
                None if not known or (ambiguity and shortage > EPS)
                else real_pending[key]
            )
            canonical, detail, divergent = _lot_status(
                material=main,
                required=info["necessaria"],
                separated=info["separada"], confirmed=info["conferida"],
                issued=qty_issued, missing=pending,
                gross_missing=shortage, gross_excess=excess,
                wrong_lots=note, ambiguity=bool(ambiguity and shortage > EPS),
                saldo_prod=_valid_qty(stock.get("saldo_g9_prod")),
                saldo=_valid_qty(stock.get("saldo")),
            )
            outcome = _result_category(
                canonical, detail, gross_missing=shortage,
                gross_excess=excess, wrong_lots=note,
                ambiguity=bool(ambiguity and shortage > EPS),
            )
            # Diferenças entre lotes continuam registradas e destacadas,
            # mas não integram alertas se a demanda total já foi baixada.
            # A situação de atenção não é a mesma coisa que alerta ativo.
            lot_difference = outcome in LOT_RESULT_CATEGORIES
            if lot_difference and remaining_demand is not None:
                divergent = remaining_demand > EPS
            informative_lot_difference = lot_difference and not divergent
            row = dict(main)
            row.update({
                "op": op, "codigo": code, "lote": lot, "lotes": lot,
                "descricao": info["descricao"] or main.get("descricao") or "",
                "necessaria": info["necessaria"],
                "separada": info["separada"],
                "conferida": info["conferida"],
                "baixada": qty_issued,
                "pendente": pending,
                "saldo": _valid_qty(stock.get("saldo")),
                "saldo_g9_prod": _valid_qty(stock.get("saldo_g9_prod")),
                "outros_enderecos": " | ".join(
                    str(entry.get("armazem") or "") + "/" +
                    str(entry.get("endereco") or "") + " · lote " +
                    str(entry.get("lote") or "") + ": " +
                    str(entry.get("saldo") or "")
                    for entry in main.get("enderecos_alternativos") or []
                    if _lot(entry.get("lote")) == lot
                ),
                "status": canonical,
                "resultado_lote": outcome,
                "detalhe_resultado_lote": detail,
                "divergente": divergent,
                "falta_bruta_lote": shortage if known else None,
                "excesso_lote": excess if known else None,
                "pendente_total_produto": pending_total,
                "pendente_demanda_produto": remaining_demand,
                "divergencia_lote_informativa": informative_lot_difference,
                "pendencia_indeterminada": ambiguity and shortage > EPS,
                "item_id": f"{op}:{code}:{lot}",
                "item_id_produto": main.get("item_id"),
                "alertas": [outcome] if divergent else [],
            })
            view_rows.append(row)

    lot_frame = pd.DataFrame(view_rows)
    headers_frame = headers.copy()
    if lot_frame.empty:
        return lot_frame, headers_frame
    counts = defaultdict(list)
    for record in view_rows:
        counts[record["op"]].append(record)
    for idx, header in headers_frame.iterrows():
        lines = counts.get(str(header["op"]), [])
        if not lines:
            continue
        headers_frame.at[idx, "itens"] = len(lines)
        headers_frame.at[idx, "produtos"] = len(lines)
        headers_frame.at[idx, "separados"] = sum(
            _valid_qty(line["separada"]) > EPS for line in lines
        )
        headers_frame.at[idx, "conferidos"] = sum(
            _valid_qty(line["conferida"]) > EPS for line in lines
        )
        headers_frame.at[idx, "baixados"] = sum(
            line["status"] == status.PRODUTO_CONSUMIDO for line in lines
        )
        headers_frame.at[idx, "divergencias"] = sum(
            bool(line["divergente"]) for line in lines
        )
    return lot_frame, headers_frame
