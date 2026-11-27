"""Regressões de navegação enxuta do módulo KARDEX SETTA."""
from __future__ import annotations

import io
import re
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
scoped_actions = ("group_scoped", "sub_scoped", "tes_scoped", "movement_scoped")
if action in scoped_actions:
    known = {"020", "520", "550"}
    configured = group_cfg.create_group(group_cfg.empty(), "RETORNOS", known_tes=known)
    configured = group_cfg.assign_group(configured, configured["grupos"][0]["id"],
                                        ["020"], known_tes=known)
    configured = group_cfg.create_group(configured, "BAIXAS", known_tes=known)
    configured = group_cfg.assign_group(configured, configured["grupos"][1]["id"],
                                        ["520", "550"], known_tes=known)
    ui._groups_read = lambda: configured
if action in ("group_only", "drill", "op_drill") + scoped_actions:
    original_table = ui._table
    def select_in_order(data, *args, **kwargs):
        displayed = original_table(data, *args, **kwargs)
        key = kwargs.get("key", "")
        if "_overview_groups_" in key:
            if action in ("group_only", "drill"):
                return {"selection": {"rows": [0]}}
            if action in scoped_actions:
                return {"selection": {"rows": [1]}}  # BAIXAS, R$ 35 em saídas.
        if "_overview_subgroups_" in key:
            if action == "drill":
                return {"selection": {"rows": [0]}}
            if action in ("sub_scoped", "tes_scoped", "movement_scoped"):
                # Consumo OP é o subgrupo dos dois movimentos da TES 550.
                ix = data["Subgrupo"].tolist().index("CONSUMO OP")
                return {"selection": {"rows": [ix]}}
        if "_overview_tes_" in key and action in ("drill", "tes_scoped", "movement_scoped"):
            return {"selection": {"rows": [0]}}
        if action == "op_drill" and "_op_table_" in key:
            return {"selection": {"rows": [0]}}
        return displayed
    ui._table = select_in_order
if action == "movement_scoped":
    original_dataframe = ui.st.dataframe
    def select_movement(*args, **kwargs):
        displayed = original_dataframe(*args, **kwargs)
        if "fm_mov_overview_mov_" in str(kwargs.get("key", "")):
            return {"selection": {"rows": [0]}}
        return displayed
    ui.st.dataframe = select_movement
try:
    ui.render_results(model, imports)
finally:
    if action in ("group_only", "drill", "op_drill") + scoped_actions:
        ui._table = original_table
    if action == "movement_scoped":
        ui.st.dataframe = original_dataframe
