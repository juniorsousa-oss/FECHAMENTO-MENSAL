"""Regressões de navegação enxuta do módulo KARDEX SETTA."""
from __future__ import annotations

import io
import sys
import unittest
from datetime import date
from pathlib import Path

import openpyxl
from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import movements as mv

PROGRAM = """
import sys
import streamlit as st
sys.path.insert(0, "tests")
from test_movement_analysis import record, imported
import movements as mv
import movement_analysis_ui as ui
import kardex_group_config as group_cfg
ui._groups_read = lambda: group_cfg.empty()

rows = [
    record(documento="AJUSTE"),
    record(tes="550", ae_original=" OP00001234567 ", documento="OP", valor_saida="20"),
    record(tes="020", tipo="PA", documento="PRODUCAO", qtd_saida=None, valor_saida=None,
           qtd_entrada="3", valor_entrada="30"),
    record(tes="001", documento="SETEMBRO", data="2026-09-10", qtd_saida=None, valor_saida=None,
           qtd_entrada="4", valor_entrada="40"),
    record(tes="550", ae_original="OP00007654321", documento="OUTRA OP", armazem="S1", valor_saida="5"),
]
pack = imported(rows)
pack["meta"].update(periodo_inicio="2026-09-01", periodo_fim="2026-10-19")
model = mv.build_model([pack])
imports = [{"chave": "synthetic", "meta": {"arquivo_nome": "teste.xlsx", "periodo_inicio": "2026-09-01",
            "periodo_fim": "2026-10-19", "lancamentos": 5}, "atualizado_em": "2026-10-21T10:00:00Z"}]
action = st.session_state.pop("_test_action", None)
if action in ("group_only", "drill", "op_drill"):
    original_table = ui._table
    def select_in_order(data, *args, **kwargs):
        displayed = original_table(data, *args, **kwargs)
        key = kwargs.get("key", "")
        if action in ("group_only", "drill") and "_overview_groups_" in key:
            return {"selection": {"rows": [0]}}
        if action == "drill" and ("_overview_subgroups_" in key or "_overview_tes_" in key):
            return {"selection": {"rows": [0]}}
        if action == "op_drill" and "_op_table_" in key:
            return {"selection": {"rows": [0]}}
        return displayed
    ui._table = select_in_order
try:
    ui.render_results(model, imports)
finally:
    if action in ("group_only", "drill", "op_drill"):
        ui._table = original_table
"""


