from datetime import datetime
from unittest import TestCase
from unittest.mock import patch
from zoneinfo import ZoneInfo

from streamlit.testing.v1 import AppTest

import central_movement_feeds as feeds
import movements as mv
import ops_lot_source as ops
from test_ops_lot_source import line, xltx_bytes


class CentralRestorationTests(TestCase):
    def test_normalized_ops_matches_original_rows(self):
        raw = xltx_bytes([line()])
        original = ops.parse(raw, "OPS.xlsx")
        xml = list(mv._xml_rows(raw))
        sheet = {
            "name": xml[0][0], "row_numbers": [r[1] for r in xml],
            "date1904": xml[0][3],
            "rows": [[r[2].get(c) for c in "ABCDEFGHIJKLMNOP"] for r in xml],
        }
        pack = {
            "format": "SETTA_SOURCE_V1", "profile": "CLOSING_XML_VALUES_V1",
            "source_sha256": original["meta"]["sha256"], "sheets": [sheet],
        }
        assert ops.parse(b"", "OPS.xlsx", source_pack=pack) == original


    def test_verify_rejects_changed_or_stale_normalized_source(self):
        key = "kardex_s2"
        row = {"source_key": key, "version": 5, "last_update_at": "today"}
        norm = {"source_key": key, "source_version": 5, "available": True,
                "profile": "CLOSING_XML_VALUES_V1"}
        with patch.object(feeds.central, "api_call", side_effect=lambda action, *a, **k:
                          {"data": [norm]} if action == "source_normalized_status"
                          else {"data": {"sources": [row]}}):
            feeds.verify_current(key, "v5|today")
            for token, stale in [("v4|yesterday", False), ("v5|today", True)]:
                norm["stale"] = stale
                try:
                    feeds.verify_current(key, token)
                except ValueError as exc:
                    assert "mudou" in str(exc)
                else:
                    raise AssertionError("Stale source allowed")


    def test_kardex_without_current_base_stays_in_current_month(self):
        app = AppTest.from_string("""
import pandas as pd
import streamlit as st
import movement_analysis_ui as ui
frame = pd.DataFrame([{'competencia': '2000-01', 'armazem': 'S2'}])
view = ui._context(frame, [], [])
st.write(f'Filtrados: {len(view)}')
    """).run()
        assert not app.exception
        assert app.selectbox[0].value == datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y-%m")
        assert any(msg.value == "Filtrados: 0" for msg in app.markdown)
        app.selectbox[0].set_value("2000-01").run()
        assert any(msg.value == "Filtrados: 1" for msg in app.markdown)
