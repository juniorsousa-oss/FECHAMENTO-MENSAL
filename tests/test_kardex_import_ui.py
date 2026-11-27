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
import central_movement_feeds as feeds
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

with patch.object(feeds, "state_or_empty", return_value={}), \\
     patch.object(ui.st,"file_uploader",return_value=files), \\
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


    def test_central_preview_requires_confirmation_and_rechecks_version_before_writing(self):
        program = """
from unittest.mock import patch
import streamlit as st
import movement_analysis_ui as ui
import central_movement_feeds as feeds
import kardex_history as history
from test_kardex_history import pack
from test_movement_analysis import record

keys = feeds.KARDEX_KEYS
state = {key: {"current": True, "applied": False, "token": "v5|test",
               "meta": {"version": 5}} for key in keys}
def parse(key, token):
    arm = key.removeprefix("kardex_").upper()
    return pack([record(armazem=arm, data="2026-11-26")], key,
                start="2026-11-02", end="2026-11-26")
def verify(key, token):
    if st.session_state.get("stale") and key=="kardex_e2":
        raise ValueError("A fonte mudou")
    st.session_state.verified = [*st.session_state.get("verified", []), key]
def mark_applied(key, entry, rows):
    st.session_state.applied = [*st.session_state.get("applied", []), (key,rows)]
def save(parsed):
    st.session_state.saved = [*st.session_state.get("saved", []), parsed]
with patch.object(feeds, "state_or_empty", return_value=state), patch.object(feeds, "load_parsed", side_effect=parse), patch.object(feeds, "verify_current", verify), patch.object(feeds, "mark_applied", mark_applied), patch.object(ui.store, "save_import", side_effect=save):
    ui._render_central_kardex("2026-11", lambda: {"2026-11"} if st.session_state.get("closed") else set())
"""
        app = AppTest.from_string(program, default_timeout=15).run()
        self.assertFalse(app.exception)
        app.button(key="fm_preview_central_kardex").click().run()
        self.assertTrue(app.dataframe)
        self.assertTrue(app.button(key="fm_apply_central_kardex").disabled)
        self.assertNotIn("saved", app.session_state)
        app.checkbox[0].check().run()
        app.session_state["stale"] = True
        app.button(key="fm_apply_central_kardex").click().run()
        self.assertNotIn("saved", app.session_state)
        self.assertTrue(any("A fonte mudou" in x.value for x in app.error))
        app.session_state["stale"] = False
        app.session_state["closed"] = True
        app.button(key="fm_apply_central_kardex").click().run()
        self.assertNotIn("saved", app.session_state)
        self.assertTrue(any("competência já está encerrada" in x.value for x in app.warning))
        self.assertFalse(any(b.key == "fm_apply_central_kardex" for b in app.button))
        app.session_state["closed"] = False
        app.run()
        app.button(key="fm_preview_central_kardex").click().run()
        app.checkbox[0].check().run()
        app.button(key="fm_apply_central_kardex").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.session_state["saved"]), 1)
        self.assertEqual(len(app.session_state["saved"][0]["rows"]), 3)
        self.assertEqual(len(app.session_state["applied"]), 3)
        self.assertEqual(app.session_state["saved"][0]["meta"]["armazens"], ["E2","EP","S2"])


if __name__ == "__main__":
    unittest.main()
