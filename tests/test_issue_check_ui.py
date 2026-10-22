from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from streamlit.testing.v1 import AppTest

PROGRAM = '''
import pandas as pd
import issue_check as c
import issue_check_ui as ui
g = pd.DataFrame([
    {"Projeto": "26000101001", "Código": "00001000", "Lote": "000001", "Descrição": "MATERIAL CONFIRMADO", "Qtd. necessária": 10,
     "Qtd. atendida": 10, "Data de separação": "19/10/26 08:00", "Data de conferência": "20/10/26 08:00"},
    {"Projeto": "26000201001", "Código": "00002000", "Lote": "000002", "Descrição": "OUTRO MATERIAL", "Qtd. necessária": 3,
     "Qtd. atendida": 3, "Data de separação": "19/10/26 08:00", "Data de conferência": None},
])
s = pd.DataFrame([{"Produto": "00001000", "Lote": "000001", "Armazem": "S2", "Endereco": "G9-PROD", "Quantidade": 6}])
m = [{"codigo": "00001000", "ae_original": "OP26000101001", "armazem": "S2", "data": "2026-10-20", "tes": "550", "qtd_saida": "4", "qtd_entrada": None, "documento": "DOC", "arquivo_origem": "teste.xlsx", "linha_origem": 3}]
meta = [{"arquivo_nome": "teste.xlsx", "periodo_inicio": "2026-01-01", "periodo_fim": "2026-10-21", "lancamentos": 1}]
model = c.reconcile(c.parse_general(g), c.parse_stock(s), m, history_metas=meta, as_of="2026-10-21")
model["source_meta"] = {key: {"last_file_name": "base_21-10-2026.xlsx", "source_version": 1, "last_update_at": "2026-10-21T10:00:00+00:00"} for key in ui.SOURCE_KEYS}
model["history_meta"] = meta
model["duplicates"] = 0
ui.render_results(model)
'''