"""


class MovementAnalysisUITests(unittest.TestCase):
    def app(self):
        app = AppTest.from_string(PROGRAM, default_timeout=20)
        app.query_params["mes"] = "2026-10"  # Explicitly exercise historical fixture.
        app.run()
        self.assertFalse(app.exception)
        return app

    def area(self, app, name):
        app.segmented_control[0].set_value(name).run()
        self.assertFalse(app.exception)

    def card_values(self, app):
        snippets = [x.value for x in app.markdown if 'class="summary-grid"' in x.value]
        self.assertEqual(len(snippets), 1)
        return re.findall(r'class="summary-card-value">([^<]+)', snippets[0])

    def test_cards_follow_full_group_subgroup_tes_and_selected_movement(self):
        app = self.app()
        self.assertEqual(self.card_values(app), [
            "R$ 30,00", "R$ 35,00", "R$ -5,00"
        ])
        app.session_state["_test_action"] = "group_scoped"
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(self.card_values(app), [
            "R$ 0,00", "R$ 35,00", "R$ -35,00"
        ])
        app.session_state["_test_action"] = "sub_scoped"
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(self.card_values(app), [
            "R$ 0,00", "R$ 25,00", "R$ -25,00"
        ])
        app.session_state["_test_action"] = "tes_scoped"
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(self.card_values(app), [
            "R$ 0,00", "R$ 25,00", "R$ -25,00"
        ])
        self.assertTrue(any("Lançamentos · CONSUMO OP" in x.value for x in app.markdown))
        app.session_state["_test_action"] = "movement_scoped"
        app.run()
        self.assertFalse(app.exception)
        # Um único lançamento de baixa deve substituir os R$ 25 do conjunto.
        self.assertEqual(self.card_values(app)[0], "R$ 0,00")
        self.assertIn(self.card_values(app)[1], ("R$ 20,00", "R$ 5,00"))
        self.assertFalse(any("Selecione o checkbox de um grupo" in x.value
                             for x in list(app.markdown) + list(app.caption)))
        self.assertFalse(any("movimentações encontradas." in x.value
                             for x in list(app.markdown) + list(app.caption)))
        self.assertEqual(app.segmented_control[0].value, "Visão geral")

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
        self.assertTrue(op["Primeiro movimento"].str.match(r"^\d{2}/\d{2}/\d{4}$").all())
        self.assertTrue(op["Último movimento"].str.match(r"^\d{2}/\d{2}/\d{4}$").all())

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

    def test_optional_warehouse_only_appears_when_in_the_selected_period(self):
        import pandas as pd
        from movement_analysis_ui import _period_warehouses
        frame = pd.DataFrame([
            {"armazem": "20", "competencia": "2026-10"},
            {"armazem": "S2", "competencia": "2026-11"},
        ])
        self.assertEqual(_period_warehouses(frame, [], "2026-11", "MÊS SELECIONADO"), ["S2"])
        self.assertEqual(_period_warehouses(frame, [], "2026-10", "MÊS SELECIONADO"), ["20", "S2"])
        self.assertEqual(_period_warehouses(frame, [], "2026-11", "ACUMULADO DO ANO"), ["20", "S2"])
        declared = [{"armazem": "20", "competencia": "2026-11"}]
        self.assertIn("20", _period_warehouses(frame, declared, "2026-11", "MÊS SELECIONADO"))

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
        self.assertEqual(len(app.dataframe), 3)
        group_table, sub_table, ledger = [x.value for x in app.dataframe]
        self.assertEqual(group_table["Grupo"].tolist(), ["SEM GRUPO"])
        self.assertIn("Subgrupo", sub_table.columns)
        self.assertIn("Grupo", ledger.columns)
        tes_filter = next(x for x in app.selectbox if x.label == "TES (opcional)")
        self.assertEqual(tes_filter.value, "Todas")
        self.assertEqual(set(ledger["TES"]), set(tes_filter.options) - {"Todas"})
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
            "CONSUMO DE OP",
        )
        self.assertTrue(any("Prioridade das condições" in x.value for x in app.markdown))
        self.area(app, "Fontes e relatórios")
        # O alimentador foi transferido para Configurações; a análise fica em leitura.
        self.assertEqual(len(app.file_uploader), 0)
        self.assertTrue(any("Situação" in table.value.columns for table in app.dataframe))

    def test_catalog_validation_and_success_in_same_screen(self):
        app = AppTest.from_string("""
import pandas as pd
import streamlit as st
from unittest.mock import patch
import movement_analysis_ui as ui
import kardex_group_config as catalog

if "test_catalog" not in st.session_state:
    st.session_state.test_catalog = catalog.empty()

def persist(updated, available):
    st.session_state.test_catalog = catalog.validated(updated, available)

with patch.object(ui, "_groups_read", lambda: st.session_state.test_catalog), \
     patch.object(ui, "_groups_commit", persist):
    ui._catalog(pd.DataFrame({"tes": ["520", "550"]}))
""", default_timeout=20).run()

        def field(label):
            return next(x for x in app.text_input if x.label == label)

        def click(label):
            next(x for x in app.button if x.label == label).click().run()
            self.assertFalse(app.exception)

        field("Nome do novo grupo").set_value("SEM GRUPO")
        click("Criar grupo")
        self.assertTrue(app.error)
        self.assertEqual(field("Nome do novo grupo").value, "SEM GRUPO")
        self.assertFalse(app.session_state.test_catalog["grupos"])

        field("Nome do novo grupo").set_value("Produção piloto")
        click("Criar grupo")
        self.assertEqual(app.success[0].value, "Grupo criado.")
        self.assertEqual(field("Nome do novo grupo").value, "")

        field("Nome do grupo").set_value("Produção piloto A")
        app.multiselect[0].set_value(["520"])
        click("Salvar grupo")
        self.assertEqual(app.success[0].value, "Grupo e TES salvos.")
        self.assertEqual(app.session_state.test_catalog["grupos"][0]["tes"], ["520"])

        field("Nome da nova condição").set_value("Auditar contagem piloto")
        click("Cadastrar condição")
        self.assertEqual(app.success[0].value, "Condição cadastrada.")
        self.assertEqual(field("Nome da nova condição").value, "")
        condition = app.session_state.test_catalog["condicoes"][-1]
        app.button(key="fm_mov_condition_up_" + condition["id"]).click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.success[0].value, "Prioridade atualizada.")
        self.assertEqual(app.session_state.test_catalog["condicoes"][-2]["id"], condition["id"])

        self.assertTrue(next(x for x in app.button if x.label == "Excluir grupo").disabled)
        app.checkbox[0].check().run()
        click("Excluir grupo")
        self.assertFalse(app.session_state.test_catalog["grupos"])
        self.assertIn("TES permanecem no Kardex", app.success[0].value)

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
