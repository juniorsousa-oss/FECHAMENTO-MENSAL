from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from streamlit.testing.v1 import AppTest

PROGRAM = '''
import sys
sys.path.insert(0,"tests")
from types import SimpleNamespace
from unittest.mock import patch
import streamlit as st
import movements as mv
import movement_analysis_ui as ui
from test_kardex_history import pack
from test_movement_analysis import record

old = pack([record(documento="ANTIGO1"), record(documento="ANTIGO2")], start="2026-10-01")
new = pack([record(documento="NOVO", data="2026-10-15")], "b", start="2026-10-01", end="2026-10-21")
new["meta"]["periodo_informado"] = True
files = [SimpleNamespace(name="outubro-S2.xlsx",getvalue=lambda:b"b")]
sources = {"outubro-S2.xlsx":new}
if st.session_state.get("overlap"):
    other = pack([record(documento="OUTRO")], "c", start="2026-10-01")
    files.append(SimpleNamespace(name="outra-versao.xlsx",getvalue=lambda:b"c"))
    sources["outra-versao.xlsx"] = other

def save(parsed, known):
    values = list(st.session_state.get("saved",[]))
    values.append(parsed["meta"])
    st.session_state.saved = values
    return {"saved":True,"key":"synthetic-key","meta":parsed["meta"],"reactivated":False}

with patch.object(ui.st,"file_uploader",return_value=files), \\
     patch.object(ui,"_parse_import",side_effect=lambda raw,name:sources[name]), \\
     patch.object(ui.store,"list_imports",return_value=[]), \\
     patch.object(ui.store,"save_import",side_effect=save):
    ui._import_controls([], mv.build_model([old]))
'''


class KardexImportUITests(unittest.TestCase):
    def test_preview_shows_the_replaced_scope_and_only_saves_after_the_import_button(self):
        app = AppTest.from_string(PROGRAM, default_timeout=15).run()
        self.assertFalse(app.exception)
        preview = app.dataframe[0].value.iloc[0]
        self.assertEqual(preview["Armazéns"], "S2")
        self.assertEqual(preview["Competências abrangidas"], "10/2026")
        self.assertEqual(preview["Registros atuais no recorte"], 2)
        self.assertEqual(preview["Novos registros"], 1)
        self.assertNotIn("saved", app.session_state)
        next(x for x in app.button if x.label == "IMPORTAR E SUBSTITUIR PERÍODOS").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.session_state["saved"]), 1)
        self.assertEqual(app.session_state["saved"][0]["competencias"], ["2026-10"])
        self.assertEqual(app.session_state["saved"][0]["armazens"], ["S2"])
        self.assertEqual(app.session_state["fm_mov_upload_epoch"], 1)

    def test_partial_month_start_blocks_import_before_any_write(self):
        app = AppTest.from_string(PROGRAM, default_timeout=15).run()
        next(x for x in app.date_input if x.label == "Início do relatório completo").set_value(date(2026,10,10)).run()
        self.assertFalse(app.exception)
        self.assertTrue(any("primeiro dia" in x.value for x in app.error))
        self.assertFalse(any(x.label == "IMPORTAR E SUBSTITUIR PERÍODOS" for x in app.button))
        self.assertNotIn("saved", app.session_state)

    def test_two_files_for_the_same_warehouse_month_are_blocked_together(self):
        app = AppTest.from_string(PROGRAM, default_timeout=15)
        app.session_state["overlap"] = True
        app.run()
        self.assertFalse(app.exception)
        self.assertTrue(any("Dois arquivos" in x.value for x in app.error))
        self.assertNotIn("saved", app.session_state)


if __name__ == "__main__":
    unittest.main()
