"""Status operacional de OP e resultados por material, em ordem de prioridade.

A análise de saldo e o KARDEX são somente evidências; o estado operacional
define se uma divergência representa alerta para a OP.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from collections import defaultdict
import re

import pandas as pd

VERSION = "2026-10-21.5"
EPS = Decimal("0.000001")
ZERO = Decimal(0)

FINALIZADO_PATIO = "FINALIZADO EM PÁTIO"
FINALIZADO_ENTREGUE = "FINALIZADO E ENTREGUE"
NF_EMITIDA = "NF EMITIDA"
FINALIZADO = "FINALIZADO"
REPORTADO = "REPORTADO"
EM_CONFERENCIA = "EM CONFERÊNCIA"
EM_SEPARACAO = "EM SEPARAÇÃO"
AGUARDANDO_INICIO = "AGUARDANDO INÍCIO"

PRODUTO_CONSUMIDO = "PRODUTO CONSUMIDO"
NAO_CONSUMIDO_G9 = "PRODUTO NÃO CONSUMIDO COM SALDO NA PRODUÇÃO"
NAO_CONSUMIDO_OUTRO = "PRODUTO NÃO CONSUMIDO COM SALDO EM ENDEREÇOS DIFERENTES DE PRODUÇÃO"
NAO_CONSUMIDO_SEM = "PRODUTO NÃO CONSUMIDO SEM SALDO PARA CONSUMO"
SEPARADO_SEM_CONFERENCIA = "PRODUTO SEPARADO AGUARDANDO CONFERÊNCIA"
AGUARDANDO_SEPARACAO = "PRODUTO AGUARDANDO SEPARAÇÃO"
CONFERIDO_AGUARDANDO_REPORTE = "PRODUTO CONFERIDO AGUARDANDO REPORTE"
AGUARDANDO_KARDEX = "AGUARDANDO KARDEX"
BAIXA_ACIMA_NECESSIDADE = "PRODUTO COM BAIXA MAIOR QUE A NECESSIDADE"
MATERIAL_CONSUMO = "MATERIAL DE CONSUMO"

FINAL_STAGES = frozenset({FINALIZADO_PATIO, FINALIZADO_ENTREGUE, NF_EMITIDA, FINALIZADO, REPORTADO})
ALERT_RESULTS = frozenset({
    NAO_CONSUMIDO_G9, NAO_CONSUMIDO_OUTRO, NAO_CONSUMIDO_SEM,
    SEPARADO_SEM_CONFERENCIA, AGUARDANDO_SEPARACAO,
    BAIXA_ACIMA_NECESSIDADE,
})


def _text(value) -> str:
    try:
        if value is None or bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _normalized(value) -> str:
    import unicodedata
    raw = unicodedata.normalize("NFKD", _text(value))
    return " ".join("".join(c for c in raw if not unicodedata.combining(c)).upper().split())


def _present(value) -> bool:
    return _normalized(value) not in ("", "NI", "N/I", "N/A", "NONE", "NULL", "NAN", "-", "NAT")


def decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(_text(value).replace(",", ".") or "0")
    except (InvalidOperation, ValueError):
        return ZERO


def has_patios_days(value) -> bool:
    raw = _text(value)
    if not _present(raw):
        return False
    try:
        candidate = Decimal(raw.replace(",", "."))
        return candidate.is_finite() and candidate >= 0
    except InvalidOperation:
        return False


def has_consumption(item) -> bool:
    """Somente consumo líquido positivo identificado no KARDEX da OP/produto."""
    return decimal(item.get("baixada")) > EPS


def op_status(info: dict, *, has_issue: bool, has_conference: bool, has_separation: bool) -> str:
    patios = info.get("dias_patio")
    if has_patios_days(patios):
        return FINALIZADO_PATIO
    if _normalized(patios) == _normalized(FINALIZADO_ENTREGUE):
        return FINALIZADO_ENTREGUE
    if _present(info.get("nota_fiscal")) or _present(info.get("data_faturamento")):
        return NF_EMITIDA
    if _normalized(info.get("condicao")) == FINALIZADO:
        return FINALIZADO
    if has_issue:
        return REPORTADO
    if has_conference:
        return EM_CONFERENCIA
    if has_separation:
        return EM_SEPARACAO
    return AGUARDANDO_INICIO


def _stock_by_lot(model: dict):
    amounts = defaultdict(lambda: ZERO)
    for raw in model.get("stock") or ():
        code, lot = _text(raw.get("codigo")), _text(raw.get("lote"))
        addr, wh = _normalized(raw.get("endereco")), _text(raw.get("armazem"))
        if code and lot:
            amounts[(code, lot, wh, addr)] += decimal(raw.get("saldo"))
    return amounts


def _item_lots(model: dict):
    # Só admite endereços de lotes conferidos; o consumo KARDEX sem lote
    # continua sendo atribuído apenas no agregado da OP/produto.
    lots = defaultdict(set)
    for row in model.get("general") or ():
        if row.get("conferencia") and _text(row.get("lote")):
            lots[row.get("item_id")].add(_text(row.get("lote")))
    return lots


def apply(model: dict, master_records: dict[str, dict] | None = None,
          catalog_types: dict[str, str] | None = None) -> dict:
    """Modelo final independente do cache: recalcula OPs, produtos e alertas.

    Chamar após reconciliar MES/KARDEX e obter os dados complementares FOR001.
    Não altera as evidências de movimento nem o modelo original cacheado.
    """
    import master_plan
    records = master_records or {}
    types = catalog_types or {}
    result = dict(model)
    ops = master_plan.enrich_ops(model["ops"], records)
    products = model["items"].copy(deep=True)
    if ops.empty or products.empty:
        result["ops"], result["items"] = ops, products
        result["status_version"] = VERSION
        return result

    amounts = _stock_by_lot(model)
    lots = _item_lots(model)
    # Índice de endereços por produto/lote: evita procurar os mesmos 10 mil
    # endereços para cada um dos ~27 mil registros do Relatório Geral.
    addresses_by_lot = defaultdict(list)
    g9_by_lot = defaultdict(lambda: ZERO)
    for (code, lot, wh, addr), qty in amounts.items():
        if addr == "G9-PROD":
            g9_by_lot[(code, lot)] += qty
        elif qty > EPS:
            addresses_by_lot[(code, lot)].append(
                {"armazem": wh, "endereco": addr, "lote": lot, "saldo": qty}
            )
    by_op = products.groupby("op", sort=False)
    # O KARDEX pode trazer consumo da OP em materiais que não constam na
    # fotografia atual do MES. Esse consumo também avança a OP para REPORTADO.
    by_op_code = defaultdict(lambda: [ZERO, ZERO])
    for movement in model.get("movements") or ():
        if movement.get("natureza") not in ("BAIXA / DEVOLUÇÃO", "CONSUMO DE OP"):
            continue
        key = (_text(movement.get("op")), _text(movement.get("codigo")))
        by_op_code[key][0] += decimal(movement.get("qtd_saida"))
        by_op_code[key][1] += decimal(movement.get("qtd_entrada"))
    op_consumed = {
        op for (op, _), (outgoing, incoming) in by_op_code.items()
        if outgoing - incoming > EPS
    }
    op_info = {}
    for row in ops.to_dict("records"):
        op = row["op"]
        group = by_op.get_group(op)
        has_issue = (op in op_consumed or
                     any(has_consumption(item) for item in group.to_dict("records")))
        stage = op_status(
            row,
            has_issue=has_issue,
            has_conference=bool(int(row.get("conferidos") or 0)),
            has_separation=bool(int(row.get("separados") or 0)),
        )
        op_info[op] = {"status": stage, "possui_consumo": has_issue,
                       "exige_baixa": stage in FINAL_STAGES or has_issue}

    # Define o resultado para cada produto SEM usar alertas do reconciliador antigo.
    for idx, item in products.iterrows():
        group = op_info[item["op"]]
        separated, confirmed = decimal(item.get("separada")), decimal(item.get("conferida"))
        net = max(decimal(item.get("baixada")), ZERO)
        expected = max(separated, confirmed)
        outstanding = max(expected - net, ZERO)
        tipo = _normalized(types.get(_text(item.get("codigo")), "NI"))
        item_lots = lots.get(item["item_id"], set())
        # Endereços alternativos só aparecem quando o G9-PROD não consegue
        # atender toda a quantidade SEPARADA, nunca apenas por saldo positivo.
        lot_prod = sum(
            (g9_by_lot[(item.get("codigo"), lot)] for lot in item_lots), ZERO
        )
        faltante_endereco = max(separated - max(lot_prod, ZERO), ZERO)
        alternatives = []
        if (separated > EPS and confirmed > EPS and outstanding > EPS
                and faltante_endereco > EPS and group["exige_baixa"]):
            for lot in item_lots:
                alternatives.extend(addresses_by_lot.get((item.get("codigo"), lot), ()))
            alternatives.sort(key=lambda r: (
                r["saldo"] + EPS < faltante_endereco,
                abs(r["saldo"] - faltante_endereco),
                -r["saldo"], r["armazem"], r["endereco"], r["lote"],
            ))
        products.at[idx, "enderecos_alternativos"] = alternatives
        products.at[idx, "outros_enderecos"] = " | ".join(
            f"{entry['armazem']}/{entry['endereco']} · lote {entry['lote']}: {entry['saldo']}"
            for entry in alternatives
        )
        products.at[idx, "tipo_material"] = tipo or "NI"
        products.at[idx, "qtd_necessaria_baixa"] = expected
        products.at[idx, "qtd_faltante_operacional"] = outstanding
        products.at[idx, "status_op"] = group["status"]
        products.at[idx, "op_possui_baixa"] = group["possui_consumo"]

        # Material Tipo II sem separação é consumo operacional e não deve
        # criar falso alerta; nos demais, baixa além da necessidade prevalece.
        if tipo == "II" and separated <= EPS:
            status, alert = MATERIAL_CONSUMO, False
        elif net - decimal(item.get("necessaria")) > EPS:
            status, alert = BAIXA_ACIMA_NECESSIDADE, True
        elif not group["exige_baixa"]:
            if confirmed > EPS:
                status = CONFERIDO_AGUARDANDO_REPORTE
            elif separated > EPS:
                status = SEPARADO_SEM_CONFERENCIA
            else:
                status = AGUARDANDO_SEPARACAO
            alert = False
        elif confirmed <= EPS:
            status = SEPARADO_SEM_CONFERENCIA if separated > EPS else AGUARDANDO_SEPARACAO
            alert = True
        elif not model.get("history_available"):
            # Sem KARDEX não é possível afirmar falta de baixa.
            status, alert = AGUARDANDO_KARDEX, False
        elif outstanding <= EPS:
            status, alert = PRODUTO_CONSUMIDO, False
        else:
            # Positivo no G9-PROD identifica material em produção mesmo quando
            # o saldo não cobre toda a quantidade faltante.
            if lot_prod > EPS:
                status = NAO_CONSUMIDO_G9
            elif any(entry["saldo"] + EPS >= outstanding for entry in alternatives):
                status = NAO_CONSUMIDO_OUTRO
            else:
                status = NAO_CONSUMIDO_SEM
            alert = True

        products.at[idx, "status"] = status
        products.at[idx, "alertas"] = [status] if alert else []
        products.at[idx, "divergente"] = alert

    counted = products.groupby("op", sort=False)
    ops["status_op"] = ops["op"].map(lambda op: op_info[op]["status"])
    ops["possui_consumo"] = ops["op"].map(lambda op: op_info[op]["possui_consumo"])
    ops["exige_baixa"] = ops["op"].map(lambda op: op_info[op]["exige_baixa"])
    ops["divergencias"] = ops["op"].map(
        lambda op: int(counted.get_group(op)["divergente"].sum()))
    ops["baixados"] = ops["op"].map(
        lambda op: int(sum(
            int(item["itens_conferidos"])
            for item in counted.get_group(op).to_dict("records")
            if item["status"] == PRODUTO_CONSUMIDO
        )))
    result["items"], result["ops"] = products, ops
    result["status_version"] = VERSION
    return result
