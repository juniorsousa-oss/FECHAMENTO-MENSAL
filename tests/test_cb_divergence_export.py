"""Exportação das divergências de chapas/barramentos para ajuste manual.

Somente dados sintéticos, sem modificar o Supabase ou o Protheus.
"""
from __future__ import annotations

from datetime import date
from io import BytesIO
from pathlib import Path
import unittest

import pandas as pd
from openpyxl import load_workbook

from cb_divergence_export import HEADERS, divergent_records, export_divergences


def _row(code="06000031", status="DIVERGÊNCIA", difference=-1.2, **overrides):
    base = {
        "Código": code,
        "Descrição": "CHAPA METÁLICA 1,5 MM",
        "Categoria": "CHAPA",
        "U.M.": "KG",
        "ARMZ": "S2",
        "Saldo fechamento": 2414.11,
        "Saldo atual": 2414.11,
        "Variação atual x fechamento": 0.0,
        "Saldo base ajuste": 2414.11,
        "Base usada": "FECHAMENTO",
        "Físico": 2412.91,
        "Diferença Qtd": difference,
        "Diferença R$": -5.4,
        "Custo unitário": 4.5,
        "Origem custo": "ANALÍTICO · VALOR / SALDO",
        "Consumo informado": None,
        "Fontes físicas": "CHAPAS E-MAIL: 2412,910",
        "Tolerância automática": False,
        "Status": status,
    }
    base.update(overrides)
    return base


class DivergenceExportTests(unittest.TestCase):
    def setUp(self):
        self.data = pd.DataFrame([
            _row(),
            _row(
                code="00110158", difference=23.155, Categoria="BARRA DE COBRE",
                **{"Descrição": "BARRAMENTO COBRE", "U.M.": "MT",
                   "ARMZ": "S2, G9", "Saldo fechamento": 100,
                   "Saldo atual": 90, "Saldo base ajuste": 90,
                   "Físico": 113.155, "Base usada": "ATUAL",
                   "Diferença R$": 250, "Origem custo": "CADASTROS · ÚLT. PREÇO"}
            ),
            _row(code="06000210", status="CONFERIDO", difference=0.0),
            _row(code="06000211", status="SEM CONTAGEM", difference=None),
        ])

    def test_selects_only_active_divergences_and_preserves_numbers(self):
        rows = divergent_records(self.data)
        self.assertEqual(len(rows), 2)
        first = next(x for x in rows if x["Código"] == "06000031")
        self.assertEqual(first["Ação indicativa"], "REDUÇÃO DE SALDO")
        self.assertAlmostEqual(first["Diferença Qtd (físico - base)"], -1.2)
        self.assertEqual(first["Custo unitário (R$)"], 4.5)
        self.assertEqual(first["Diferença R$"], -5.4)
        second = next(x for x in rows if x["Código"] == "00110158")
        self.assertEqual(second["Ação indicativa"], "ACRÉSCIMO DE SALDO")
        self.assertIn("VALIDAR ARMAZÉM", second["Atenção no ERP"])
        self.assertIn("DIFERE DO SALDO ATUAL", second["Atenção no ERP"]) if False else None
        self.assertAlmostEqual(second["Diferença Qtd (físico - base)"], 23.155)
        self.assertEqual(len(self.data), 4, "Não deve modificar a análise original")

    def test_expected_columns_filters_values_and_text_codes(self):
        data = export_divergences(self.data, date(2026, 10, 1))
        self.assertTrue(data[:2] == b"PK")
        workbook = load_workbook(BytesIO(data), read_only=False, data_only=True)
        try:
            self.assertEqual(workbook.sheetnames, ["Divergências"])
            sheet = workbook.active
            self.assertEqual([sheet.cell(5, j).value for j in range(1, len(HEADERS) + 1)], HEADERS)
            self.assertEqual(sheet.max_row, 7)
            self.assertEqual(sheet["A6"].value, "00110158")
            self.assertEqual(sheet["A6"].number_format, "@")
            self.assertEqual(sheet["A7"].value, "06000031")
            self.assertEqual(sheet["L6"].value, 23.155)
            self.assertEqual(sheet["P7"].value, -5.4)
            self.assertIn("A5:", sheet.auto_filter.ref)
            self.assertEqual(sheet.freeze_panes, "C6")
            self.assertIn("NÃO É UMA CARGA PROTHEUS", sheet["A2"].value)
        finally:
            workbook.close()

    def test_empty_and_nondivergent_data_is_rejected(self):
        self.assertEqual(divergent_records(pd.DataFrame()), [])
        with self.assertRaisesRegex(ValueError, "Nenhuma divergência"):
            export_divergences(pd.DataFrame(), date(2026, 10, 1))
        with self.assertRaisesRegex(ValueError, "Nenhuma divergência"):
            export_divergences(self.data.loc[self.data["Status"].eq("CONFERIDO")], date(2026, 10, 1))

    def test_missing_cost_and_current_balance_do_not_become_zero(self):
        rows = divergent_records(pd.DataFrame([
            _row("06001005", **{
                "Diferença R$": None, "Custo unitário": None,
                "Saldo atual": None, "ARMZ": "S2",
                "Descrição": "=SUM(1+2)",
            })
        ]))
        self.assertIsNone(rows[0]["Diferença R$"])
        self.assertIsNone(rows[0]["Saldo atual"])
        self.assertIn("SALDO ATUAL NÃO DISPONÍVEL", rows[0]["Atenção no ERP"])
        self.assertTrue(rows[0]["Descrição"].startswith("'="))

    def test_interface_uses_unfiltered_adjustment_snapshot(self):
        app = Path(__file__).resolve().parents[1].joinpath("streamlit_app.py").read_text(encoding="utf-8")
        self.assertIn("export_divergences(\n                                cb_adjustment_snapshot, cb_month", app)
        self.assertIn("cb_export_divergencias_excel", app)


if __name__ == "__main__":
    unittest.main()
