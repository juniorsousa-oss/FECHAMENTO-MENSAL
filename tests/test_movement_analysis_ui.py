from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path

import openpyxl
from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import movements as mv


PROGRAM = '''
import sys
import streamlit as st
sys.path.insert(0, "tests")
from test_movement_analysis import record, imported
import movements as mv
import movement_analysis_ui as ui

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
if action == "group":
    st.session_state.test_selection = {"selection": {"rows": [0]}}
    ui._group_selected("test_selection", [mv.ADJUSTMENT])
elif action == "condition":
    branch = model["frame"].loc[model["frame"]["documento"] == "AJUSTE"].iloc[0]
    st.session_state.test_selection = {"selection": {"rows": [0]}}
    ui._tes_selected("test_selection", [(branch.grupo_analise, branch.tes, branch.subgrupo_analise)])
elif action == "op":
    st.session_state.test_selection = {"selection": {"rows": [0]}}
    ui._op_selected("test_selection", ["OP00001234567"])
ui.render_results(model, imports)
'''


class MovementAnalysisUITests(unittest.TestCase):
    def app(self):
        app = AppTest.from_string(PROGRAM, default_timeout=20).run()
        self.assertFalse(app.exception)
        return app

    def area(self, app, name):
        app.segmented_control[0].set_value(name).run()
        self.assertFalse(app.exception)

    def test_summary_has_no_consultation_filters_and_keeps_the_period_totals(self):
        app = self.app()
        self.assertEqual(len(app.text_input), 0)
        self.assertEqual([x.label for x in app.multiselect], ["Armazéns"])
        self.assertEqual(len(app.file_uploader), 0)
        self.assertEqual(app.segmented_control[0].value, "Visão geral")
        groups = app.dataframe[0].value
        self.assertEqual(groups["Entrada (R$)"].sum(), 30)
        self.assertEqual(groups["Saída (R$)"].sum(), 35)
        self.assertTrue(any("PERÍODO PARCIAL" in x.value for x in app.caption))

    def test_consultation_filters_are_local_and_survive_navigation(self):
        app = self.app()
        self.area(app, "Grupos e TES")
        next(x for x in app.multiselect if x.label == "Grupo de análise").set_value([mv.ADJUSTMENT]).run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.dataframe[0].value), 1)
        self.area(app, "Por OP")
        self.assertEqual(app.text_input[0].value, "")
        app.text_input[0].set_value("00001234567").run()
        self.assertEqual(app.dataframe[0].value["OP"].tolist(), ["OP00001234567"])
        self.area(app, "Visão geral")
        self.assertEqual(app.dataframe[0].value["Saída (R$)"].sum(), 35)
        self.area(app, "Grupos e TES")
        self.assertEqual(next(x for x in app.multiselect if x.label == "Grupo de análise").value, [mv.ADJUSTMENT])
        self.area(app, "Por OP")
        self.assertEqual(app.text_input[0].value, "00001234567")

    def test_group_and_condition_drilldown_opens_only_matching_records(self):
        app = self.app()
        app.session_state["_test_action"] = "group"
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(app.segmented_control[0].value, "Grupos e TES")
        app.session_state["_test_action"] = "condition"
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(app.segmented_control[0].value, "Movimentações")
        self.assertEqual(len(app.dataframe[0].value), 1)
        self.assertEqual(app.dataframe[0].value["TES"].tolist(), ["520"])
        self.assertTrue(any("Grupo:" in x.value and "Condição:" in x.value for x in app.caption))
        next(x for x in app.button if "VOLTAR PARA" in x.label).click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.segmented_control[0].value, "Grupos e TES")

    def test_op_drilldown_clears_old_record_filters_and_preserves_original_ae(self):
        app = self.app()
        self.area(app, "Movimentações")
        self.assertEqual(set(app.dataframe[0].value["Endereçamento compensado"]), {"NÃO"})
        self.assertTrue(any("Endereçamento compensado" in x.value for x in app.caption))
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
        self.assertFalse(any("VOLTAR PARA" in x.label for x in app.button))

    def test_classification_and_sources_remain_available_after_an_empty_search(self):
        app = self.app()
        self.area(app, "Movimentações")
        app.text_input[0].set_value("INEXISTENTE").run()
        self.assertEqual(len(app.dataframe), 0)
        self.area(app, "Classificação")
        self.assertEqual(len(app.text_input), 0)
        self.assertEqual(len(app.dataframe[0].value), 8)
        self.assertIn("999 · consumo de OPs / descrição ORDEM DE PRODUÇÃO", app.dataframe[0].value["Condição"].tolist())
        next(x for x in app.button if x.label == "DETALHAR AJUSTES A REFINAR").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.segmented_control[0].value, "Grupos e TES")
        self.assertEqual(len(app.dataframe[0].value), 1)
        self.area(app, "Fontes e relatórios")
        self.assertEqual(len(app.file_uploader), 1)
        self.assertTrue(any("Situação" in frame.value.columns for frame in app.dataframe))
        self.assertTrue(any("4 registros" in x.value for x in app.caption))

    def test_period_and_warehouse_scope_apply_to_every_consultation(self):
        app = self.app()
        next(x for x in app.multiselect if x.label == "Armazéns").set_value(["S2"]).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.dataframe[0].value["Saída (R$)"].sum(), 30)
        self.area(app, "Por OP")
        self.assertEqual(app.dataframe[0].value["OP"].tolist(), ["OP00001234567"])
        self.area(app, "Visão geral")
        next(x for x in app.selectbox if x.label == "Período da análise").set_value("ACUMULADO DO ANO").run()
        self.assertFalse(app.exception)
        self.assertEqual(app.dataframe[0].value["Entrada (R$)"].sum(), 70)
        next(x for x in app.selectbox if x.label == "Competência analisada").set_value("2026-09").run()
        self.assertFalse(app.exception)
        self.assertEqual(app.dataframe[0].value["Entrada (R$)"].sum(), 40)
        self.assertEqual(app.dataframe[0].value["Saída (R$)"].sum(), 0)

    def test_record_excel_uses_the_visible_consultation_not_the_whole_history(self):
        app = self.app()
        app.session_state["_test_action"] = "op"
        app.run()
        next(x for x in app.button if x.label == "PREPARAR EXCEL DO RECORTE").click().run()
        self.assertFalse(app.exception)
        output = app.session_state["fm_mov_excel"][1]
        workbook = openpyxl.load_workbook(io.BytesIO(output), read_only=True)
        sheet = workbook["Movimentações"]
        self.assertEqual(len(list(sheet.iter_rows(values_only=True))), 2)
        self.assertEqual(sheet["AE2"].value, " OP00001234567 ")
        workbook.close()


if __name__ == "__main__":
    unittest.main()