class IssueCheckUITests(unittest.TestCase):
    def test_op_filters_material_evidence_and_export(self):
        app = AppTest.from_string(PROGRAM, default_timeout=20).run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.expander), 0)  # fontes e OPs são abertas sob demanda
        self.assertTrue(any("ORDEM COM ALERTA" in b.label for b in app.button))
        self.assertTrue(any("ORDEM OK" in b.label for b in app.button))
        self.assertEqual(len(app.dataframe), 0)  # nenhum detalhe pesado antes do clique
        self.assertFalse(any(r.label == "Consulta" for r in app.radio))

        next(b for b in app.button if "OP 26000101001" in b.label).click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.dataframe), 1)
        self.assertFalse(any("Histórico incompleto" in t.value.columns for t in app.dataframe))
        self.assertIn("Outros endereços", app.dataframe[0].value.columns)

        # A tabela possui seleção nativa (checkbox) e já não oferece a
        # busca duplicada por selectbox. Evidências só aparecem após seleção.
        self.assertFalse(any(x.label == "DETALHAR MATERIAL E EVIDÊNCIAS" for x in app.selectbox))
        self.assertEqual(len(app.tabs), 0)
        import issue_check_ui as ui
        frame = ui._filter(pd.DataFrame([{"op": "26000101001", "item_id": "a"},
                                        {"op": "26000201001", "item_id": "b"}]),
                           "", "Todos")
        self.assertEqual(ui._material_at_position(frame, {"rows": [0]})["item_id"], "a")
        self.assertEqual(ui._material_at_position(frame, {"rows": [1]})["item_id"], "b")
        self.assertIsNone(ui._material_at_position(frame, {"rows": []}))

        next(x for x in app.selectbox if x.label == "ALERTAS").set_value("Com alertas")
        # Formulários só enviam os valores rascunhados quando recebem submit.
        self.assertEqual(len([b for b in app.button if "OP 2600" in b.label]), 2)
        next(b for b in app.button if b.label == "PESQUISAR").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len([b for b in app.button if "OP 2600" in b.label]), 1)

        next(x for x in app.selectbox if x.label == "ALERTAS").set_value("Todos")
        next(x for x in app.text_input if x.label == "LOCALIZAR OP").set_value("26000201001")
        self.assertFalse(app.exception)
        next(b for b in app.button if b.label == "PESQUISAR").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len([b for b in app.button if "OP 2600" in b.label]), 1)
        self.assertTrue(any("ORDEM OK" in b.label for b in app.button))
        self.assertTrue(any("PREPARAR RELATÓRIO COMPLETO" in b.label for b in app.button))


    def test_responsive_filters_cards_and_all_warehouses_without_manual_controls(self):
        import issue_check_ui as ui
        source = (Path(__file__).resolve().parents[1] / "issue_check_ui.py").read_text("utf-8")
        renderer = source.split("def render_issue_check():", 1)[1]
        self.assertNotIn('ATUALIZAR CONFERÊNCIA', renderer)
        self.assertNotIn('st.multiselect(', renderer)
        self.assertIn('chosen = tuple(sorted(set(options) | import_warehouses))', renderer)
        self.assertIn('fm-issue-filter-heading', source)
        self.assertIn('[data-baseweb="input"]', source)
        self.assertIn('focus-within', source)
        self.assertIn('.fm-issue-meta', source)
        self.assertIn('grid-template-columns:repeat(2,minmax(0,1fr))', source)
        markup = ui._op_metadata({
            "cliente": "<script>alert(1)</script>",
            "condicao": "FINALIZADO", "nota_fiscal": "100",
            "data_faturamento": "21/10/2026", "dias_patio": "3",
            "status_op": "FINALIZADO EM PÁTIO",
        })
        self.assertIn("&lt;script&gt;", markup)
        self.assertNotIn("<script>", markup)
        self.assertIn("21/10/2026", markup)
        self.assertIn("FINALIZADO EM PÁTIO", markup)

    def test_filter_inputs_have_contrast_borders_and_desktop_mobile_groups(self):
        # Regressão: os placeholders eram visíveis, mas as superfícies
        # clicáveis dos selects, datas e busca não possuíam demarcação.
        source = (Path(__file__).resolve().parents[1] / "issue_check_ui.py").read_text("utf-8")
        for selector in (
            '.st-key-fm_issue_filters [data-testid="stTextInput"] [data-baseweb="input"]',
            '.st-key-fm_issue_filters [data-testid="stDateInput"] [data-baseweb="input"]',
            '.st-key-fm_issue_filters [data-testid="stSelectbox"] [data-baseweb="select"] > div',
            '.st-key-fm_issue_filters [data-testid="stTextInput"] input',
            '.st-key-fm_issue_filters [data-testid="stDateInput"] input',
        ):
            self.assertIn(selector, source)
        self.assertIn('border:2px solid #9dabbf!important', source)
        self.assertIn('min-height:48px!important', source)
        self.assertIn('box-shadow:0 0 0 3px rgba(24,49,79,.16)', source)
        for key in ("fm_issue_search_group", "fm_issue_class_group", "fm_issue_date_filters"):
            self.assertIn(f'key="{key}"', source)
        self.assertIn("01 · PESQUISA", source)
        self.assertIn("02 · CLASSIFICAÇÃO", source)
        self.assertIn("03 · PERÍODO DE FATURAMENTO", source)
        app = AppTest.from_string(PROGRAM, default_timeout=20).run()
        self.assertFalse(app.exception)
        self.assertEqual({w.label for w in app.date_input}, {"DATA INICIAL", "DATA FINAL"})
        self.assertTrue(any(w.label == "LOCALIZAR OP" for w in app.text_input))
        self.assertTrue(any(w.label == "STATUS DA OP" for w in app.selectbox))
        self.assertTrue(any(w.label == "ALERTAS" for w in app.selectbox))

    def test_selectbox_content_and_filter_buttons_use_shared_alignment(self):
        source = (Path(__file__).resolve().parents[1] / "issue_check_ui.py").read_text("utf-8")
        self.assertIn(
            '.st-key-fm_issue_class_group [data-testid="stSelectbox"] [data-baseweb="select"] > div > div:first-child',
            source,
        )
        self.assertIn('align-items:center!important;', source)
        self.assertIn(
            '.st-key-fm_issue_class_group [data-testid="stSelectbox"] [data-baseweb="select"] svg',
            source,
        )
        self.assertIn(
            '.st-key-fm_issue_filters .st-key-fm_issue_search_submit button,',
            source,
        )
        self.assertIn(
            '.st-key-fm_issue_filters .st-key-fm_issue_clear_filters button {',
            source,
        )
        # A altura do cartão precisa comportar os selects, sem esticar seus
        # nós internos (isso causava truncamento junto à borda inferior).
        select_rules = source.split("/* Classificação: a caixa inteira", 1)[1].split(
            "/* Faixa de ações única", 1
        )[0]
        self.assertIn('height:auto!important;', select_rules)
        self.assertNotIn('height:100%!important;', select_rules)
        self.assertIn('height:48px!important;', select_rules)
        self.assertIn('overflow:visible!important;', select_rules)
        self.assertIn('min-height:136px!important;', source)
        # Os dois submits compartilham o mesmo contêiner de ações.
        action_layout = source.split(
            'with st.container(key="fm_issue_filter_actions"):', 1
        )[1].split("if submitted:", 1)[0]
        self.assertIn('action_search, action_clear = st.columns([1, 1], gap="small")', action_layout)
        self.assertNotIn('with actions:', action_layout)
        self.assertIn('max-width:450px!important;', source)
        self.assertIn('flex-direction:row!important;', source)
        self.assertIn('"PESQUISAR"', action_layout)
        self.assertIn('"LIMPAR FILTROS"', action_layout)
        self.assertIn('height:46px!important;', source)
        self.assertIn('margin:0!important;', source)
        self.assertIn('with st.form("fm_issue_filter_form"', source)
        app = AppTest.from_string(PROGRAM, default_timeout=20).run()
        self.assertFalse(app.exception)
        self.assertTrue(any(b.label == "PESQUISAR" for b in app.button))
        self.assertTrue(any(b.label == "LIMPAR FILTROS" for b in app.button))

    def test_invoice_filters_have_two_independent_calendars_and_can_clear(self):
        from datetime import date
        app = AppTest.from_string(PROGRAM, default_timeout=20).run()
        self.assertFalse(app.exception)
        dates = {widget.label: widget for widget in app.date_input}
        self.assertEqual(set(dates), {"DATA INICIAL", "DATA FINAL"})
        self.assertTrue(all(widget.value is None for widget in dates.values()))
        # Como ambos os calendários pertencem ao mesmo formulário, os
        # rascunhos só chegam ao servidor quando PESQUISAR é pressionado.
        dates["DATA INICIAL"].set_value(date(2026, 10, 1))
        dates["DATA FINAL"].set_value(date(2026, 10, 31))
        next(x for x in app.button if x.label == "PESQUISAR").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(
            next(x for x in app.date_input if x.label == "DATA INICIAL").value,
            date(2026, 10, 1)
        )
        self.assertEqual(
            next(x for x in app.date_input if x.label == "DATA FINAL").value,
            date(2026, 10, 31)
        )
        self.assertFalse(app.exception)
        next(x for x in app.button if x.label == "LIMPAR FILTROS").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(all(widget.value is None for widget in app.date_input))

    def test_selected_row_lookup_preserves_original_dataframe_position(self):
        import pandas as pd
        import issue_check_ui as ui
        group = pd.DataFrame([
            {"item_id": "op:a", "codigo": "A"},
            {"item_id": "op:b", "codigo": "B"},
            {"item_id": "op:c", "codigo": "C"},
        ], index=[99, 10, 25])
        self.assertEqual(ui._material_at_position(group, {"rows": [1]})["item_id"], "op:b")
        self.assertIsNone(ui._material_at_position(group, {"rows": []}))
        self.assertIsNone(ui._material_at_position(group, {"rows": [6]}))
        self.assertIsNone(ui._material_at_position(group, {"rows": [-1]}))

    def test_an_unavailable_source_is_not_presented_as_zero_stock_or_issues(self):
        program = '''
from unittest.mock import patch
import issue_check_ui as ui
with patch.object(ui, "_states", return_value={"relatorio_geral": {"available": False, "status": "ERRO"}}):
    ui.render_issue_check()
'''
        app = AppTest.from_string(program, default_timeout=10).run()
        self.assertFalse(app.exception)
        self.assertTrue(any("indisponível" in x.value for x in app.error))
        self.assertEqual(len(app.dataframe), 0)


if __name__ == "__main__":
    unittest.main()
