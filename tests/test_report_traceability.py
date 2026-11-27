import unittest
from datetime import date
from io import BytesIO

import pandas as pd
from openpyxl import load_workbook

import reports
import reports_ui


def workbook(data):
    return load_workbook(BytesIO(data))


class ReportTraceabilityTests(unittest.TestCase):
    def test_stock_preserves_sheets_and_marks_live_vs_previous_source(self):
        imports = [
            {"competencia": "2026-10-01", "arquivo_nome": "out.xlsx", "importado_em": "2026-11-01T09:00:00Z"},
            {"competencia": "2026-11-01", "arquivo_nome": "nov.xlsx", "preview": True, "source_version": 12},
        ]
        summaries = [
            {"competencia": row["competencia"], "dimensao": "TOTAL", "chave": "TOTAL", "valor_total": value}
            for row, value in zip(imports, [100, 120])
        ]
        start, end = date(2026, 11, 1), date(2026, 11, 26)
        trace = reports_ui._stock_trace(imports, ["11/2026"])
        out = workbook(reports.export_stock(summaries, imports, start, end, trace=trace))
        self.assertEqual(out.sheetnames, ["Resumo Geral", "Por Armazém", "Por Tipo", "Evolução Mensal", reports.TRACE_SHEET])
        self.assertEqual(out["Resumo Geral"]["D2"].value, 20)
        recorded = dict(out[reports.TRACE_SHEET].values)
        self.assertIn("Versão: 12", recorded["Fonte 11/2026 · prévia"])
        self.assertNotIn("Versão:", recorded["Fonte 10/2026 · saldo inicial"])
        self.assertIn("Atualização registrada", recorded["Fonte 10/2026 · saldo inicial"])

    def test_issues_keep_25_data_columns(self):
        trace = [("Fonte OPS", "Identificador: a"), ("Período solicitado", "11/2026")]
        out = workbook(reports.export_issues({"ops": pd.DataFrame(), "items": pd.DataFrame()}, trace=trace))
        self.assertEqual(out.sheetnames, ["Conferência de Baixas", reports.TRACE_SHEET])
        self.assertEqual(out["Conferência de Baixas"].max_column, 25)
        self.assertIn(("Fonte OPS", "Identificador: a"), list(out[reports.TRACE_SHEET].values))

    def test_kardex_trace_contains_only_covered_exported_sources(self):
        frame = pd.DataFrame({"competencia": ["2026-11"], "armazem": ["S2"]})
        model = {
            "versao": "r4",
            "import_registry": [{"import_id": "k1", "importado_em": "2026-11-09T00:00:00Z"}],
            "coverage_metas": [
                {"competencia": "2026-11", "armazem": name, "arquivo_nome": name + ".xlsx",
                 "import_id": ident, "periodo_inicio": "2026-11-01", "periodo_fim": "2026-11-09"}
                for name, ident in [("S2", "k1"), ("E2", "k2")]
            ],
        }
        trace = reports_ui._kardex_trace(model, frame, date(2026, 11, 2), date(2026, 11, 25))
        for concise in [False, True]:
            out = workbook(reports.export_kardex(pd.DataFrame(), {"grupos": []}, summary_only=concise, trace=trace))
            expected = ["Grupos e TES"] if concise else ["Grupos e TES", "Por OP", "Movimentações"]
            self.assertEqual(out.sheetnames, expected + [reports.TRACE_SHEET])
            recorded = dict(out[reports.TRACE_SHEET].values)
            self.assertIn("k1", recorded["Fonte KARDEX · 2026-11 / S2"])
            self.assertNotIn("Fonte KARDEX · 2026-11 / E2", recorded)

    def test_report_page_switches_between_ready_and_no_data_for_selected_dates(self):
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_string("""
import streamlit as st
import reports_ui
reports_ui.render_reports(
    summaries=[{'competencia': '2020-01-01', 'dimensao': 'TOTAL', 'chave': 'TOTAL', 'valor_total': 120}],
    imports=[{'competencia': '2020-01-01', 'arquivo_nome': 'analitico.xlsx'}],
)
""").run()
        self.assertFalse(app.exception)
        today = reports_ui.datetime.now(reports_ui.ZoneInfo("America/Sao_Paulo")).date()
        self.assertEqual(len(app.date_input), 0)
        app.radio(key="fm_reports_period_mode").set_value("Período personalizado").run()
        self.assertEqual(app.date_input(key="fm_reports_start").value, today.replace(day=1))
        self.assertEqual(app.date_input(key="fm_reports_end").value, today)
        from datetime import date
        self.assertEqual(reports_ui._month_bounds(date(2024, 2, 17), today),
                         (date(2024, 2, 1), date(2024, 2, 29)))
        self.assertTrue(any(f"Sem dados de estoque para {today:%m/%Y}" in msg.value for msg in app.info))
        self.assertEqual(len(app.get("download_button")), 0)
        self.assertEqual(list(app.button), [])
        app.radio(key="fm_reports_period_mode").set_value("Histórico completo").run()
        self.assertFalse(any("Sem dados" in msg.value for msg in app.info))
        app.button(key="fm_reports_prepare").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any("Pronto para baixar" in line.value for line in app.caption))
        self.assertEqual(len(app.get("download_button")), 1)
        data = app.session_state["fm_reports_ready"][1]
        self.assertIn(reports.TRACE_SHEET, workbook(data).sheetnames)
        self.assertNotIn("fm_reports_prepare", [button.key for button in app.button])
        app.button(key="fm_reports_reset").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.get("download_button")), 0)
        self.assertEqual(app.button(key="fm_reports_prepare").label, "Gerar Excel")
