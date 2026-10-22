from __future__ import annotations

import io
import sys
import unittest
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
if action == "tes":
    st.session_state.test_selection = {"selection": {"rows": [0]}}
    ui._tes_selected("test_selection", ["520"])
elif action == "op":
    st.session_state.test_selection = {"selection": {"rows": [0]}}
    ui._op_selected("test_selection", ["OP00001234567"])
ui.render_results(model, imports)
"""


class MovementAnalysisUITests(unittest.TestCase):
    def app(self):
        app = AppTest.from_string(PROGRAM, default_timeout=20).run()
        self.assertFalse(app.exception)
        return app

    def area(self, app, name):
        app.segmented_control[0].set_value(name).run()
        self.assertFalse(app.exception)

    def test_all_visible_kardex_dates_follow_ptbr(self):
        from datetime import date
        import movement_analysis_ui as ui
        self.assertEqual(ui._br_date("2026-10-22"), "22/10/2026")
        self.assertEqual(ui._br_date(date(2026, 1, 5)), "05/01/2026")
        self.assertEqual(ui._br_month("2026-10"), "10/2026")
        app = self.app()
        self.area(app, "Por OP")
        op = app.dataframe[0].value
        self.assertIn("Primeiro movimento", op.columns)
        self.assertTrue(op["Primeiro movimento"].str.match(r"^\d{2}/\d{2}/\d{4}$").all())
        self.assertTrue(op["Último movimento"].str.match(r"^\d{2}/\d{2}/\d{4}$").all())
        self.area(app, "Movimentações")
        ledger = app.dataframe[0].value
        self.assertTrue(ledger["Data"].notna().all())

    def test_warehouse_registry_remains_accessible(self):
        from test_movement_analysis import imported, record
        import movement_analysis_ui as ui
        model = mv.build_model([imported([
            record(armazem="S2", documento="S2"),
            record(armazem="E2", data="2026-10-20", documento="E2"),
        ])])
        states = ui._warehouse_registry_overview(model).set_index("Armazém")
        self.assertEqual(states.loc["S2", "Situação"], "ATIVO")
        self.assertEqual(states.loc["E2", "Situação"], "ATIVO")
        self.assertEqual(states.loc["EP", "Situação"], "PENDENTE DE IMPORTAÇÃO")
        self.assertEqual(states.loc["20", "Situação"], "PENDENTE DE IMPORTAÇÃO")

    def test_summary_uses_tes_and_literal_description_only(self):
        app = self.app()
        self.assertEqual([x.label for x in app.multiselect], ["Armazéns"])
        self.assertEqual(app.segmented_control[0].value, "Visão geral")
        frame = app.dataframe[0].value
        self.assertIn("Grupo", frame.columns)
        self.assertEqual(frame["Grupo"].tolist(), ["SEM GRUPO"])
        # Escopo inicial é outubro: o lançamento de setembro não entra nos cards.
        self.assertEqual(frame["Entrada (R$)"].sum(), 30)
        self.assertEqual(frame["Saída (R$)"].sum(), 35)
        self.assertEqual(frame["Movimentos"].sum(), 4)

    def test_tes_local_filter_survives_navigation(self):
        app = self.app()
        self.area(app, "TES e descrições")
        tes = next(x for x in app.multiselect if x.label == "Códigos TES")
        tes.set_value(["520"]).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.dataframe[0].value["TES"].tolist(), ["520"])
        self.area(app, "Por OP")
        next(x for x in app.text_input if x.label == "Buscar OP ou material").set_value("00001234567").run()
        self.assertEqual(app.dataframe[0].value["OP"].tolist(), ["OP00001234567"])
        self.area(app, "Visão geral")
        self.assertEqual(app.dataframe[0].value["Saída (R$)"].sum(), 35)
        self.area(app, "TES e descrições")
        self.assertEqual(next(x for x in app.multiselect if x.label == "Códigos TES").value, ["520"])

    def test_tes_selection_opens_only_matching_ledger_records(self):
        app = self.app()
        app.session_state["_test_action"] = "tes"
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(app.segmented_control[0].value, "Movimentações")
        self.assertEqual(app.dataframe[0].value["TES"].tolist(), ["520"])
        self.assertEqual(len(app.dataframe[0].value), 1)
        self.assertTrue(any("TES: 520" in x.value for x in app.caption))
        next(x for x in app.button if "VOLTAR PARA" in x.label).click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.segmented_control[0].value, "TES e descrições")

    def test_op_drilldown_preserves_original_ae_and_clears_search(self):
        app = self.app()
        self.area(app, "Movimentações")
        self.assertNotIn("Endereçamento compensado", app.dataframe[0].value.columns)
        next(x for x in app.text_input if x.label == "Buscar nos registros").set_value("INEXISTENTE").run()
        self.assertEqual(len(app.dataframe), 0)
        app.session_state["_test_action"] = "op"
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.dataframe[0].value), 1)
        self.assertEqual(app.dataframe[0].value["AE original"].tolist(), [" OP00001234567 "])
        self.assertEqual(next(x for x in app.text_input if x.label == "Buscar nos registros").value, "")
        next(x for x in app.button if x.label == "LIMPAR CONSULTA").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.dataframe[0].value), 4)

    def test_catalog_independent_of_search_and_sources_accessible(self):
        app = self.app()
        self.area(app, "Movimentações")
        app.text_input[0].set_value("INEXISTENTE").run()
        self.assertEqual(len(app.dataframe), 0)
        self.area(app, "Cadastros")
        # Catálogo: 342 códigos cadastrados mais eventuais TES do KARDEX
        # sem correspondência; nunca descartar os códigos não cadastrados.
        catalog_view = app.dataframe[0].value
        self.assertGreaterEqual(len(catalog_view), 342)
        self.assertEqual(len(catalog_view["TES"].unique()), len(catalog_view))
        self.assertIn("Descrição TES", catalog_view.columns)
        self.assertNotIn("Tipo de TM", catalog_view.columns)
        self.assertNotIn("Origem", catalog_view.columns)
        self.assertEqual(
            catalog_view.loc[catalog_view["TES"] == "540", "Descrição TES"].iloc[0],
            "BAIX CUSTO E QTD ZER",
        )
        self.assertEqual(
            catalog_view.loc[catalog_view["TES"] == "499", "Descrição TES"].iloc[0],
            "ENTRADA DE INVENTÁRIO/ENTRADA OP",
        )
        self.assertEqual(
            catalog_view.loc[catalog_view["TES"] == "999", "Descrição TES"].iloc[0],
            "SAÍDA DE INVENTÁRIO/CONSUMO OP",
        )
        self.assertTrue(set(mv.tes_reference()).issubset(set(catalog_view["TES"])))
        self.assertNotIn("Condição", app.dataframe[0].value.columns)
        self.area(app, "Fontes e relatórios")
        self.assertEqual(len(app.file_uploader), 1)
        self.assertTrue(any("Situação" in frame.value.columns for frame in app.dataframe))

    def test_period_and_warehouse_scope(self):
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

    def test_excel_of_filtered_op_preserves_ae(self):
        app = self.app()
        app.session_state["_test_action"] = "op"
        app.run()
        next(x for x in app.button if x.label == "PREPARAR EXCEL DO RECORTE").click().run()
        self.assertFalse(app.exception)
        wb = openpyxl.load_workbook(io.BytesIO(app.session_state["fm_mov_excel"][1]), read_only=True)
        self.assertEqual(wb.sheetnames, ["Grupos e TES", "Por OP", "Movimentações"])
        self.assertEqual(wb["Movimentações"]["H2"].value, " OP00001234567 ")
        self.assertEqual(len(list(wb["Movimentações"].iter_rows(values_only=True))), 2)
        self.assertEqual(wb["Por OP"]["A2"].value, "OP00001234567")
        self.assertEqual(wb["Grupos e TES"]["A2"].value, "SEM GRUPO")
        wb.close()


if __name__ == "__main__":
    unittest.main()
