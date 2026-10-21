from __future__ import annotations

import sys
import unittest
from pathlib import Path

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
    def test_op_filters_material_evidence_and_all_areas(self):
        app = AppTest.from_string(PROGRAM, default_timeout=20).run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.expander), 2)

        detail = next(x for x in app.selectbox if x.label == "Detalhar material e evidências")
        detail.set_value("26000101001:00001000").run()
        self.assertFalse(app.exception)
        self.assertTrue(any(t.label == "MOVIMENTOS KARDEX" for t in app.tabs))
        self.assertTrue(any("SALDO EM G9-PROD" in x.value for x in app.error))
        app.radio[0].set_value("Divergências").run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.dataframe[0].value), 1)
        app.radio[0].set_value("Fontes e critérios").run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.dataframe[0].value), 2)
        app.radio[0].set_value("Por OP").run()
        app.text_input[0].set_value("26000201001").run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.expander), 1)
        next(x for x in app.button if x.label == "LIMPAR FILTROS").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.expander), 2)

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
