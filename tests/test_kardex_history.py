from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import issue_check as check
import kardex_history as history
import movement_store as store
import movements as mv
import pandas as pd
from test_movement_analysis import imported, record


def pack(rows, digest="a", start="2026-01-01", end="2026-10-21", *, replace=False):
    value = imported(rows, digest)
    value["meta"].update(periodo_inicio=start, periodo_fim=end)
    return history.prepare_import(value) if replace else value


class KardexHistoryTests(unittest.TestCase):
    def test_replacement_removes_old_rows_even_if_the_new_signature_or_quantity_changed(self):
        old = pack([record(documento="EXCLUIDO"), record(documento="CORRIGIDO", valor_saida="40"),
                    record(data="2026-09-10", documento="SETEMBRO")])
        new = pack([record(documento="CORRIGIDO", valor_saida="15")], "b", start="2026-10-01", replace=True)
        snapshot = mv.history_snapshot([old, new])
        self.assertEqual({r["documento"] for r in snapshot["rows"]}, {"CORRIGIDO", "SETEMBRO"})
        self.assertEqual(next(r for r in snapshot["rows"] if r["documento"] == "CORRIGIDO")["valor_saida"], "15")
        self.assertEqual(snapshot["registry"][0]["status"], "PARCIALMENTE SUBSTITUÍDO")
        self.assertEqual(snapshot["registry"][1]["status"], "VIGENTE")

    def test_consolidated_ep_20_e2_zip_preserves_s2_and_empty_20_months(self):
        import io
        import json
        from zipfile import ZipFile, ZIP_DEFLATED

        scopes = []
        for wh in ("EP", "20", "E2"):
            for month, first, last in (
                ("2026-01", "2026-01-01", "2026-01-31"),
                ("2026-10", "2026-10-01", "2026-10-21"),
            ):
                scopes.append({"competencia": month, "armazem": wh,
                               "periodo_inicio": first, "periodo_fim": last})
        rows = [
            record(armazem="EP", data="2026-01-08", documento="EP JAN"),
            record(armazem="20", data="2026-01-29", documento="20 JAN"),
            record(armazem="E2", data="2026-10-21", documento="E2 OUT"),
        ]
        manifest = {"formato": mv.HISTORY_FORMAT, "periodo_inicio": "2026-01-01",
                    "periodo_fim": "2026-10-21", "coberturas": scopes}
        stream = io.BytesIO()
        with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
            archive.writestr("manifesto.json", json.dumps(manifest))
            archive.writestr("movimentacoes.jsonl", "\\n".join(json.dumps(row) for row in rows) + "\\n")
        parsed = mv.parse_report(stream.getvalue(), "KARDEX_EP_20_E2.zip")
        self.assertEqual(len(parsed["rows"]), 3)
        self.assertEqual(len(parsed["meta"]["coberturas_arquivo"]), 6)
        prepared = history.prepare_import(parsed)
        self.assertEqual(prepared["meta"]["armazens"], ["20", "E2", "EP"])
        existing_s2 = pack([record(documento="S2 VIGENTE")], "s2",
                           start="2026-10-01", replace=True)
        snapshot = mv.history_snapshot([existing_s2, prepared])
        self.assertEqual({r["armazem"] for r in snapshot["rows"]},
                         {"S2", "EP", "20", "E2"})
        self.assertTrue(any(meta["armazem"] == "20" and meta["competencia"] == "2026-10"
                            and meta["lancamentos"] == 0 for meta in snapshot["coverage"]))
        self.assertTrue(any(r["documento"] == "S2 VIGENTE" for r in snapshot["rows"]))

    def test_a_second_warehouse_is_added_and_does_not_remove_the_first(self):
        s2 = pack([record(documento="S2")], start="2026-10-01", replace=True)
        s1 = pack([record(documento="S1", armazem="S1")], "b", start="2026-10-01", replace=True)
        self.assertEqual({r["armazem"] for r in mv.merge_imports([s2, s1])[0]}, {"S1", "S2"})
        s2_new = pack([record(documento="S2-NOVO")], "c", start="2026-10-01", replace=True)
        self.assertEqual({r["documento"] for r in mv.merge_imports([s2, s1, s2_new])[0]}, {"S1", "S2-NOVO"})

    def test_legacy_report_with_many_months_and_warehouses_remains_active_outside_the_replacement(self):
        old = pack([record(documento="S2-OUT"), record(armazem="S1", documento="S1-OUT"),
                    record(data="2026-09-15", documento="S2-SET"), record(data="2026-09-15", armazem="S1", documento="S1-SET")])
        new = pack([record(documento="S2-NOVO")], "b", start="2026-10-01", replace=True)
        self.assertEqual({r["documento"] for r in mv.merge_imports([old, new])[0]}, {"S2-NOVO", "S1-OUT", "S2-SET", "S1-SET"})

    def test_latest_server_timestamp_controls_the_version_independently_of_input_order(self):
        first = pack([record(documento="ANTIGO")], start="2026-10-01", replace=True)
        second = pack([record(documento="NOVO")], "b", start="2026-10-01", replace=True)
        first["_imported_at"], second["_imported_at"] = "2026-10-21T10:00:00Z", "2026-10-21T11:00:00Z"
        self.assertEqual(mv.merge_imports([second, first])[0][0]["documento"], "NOVO")
        first["_imported_at"] = "2026-10-21T12:00:00Z"
        self.assertEqual(mv.merge_imports([first, second])[0][0]["documento"], "ANTIGO")

    def test_latest_file_shorter_coverage_does_not_keep_future_rows_or_old_coverage(self):
        old = pack([record(data="2026-10-19", documento="ANTIGO")], start="2026-10-01", end="2026-10-19")
        new = pack([record(data="2026-10-10", documento="NOVO")], "b", start="2026-10-01", end="2026-10-10", replace=True)
        snapshot = mv.history_snapshot([old, new])
        self.assertEqual([r["documento"] for r in snapshot["rows"]], ["NOVO"])
        self.assertEqual(check.coverage(snapshot["coverage"], ("S2",))["fim"], "2026-10-10")
        self.assertEqual(snapshot["registry"][0]["status"], "SUBSTITUÍDO")

    def test_whole_month_is_cleared_when_a_new_multi_month_report_has_no_rows_in_it(self):
        old = pack([record(data="2026-09-10", documento="SETEMBRO")])
        new = pack([record(data="2026-08-01", documento="AGOSTO"), record(documento="OUTUBRO")], "b",
                   start="2026-08-01", replace=True)
        snapshot = mv.history_snapshot([old, new])
        self.assertEqual({r["documento"] for r in snapshot["rows"]}, {"AGOSTO", "OUTUBRO"})
        self.assertTrue(any(m["competencia"] == "2026-09" and m["lancamentos"] == 0 for m in snapshot["coverage"]))

    def test_repeated_rows_inside_the_replacement_are_kept_once_per_occurrence(self):
        row = record()
        old = pack([row])
        new = pack([row, row], "b", start="2026-10-01", replace=True)
        rows, duplicates = mv.merge_imports([old, new])
        self.assertEqual((len(rows), duplicates), (2, 0))

    def test_same_product_and_document_in_different_warehouses_are_not_deduplicated(self):
        new = pack([record(), record(armazem="S1")], start="2026-10-01", replace=True)
        self.assertEqual(len(mv.merge_imports([new])[0]), 2)

    def test_invalid_dates_and_overlapping_batch_are_rejected_before_saving(self):
        value = pack([record(data="2026-10-10")], start="2026-10-10")
        with self.assertRaisesRegex(ValueError, "primeiro dia"):
            history.prepare_import(value)
        with self.assertRaisesRegex(ValueError, "fora do período"):
            history.prepare_import(value, "2026-09-01", "2026-09-30")
        replacement = pack([record()], start="2026-10-01", replace=True)
        with self.assertRaisesRegex(ValueError, "Dois arquivos"):
            history.validate_batch([replacement, replacement])
        other = pack([record(armazem="S1")], "b", start="2026-10-01", replace=True)
        history.validate_batch([replacement, other])

    def test_prepared_file_identity_depends_on_the_extraction_coverage(self):
        source = pack([record()], start="2026-10-01")
        first = history.prepare_import(source, "2026-10-01", "2026-10-19")
        second = history.prepare_import(source, "2026-10-01", "2026-10-21")
        self.assertNotEqual(first["meta"]["import_id"], second["meta"]["import_id"])
        self.assertEqual(first["meta"]["sha256"], second["meta"]["sha256"])
        self.assertEqual(mv.unpack_import(mv.pack_import(first)), first)

    def test_backup_restores_active_scopes_and_never_reintroduces_superseded_rows(self):
        old = pack([record(data="2026-09-10", documento="SET"), record(documento="ANTIGO")])
        new = pack([record(documento="NOVO", ae_original=" OP00001234567 ")], "b", start="2026-10-01", replace=True)
        model = mv.build_model([old, new])
        restored = history.prepare_import(mv.parse_report(mv.export_history(model), "backup.zip"))
        snapshot = mv.history_snapshot([old, new, restored])
        self.assertEqual({r["documento"] for r in snapshot["rows"]}, {"SET", "NOVO"})
        self.assertEqual(next(r for r in snapshot["rows"] if r["documento"] == "NOVO")["ae_original"], " OP00001234567 ")
        self.assertEqual(check.coverage(snapshot["coverage"], ("S2",))["fim"], "2026-10-21")

    def test_backup_can_preserve_empty_month_and_real_gaps_in_a_warehouse(self):
        first = pack([record(data="2026-01-01", documento="JAN")], start="2026-01-01", end="2026-01-31")
        later = pack([record(documento="OUT")], "b", start="2026-10-01", replace=True)
        restored = history.prepare_import(mv.parse_report(mv.export_history(mv.build_model([first, later])), "backup.zip"))
        intervals = check.coverage(mv.history_snapshot([restored])["coverage"], ("S2",))["intervalos"]
        self.assertEqual(intervals, [["2026-01-01", "2026-01-31"], ["2026-10-01", "2026-10-21"]])

    def test_warehouse_coverage_uses_the_common_period_and_does_not_borrow_other_warehouses(self):
        a = pack([record()], start="2026-10-01", end="2026-10-19", replace=True)
        b = pack([record(armazem="S1")], "b", start="2026-10-01", end="2026-10-21", replace=True)
        metas = mv.history_snapshot([a, b])["coverage"]
        self.assertEqual(check.coverage(metas, ("S2",))["fim"], "2026-10-19")
        self.assertEqual(check.coverage(metas, ("S1",))["fim"], "2026-10-21")
        self.assertEqual(check.coverage(metas, ("S1", "S2"))["fim"], "2026-10-19")
        self.assertEqual(check.coverage(metas, ("S3",))["intervalos"], [])

    def test_issue_check_does_not_claim_missing_issues_when_only_another_warehouse_has_history(self):
        general = check.parse_general(pd.DataFrame([{"Projeto": "26000101001", "Código": "00001000", "Lote": "000001",
                    "Qtd. necessária": 2, "Qtd. atendida": 2, "Data de separação": "19/10/2026 08:00",
                    "Data de conferência": "20/10/2026 08:00"}]))
        stock = check.parse_stock(pd.DataFrame([{"Produto": "00001000", "Lote": "000001", "Armazem": "S2", "Endereco": "G9-PROD", "Quantidade": 0}]))
        source = pack([record(armazem="S1")], start="2026-10-01", replace=True)
        snapshot = mv.history_snapshot([source])
        result = check.reconcile(general, stock, snapshot["rows"], history_metas=snapshot["coverage"], as_of="2026-10-21")
        self.assertFalse(result["history_available"])
        self.assertIsNone(result["items"].iloc[0]["baixada"])
        self.assertTrue(result["items"].iloc[0]["historico_incompleto"])


