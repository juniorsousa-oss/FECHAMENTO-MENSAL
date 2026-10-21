from __future__ import annotations

import sys
import unittest
from pathlib import Path
from decimal import Decimal

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import issue_check as check
import operational_status as op

OP = "26000101001"
CODE = "00001000"
LOT = "000001"
META = [{"arquivo_nome": "kardex.xlsx", "periodo_inicio": "2026-01-01",
         "periodo_fim": "2026-10-21", "lancamentos": 100}]


def raw_item(code=CODE, separacao=True, conferencia=True, qty=10):
    return {
        "Projeto": OP, "Código": code, "Lote": LOT, "Descrição": "MATERIAL",
        "Qtd. necessária": qty, "Qtd. atendida": qty,
        "Data de separação": "19/10/26 08:00" if separacao else None,
        "Data de conferência": "20/10/26 08:00" if conferencia else None,
    }


def raw_stock(qty, endereco="G9-PROD", lot=LOT):
    return {"Produto": CODE, "Lote": lot, "Armazem": "S2",
            "Endereco": endereco, "Quantidade": qty}


def movement(code=CODE, quantity=4):
    return {
        "codigo": code, "ae_original": "OP" + OP, "armazem": "S2",
        "data": "2026-10-20", "tes": "550", "qtd_saida": str(quantity),
        "qtd_entrada": None, "documento": "CONSUMO",
        "arquivo_origem": "kardex.xlsx", "linha_origem": 1,
    }


def model(rows=None, stocks=None, moves=None, master=None, metas=None):
    general = check.parse_general(pd.DataFrame(rows or [raw_item()]))
    stock = check.parse_stock(pd.DataFrame(stocks)) if stocks else []
    source = check.reconcile(
        general, stock, moves if moves is not None else [],
        history_metas=META if metas is None else metas, as_of="2026-10-21",
    )
    return op.apply(source, {OP: master} if master is not None else {})


