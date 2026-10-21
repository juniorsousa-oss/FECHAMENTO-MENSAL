from __future__ import annotations

import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import inventory_db as db


class CbParallelConnectionTests(unittest.TestCase):
    def test_parallel_reads_use_explicit_credentials_not_streamlit_secrets(self):
        url, key = "https://test.supabase.co", "session-test-key"

        def reader():
            return db.supabase_url(), db.supabase_key()

        with patch.object(db, "_secret", side_effect=AssertionError("secret accessed in worker")):
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = [
                    pool.submit(db.read_with_connection, reader, url, key)
                    for _ in range(8)
                ]
                self.assertEqual([item.result() for item in futures], [(url, key)] * 8)

        self.assertIsNone(db._CONNECTION_OVERRIDE.get())

    def test_worker_connection_context_resets_after_failure(self):
        def failing():
            self.assertEqual(db.supabase_key(), "temporary")
            raise ValueError("read failed")

        with self.assertRaisesRegex(ValueError, "read failed"):
            db.read_with_connection(failing, "https://test.supabase.co", "temporary")
        self.assertIsNone(db._CONNECTION_OVERRIDE.get())


if __name__ == "__main__":
    unittest.main()
