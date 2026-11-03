"""Regressões dos três relatórios e filtros, sem campos extras no Geral."""
from __future__ import annotations

from datetime import date
from io import BytesIO
import unittest
from unittest.mock import patch

import pandas as pd
from openpyxl import load_workbook

import reports


class ReportsTests(unittest.TestCase):
    def test_excel_quantities_use_general_without_trailing_comma(self):
        wb = reports._Excel()
        wb.sheet("Quantidades", ["Valor"], quantity={0})
        for value in (100, 100.0, 0, -2, 3.25):
            wb.add("Quantidades", [value])
        saved = load_workbook(BytesIO(wb.save()), read_only=True, data_only=True)
        try:
            values = list(saved.active.values)
            self.assertEqual([r[0] for r in values[1:]], [100, 100, 0, -2, 3.25])
            for number in range(2, 7):
                self.assertEqual(saved.active[f"A{number}"].number_format, "General")
        finally:
            saved.close()

    def test_prior_faturamento_filters_by_activity_without_extra_export_columns(self):
        model = {
            "as_of": "2026-10-31", "baixas_fonte": "OPS", "history_available": True,
            "ops": pd.DataFrame([
                {"op": "25027101001", "data_faturamento": "19/05/2026",
                 "divergencias": 0, "status_op": "NF EMITIDA"},
                {"op": "26000101001", "data_faturamento": "20/09/2026",
                 "divergencias": 0, "status_op": "NF EMITIDA"},
            ]),
            "items": pd.DataFrame([
                {"op": "25027101001", "codigo": "06050123", "tipo_material": "MP"},
                {"op": "26000101001", "codigo": "06050189", "tipo_material": "MP"},
            ]),
            "general": [
                {"op": "25027101001", "codigo": "06050123", "lote": "000001",
                 "necessaria": 1, "atendida": 1,
                 "descricao": "MATERIAL A", "responsavel_conferencia": "CONF",
                 "separacao": "2026-08-17", "conferencia": "2026-08-20"},
                {"op": "26000101001", "codigo": "06050189", "lote": "000001",
                 "necessaria": 3, "atendida": 3,
                 "descricao": "MATERIAL B", "responsavel_conferencia": "",
                 "separacao": "2026-09-10", "conferencia": ""},
            ],
            "movements": [],
        }
        start, end = date(2026, 8, 1), date(2026, 10, 31)
        diagnosis = reports.selection_diagnostics(model, start, end)
        self.assertEqual(diagnosis["selected"], {"26000101001"})
        self.assertEqual(reports.issue_rows(model, start, end)[0][0], "26000101001")
        old = reports.issue_rows(model, start, end, include_prior_billing=True)
        self.assertEqual({r[0] for r in old}, {"25027101001", "26000101001"})
        self.assertEqual(len(reports.OP_COLUMNS), 10)
        self.assertNotIn("Separações inferidas da conferência", reports.OP_COLUMNS)
        self.assertNotIn("Valor previsto da baixa (R$)", reports.OP_COLUMNS)
        self.assertNotIn("Data última atividade no período", reports.OP_COLUMNS)

    def test_future_activity_beyond_mes_snapshot_is_excluded(self):
        model = {
            "as_of": "2026-10-21", "baixas_fonte": "OPS",
            "history_available": True,
            "ops": pd.DataFrame([{"op": "26000101001", "data_faturamento": "NI"}]),
            "general": [{
                "op": "26000101001", "codigo": "06050123", "lote": "000001",
                "necessaria": 1, "atendida": 1, "descricao": "MATERIAL",
                "responsavel_conferencia": "CONF",
                "separacao": "2026-11-02", "conferencia": "2026-11-02",
            }],
            "movements": [],
        }
        self.assertFalse(reports.issue_rows(
            model, date(2026, 8, 1), date(2026, 11, 3)))

    def test_stock_workbook_has_four_tabs_and_no_fake_initial_balance(self):
        entries, imports = [], []
        for month, total in ((8, 100.0), (9, 110.0), (10, 120.0)):
            day = date(2026, month, 1).isoformat()
            imports.append({"competencia": day, "status": "VALIDO",
                            "preview": month == 10})
            entries.extend([
                {"competencia": day, "dimensao": "TOTAL",
                 "chave": "TOTAL", "valor_total": total},
                {"competencia": day, "dimensao": "ARMZ",
                 "chave": "ARMZ:S2", "valor_total": total},
                {"competencia": day, "dimensao": "TP",
                 "chave": "TP:MP", "valor_total": total},
            ])
        found = reports.stock_data(entries, imports,
                                   date(2026, 9, 15), date(2026, 10, 20))
        self.assertEqual(len(found["Evolução Mensal"]), 2)
        self.assertEqual(found["Evolução Mensal"][0][1:4], [100.0, 110.0, 10.0])
        self.assertEqual(found["Evolução Mensal"][1][-1], "PRÉVIA")
        wb = load_workbook(BytesIO(reports.export_stock(entries, imports)),
                           read_only=True, data_only=True)
        try:
            self.assertEqual(wb.sheetnames, [
                "Resumo Geral", "Por Armazém", "Por Tipo", "Evolução Mensal"])
            self.assertIsNone(list(wb["Evolução Mensal"].values)[1][1])
        finally:
            wb.close()

    def test_kardex_filters_do_not_mutate_original_frame(self):
        frame = pd.DataFrame([
            {"data": "2026-10-03", "armazem": "S2", "tipo": "II", "tes": "520"},
            {"data": "2026-10-05", "armazem": "EP", "tipo": "EP", "tes": "520"},
            {"data": "2026-09-30", "armazem": "S2", "tipo": "MP", "tes": "020"},
        ])
        filtered = reports.filtered_kardex(
            frame, date(2026, 10, 1), date(2026, 10, 31),
            warehouses={"S2"}, types={"II"}, groups={"520"},
        )
        self.assertEqual(len(filtered), 1)
        self.assertEqual(len(frame), 3)
        with patch("movements.export_excel", return_value=b"x") as excel:
            self.assertEqual(reports.export_kardex(filtered, {},
                                                   summary_only=True), b"x")
            self.assertTrue(excel.call_args.kwargs["summary_only"])


if __name__ == "__main__":
    unittest.main()
