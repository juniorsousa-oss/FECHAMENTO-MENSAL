"""Regressões da conferência por OP + produto + lote (MES + OPS).

Nenhuma base de produção é modificada. Os três testes de falta diferenciam
ausência real de quantidade e diferença somente no vínculo do lote.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO
import unittest

import pandas as pd
from openpyxl import load_workbook

import issue_check
import lot_conference
import operational_status as stages
import reports


OP = "26015901001"
CODE = "00041468"
LOT_A = "062285"
LOT_B = "062984"
LOT_C = "062985"
META = {
    "arquivo_nome": "OPS.xlsx",
    "periodo_inicio": "2026-01-01",
    "periodo_fim": "2026-11-04",
    "movimentos_validos": 3,
}


def mes(lot: str, quantity: int, *, confirmed=True):
    return {
        "Projeto": OP, "Código": CODE,
        "Descrição": "LONGARINA",
        "Lote": lot,
        "Qtd. necessária": quantity,
        "Qtd. atendida": quantity,
        "Data de separação": "03/10/2026",
        "Resp. Conferencia": "MOISÉS" if confirmed else "",
        "Data de conferência": "03/10/2026" if confirmed else "",
    }


def move(lot: str, qty: int, day="2026-10-04"):
    return {
        "op": OP, "codigo": CODE, "lote": lot,
        "tipo_movimento": "RE0", "tes": "550",
        "data": day, "quantidade": str(qty),
        "documento": "DOC",
    }


def model(lines, ops, *, with_prices=True):
    parsed = issue_check.parse_general(pd.DataFrame(lines))
    reconciled = issue_check.reconcile_ops(
        parsed, [], ops, ops_meta=META, as_of="2026-11-04"
    )
    result = stages.apply(reconciled)
    if with_prices:
        result["catalog_prices"] = {CODE: 20.0}
    return result


class LotReportTests(unittest.TestCase):
    def test_large_ops_history_uses_indexed_lookup_per_product(self):
        """Carga sintética: muitos materiais e baixas sem multiplicar varreduras."""
        import time

        n = 2500
        general, items, ops, moves = [], [], [], []
        for k in range(n):
            op = f"{26000000000+k}"
            code = f"{k:08d}"
            product_id = f"{op}:{code}"
            general.append({
                "op": op, "codigo": code, "lote": "000000001",
                "necessaria": Decimal("1"), "atendida": Decimal("1"),
                "responsavel_conferencia": "CONFERENTE",
                "descricao": "MATERIAL",
            })
            items.append({
                "op": op, "codigo": code, "item_id": product_id,
                "descricao": "MATERIAL", "tipo_material": "MP",
                "status": stages.PRODUTO_CONSUMIDO,
                "enderecos_alternativos": [],
            })
            ops.append({
                "op": op, "itens": 1, "produtos": 1, "separados": 1,
                "conferidos": 1, "baixados": 1, "divergencias": 0,
            })
            moves.append({
                "op": op, "codigo": code, "lote": "000000001",
                "natureza": "BAIXA / DEVOLUÇÃO",
                "qtd_saida": "1", "qtd_entrada": "0",
            })
        # Movimentações adicionais do histórico, sem OP correspondente
        # à base Geral atual, não podem disparar nova busca para cada item.
        for k in range(8000):
            moves.append({
                "op": f"{30000000000+k}", "codigo": f"{k:08d}",
                "lote": "000000002", "natureza": "BAIXA / DEVOLUÇÃO",
                "qtd_saida": "1", "qtd_entrada": "0",
            })
        source = {
            "general": general,
            "items": pd.DataFrame(items),
            "ops": pd.DataFrame(ops),
            "lots": pd.DataFrame(),
            "movements": moves,
            "history_available": True,
        }
        beginning = time.perf_counter()
        lines, headers = lot_conference.build(source)
        elapsed = time.perf_counter() - beginning
        self.assertEqual(len(lines), n)
        self.assertEqual(len(headers), n)
        self.assertTrue((lines["pendente"] == Decimal("0")).all())
        self.assertTrue((lines["baixada"] == Decimal("1")).all())
        self.assertFalse(lines["divergente"].any())
        # Limite generoso de CI, mas evita regressão quadrática
        # (>25 milhões de verificações desnecessárias).
        self.assertLess(elapsed, 18.0)

    def test_swapped_lots_3_2_vs_2_3_have_zero_real_pending_but_both_alert(self):
        result = model(
            [mes(LOT_A, 3), mes(LOT_B, 2)],
            [move(LOT_A, 2), move(LOT_B, 3)],
        )
        lot_items = result["lot_items"]
        self.assertEqual(len(lot_items), 2)
        lots = lot_items.set_index("lote")
        self.assertEqual(
            (lots.loc[LOT_A, "necessaria"], lots.loc[LOT_A, "conferida"],
             lots.loc[LOT_A, "baixada"], lots.loc[LOT_A, "pendente"]),
            (3, 3, 2, 0),
        )
        self.assertEqual(
            (lots.loc[LOT_B, "necessaria"], lots.loc[LOT_B, "conferida"],
             lots.loc[LOT_B, "baixada"], lots.loc[LOT_B, "pendente"]),
            (2, 2, 3, 0),
        )
        self.assertEqual(result["items"].iloc[0]["pendente"], 0)
        self.assertFalse(lot_items["divergente"].any())
        self.assertTrue(lot_items["divergencia_lote_informativa"].all())
        self.assertTrue((lot_items["pendente_demanda_produto"] == Decimal("0")).all())
        self.assertEqual(lots.loc[LOT_A, "resultado_lote"], "BAIXA A MENOR NESTE LOTE")
        self.assertEqual(lots.loc[LOT_B, "resultado_lote"], "BAIXA A MAIOR NESTE LOTE")
        self.assertIn("COMPENSADA EM OUTRO LOTE",
                      lots.loc[LOT_A, "detalhe_resultado_lote"])
        self.assertIn("BAIXA A MAIOR NESTE LOTE (1)",
                      lots.loc[LOT_B, "detalhe_resultado_lote"])
        head = result["lot_ops"].iloc[0]
        self.assertEqual((head["itens"], head["separados"], head["conferidos"],
                          head["divergencias"]), (2, 2, 2, 0))
        rows = reports.issue_rows(result)
        self.assertEqual(len(rows), 2)
        self.assertEqual({r[14] for r in rows}, {LOT_A, LOT_B})
        self.assertEqual(sum(r[17] for r in rows), 5)
        self.assertEqual(sum(r[18] for r in rows), 5)
        self.assertEqual(sum(r[19] for r in rows), 0)
        self.assertTrue(all("BAIXA A" in r[24] for r in rows))
        book = load_workbook(
            BytesIO(reports.export_issues(result)),
            read_only=False, data_only=True,
        )
        try:
            sheet = book.active
            self.assertEqual(sheet.max_column, 25)
            self.assertEqual(sheet.max_row, 3)
            self.assertEqual({sheet["O2"].value, sheet["O3"].value},
                             {LOT_A, LOT_B})
            self.assertEqual(sheet["T2"].value, 0)
            self.assertEqual(sheet["T3"].value, 0)
            self.assertEqual(sheet["Y2"].fill.patternType, "solid")
            self.assertEqual(sheet["Y3"].fill.patternType, "solid")
            self.assertTrue(sheet["Y2"].fill.fgColor.rgb.endswith("FFF3D6"))
            self.assertTrue(sheet["Y3"].fill.fgColor.rgb.endswith("FFF3D6"))
            self.assertEqual(sheet["F2"].value, 0)
            self.assertEqual(sheet["F3"].value, 0)
        finally:
            book.close()

    def test_unfulfilled_demand_makes_lot_mismatch_an_active_alert(self):
        result = model(
            [mes(LOT_A, 3), mes(LOT_B, 2)],
            [move(LOT_A, 1), move(LOT_B, 3)],
        )
        lots = result["lot_items"]
        self.assertTrue(lots["divergente"].all())
        self.assertFalse(lots["divergencia_lote_informativa"].any())
        self.assertTrue((lots["pendente_demanda_produto"] == Decimal("1")).all())
        self.assertEqual(result["lot_ops"].iloc[0]["divergencias"], 2)
        self.assertEqual(result["items"].iloc[0]["pendente"], 1)
        self.assertEqual(
            {r[-1] for r in reports.issue_rows(result)},
            {"BAIXA A MENOR NESTE LOTE", "BAIXA A MAIOR NESTE LOTE"},
        )
        # Mesmo quando há alerta ativo, as duas categorias têm tom
        # âmbar: a condição de gravidade é registrada separadamente.
        wb = load_workbook(BytesIO(reports.export_issues(result)), data_only=True)
        try:
            self.assertTrue(wb.active["Y2"].fill.fgColor.rgb.endswith("FFF3D6"))
            self.assertTrue(wb.active["Y3"].fill.fgColor.rgb.endswith("FFF3D6"))
            self.assertEqual(wb.active["F2"].value, 2)
        finally:
            wb.close()

    def test_total_required_includes_not_yet_conferred_lot(self):
        # 4 unidades conferidas/baixadas não atendem a necessidade de 5.
        # O sistema não pode quitar o alerta só porque conferidas=baixadas.
        lines = [
            mes(LOT_A, 3),
            mes(LOT_B, 2, confirmed=False),
        ]
        result = model(lines, [move(LOT_A, 4)])
        lot_a = result["lot_items"].set_index("lote").loc[LOT_A]
        self.assertEqual(lot_a["conferida"], 3)
        self.assertEqual(lot_a["baixada"], 4)
        self.assertEqual(lot_a["pendente_total_produto"], 0)
        self.assertEqual(lot_a["pendente_demanda_produto"], 1)
        self.assertTrue(lot_a["divergente"])
        self.assertEqual(lot_a["resultado_lote"], "BAIXA A MAIOR NESTE LOTE")

    def test_attention_states_are_fixed_colors_without_creating_lot_errors(self):
        for state in (
            stages.AGUARDANDO_SEPARACAO,
            stages.SEPARADO_SEM_CONFERENCIA,
            "BAIXA A MAIOR NESTE LOTE",
            "BAIXA A MENOR NESTE LOTE",
            "DIVERGÊNCIA DE LOTE",
        ):
            with self.subTest(state=state):
                self.assertTrue(lot_conference.is_attention_result(state))
        self.assertFalse(
            lot_conference.is_attention_result(stages.NAO_CONSUMIDO_SEM)
        )
        waiting = model([mes(LOT_A, 2, confirmed=False)], [])
        item = waiting["lot_items"].iloc[0]
        self.assertEqual(item["resultado_lote"],
                         stages.SEPARADO_SEM_CONFERENCIA)
        wb = load_workbook(BytesIO(reports.export_issues(waiting)), data_only=True)
        try:
            self.assertTrue(wb.active["Y2"].fill.fgColor.rgb.endswith("FFF3D6"))
        finally:
            wb.close()

    def test_lot_mismatch_resolved_is_excluded_from_alerts_only_export(self):
        result = model(
            [mes(LOT_A, 3), mes(LOT_B, 2)],
            [move(LOT_A, 2), move(LOT_B, 3)],
        )
        self.assertEqual(result["lot_ops"].iloc[0]["divergencias"], 0)
        # Exibir normalmente no relatório completo, mas NÃO no relatório
        # filtrado por OPs com alertas.
        self.assertEqual(len(reports.issue_rows(result)), 2)
        self.assertEqual(
            reports.issue_rows(result, alerts_only=True), []
        )

    def test_one_real_missing_baixa_is_attributed_to_correct_lot(self):
        result = model(
            [mes(LOT_A, 3), mes(LOT_B, 2)],
            [move(LOT_A, 2), move(LOT_B, 2)],
        )
        rows = result["lot_items"].set_index("lote")
        self.assertEqual(rows.loc[LOT_A, "pendente"], 1)
        self.assertEqual(rows.loc[LOT_B, "pendente"], 0)
        self.assertEqual(rows.loc[LOT_A, "resultado_lote"],
                         stages.NAO_CONSUMIDO_SEM)
        self.assertIn("FALTAM 1 NESTE LOTE",
                      rows.loc[LOT_A, "detalhe_resultado_lote"])
        self.assertEqual(rows.loc[LOT_B, "status"], stages.PRODUTO_CONSUMIDO)
        self.assertFalse(rows.loc[LOT_B, "divergente"])
        excel = reports.issue_rows(result)
        a = next(r for r in excel if r[14] == LOT_A)
        b = next(r for r in excel if r[14] == LOT_B)
        self.assertEqual((a[19], b[19]), (1, 0))
        self.assertEqual((a[20], b[20]), (20, None))
        self.assertEqual(result["items"].iloc[0]["pendente"], 1)

    def test_partial_cross_lot_credit_still_identifies_remainder(self):
        result = model(
            [mes(LOT_A, 3), mes(LOT_B, 2)],
            [move(LOT_A, 1), move(LOT_B, 3)],
        )
        lots = result["lot_items"].set_index("lote")
        self.assertEqual(lots.loc[LOT_A, "falta_bruta_lote"], 2)
        self.assertEqual(lots.loc[LOT_A, "pendente"], 1)
        self.assertEqual(lots.loc[LOT_B, "excesso_lote"], 1)
        self.assertEqual(lots.loc[LOT_B, "pendente"], 0)
        self.assertEqual(lots.loc[LOT_A, "resultado_lote"],
                         "BAIXA A MENOR NESTE LOTE")
        self.assertIn("PENDÊNCIA REAL 1",
                      lots.loc[LOT_A, "detalhe_resultado_lote"])
        self.assertEqual(result["items"].iloc[0]["pendente"], 1)
        self.assertEqual(
            sum(r[19] or 0 for r in reports.issue_rows(result)), 1
        )

    def test_same_op_product_lot_multiple_general_lines_are_summed_once(self):
        result = model(
            [mes(LOT_A, 1), mes(LOT_A, 2), mes(LOT_B, 2)],
            [move(LOT_A, 3), move(LOT_B, 2)],
        )
        lot_view = result["lot_items"]
        self.assertEqual(len(lot_view), 2)
        self.assertEqual(result["lot_ops"].iloc[0]["itens"], 2)
        lot_a = lot_view.set_index("lote").loc[LOT_A]
        self.assertEqual((lot_a["necessaria"], lot_a["separada"],
                          lot_a["conferida"], lot_a["baixada"],
                          lot_a["pendente"]), (3, 3, 3, 3, 0))

    def test_multiple_candidate_lots_partial_credit_is_marked_ambiguous(self):
        result = model(
            [mes(LOT_A, 3), mes(LOT_B, 4), mes(LOT_C, 2)],
            [move(LOT_A, 1), move(LOT_B, 3), move(LOT_C, 3)],
        )
        # Total confirmado 9, total baixa 7. Falta real 2, mas um excesso
        # em C pode ser de A ou B; nenhum lote pode ser escolhido arbitrariamente.
        view = result["lot_items"].set_index("lote")
        self.assertEqual(result["items"].iloc[0]["pendente"], 2)
        self.assertIsNone(view.loc[LOT_A, "pendente"])
        self.assertIsNone(view.loc[LOT_B, "pendente"])
        self.assertTrue(view.loc[LOT_A, "pendencia_indeterminada"])
        self.assertTrue(view.loc[LOT_B, "pendencia_indeterminada"])
        self.assertEqual(view.loc[LOT_A, "resultado_lote"],
                         "DIVERGÊNCIA DE LOTES — PENDÊNCIA A APURAR")
        self.assertIn("NÃO PODE SER COMPROVADA",
                      view.loc[LOT_A, "detalhe_resultado_lote"])
        self.assertEqual(view.loc[LOT_C, "pendente"], 0)
        self.assertIsNone(
            next(r for r in reports.issue_rows(result) if r[14] == LOT_A)[20]
        )

    def test_baixa_in_unexpected_lot_does_not_create_fake_shortage(self):
        result = model(
            [mes(LOT_A, 3)],
            [move(LOT_C, 3)],
        )
        row = result["lot_items"].iloc[0]
        self.assertEqual(row["pendente"], 0)
        self.assertEqual(row["baixada"], 0)
        self.assertFalse(row["divergente"])
        self.assertTrue(row["divergencia_lote_informativa"])
        self.assertEqual(row["pendente_demanda_produto"], Decimal("0"))
        self.assertEqual(row["resultado_lote"], "BAIXA A MENOR NESTE LOTE")
        self.assertIn(LOT_C, row["detalhe_resultado_lote"])
        self.assertIn("COMPENSADA", row["detalhe_resultado_lote"])

    def test_fixed_result_labels_group_different_error_quantities_in_excel(self):
        """A categoria é estável, mesmo com quantidades de excesso distintas."""
        cases = [
            (Decimal("1"), "BAIXA A MAIOR NESTE LOTE"),
            (Decimal("2"), "BAIXA A MAIOR NESTE LOTE"),
            (Decimal("11"), "BAIXA A MAIOR NESTE LOTE"),
            (Decimal("54"), "BAIXA A MAIOR NESTE LOTE"),
        ]
        for excess, expected in cases:
            with self.subTest(excesso=excess):
                label = lot_conference._result_category(
                    stages.BAIXA_LOTE_DIVERGENTE,
                    f"BAIXA A MAIOR NESTE LOTE ({excess}); DIVERGÊNCIA DE LOTE",
                    gross_missing=Decimal("0"), gross_excess=excess,
                    wrong_lots="DIVERGÊNCIA DE LOTE", ambiguity=False,
                )
                self.assertEqual(label, expected)
                self.assertNotIn("(", label)

        result = model(
            [mes(LOT_A, 3), mes(LOT_B, 2)],
            [move(LOT_A, 2), move(LOT_B, 3)],
        )
        table_labels = set(result["lot_items"]["resultado_lote"])
        excel_labels = {r[-1] for r in reports.issue_rows(result)}
        self.assertEqual(table_labels, excel_labels)
        self.assertEqual(table_labels, {
            "BAIXA A MENOR NESTE LOTE", "BAIXA A MAIOR NESTE LOTE"
        })
        wb = load_workbook(BytesIO(reports.export_issues(result)), data_only=True)
        try:
            worksheet = wb.active
            self.assertEqual(
                {worksheet["Y2"].value, worksheet["Y3"].value},
                table_labels,
            )
        finally:
            wb.close()

    def test_header_and_report_filter_count_each_lot_as_separate_product(self):
        result = model(
            [mes(LOT_A, 3), mes(LOT_B, 2)],
            [move(LOT_A, 2), move(LOT_B, 3)],
        )
        start, end = date(2026, 10, 1), date(2026, 10, 31)
        # Os dados da OP oriundos do FOR001 são ausentes na amostra:
        # o período de faturamento só pode incluir OP com data real.
        result["lot_ops"]["data_faturamento"] = "16/10/2026"
        result["ops"]["data_faturamento"] = "16/10/2026"
        filtered = reports.issue_rows(result, start, end)
        self.assertEqual(len(filtered), 2)
        self.assertEqual(
            {r[14] for r in filtered}, {LOT_A, LOT_B}
        )
        selected = reports.issue_rows(
            result, start, end, material_types={"MP"}
        )
        # Sem tipo cadastrado, não inventar que os materiais são MP.
        self.assertEqual(selected, [])


if __name__ == "__main__":
    unittest.main()
