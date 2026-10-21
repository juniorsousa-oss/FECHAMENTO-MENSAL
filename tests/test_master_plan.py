from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import master_plan as plan
import issue_check_ui as ui


def row(op, cliente=None, condicao=None, nota=None, faturamento=None, dias=None):
    cells = [None] * 24
    for col, value in {
        0: op, 2: cliente, 14: condicao, 16: nota, 17: faturamento, 19: dias,
    }.items():
        cells[col] = value
    return cells


class MasterPlanTests(unittest.TestCase):
    def test_parse_fifth_row_headers_and_link_by_complete_op(self):
        base = [
            [None] * 24,
            [None] * 24,
            [None] * 24,
            [None] * 24,
            ["ORDEM PRODUÇÃO", "PSY", "CLIENTE"] + [None] * 21,
            row(26000101001, "CLIENTE TESTE", "LIBERADO", 98765, 45946, 3),
            row("26000201001", "OUTRO CLIENTE", "", "-", None, None),
        ]
        records = plan.parse_frame(pd.DataFrame(base))
        self.assertEqual(records["26000101001"], {
            "cliente": "CLIENTE TESTE", "condicao": "LIBERADO",
            "nota_fiscal": "98765", "data_faturamento": "16/10/2025",
            "dias_patio": "3",
        })
        self.assertEqual(records["26000201001"]["nota_fiscal"], "NI")
        self.assertNotIn("2600010100", records)

    def test_missing_errors_and_repeated_op_keep_last_nonempty_field(self):
        frame = pd.DataFrame([
            row("26000301001", "CLIENTE ORIGINAL", "#NAME?", 123, None, "1901-03-20T00:00:00Z"),
            row("26000301001", None, "PRONTO", "#N/A", None, None),
        ])
        records = plan.parse_frame(frame)
        self.assertEqual(records["26000301001"]["cliente"], "CLIENTE ORIGINAL")
        self.assertEqual(records["26000301001"]["condicao"], "PRONTO")
        self.assertEqual(records["26000301001"]["nota_fiscal"], "123")
        self.assertEqual(records["26000301001"]["dias_patio"], "445")

    def test_iso_dates_never_swap_day_and_month(self):
        cases = {
            "2026-10-06": "06/10/2026",
            "2026-10-06T00:00:00": "06/10/2026",
            "2026-10-06T00:00:00.000Z": "06/10/2026",
            "2026-10-06 03:45:11": "06/10/2026",
            "2026-06-10T00:00:00": "10/06/2026",
            "2026-10-16": "16/10/2026",
            "06/10/2026": "06/10/2026",
            "16/10/2026": "16/10/2026",
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(plan._date(source), expected)

    def test_normalized_for001_iso_faturamento_preserves_calendar_date(self):
        frame = pd.DataFrame([
            row("26000101001", "CLIENTE TESTE", "FINALIZADO", 10255,
                "2026-10-06T00:00:00.000", None),
            row("26000201001", "OUTRO CLIENTE", "FINALIZADO", 9840,
                "2026-06-10T00:00:00", None),
        ])
        records = plan.parse_frame(frame)
        self.assertEqual(records["26000101001"]["data_faturamento"], "06/10/2026")
        self.assertEqual(records["26000201001"]["data_faturamento"], "10/06/2026")
        self.assertIn("FATURAMENTO: 06/10/2026", plan.label_fields(records["26000101001"]))

    def test_faturamento_filter_uses_corrected_dates(self):
        records = plan.parse_frame(pd.DataFrame([
            row("26000101001", "CLIENTE TESTE", "FINALIZADO", 10255,
                "2026-10-06T00:00:00", None),
            row("26000201001", "OUTRO CLIENTE", "FINALIZADO", 9840,
                "2026-06-10T00:00:00", None),
        ]))
        ops = pd.DataFrame([
            {"op": "26000101001", "status_op": "NF EMITIDA"},
            {"op": "26000201001", "status_op": "NF EMITIDA"},
        ])
        enriched = plan.enrich_ops(ops, records)
        items = pd.DataFrame([
            {"op": "26000101001", "codigo": "A"},
            {"op": "26000201001", "codigo": "B"},
        ])
        from datetime import date
        october = ui._filter_op_status_invoice(
            items, enriched, "Todos os status", (date(2026, 10, 1), date(2026, 10, 31))
        )
        self.assertEqual(october["codigo"].tolist(), ["A"])

    def test_dias_patio_can_signal_delivered_without_numeric_days(self):
        frame = pd.DataFrame([row("26000401001", "CLIENTE", "FINALIZADO",
                                  None, None, "FINALIZADO E ENTREGUE")])
        parsed = plan.parse_frame(frame)
        self.assertEqual(parsed["26000401001"]["dias_patio"], "FINALIZADO E ENTREGUE")

    def test_enrichment_retains_all_orders_and_missing_values_as_NI(self):
        ops = pd.DataFrame([{"op": "26000101001", "itens": 5}, {"op": "26009901001", "itens": 1}])
        records = {"26000101001": {"cliente": "TESTE", "condicao": "EM PRODUÇÃO"}}
        enriched = plan.enrich_ops(ops, records)
        self.assertEqual(len(enriched), 2)
        self.assertEqual(enriched.iloc[0]["cliente"], "TESTE")
        self.assertEqual(enriched.iloc[1]["cliente"], "NI")
        self.assertEqual(enriched.iloc[0]["nota_fiscal"], "NI")
        self.assertIn("| CLIENTE: TESTE |", "| " + plan.label_fields(enriched.iloc[0].to_dict()))

    def test_optional_source_failure_is_not_a_blocker(self):
        with patch.object(ui.central, "source_state_for", side_effect=RuntimeError("fora do ar")):
            rows, meta = ui._optional_master_plan()
        self.assertEqual(rows, {})
        self.assertIn("fora do ar", meta["erro"])

    def test_left_alignment_targets_inner_streamlit_button_wrapper(self):
        css = Path(__file__).resolve().parents[1].joinpath("issue_check_ui.py").read_text("utf-8")
        self.assertIn('button > div,', css)
        self.assertIn('justify-content:flex-start!important', css)
        # A atualização visual separa os indicadores no botão e mantém
        # os mesmos campos do FOR001 em uma grade de metadados.
        self.assertIn('st.markdown(_op_metadata(context)', css)
        self.assertIn('("Cliente", context.get("cliente")', css)
        self.assertIn('("Faturamento", context.get("data_faturamento")', css)


if __name__ == "__main__":
    unittest.main()
