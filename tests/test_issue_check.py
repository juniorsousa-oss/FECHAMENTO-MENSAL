from __future__ import annotations

import sys
import unittest
from decimal import Decimal as D
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import issue_check as c

OP = "26000101001"
OTHER_OP = "26000201001"
CODE = "00001000"
META = [{"arquivo_nome": "teste.xlsx", "periodo_inicio": "2026-01-01", "periodo_fim": "2026-10-21", "lancamentos": 1}]


def general(**changes):
    row = {"Projeto": OP, "P.A.": "50000001", "Descrição P.A.": "PA TESTE", "Código": CODE,
           "Lote": "000001", "Descrição": "MATERIAL TESTE", "Qtd. necessária": 10, "Qtd. atendida": 10,
           "Data de separação": "19/10/26 08:00", "Data de conferência": "20/10/26 08:00"}
    row.update(changes)
    return row


def stock(**changes):
    row = {"Produto": CODE, "Lote": "000001", "Armazem": "S2", "Endereco": "G9-PROD", "Quantidade": 6, "Empenho": 0}
    row.update(changes)
    return row


def movement(**changes):
    row = {"codigo": CODE, "ae_original": "OP" + OP, "armazem": "S2", "data": "2026-10-20", "tes": "550",
           "qtd_saida": "4", "qtd_entrada": None, "documento": "DOC", "arquivo_origem": "teste.xlsx", "linha_origem": 3}
    row.update(changes)
    return row


def audit(g=None, s=None, m=None, **changes):
    args = {"history_metas": META, "as_of": "2026-10-21"}
    args.update(changes)
    return c.reconcile(c.parse_general(pd.DataFrame(g if g is not None else [general()])),
                       c.parse_stock(pd.DataFrame(s)) if s else [], m if m is not None else [], **args)


