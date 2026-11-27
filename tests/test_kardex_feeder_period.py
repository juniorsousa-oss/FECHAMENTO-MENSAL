"""Central Kardex period selection, using isolated Streamlit sessions."""

import unittest

from streamlit.testing.v1 import AppTest


PROGRAM = """
import sys
from unittest.mock import patch
import streamlit as st
sys.path.insert(0, "tests")
from test_kardex_history import pack, record
from movement_analysis_ui import _render_central_kardex
import central_movement_feeds as feeds
import movement_store as store

current = st.session_state.get("fixture_current", "2026-12")
source_month = st.session_state.get("fixture_source", "2026-11")
state = {k: {"current": True, "token": k} for k in feeds.KARDEX_KEYS}
reads = 0

def closed():
    global reads
    reads += 1
    if st.session_state.get("fixture_db_failure"):
        raise RuntimeError("fixture database unavailable")
    if st.session_state.get("fixture_closed") or (
        st.session_state.get("fixture_race") and reads > 1
    ):
        return {"2026-11-01"}
    return set()

def parsed(key, token):
    warehouse = key.removeprefix("kardex_").upper()
    month = "2026-12" if st.session_state.get("fixture_mixed") and warehouse == "EP" else source_month
    return pack([record(armazem=warehouse, data=month + "-20")], key,
                start=month + "-19", end=month + "-21")

with patch.object(feeds, "state_or_empty", return_value=state), \
     patch.object(feeds, "describe", side_effect=lambda k, _entry: k), \
     patch.object(feeds, "load_parsed", side_effect=parsed), \
     patch.object(feeds, "verify_current"), \
     patch.object(feeds, "mark_applied"), \
     patch.object(store, "save_import", side_effect=lambda batch: st.session_state.update(fixture_applied=batch)):
    _render_central_kardex(current, closed)
"""


class KardexFeederPeriodTests(unittest.TestCase):
    def app(self, **state):
        app = AppTest.from_string(PROGRAM)
        for key, value in state.items():
            app.session_state[key] = value
        app.run()
        self.assertFalse(app.exception)
        return app

    def test_default_and_open_previous_period(self):
        app = self.app()
        self.assertEqual(app.selectbox[0].value, "2026-12")
        app.selectbox[0].select("2026-11").run()
        app.button(key="fm_preview_central_kardex").click().run()
        self.assertTrue(app.success)
        preview = app.session_state["fm_central_kardex_preview"]
        scope = preview["batch"]["meta"]["escopos"]
        self.assertEqual({(s["armazem"], s["competencia"], s["periodo_inicio"], s["periodo_fim"])
                          for s in scope},
                         {(a, "2026-11", "2026-11-19", "2026-11-21") for a in ("S2", "EP", "E2")})
        app.selectbox[0].select("2026-12").run()
        self.assertFalse(app.success)
        self.assertNotIn("fm_central_kardex_preview", app.session_state)

    def test_closed_previous_not_offered_and_db_failure_blocks_preview(self):
        app = self.app(fixture_closed=True)
        self.assertEqual(len(app.selectbox[0].options), 1)
        self.assertEqual(app.selectbox[0].value, "2026-12")
        app = self.app(fixture_db_failure=True)
        self.assertTrue(app.error)
        self.assertFalse(app.button)

    def test_mixed_sources_are_rejected(self):
        app = self.app(fixture_mixed=True)
        app.selectbox[0].select("2026-11").run()
        app.button(key="fm_preview_central_kardex").click().run()
        self.assertIn("Kardex não consolidado", app.error[0].value)
        self.assertNotIn("fixture_applied", app.session_state)

    def test_previous_month_can_be_confirmed_with_unchanged_sources(self):
        app = self.app()
        app.selectbox[0].select("2026-11").run()
        app.button(key="fm_preview_central_kardex").click().run()
        app.checkbox[0].check().run()
        app.button(key="fm_apply_central_kardex").click().run()
        self.assertEqual(app.session_state["fixture_applied"]["meta"]["competencias"], ["2026-11"])

    def test_rechecks_closed_at_apply(self):
        app = self.app()
        app.selectbox[0].select("2026-11").run()
        app.button(key="fm_preview_central_kardex").click().run()
        app.checkbox[0].check().run()
        app.session_state["fixture_race"] = True
        app.button(key="fm_apply_central_kardex").click().run()
        self.assertIn("competência já está encerrada", app.error[0].value)
        self.assertNotIn("fixture_applied", app.session_state)

    def test_january_allows_open_december_without_changing_default(self):
        app = self.app(fixture_current="2027-01", fixture_source="2026-12")
        self.assertEqual(app.selectbox[0].value, "2027-01")
        app.selectbox[0].select("2026-12").run()
        app.button(key="fm_preview_central_kardex").click().run()
        self.assertTrue(app.success)


if __name__ == "__main__":
    unittest.main()
