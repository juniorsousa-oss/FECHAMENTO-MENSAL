from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import central_fechamento_data as central
import movement_store as store


class SourceStatusCacheTests(unittest.TestCase):
    def tearDown(self):
        central.source_state_for.clear()
        central._consumer_status_rows.clear()

    def test_source_versions_are_checked_once_per_cache_window(self):
        central.source_state_for.clear()
        payload = {"data": {"sources": [
            {"source_key": "analitico", "version": 8, "available": True},
            {"source_key": "cadastros", "version": 4, "available": True},
        ]}}
        with patch.object(central, "api_call", return_value=payload) as call:
            for _ in range(3):
                self.assertEqual(central.source_state()["version"], 8)
                self.assertEqual(central.source_state_for("cadastros")["version"], 4)
            self.assertEqual(call.call_count, 2)
            central.source_state_for.clear()
            self.assertEqual(central.source_state()["version"], 8)
            self.assertEqual(call.call_count, 3)

    def test_sync_status_is_shared_between_sources_and_invalidatable(self):
        central._consumer_status_rows.clear()
        payload = {"data": [
            {"source_key": "analitico", "version_token": "v8"},
            {"source_key": "cadastros", "version_token": "v4"},
        ]}
        with patch.object(central, "api_call", return_value=payload) as call:
            self.assertEqual(central.sync_state()["version_token"], "v8")
            self.assertEqual(central.sync_state_for("cadastros")["version_token"], "v4")
            self.assertEqual(call.call_count, 1)
            central._consumer_status_rows.clear()
            central.sync_state()
            self.assertEqual(call.call_count, 2)


class KardexParallelTests(unittest.TestCase):
    def test_active_imports_are_loaded_concurrently_but_keep_chronology(self):
        entries = [
            {"chave": f"file-{i}", "atualizado_em": f"2026-10-21T10:00:0{i}",
             "meta": {"arquivo_nome": f"{i}.xlsx"}}
            for i in range(4)
        ]
        barrier = threading.Barrier(2, timeout=5)
        threads = set()
        lock = threading.Lock()

        def load(key):
            with lock:
                threads.add(threading.get_ident())
            barrier.wait()
            return {"meta": {"arquivo_nome": key}, "rows": [{"codigo": key}]}

        with patch.object(store, "load_import", side_effect=load), \
             patch.object(store.db, "supabase_url", return_value="https://example.supabase.co"), \
             patch.object(store.db, "supabase_key", return_value="test-only"), \
             patch.object(store.db, "read_with_connection", side_effect=lambda reader, url, key: reader()):
            result = store.load_history(entries)

        self.assertGreaterEqual(len(threads), 2)
        self.assertEqual([pack["_key"] for pack in result], [f"file-{i}" for i in range(4)])
        self.assertEqual([pack["rows"][0]["codigo"] for pack in result], [f"file-{i}" for i in range(4)])

    def test_http_session_is_reused_inside_thread(self):
        self.assertIs(store._http(), store._http())


class LazyRenderingTests(unittest.TestCase):
    def test_expensive_physical_imports_and_history_require_user_action(self):
        source = (Path(__file__).resolve().parents[1] / "streamlit_app.py").read_text("utf-8")
        self.assertIn('if st.toggle(\n            "GERENCIAR FONTES E CONTAGENS"', source)
        self.assertIn('if cb_source_active == "CHAPAS · E-MAIL":', source)
        self.assertIn('if cb_source_active == "BARRAMENTOS · EXCEL":', source)
        self.assertIn('if cb_source_active == "ALMOXARIFADO · BARRAS":', source)
        self.assertIn('if st.toggle(\n                "HISTÓRICO DE AJUSTES · MÊS A MÊS"', source)
        self.assertIn("def _refresh_fm_data()", source)
        self.assertIn("def load_cb_adjustment_history()", source)


if __name__ == "__main__":
    unittest.main()