class OpPriorityTests(unittest.TestCase):
    def test_priority_is_checked_backwards(self):
        info = {"dias_patio": "3", "nota_fiscal": "12",
                "data_faturamento": "20/10/2026", "condicao": "FINALIZADO"}
        self.assertEqual(op.op_status(info, has_issue=True, has_conference=True, has_separation=True),
                         op.FINALIZADO_PATIO)
        info["dias_patio"] = "FINALIZADO E ENTREGUE"
        self.assertEqual(op.op_status(info, has_issue=True, has_conference=True, has_separation=True),
                         op.FINALIZADO_ENTREGUE)
        info["dias_patio"] = "NI"
        self.assertEqual(op.op_status(info, has_issue=True, has_conference=True, has_separation=True),
                         op.NF_EMITIDA)
        info["nota_fiscal"] = info["data_faturamento"] = "NI"
        self.assertEqual(op.op_status(info, has_issue=True, has_conference=True, has_separation=True),
                         op.FINALIZADO)
        info["condicao"] = "NORMAL"
        self.assertEqual(op.op_status(info, has_issue=True, has_conference=True, has_separation=True),
                         op.REPORTADO)
        self.assertEqual(op.op_status(info, has_issue=False, has_conference=True, has_separation=True),
                         op.EM_CONFERENCIA)
        self.assertEqual(op.op_status(info, has_issue=False, has_conference=False, has_separation=True),
                         op.EM_SEPARACAO)
        self.assertEqual(op.op_status(info, has_issue=False, has_conference=False, has_separation=False),
                         op.AGUARDANDO_INICIO)

    def test_zero_days_is_numeric_and_n_i_not_final(self):
        self.assertTrue(op.has_patios_days("0"))
        self.assertFalse(op.has_patios_days("NI"))
        self.assertFalse(op.has_patios_days("FINALIZADO E ENTREGUE"))
        self.assertFalse(op.has_patios_days("-2"))

    def test_fully_consumed_when_confirmed_and_separated(self):
        result = model(moves=[movement(quantity=10)], stocks=[raw_stock(0)])
        product = result["items"].iloc[0]
        self.assertEqual(result["ops"].iloc[0]["status_op"], op.REPORTADO)
        self.assertEqual(product.status, op.PRODUTO_CONSUMIDO)
        self.assertFalse(product.divergente)
        self.assertEqual(result["ops"].iloc[0].divergencias, 0)
        self.assertEqual(result["ops"].iloc[0].baixados, 1)

    def test_partial_consumption_and_g9_stock_is_alert(self):
        result = model(moves=[movement(quantity=4)], stocks=[raw_stock(2)])
        product = result["items"].iloc[0]
        self.assertEqual(product.status, op.NAO_CONSUMIDO_G9)
        self.assertTrue(product.divergente)
        self.assertEqual(product.qtd_faltante_operacional, Decimal(6))

    def test_other_address_must_individually_cover_shortage(self):
        stocks = [raw_stock(0), raw_stock(3, "E-A"), raw_stock(6, "E-B"),
                  raw_stock(25, "OUTRO-LOTE", "000002")]
        result = model(master={"condicao": "FINALIZADO"}, stocks=stocks)
        product = result["items"].iloc[0]
        self.assertEqual(product.status, op.NAO_CONSUMIDO_SEM)
        self.assertTrue(product.divergente)
        self.assertNotIn("OUTRO-LOTE", product.outros_enderecos)
        stocks[2]["Quantidade"] = 10
        product = model(master={"condicao": "FINALIZADO"}, stocks=stocks)["items"].iloc[0]
        self.assertEqual(product.status, op.NAO_CONSUMIDO_OUTRO)
        self.assertTrue(product.divergente)

    def test_advanced_op_alerts_start_only_after_separation(self):
        sep = model(rows=[raw_item(conferencia=False)],
                    master={"condicao": "FINALIZADO"})
        self.assertEqual(sep["items"].iloc[0].status, op.SEPARADO_SEM_CONFERENCIA)
        self.assertTrue(sep["items"].iloc[0].divergente)
        none = model(rows=[raw_item(separacao=False, conferencia=False)],
                     master={"nota_fiscal": "124"})
        self.assertEqual(none["items"].iloc[0].status, op.AGUARDANDO_SEPARACAO)
        self.assertFalse(none["items"].iloc[0].divergente)
        self.assertEqual(int(none["ops"].iloc[0].divergencias), 0)

    def test_unseparated_items_are_exempt_across_all_op_stages(self):
        scenarios = [
            ({"dias_patio": "4"}, [], "FINALIZADO EM PÁTIO"),
            ({"dias_patio": "FINALIZADO E ENTREGUE"}, [], "FINALIZADO E ENTREGUE"),
            ({"nota_fiscal": "124"}, [], "NF EMITIDA"),
            ({"condicao": "FINALIZADO"}, [], "FINALIZADO"),
            ({}, [movement("00002000", 2)], "REPORTADO"),
            ({}, [], "AGUARDANDO INÍCIO"),
        ]
        for extra, movements, stage in scenarios:
            with self.subTest(stage=stage):
                result = model(
                    rows=[raw_item(separacao=False, conferencia=False)],
                    master=extra, moves=movements,
                )
                self.assertEqual(result["ops"].iloc[0].status_op, stage)
                self.assertEqual(result["items"].iloc[0].status, op.AGUARDANDO_SEPARACAO)
                self.assertFalse(result["items"].iloc[0].divergente)

    def test_unseparated_excess_consumption_is_not_alert_before_separation(self):
        item = model(rows=[raw_item(separacao=False, conferencia=False, qty=1)],
                     moves=[movement(quantity=3)], master={"condicao": "FINALIZADO"})
        self.assertEqual(item["items"].iloc[0].status, op.AGUARDANDO_SEPARACAO)
        self.assertFalse(item["items"].iloc[0].divergente)

    def test_op_without_consumption_and_unfinished_has_no_alert(self):
        for separate, confer, expected, op_stage in [
            (True, True, op.CONFERIDO_AGUARDANDO_REPORTE, op.EM_CONFERENCIA),
            (True, False, op.SEPARADO_SEM_CONFERENCIA, op.EM_SEPARACAO),
            (False, False, op.AGUARDANDO_SEPARACAO, op.AGUARDANDO_INICIO),
        ]:
            with self.subTest(separate=separate, conference=confer):
                result = model(rows=[raw_item(separacao=separate, conferencia=confer)])
                self.assertEqual(result["items"].iloc[0].status, expected)
                self.assertEqual(result["ops"].iloc[0]["status_op"], op_stage)
                self.assertFalse(result["items"].iloc[0].divergente)

    def test_movement_of_another_product_also_reports_op(self):
        result = model(rows=[raw_item()], moves=[movement("00002000", 2)])
        self.assertEqual(result["ops"].iloc[0].status_op, op.REPORTADO)
        self.assertTrue(result["items"].iloc[0].divergente)

    def test_excess_consumption_uses_quantity_necessary_not_conference(self):
        # 2 necessários, 1 separado e 3 baixados: excesso sobre SOLICITAÇÃO.
        row = raw_item(qty=2)
        row["Qtd. atendida"] = 1
        result = model(rows=[row], moves=[movement(quantity=3)])
        product = result["items"].iloc[0]
        self.assertEqual(product.status, op.BAIXA_ACIMA_NECESSIDADE)
        self.assertTrue(product.divergente)
        self.assertEqual(int(result["ops"].iloc[0].divergencias), 1)

    def test_type_ii_without_separation_is_consumption_material_not_alert(self):
        initial = check.reconcile(
            check.parse_general(pd.DataFrame([raw_item(separacao=False, conferencia=False)])),
            [], [], history_metas=META, as_of="2026-10-21",
        )
        result = op.apply(initial, {OP: {"condicao": "FINALIZADO"}}, {CODE: "II"})
        item = result["items"].iloc[0]
        self.assertEqual(item.status, op.MATERIAL_CONSUMO)
        self.assertFalse(item.divergente)
        self.assertEqual(item.tipo_material, "II")
        self.assertEqual(result["ops"].iloc[0].divergencias, 0)

    def test_type_ii_with_separation_keeps_normal_rules(self):
        initial = check.reconcile(
            check.parse_general(pd.DataFrame([raw_item(conferencia=False)])),
            [], [], history_metas=META, as_of="2026-10-21",
        )
        result = op.apply(initial, {OP: {"condicao": "FINALIZADO"}}, {CODE: "II"})
        self.assertEqual(result["items"].iloc[0].status, op.SEPARADO_SEM_CONFERENCIA)
        self.assertTrue(result["items"].iloc[0].divergente)

    def test_type_ii_without_separation_remains_consumption_material_even_if_not_required(self):
        initial = check.reconcile(
            check.parse_general(pd.DataFrame([raw_item(separacao=False, conferencia=False, qty=0)])),
            [], [movement(quantity=2)], history_metas=META, as_of="2026-10-21",
        )
        result = op.apply(initial, {OP: {"condicao": "FINALIZADO"}}, {CODE: "II"})
        self.assertEqual(result["items"].iloc[0].status, op.MATERIAL_CONSUMO)
        self.assertFalse(result["items"].iloc[0].divergente)

    def test_type_ii_with_separation_is_flagged_if_consumption_exceeds_required(self):
        initial = check.reconcile(
            check.parse_general(pd.DataFrame([raw_item(qty=1)])),
            [], [movement(quantity=2)], history_metas=META, as_of="2026-10-21",
        )
        result = op.apply(initial, {OP: {"condicao": "FINALIZADO"}}, {CODE: "II"})
        self.assertEqual(result["items"].iloc[0].status, op.BAIXA_ACIMA_NECESSIDADE)
        self.assertTrue(result["items"].iloc[0].divergente)

    def test_other_addresses_only_if_g9_cannot_cover_separated_qty(self):
        stock = [
            raw_stock(10, "G9-PROD"),
            raw_stock(20, "G9-RESERVA"),
        ]
        result = model(master={"condicao": "FINALIZADO"}, stocks=stock)
        self.assertEqual(result["items"].iloc[0].outros_enderecos, "")
        self.assertEqual(result["items"].iloc[0].enderecos_alternativos, [])
        stock[0]["Quantidade"] = 7
        partial = model(master={"condicao": "FINALIZADO"}, stocks=stock)
        product = partial["items"].iloc[0]
        self.assertEqual(product.status, op.NAO_CONSUMIDO_G9)
        self.assertIn("G9-RESERVA", product.outros_enderecos)
        self.assertEqual(float(product.enderecos_alternativos[0]["saldo"]), 20)

    def test_no_kardex_cannot_certify_consumption(self):
        result = model(master={"condicao": "FINALIZADO"}, metas=[])
        product = result["items"].iloc[0]
        self.assertEqual(result["ops"].iloc[0].status_op, op.FINALIZADO)
        self.assertEqual(product.status, op.AGUARDANDO_KARDEX)
        self.assertFalse(product.divergente)

    def test_old_alerts_do_not_leak_into_new_operational_model(self):
        source = check.reconcile(check.parse_general(pd.DataFrame([raw_item()])),
                                 [], [], history_metas=META, as_of="2026-10-21")
        self.assertTrue(source["items"].iloc[0].divergente)
        new = op.apply(source)
        self.assertEqual(new["items"].iloc[0].status, op.CONFERIDO_AGUARDANDO_REPORTE)
        self.assertFalse(new["items"].iloc[0].divergente)
        self.assertEqual(int(new["ops"].iloc[0].divergencias), 0)


if __name__ == "__main__":
    unittest.main()