class KardexStoreTests(unittest.TestCase):
    def setUp(self):
        self.values = {}
        self.serial = 0
        self.patches = [patch.object(store.db, "rpc", side_effect=self.rpc),
                        patch.object(store, "load_import", side_effect=self.load),
                        patch.object(store, "list_imports", side_effect=self.list)]
        for mocked in self.patches:
            mocked.start()
            self.addCleanup(mocked.stop)

    def rpc(self, name, params, timeout):
        self.assertEqual(name, "fm_salvar_configuracao")
        self.serial += 1
        self.values[params["p_chave"]] = (self.serial, params["p_valor"])

    def load(self, key):
        serial, value = self.values[key]
        return {**mv.unpack_import(value), "_key": key, "_imported_at": f"2026-10-21T10:00:{serial:02d}Z"}

    def list(self):
        return [{"chave": key, "meta": value["meta"]} for key, (_, value) in sorted(self.values.items(), key=lambda p: p[1][0])]

    def test_saving_same_active_file_is_idempotent_but_reuploading_an_old_version_reactivates_it(self):
        a = pack([record(documento="A")], start="2026-10-01", replace=True)
        b = pack([record(documento="B")], "b", start="2026-10-01", replace=True)
        first = store.save_import(a)
        self.assertTrue(first["saved"])
        self.assertFalse(store.save_import(a)["saved"])
        store.save_import(b)
        reactivated = store.save_import(a)
        self.assertTrue(reactivated["reactivated"])
        self.assertEqual(len(self.values), 2)
        self.assertEqual(mv.merge_imports([self.load(k) for k in self.values])[0][0]["documento"], "A")

    def test_failed_write_leaves_the_previous_file_active(self):
        a = pack([record(documento="A")], start="2026-10-01", replace=True)
        b = pack([record(documento="B")], "b", start="2026-10-01", replace=True)
        store.save_import(a)
        with patch.object(store.db, "rpc", side_effect=RuntimeError("conexão interrompida")):
            with self.assertRaisesRegex(RuntimeError, "interrompida"):
                store.save_import(b)
        self.assertEqual(len(self.values), 1)
        self.assertEqual(mv.merge_imports([self.load(k) for k in self.values])[0][0]["documento"], "A")

    def test_archived_payloads_are_not_loaded_but_remain_in_the_registry(self):
        a = pack([record(documento="A")], start="2026-10-01", replace=True)
        b = pack([record(documento="B")], "b", start="2026-10-01", replace=True)
        old, new = store.save_import(a), store.save_import(b)
        with patch.object(store, "load_import", side_effect=self.load) as loader:
            loaded = store.load_history(self.list())
            loader.assert_called_once_with(new["key"])
        snapshot = mv.history_snapshot(loaded)
        self.assertEqual([r["documento"] for r in snapshot["rows"]], ["B"])
        self.assertEqual(snapshot["registry"][0]["lancamentos"], 1)
        self.assertEqual(snapshot["registry"][0]["status"], "SUBSTITUÍDO")

    def test_readback_mismatch_is_reported_and_a_retry_does_not_duplicate_the_committed_file(self):
        a = pack([record(documento="A")], start="2026-10-01", replace=True)
        with patch.object(store, "load_import", return_value=pack([record()], "c")):
            with self.assertRaisesRegex(RuntimeError, "conferência"):
                store.save_import(a)
        self.assertEqual(len(self.values), 1)
        self.assertFalse(store.save_import(a)["saved"])


if __name__ == "__main__":
    unittest.main()
