import gzip
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from streamlit.testing.v1 import AppTest
from central_closing_bundle import FORMAT, SOURCES, compile_preview


def sources():
    return {key: {"current": True, "token": f"v{i}|2026-11-27T11:00:00Z"}
            for i, key in enumerate(SOURCES, start=1)}


def parsed(*_):
    return {"rows": [{"codigo": "00001000", "quantidade": "0.001"}], "meta": {
        "arquivo_nome": "origem.xlsx", "sha256": "a" * 64,
        "periodo_inicio": "2026-10-01", "periodo_fim": "2026-10-31"}}


class ConsolidationTests(unittest.TestCase):
    def test_report_preserves_values_origins_and_versions(self):
        state = sources()
        verified = []
        with TemporaryDirectory() as folder:
            report = Path(folder) / "fechamento.json.gz"
            counts = compile_preview(report, sources=state, load_parsed=parsed,
                                     verify_current=lambda key, token: verified.append((key, token)))
            with gzip.open(report, "rt") as handle:
                bundle = json.load(handle)
            self.assertEqual(bundle["format"], FORMAT)
            self.assertEqual(counts, dict.fromkeys(SOURCES, 1))
            self.assertEqual(verified, [(key, state[key]["token"]) for key in SOURCES])
            for key in SOURCES:
                item = bundle["sources"][key]
                self.assertEqual(item["metadata"]["source_token"], state[key]["token"])
                self.assertEqual(item["rows"], parsed()["rows"])

    def test_refuses_incomplete_changed_or_large_lot_preserves_previous(self):
        state = sources()
        with TemporaryDirectory() as folder:
            report = Path(folder) / "fechamento.json.gz"
            report.write_bytes(b"last-valid")
            missing = {k: v for k, v in state.items() if k != "kardex_ep"}
            with self.assertRaisesRegex(ValueError, "kardex_ep"):
                compile_preview(report, sources=missing, load_parsed=parsed,
                                verify_current=lambda *_: None)
            def fail(key, token):
                if key == "kardex_e2":
                    raise ValueError("Mudou")
            with self.assertRaisesRegex(ValueError, "Mudou"):
                compile_preview(report, sources=state, load_parsed=parsed, verify_current=fail)
            with self.assertRaisesRegex(ValueError, "limite"):
                compile_preview(report, sources=state, load_parsed=parsed,
                                verify_current=lambda *_: None, max_bytes=10)
            self.assertEqual(report.read_bytes(), b"last-valid")
            self.assertEqual(list(Path(folder).iterdir()), [report])

    def test_preview_requires_complete_versions_and_invalidates_on_change(self):
        app = AppTest.from_string("""
import streamlit as st
from unittest.mock import patch
from central_closing_bundle import SOURCES
from central_closing_bundle_ui import render_central_closing_bundle
import central_movement_feeds as feeds

rev = st.session_state.get("revision", 0)
state = {key: {"current": True, "token": f"v{rev}|today", "meta": {"version": rev}} for key in SOURCES} if rev else {}
def read(key, token):
    return {"rows": [{"lote":"00015"}], "meta": {
        "arquivo_nome": "ERP.xlsx", "sha256": "a" * 64,
        "periodo_inicio": "2026-10-01", "periodo_fim": "2026-10-31"}}

with patch.object(feeds, "state_or_empty", return_value=state), patch.object(feeds, "parse_current_source", side_effect=read), patch.object(feeds, "verify_current"):
    render_central_closing_bundle()
""").run()
        assert not app.exception
        button = app.button(key="fm_central_compile")
        assert button.disabled
        app.session_state["revision"] = 1
        app.run()
        app.button(key="fm_central_compile").click().run()
        assert not app.exception
        assert "4 registros de 4 fontes" in app.success[0].value
        assert len(app.get("download_button")) == 1
        app.session_state["revision"] = 2
        app.run()
        assert not app.success
        assert not app.get("download_button")