class IssueCheckTests(unittest.TestCase):
    def test_cumulative_history_sums_same_op_product_across_months_without_common_warehouse_period(self):
        metas = [
            {"arquivo_nome": "JAN_S2.xlsx", "armazem": "S2",
             "periodo_inicio": "2026-01-01", "periodo_fim": "2026-01-31"},
            {"arquivo_nome": "SET_S2.xlsx", "armazem": "S2",
             "periodo_inicio": "2026-09-01", "periodo_fim": "2026-09-30"},
            {"arquivo_nome": "OUT_S1.xlsx", "armazem": "S1",
             "periodo_inicio": "2026-10-01", "periodo_fim": "2026-10-21"},
        ]
        movements = [
            movement(data="2026-01-12", qtd_saida="2", documento="JAN"),
            movement(data="2026-09-18", qtd_saida="3", documento="SET"),
            movement(data="2026-10-08", armazem="S1", qtd_saida="4", documento="OUT"),
            movement(data="2026-10-09", armazem="S1", qtd_saida=None,
                     qtd_entrada="1", documento="DEV", tes="020"),
            # Movimentos futuros não entram no saldo acumulado de referência.
            movement(data="2026-10-22", qtd_saida="99", documento="FUT"),
            # Outros produtos/OPs não podem contaminar esta soma.
            movement(data="2026-09-18", codigo="00009999", qtd_saida="20"),
            movement(data="2026-09-18", ae_original="OP99999999", qtd_saida="30"),
        ]
        result = audit(
            m=movements, history_metas=metas, warehouses=("S1", "S2"),
            accumulated_history=True,
        )
        product = result["items"].iloc[0]
        self.assertEqual(product.saida_bruta, D(9))
        self.assertEqual(product.devolvida, D(1))
        self.assertEqual(product.baixada, D(8))
        self.assertEqual(product.pendente, D(2))
        self.assertEqual(result["movimentos_apos_base"], 1)
        self.assertEqual(result["coverage"]["modo"], "ACUMULADO")
        self.assertEqual(result["coverage"]["inicio"], "2026-01-01")
        self.assertEqual(result["coverage"]["fim"], "2026-10-21")
        self.assertEqual(result["coverage"]["por_armazem"]["S1"]["inicio"], "2026-10-01")
        self.assertEqual(result["coverage"]["por_armazem"]["S2"]["fim"], "2026-09-30")
        self.assertFalse(product.historico_incompleto)

    def test_previous_coverage_mode_still_reports_warehouse_intersection(self):
        metas = [
            {"armazem": "S2", "periodo_inicio": "2026-01-01",
             "periodo_fim": "2026-01-31"},
            {"armazem": "S1", "periodo_inicio": "2026-10-01",
             "periodo_fim": "2026-10-21"},
        ]
        self.assertEqual(c.coverage(metas, ("S1", "S2"))["intervalos"], [])

    def test_confirmed_without_stock_or_issue_is_an_alert(self):
        item = audit()["items"].iloc[0]
        self.assertEqual(item.sem_saldo, 10)
        self.assertEqual(item.pendente, 10)
        self.assertIn(c.MISSING, item.alertas)

    def test_partial_issue_with_remaining_g9_prod_stock_is_an_alert(self):
        item = audit(s=[stock()], m=[movement()])["items"].iloc[0]
        self.assertEqual((item.conferida, item.baixada, item.pendente, item.em_g9_prod, item.sem_saldo), (10, 4, 6, 6, 0))
        self.assertEqual(item.alertas, [c.PROD_PENDING])

    def test_issue_of_another_product_does_not_clear_the_op(self):
        item = audit(s=[stock(Quantidade=10)], m=[movement(codigo="00002000", qtd_saida="10")])["items"].iloc[0]
        self.assertEqual(item.baixada, 0)
        self.assertEqual(item.pendente, 10)
        self.assertIn(c.PROD_PENDING, item.alertas)

    def test_stock_before_the_first_issue_of_the_op_is_shown_separately(self):
        item = audit(s=[stock(Quantidade=10)])["items"].iloc[0]
        self.assertNotIn(c.PROD_PENDING, item.alertas)
        self.assertFalse(item.op_possui_baixa)
        self.assertIn("OP SEM BAIXAS", item.status)

    def test_a_fully_reversed_issue_does_not_mean_the_op_has_net_consumption(self):
        item = audit(s=[stock(Quantidade=10)], m=[movement(codigo="00002000"),
                     movement(codigo="00002000", qtd_saida=None, qtd_entrada="4", tes="020")])["items"].iloc[0]
        self.assertFalse(item.op_possui_baixa)
        self.assertNotIn(c.PROD_PENDING, item.alertas)

    def test_complete_issue_is_recognized_without_stock(self):
        item = audit(m=[movement(qtd_saida="10")])["items"].iloc[0]
        self.assertEqual(item.status, "BAIXA IDENTIFICADA")
        self.assertFalse(item.divergente)

    def test_partial_stock_and_partial_issue_can_produce_both_alerts(self):
        item = audit(s=[stock(Quantidade=2)], m=[movement()])["items"].iloc[0]
        self.assertEqual((item.sem_saldo, item.em_g9_prod), (4, 2))
        self.assertIn(c.MISSING, item.alertas)
        self.assertIn(c.PROD_PENDING, item.alertas)

    def test_returns_reduce_the_net_issued_quantity(self):
        item = audit(m=[movement(qtd_saida="10"), movement(tes="020", qtd_saida=None, qtd_entrada="2")])["items"].iloc[0]
        self.assertEqual((item.saida_bruta, item.devolvida, item.baixada, item.pendente), (10, 2, 8, 2))

    def test_address_transfers_remain_as_evidence_but_do_not_prove_consumption(self):
        model = audit(m=[movement(tes="999", qtd_saida="10"), movement(tes="499", qtd_saida=None, qtd_entrada="10")])
        self.assertEqual(len(model["movements"]), 2)
        self.assertEqual(model["items"].iloc[0].baixada, 0)
        self.assertIn(c.MISSING, model["items"].iloc[0].alertas)

    def test_op_link_must_match_completely(self):
        item = audit(m=[movement(ae_original="OP" + OP + "0"), movement(ae_original="CC" + OP)])["items"].iloc[0]
        self.assertEqual(item.baixada, 0)
        item = audit(m=[movement(ae_original=" OP " + OP + " ")])["items"].iloc[0]
        self.assertEqual(item.baixada, 4)

    def test_one_issue_is_not_repeated_across_lots(self):
        model = audit(g=[general(**{"Qtd. atendida": 5}), general(Lote="000002", **{"Qtd. atendida": 5})],
                      m=[movement(qtd_saida="6")])
        self.assertEqual(len(model["items"]), 1)
        item = model["items"].iloc[0]
        self.assertEqual((item.conferida, item.baixada, item.pendente, item.sem_saldo), (10, 6, 4, 4))
        self.assertEqual(model["lots"].pendente_minima.tolist(), [0, 0])
        self.assertEqual(model["lots"].pendente_maxima.tolist(), [4, 4])

    def test_op_counters_use_distinct_product_codes_not_mes_lines(self):
        rows = [
            general(**{"Qtd. atendida": 4, "Qtd. necessária": 4}),
            general(Lote="000002", **{"Qtd. atendida": 6, "Qtd. necessária": 6}),
            general(Código="00002000", Lote="000003",
                    **{"Data de conferência": None}),
        ]
        result = audit(g=rows)
        op_row = result["ops"].iloc[0]
        self.assertEqual(int(op_row.itens), 2)
        self.assertEqual(int(op_row.produtos), 2)
        self.assertEqual(int(op_row.separados), 2)
        self.assertEqual(int(op_row.conferidos), 1)
        self.assertEqual(int(op_row.linhas_mes), 3)
        self.assertEqual(int(op_row.linhas_separadas_mes), 3)
        self.assertEqual(int(op_row.linhas_conferidas_mes), 2)
        self.assertEqual(len(result["items"]), 2)

    def test_stock_of_another_lot_does_not_cover_the_confirmed_lot(self):
        item = audit(s=[stock(Lote="000002", Quantidade=100)])["items"].iloc[0]
        self.assertEqual(item.saldo, 0)
        self.assertEqual(item.sem_saldo, 10)

    def test_displayed_stock_keeps_the_actual_quantity_not_only_the_demand(self):
        item = audit(g=[general(**{"Qtd. atendida": 5})], s=[stock(Quantidade=20)])["items"].iloc[0]
        self.assertEqual((item.saldo, item.saldo_g9_prod, item.cobertura_saldo, item.em_g9_prod), (20, 20, 5, 5))

    def test_the_same_stock_is_not_promised_independently_to_two_ops(self):
        model = audit(g=[general(**{"Qtd. atendida": 8}), general(Projeto=OTHER_OP, **{"Qtd. atendida": 8})],
                      s=[stock(Endereco="ALMOX", Quantidade=10)])
        self.assertTrue(model["items"].conflito_saldo.all())
        self.assertTrue(model["items"].saldo_compartilhado.all())
        self.assertTrue(all(c.SHARED in alerts for alerts in model["items"].alertas))
        self.assertEqual(model["lots"].demanda_compartilhada_minima.tolist(), [16, 16])

    def test_issued_quantity_is_removed_before_testing_shared_pending_demand(self):
        model = audit(g=[general(**{"Qtd. atendida": 8}), general(Projeto=OTHER_OP, **{"Qtd. atendida": 8})],
                      s=[stock(Endereco="ALMOX", Quantidade=10)], m=[movement(qtd_saida="6")])
        self.assertFalse(model["items"].conflito_saldo.any())
        self.assertEqual(model["lots"].demanda_compartilhada_minima.tolist(), [10, 10])

    def test_lot_pending_bounds_preserve_the_unknown_lot_of_the_issue(self):
        model = audit(g=[general(**{"Qtd. atendida": 8}), general(Lote="000002", **{"Qtd. atendida": 2})],
                      m=[movement(qtd_saida="6")])
        lots = model["lots"].set_index("lote")
        self.assertEqual((lots.loc["000001", "pendente_minima"], lots.loc["000001", "pendente_maxima"]), (2, 4))
        self.assertEqual((lots.loc["000002", "pendente_minima"], lots.loc["000002", "pendente_maxima"]), (0, 2))

    def test_unavailable_history_is_unknown_instead_of_zero_issues(self):
        item = audit(history_metas=[])["items"].iloc[0]
        self.assertIsNone(item.baixada)
        self.assertIsNone(item.pendente)
        self.assertIsNone(item.sem_saldo)
        self.assertNotIn(c.MISSING, item.alertas)
        self.assertEqual(item.status, "AGUARDANDO KARDEX")

    def test_movements_after_the_stock_snapshot_do_not_clear_older_gaps(self):
        model = audit(m=[movement(data="2026-10-22", qtd_saida="10")])
        self.assertEqual(model["movimentos_apos_base"], 1)
        self.assertEqual(model["items"].iloc[0].pendente, 10)

    def test_a_gap_inside_history_is_not_mistaken_for_complete_coverage(self):
        metas = [{**META[0], "periodo_fim": "2026-03-31"}, {**META[0], "periodo_inicio": "2026-06-01"}]
        item = audit(g=[general(**{"Data de conferência": "15/05/26 08:00"})], history_metas=metas)["items"].iloc[0]
        self.assertTrue(item.historico_incompleto)
        self.assertTrue(audit(history_metas=[{**META[0], "periodo_fim": "2026-10-19"}])["items"].iloc[0].historico_incompleto)
        self.assertFalse(audit()["items"].iloc[0].historico_incompleto)

    def test_a_confirmation_after_the_stock_date_is_not_complete(self):
        item = audit(g=[general(**{"Data de conferência": "22/10/26 08:00"})],
                     history_metas=[{**META[0], "periodo_fim": "2026-10-31"}])["items"].iloc[0]
        self.assertTrue(item.historico_incompleto)

    def test_different_source_dates_are_not_presented_as_complete(self):
        model = audit(sources_same_day=False)
        self.assertTrue(model["items"].iloc[0].historico_incompleto)
        self.assertEqual(model["ops"].iloc[0].incompletos, 1)

    def test_only_confirmed_quantities_enter_the_audit(self):
        item = audit(g=[general(**{"Data de conferência": None})], s=[stock()])["items"].iloc[0]
        self.assertEqual(item.conferida, 0)
        self.assertFalse(item.divergente)
        self.assertEqual(item.status, "AGUARDANDO CONFERÊNCIA")

    def test_a_partial_confirmation_uses_attended_not_required_quantity(self):
        item = audit(g=[general(**{"Qtd. atendida": 4})], m=[movement(qtd_saida="4")])["items"].iloc[0]
        self.assertEqual((item.necessaria, item.conferida, item.pendente), (10, 4, 0))

    def test_confirmation_without_attended_quantity_stays_visible(self):
        item = audit(g=[general(**{"Qtd. atendida": 0})])["items"].iloc[0]
        self.assertIn(c.NO_QUANTITY, item.alertas)
        self.assertNotIn(c.MISSING, item.alertas)

    def test_missing_material_codes_remain_separate_source_records(self):
        model = audit(g=[general(Código=None, **{"Data de conferência": None}),
                         general(Código=None, Descrição="SEGUNDO MATERIAL", **{"Data de conferência": None})])
        self.assertEqual(len(model["items"]), 2)
        self.assertEqual(model["items"].codigo.tolist(), ["", ""])
        self.assertEqual(model["ops"].iloc[0].itens, 2)
        self.assertTrue(all(c.NO_CODE in alerts for alerts in model["items"].alertas))

    def test_normalized_matrix_headers_dates_and_identifiers(self):
        row = general()
        frame = pd.DataFrame([list(row), list(row.values())])
        parsed = c.parse_general(frame)[0]
        self.assertEqual((parsed["codigo"], parsed["lote"], parsed["op"]), (CODE, "000001", OP))
        self.assertEqual(parsed["conferencia"], "2026-10-20T08:00:00")
        self.assertEqual(parsed["linha_origem"], 2)
        stock_matrix = pd.DataFrame([["Listagem do Browse"], list(stock()), list(stock().values())])
        self.assertEqual(c.parse_stock(stock_matrix)[0]["linha_origem"], 3)

    def test_blank_lot_and_zero_lot_are_not_combined(self):
        item = audit(g=[general(Lote="")], s=[stock(Lote="000000000", Quantidade=10)])["items"].iloc[0]
        self.assertIn(c.NO_LOT, item.alertas)
        self.assertIsNone(item.sem_saldo)

    def test_negative_stock_offsets_positive_stock_without_disappearing(self):
        model = audit(g=[general(**{"Qtd. atendida": 5})], s=[stock(Quantidade=10), stock(Quantidade=-7)])
        self.assertEqual(model["negative_stock_rows"], 1)
        self.assertEqual(model["items"].iloc[0].sem_saldo, 2)

    def test_decimal_precision_does_not_hide_material_differences(self):
        item = audit(m=[movement(qtd_saida="9.9999999999")])["items"].iloc[0]
        self.assertEqual(item.pendente, 0)
        item = audit(m=[movement(qtd_saida="9.999")])["items"].iloc[0]
        self.assertEqual(item.pendente, D("0.001"))

    def test_missing_quantities_and_wrong_schema_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Quantidade ausente"):
            c.parse_general(pd.DataFrame([general(**{"Qtd. atendida": None})]))
        with self.assertRaisesRegex(ValueError, "Cabeçalho"):
            c.parse_stock(pd.DataFrame({"Qualquer coluna": [1]}))

    def test_warehouse_filter_is_applied_to_both_stock_and_kardex(self):
        model = audit(s=[stock(Armazem="E2", Quantidade=10)], m=[movement(armazem="E2", qtd_saida="10")])
        self.assertEqual(model["items"].iloc[0].sem_saldo, 10)
        other = audit(s=[stock(Armazem="E2", Quantidade=10)], m=[movement(armazem="E2", qtd_saida="10")], warehouses=("E2",))
        self.assertEqual(other["items"].iloc[0].pendente, 0)


if __name__ == "__main__":
    unittest.main()
