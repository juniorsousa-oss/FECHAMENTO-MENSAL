from __future__ import annotations

import sys
import unittest
from datetime import date
from io import BytesIO
from pathlib import Path

import openpyxl
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import catalog_types
import issue_check_ui as ui


class CatalogAndFiltersTests(unittest.TestCase):
    def test_catalog_detects_tipo_ii_from_row_two_and_padded_code(self):
        rows = [
            [None, None, None, None],
            [None, "CÓDIGO", "DESCRIÇÃO", "TIPO"],
            [None, 100618, "BOTAO", "II"],
            [None, "00001000", "MATERIAL", "I"],
            [None, "00101054", "COBRE", None],
        ]
        parsed = catalog_types.parse_frame(pd.DataFrame(rows))
        self.assertEqual(parsed["00100618"], "II")
        self.assertEqual(parsed["00001000"], "I")
        self.assertNotIn("00101054", parsed)

    def test_raw_catalog_matches_normalized(self):
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        for row in [
            [None, None, None, None],
            [None, "CODIGO", "DESCRICAO", "TP"],
            [None, "00101061", "CABO", "II"],
        ]:
            sheet.append(row)
        raw = BytesIO()
        workbook.save(raw)
        self.assertEqual(catalog_types.parse_raw(raw.getvalue())["00101061"], "II")

    def test_filter_status_and_invoice_date_keep_full_op(self):
        items = pd.DataFrame([
            {"op": "100", "codigo": "01"},
            {"op": "100", "codigo": "02"},
            {"op": "200", "codigo": "03"},
            {"op": "300", "codigo": "04"},
        ])
        ops = pd.DataFrame([
            {"op": "100", "status_op": "NF EMITIDA", "data_faturamento": "15/10/2026"},
            {"op": "200", "status_op": "REPORTADO", "data_faturamento": "NI"},
            {"op": "300", "status_op": "NF EMITIDA", "data_faturamento": "18/10/2026"},
        ])
        result = ui._filter_op_status_invoice(
            items, ops, "NF EMITIDA", (date(2026, 10, 15), date(2026, 10, 16))
        )
        self.assertEqual(result.codigo.tolist(), ["01", "02"])
        self.assertEqual(
            ui._filter_op_status_invoice(items, ops, "REPORTADO", ()).op.tolist(),
            ["200"],
        )
        self.assertEqual(
            ui._filter_op_status_invoice(items, ops, "Todos os status", (date(2026, 10, 18),)).op.tolist(),
            ["300"],
        )

    def test_missing_catalog_source_does_not_crash(self):
        from unittest.mock import patch
        with patch.object(ui.central, "source_state_for", side_effect=RuntimeError("indisponível")):
            records, meta = ui._optional_catalog_types()
        self.assertEqual(records, {})
        self.assertIn("indisponível", meta["erro"])


if __name__ == "__main__":
    unittest.main()