class MovementAnalysisUITests(unittest.TestCase):
    def app(self):
        app = AppTest.from_string(PROGRAM, default_timeout=20).run()
        self.assertFalse(app.exception)
        return app

    def area(self, app, name):
        app.segmented_control[0].set_value(name).run()
        self.assertFalse(app.exception)

    def test_menu_only_four_areas_and_legacy_session_is_redirected(self):
        import movement_analysis_ui as ui
        expected = ["Visão geral", "Por OP", "Cadastros", "Fontes e relatórios"]
        self.assertEqual(ui.AREAS, expected)
        self.assertEqual([ui.AREA_LABELS[x] for x in expected],
                         ["Resumo", "Consulta por OP", "Cadastros", "Fontes e relatórios"])
        app = self.app()
        self.assertEqual(app.segmented_control[0].value, "Visão geral")
        for obsolete in ("Movimentações", "TES e descrições"):
            app.session_state["fm_mov_area"] = obsolete
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(app.segmented_control[0].value, "Visão geral")

    def test_visible_dates_and_simplified_filters(self):
        import movement_analysis_ui as ui
        self.assertEqual(ui._br_date("2026-10-22"), "22/10/2026")
        self.assertEqual(ui._br_date(date(2026, 1, 5)), "05/01/2026")
        self.assertEqual(ui._br_month("2026-10"), "10/2026")
        app = self.app()
        self.area(app, "Por OP")
        self.assertEqual([x.label for x in app.text_input], ["Buscar OP ou material"])
        op = app.dataframe[0].value
        self.assertIn("Primeiro movimento", op.columns)
        self.assertTrue(op["Primeiro movimento"].str.match(r"^\\d{2}/\\d{2}/\\d{4}$").all())
        self.assertTrue(op["Último movimento"].str.match(r"^\\d{2}/\\d{2}/\\d{4}$").all())

    def test_group_totals_include_registered_groups_without_movement(self):
        from test_movement_analysis import imported, record
        import movement_analysis_ui as ui
        import kardex_group_config as cfg
        import kardex_conditions as cond
        frame = mv.build_model([imported([record(tes="550")])])["frame"]
        data = cfg.create_group(cfg.empty(), "COMPRAS", known_tes={"550"})
        data = cfg.create_group(data, "FLUXO DE ESTOQUE", known_tes={"550"})
        data = cfg.assign_group(data, data["grupos"][1]["id"], ["550"],
                                known_tes={"550"})
        summary = ui._overview_group_totals(cond.classify(frame, data), data)
        self.assertEqual(summary["Grupo"].tolist(), ["COMPRAS", "FLUXO DE ESTOQUE"])
        self.assertEqual(summary["lancamentos"].tolist(), [0, 1])
        self.assertEqual(summary["valor_saida"].sum(), frame["valor_saida"].sum())

    def test_responsive_table_height_avoids_blank_rows(self):
        import movement_analysis_ui as ui
        self.assertEqual(ui._grid_height(1), 74)
        self.assertEqual(ui._grid_height(2), 109)
        self.assertEqual(ui._grid_height(6), 249)
        self.assertEqual(ui._grid_height(0), 72)
        self.assertEqual(ui._grid_height(30, 550), 550)
        self.assertIsNone(ui._picked_index({"selection": {"rows": []}}, 6))
        self.assertIsNone(ui._picked_index({"selection": {"rows": [6]}}, 6))
        self.assertEqual(ui._picked_index({"selection": {"rows": [2]}}, 6), 2)

    def test_summary_progressive_drilldown_stays_on_summary(self):
        app = self.app()
        self.assertFalse(any("Subgrupo" in table.value.columns for table in app.dataframe))
        app.session_state["_test_action"] = "group_only"
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(app.segmented_control[0].value, "Visão geral")
        self.assertIn("Subgrupo", app.dataframe[1].value.columns)
        self.assertFalse(any("TES" in table.value.columns for table in app.dataframe[2:]))
        app.session_state["_test_action"] = "drill"
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(app.segmented_control[0].value, "Visão geral")
        self.assertGreaterEqual(len(app.dataframe), 4)
        group_table, sub_table, tes_table, ledger = [x.value for x in app.dataframe[:4]]
        self.assertEqual(group_table["Grupo"].tolist(), ["SEM GRUPO"])
        self.assertIn("Subgrupo", sub_table.columns)
        self.assertIn("TES", tes_table.columns)
        self.assertIn("Grupo", ledger.columns)
        self.assertEqual(set(ledger["TES"]), {tes_table.iloc[0]["TES"]})
        self.assertEqual(set(ledger["Subgrupo"]), {sub_table.iloc[0]["Subgrupo"]})

    def test_op_lookup_and_inline_movements(self):
        app = self.app()
        self.area(app, "Por OP")
        self.assertIn("OP", app.dataframe[0].value.columns)
        app.session_state["_test_action"] = "op_drill"
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(app.segmented_control[0].value, "Por OP")
        self.assertGreaterEqual(len(app.dataframe), 2)
        ledger = app.dataframe[1].value
        self.assertEqual(set(ledger["AE original"]), {" OP00001234567 "})
        self.assertEqual(set(ledger["Subgrupo"]), {"CONSUMO OP"})
        self.assertEqual(set(ledger["TES"]), {"550"})

    def test_op_search_still_filters_and_reset(self):
        app = self.app()
        self.area(app, "Por OP")
        next(x for x in app.text_input if x.label == "Buscar OP ou material").set_value("00001234567").run()
        self.assertFalse(app.exception)
        self.assertEqual(app.dataframe[0].value["OP"].tolist(), ["OP00001234567"])
        next(x for x in app.button if x.label == "LIMPAR CONSULTA").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.dataframe[0].value), 2)

    def test_catalog_and_import_export_remain_available(self):
        app = self.app()
        self.area(app, "Cadastros")
        catalog = app.dataframe[0].value
        self.assertGreaterEqual(len(catalog), 342)
        self.assertIn("Descrição TES", catalog.columns)
        self.assertEqual(
            catalog.loc[catalog["TES"] == "999", "Descrição TES"].iloc[0],
            "SAÍDA DE INVENTÁRIO/CONSUMO OP",
        )
        self.assertTrue(any("CONDIÇÕES E SUBGRUPOS" in x.value for x in app.markdown))
        self.area(app, "Fontes e relatórios")
        self.assertEqual(len(app.file_uploader), 1)
        self.assertTrue(any("Situação" in table.value.columns for table in app.dataframe))

    def test_month_and_warehouse_scope(self):
        app = self.app()
        next(x for x in app.multiselect if x.label == "Armazéns").set_value(["S2"]).run()
        self.assertEqual(app.dataframe[0].value["Saída (R$)"].sum(), 30)
        self.area(app, "Por OP")
        self.assertEqual(app.dataframe[0].value["OP"].tolist(), ["OP00001234567"])
        self.area(app, "Visão geral")
        next(x for x in app.selectbox if x.label == "Período da análise").set_value("ACUMULADO DO ANO").run()
        self.assertEqual(app.dataframe[0].value["Entrada (R$)"].sum(), 70)
        next(x for x in app.selectbox if x.label == "Competência analisada").set_value("2026-09").run()
        self.assertEqual(app.dataframe[0].value["Entrada (R$)"].sum(), 40)

    def test_excel_complete_in_reports_menu(self):
        app = self.app()
        self.area(app, "Fontes e relatórios")
        next(x for x in app.button if x.label == "PREPARAR EXCEL DO RECORTE").click().run()
        self.assertFalse(app.exception)
        wb = openpyxl.load_workbook(io.BytesIO(app.session_state["fm_mov_excel"][1]),
                                    read_only=True)
        self.assertEqual(wb.sheetnames, ["Grupos e TES", "Por OP", "Movimentações"])
        ledger = wb["Movimentações"]
        self.assertEqual(ledger["F1"].value, "Grupo")
        self.assertEqual(ledger["G1"].value, "Subgrupo")
        self.assertEqual(len(list(ledger.iter_rows(values_only=True))), 5)
        self.assertEqual(wb["Por OP"]["A2"].value, "OP00001234567")
        wb.close()


if __name__ == "__main__":
    unittest.main()
