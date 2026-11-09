"""Regressões da nova fonte OPS, agregação por OP/produto/lote e histórico.

São usados somente dados sintéticos: nenhuma movimentação real é gravada.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
import unittest
from unittest.mock import patch

import pandas as pd
from openpyxl import Workbook

import issue_check
import ops_lot_source as src
import operational_status as stages


OP = "26000101001"
CODE = "00001000"
LOT_A = "000123"
LOT_B = "000124"
LOT_C = "000125"
META = {"arquivo_nome": "OPS.xltx", "periodo_inicio": "2026-01-01",
        "periodo_fim": "2026-11-03", "movimentos_validos": 5}


def xltx_bytes(rows):
    wb = Workbook()
    sh = wb.active
    sh.append(["Ordens de Produção"])
    sh.append([
        "Centro Custo", "Ord Producao", "Tipo RE/DE", "Produto",
        "Descricao", "Quantidade", "UM", "Custo Unitario", "Custo",
        "Documento", "DT Emissao", "Custo Stand.", "TotalSTD",
        "Lote", "TP Movimento", "Custo",
    ])
    for row in rows:
        sh.append(row)
    out = BytesIO()
    wb.save(out)
    wb.close()
    return out.getvalue()


def line(op=OP, code=CODE, kind="RE0", qty=1, day=46300, lot=LOT_A, tes="550"):
    # Data serializada no formato Excel (igual ao OPS fornecido).
    return [600101, op, kind, code, "MATERIAL", qty, "UN", 0, 0,
            "DOC-01", day, 0, 0, lot, tes, 0]


def general_rows():
    return issue_check.parse_general(pd.DataFrame([
        {"Projeto": OP, "Código": CODE, "Lote": LOT_A,
         "Qtd. necessária": 10, "Qtd. atendida": 10,
         "Data de separação": "02/10/26 08:00",
         "Data de conferência": "03/10/26 08:00",
         "Resp. Conferencia": "CONFERENTE", "Descrição": "MATERIAL TESTE"},
        {"Projeto": OP, "Código": CODE, "Lote": LOT_B,
         "Qtd. necessária": 10, "Qtd. atendida": 10,
         "Data de separação": "02/10/26 08:00",
         "Data de conferência": "03/10/26 08:00",
         "Resp. Conferencia": "CONFERENTE", "Descrição": "MATERIAL TESTE"},
    ]))


def ops_record(lot=LOT_A, qty="1", day="2026-10-05", code=CODE, op=OP):
    return {"op": op, "codigo": code, "lote": lot, "data": day,
            "tipo_movimento": "RE0", "tes": "550", "quantidade": qty,
            "documento": "DOC", "linha_origem": 3}


class OpsSourceTests(unittest.TestCase):
    def test_new_header_aliases_and_reordered_columns_are_recognized_safely(self):
        wb = Workbook()
        sh = wb.active
        sh.title = "Novas OPS"
        # Exportação modificada: cabeçalhos com nomes alternativos e
        # todas as colunas deslocadas uma posição, mantendo RE/DE e TES.
        sh.append(["Relatório de Produção OPS"])
        cols = [
            "Centro Custo", "Ordem de Produção", "Tipo Movimento",
            "Código Produto", "Descricao", "Qtd Movimentada", "UM",
            "Custo Unitario", "Custo", "Documento",
            "Data Movimento", "Custo Stand.", "TotalSTD",
            "Número Lote", "TES", "Custo",
        ]
        sh.append(["Adicional"] + cols)
        sh.append(["IGNORAR"] + line(op="26017801001", code="06050080",
                                    kind="RE1", tes="999", qty=16,
                                    lot="000000000", day=46315))
        sh.append(["IGNORAR"] + line(op="26017801001", code="06050080",
                                    kind="RE0", tes="550", qty=2,
                                    lot="000000000", day=46316))
        out = BytesIO()
        wb.save(out)
        wb.close()
        parsed = src.parse(out.getvalue(), "OPS.xltx")
        self.assertEqual(parsed["meta"]["movimentos_validos"], 2)
        self.assertEqual(parsed["meta"]["re1_999_reconhecidos"], 1)
        self.assertEqual(sum(Decimal(x["quantidade"]) for x in parsed["rows"]),
                         Decimal("18"))
        self.assertEqual(parsed["meta"]["mapeamento_colunas"]["Novas OPS"]["op"], "C")
        self.assertEqual(parsed["meta"]["mapeamento_colunas"]["Novas OPS"]["codigo"], "E")
        self.assertEqual(parsed["meta"]["mapeamento_colunas"]["Novas OPS"]["quantidade"], "G")
        self.assertEqual(parsed["meta"]["mapeamento_colunas"]["Novas OPS"]["data"], "L")
        self.assertEqual(parsed["meta"]["mapeamento_colunas"]["Novas OPS"]["lote"], "O")
        self.assertEqual(parsed["meta"]["mapeamento_colunas"]["Novas OPS"]["tes"], "P")
        self.assertEqual(parsed["meta"]["versao"], src.VERSION)

    def test_old_format_still_works_without_changing_classification_version(self):
        parsed = src.parse(xltx_bytes([line(kind="RE1", tes="999", qty=16)]),
                           "OPS.xltx")
        self.assertEqual(parsed["meta"]["mapeamento_colunas"]["Sheet"]["op"], "B")
        self.assertEqual(parsed["meta"]["mapeamento_colunas"]["Sheet"]["codigo"], "D")
        self.assertEqual(parsed["meta"]["mapeamento_colunas"]["Sheet"]["quantidade"], "F")
        self.assertEqual(parsed["meta"]["mapeamento_colunas"]["Sheet"]["data"], "K")
        self.assertEqual(parsed["meta"]["mapeamento_colunas"]["Sheet"]["lote"], "N")
        self.assertEqual(parsed["meta"]["versao"], src.VERSION)

    def test_missing_tes_or_re_de_must_never_fabricate_baixa(self):
        wb = Workbook()
        sh = wb.active
        sh.append(["OP", "Produto", "Quantidade", "Data baixa", "Lote"])
        sh.append([OP, CODE, 16, "20/10/2026", LOT_A])
        out = BytesIO()
        wb.save(out)
        wb.close()
        with self.assertRaisesRegex(ValueError, "Necessário identificar OP"):
            src.parse(out.getvalue(), "OPS.xlsx")

    def test_incompatible_header_reports_readable_column_sample(self):
        wb = Workbook()
        sh = wb.active
        sh.title = "Base"
        sh.append(["Centro", "Ordem de Produção", "Tipo RE/DE",
                   "Produto", "Descrição", "Saldo", "Un", "Custo",
                   "Total", "Doc", "DT Emissão", "outro", "outro",
                   "Lote", "TP Movimento"])
        out = BytesIO()
        wb.save(out)
        wb.close()
        with self.assertRaisesRegex(ValueError, "Saldo"):
            src.parse(out.getvalue(), "OPS.xltx")

    def test_partial_interval_preserves_old_movements_even_when_file_is_smaller(self):
        recent = src.parse(xltx_bytes([line(kind="RE1", tes="999", qty=16)]),
                           "OPS.xltx")
        old = src.parse(xltx_bytes([
            line(kind="RE0", tes="550", qty=5, day=42000),
            line(kind="RE0", tes="550", qty=8, day=46300),
            line(kind="RE0", tes="550", qty=6, day=46301),
        ]), "OPS-HISTORICO.xltx")
        plan = src.plan_period_replace(recent, old)
        summary = plan["impact"]
        # O arquivo novo cobre apenas o dia 46300 por exemplo: linha de
        # 2014 e o dia seguinte permanecem na fotografia final.
        self.assertEqual(summary["historico_anterior"], 3)
        self.assertEqual(summary["preservados"], 2)
        self.assertEqual(summary["substituidos"], 1)
        self.assertEqual(summary["novos"], 1)
        self.assertEqual(summary["apos_substituicao"], 3)
        records = plan["candidate"]["rows"]
        days = {r["data"] for r in records}
        self.assertEqual(len(days), 3)
        self.assertEqual(sum(Decimal(r["quantidade"]) for r in records
                             if r["data"] == recent["meta"]["periodo_inicio"]),
                         Decimal("16"))

    def test_op_snapshot_replaces_only_selected_ops_across_all_dates(self):
        """Relatório filtrado por OP não deve somar fotografias antigas."""
        other_op = "26000101002"
        old = src.parse(xltx_bytes([
            line(op=OP, code=CODE, qty=2, kind="RE0", tes="550", day=46300),
            line(op=OP, code=CODE, qty=2, kind="RE1", tes="999", day=46301),
            line(op=other_op, code=CODE, qty=7, day=46295),
        ]), "historico.xlsx")
        fresh = src.parse(xltx_bytes([
            line(op=OP, code=CODE, qty=2, kind="RE1", tes="999", day=46332),
        ]), "op-completa.xlsx")
        plan = src.plan_period_replace(fresh, old, replace_mode="op")
        impact = plan["impact"]
        self.assertEqual(impact["modo_substituicao"], "op")
        self.assertEqual(impact["ops_afetadas"], 1)
        self.assertEqual(impact["preservados"], 1)
        self.assertEqual(impact["substituidos"], 2)
        self.assertEqual(impact["novos"], 1)
        self.assertEqual(impact["apos_substituicao"], 2)
        self.assertEqual(
            plan["candidate"]["meta"]["politica"],
            "SUBSTITUIR_OPS_DO_ARQUIVO",
        )
        rows = plan["candidate"]["rows"]
        self.assertEqual(
            sum(Decimal(r["quantidade"]) for r in rows if r["op"] == OP),
            Decimal("2"),
        )
        self.assertEqual(
            sum(Decimal(r["quantidade"]) for r in rows if r["op"] == other_op),
            Decimal("7"),
        )
        again = src.plan_period_replace(
            fresh, plan["candidate"], replace_mode="op",
        )
        self.assertFalse(again["impact"]["alterou"])

    def test_unknown_ops_replace_mode_cannot_change_existing_history(self):
        old = src.parse(xltx_bytes([line()]), "old.xlsx")
        fresh = src.parse(xltx_bytes([line(qty=2)]), "fresh.xlsx")
        with self.assertRaisesRegex(ValueError, "Modo de substituição OPS"):
            src.plan_period_replace(fresh, old, replace_mode="unknown")

    def test_parser_cache_version_is_distinct_from_saved_classification(self):
        import issue_check_ui as ui
        raw = xltx_bytes([line(kind="RE1", tes="999", qty=16)])
        parsed = ui._parse_ops_upload(raw, "OPS.xltx", src.VERSION,
                                      src.PARSER_VERSION)
        self.assertEqual(parsed["meta"]["versao"], src.VERSION)
        with self.assertRaisesRegex(RuntimeError, "Versão do leitor OPS"):
            ui._parse_ops_upload(raw, "OPS.xltx", src.VERSION, "OLD-PARSER")

    def test_reader_captures_lots_and_counts_re1_999_without_production(self):
        raw = xltx_bytes([
            line(qty=5, day=46220),
            line(qty=3, day=46221),
            line(qty=4, day=46222, lot=LOT_B, kind="RE6"),
            line(qty=1, day=46221, lot=LOT_C, kind="RE1", tes="999"),
            line(qty=2, day=46221, lot=LOT_C, kind="PR0", tes="010"),
            line(qty=-1, day=46221, lot=LOT_A, kind="DE0", tes="020"),
            line(qty=2, day=46222, lot="", kind="RE0"),
        ])
        parsed = src.parse(raw, "OPS.xltx")
        self.assertEqual(parsed["meta"]["movimentos_validos"], 6)
        self.assertEqual(parsed["meta"]["outros_movimentos_ignorados"], 1)
        self.assertEqual(parsed["meta"]["re1_999_reconhecidos"], 1)
        self.assertEqual(parsed["meta"]["movimentos_sem_lote"], 1)
        self.assertEqual(len(parsed["rows"]), 6)
        day = (date(1899, 12, 30) + timedelta(days=46220)).isoformat()
        self.assertEqual(
            sum(Decimal(r["quantidade"]) for r in parsed["rows"]
                if r["codigo"] == CODE and r["lote"] == LOT_A), Decimal("7"))
        self.assertEqual(next(r for r in parsed["rows"] if r["data"] == day)["lote"], LOT_A)
        self.assertEqual(src._unpack(src._pack(parsed)), parsed)

    def test_regression_nf_2026_10_20_re1_999_op_26017801001(self):
        """Exatamente a chave e a data demonstradas pelo usuário (dados sintéticos)."""
        op = "26017801001"
        code = "06050080"
        lote = "000000000"
        excel_row = line(op=op, code=code, kind="RE1", tes="999",
                         qty=16, lot=lote, day=46315)
        raw = xltx_bytes([
            excel_row,
            line(op=op, code=code, kind="PR0", tes="010",
                 qty=16, lot=lote, day=46315),
        ])
        parsed = src.parse(raw, "OPS.xltx")
        self.assertEqual(parsed["meta"]["movimentos_validos"], 1)
        self.assertEqual(parsed["meta"]["re1_999_reconhecidos"], 1)
        self.assertEqual(parsed["meta"]["outros_movimentos_ignorados"], 1)
        self.assertEqual(parsed["rows"][0]["op"], op)
        self.assertEqual(parsed["rows"][0]["codigo"], code)
        self.assertEqual(parsed["rows"][0]["lote"], lote)
        self.assertEqual(parsed["rows"][0]["data"], "2026-10-20")
        self.assertEqual(parsed["rows"][0]["quantidade"], "16")
        geral = issue_check.parse_general(pd.DataFrame([{
            "Projeto": op, "Código": code, "Lote": lote,
            "Qtd. necessária": 16, "Qtd. atendida": 16,
            "Data de separação": "19/10/26 08:00",
            "Data de conferência": "20/10/26 10:00",
            "Resp. Conferencia": "CONFERENTE",
            "Descrição": "PUXADOR PLANO GRANDE 168X28 MM PRETO",
        }]))
        model = issue_check.reconcile_ops(
            geral, [], parsed["rows"],
            ops_meta=parsed["meta"], as_of="2026-10-30")
        item = stages.apply(model)["items"].iloc[0]
        self.assertEqual(item.baixada, Decimal("16"))
        self.assertEqual(item.pendente, Decimal("0"))
        self.assertEqual(item.status, stages.PRODUTO_CONSUMIDO)
        self.assertFalse(item.divergente)

    def test_outdated_stored_source_is_blocked_without_modifying_history(self):
        parsed = src.parse(xltx_bytes([line(kind="RE1", tes="999", qty=16)]),
                           "OPS.xltx")
        stale_snapshot = {
            "meta": {**parsed["meta"], "versao": "2026-11-03.1"},
            "rows": parsed["rows"],
        }
        with patch.object(src, "load", return_value=stale_snapshot), \
             patch.object(src.db, "rpc") as rpc:
            with self.assertRaisesRegex(ValueError, "incompatível"):
                src.save(parsed)
        rpc.assert_not_called()

    def test_outdated_cached_parse_cannot_be_saved_or_falsely_reported_current(self):
        parsed = src.parse(xltx_bytes([
            line(kind="RE1", tes="999", qty=16)
        ]), "OPS.xltx")
        stale = {
            **parsed,
            "meta": {**parsed["meta"], "versao": "2026-11-03.1"}
        }
        with patch.object(src, "load", return_value={}), \
             patch.object(src.db, "rpc") as rpc:
            with self.assertRaisesRegex(ValueError, "desatualizadas"):
                src.save(stale)
        rpc.assert_not_called()

    def test_period_replace_writes_backup_before_current_and_verifies_sha(self):
        before = src.parse(xltx_bytes([
            line(kind="RE0", tes="550", qty=4, day=42000),
            line(kind="RE0", tes="550", qty=3, day=46300),
        ]), "base.xlsx")
        parsed = src.parse(xltx_bytes([
            line(kind="RE1", tes="999", qty=16, day=46300),
        ]), "novo.xlsx")
        candidate = src.plan_period_replace(parsed, before)["candidate"]
        with patch.object(src, "load", return_value=before), \
             patch.object(src, "read_meta", side_effect=[
                 before["meta"], candidate["meta"]
             ]), \
             patch.object(src.db, "rpc") as rpc:
            result = src.save(parsed, expected_previous_sha=before["meta"]["sha256"])
        self.assertTrue(result["saved"])
        self.assertEqual(rpc.call_count, 2)
        self.assertEqual(rpc.call_args_list[0].args[1]["p_chave"], src.BACKUP_KEY)
        self.assertEqual(rpc.call_args_list[1].args[1]["p_chave"], src.KEY)
        self.assertEqual(result["meta"]["sha256"], candidate["meta"]["sha256"])

    def test_concurrent_change_aborts_without_backups_or_new_writes(self):
        parsed = src.parse(xltx_bytes([
            line(kind="RE1", tes="999", qty=16, day=46300),
        ]), "novo.xlsx")
        before = src.parse(xltx_bytes([
            line(kind="RE0", tes="550", qty=3, day=46299),
        ]), "base.xlsx")
        with patch.object(src, "load", return_value=before), \
             patch.object(src.db, "rpc") as rpc:
            with self.assertRaisesRegex(RuntimeError, "mudou desde a prévia"):
                src.save(parsed, expected_previous_sha="stale-token")
        rpc.assert_not_called()

    def test_existing_snapshot_can_be_reimported_idempotently(self):
        parsed = src.parse(xltx_bytes([line(kind="RE1", tes="999", qty=16)]),
                           "OPS.xltx")
        with patch.object(src, "load", return_value=parsed), \
             patch.object(src.db, "rpc") as rpc:
            result = src.save(parsed)
        self.assertFalse(result["saved"])
        rpc.assert_not_called()

    def test_ui_cache_key_includes_processing_rules_version(self):
        import inspect
        import issue_check_ui as ui
        signature = inspect.signature(ui._parse_ops_upload)
        self.assertIn("rules_version", signature.parameters)
        raw = xltx_bytes([line(kind="RE1", tes="999", qty=16)])
        with self.assertRaisesRegex(RuntimeError, "Versão das regras OPS divergente"):
            ui._parse_ops_upload(raw, "OPS.xltx", "2026-11-03.1")
        accepted = ui._parse_ops_upload(raw, "OPS.xltx", src.VERSION)
        self.assertEqual(accepted["meta"]["versao"], src.VERSION)
        self.assertEqual(accepted["meta"]["re1_999_reconhecidos"], 1)

    def test_multiple_days_same_op_product_lot_are_added_without_cross_lot_credit(self):
        general = general_rows()
        records = [
            ops_record(qty="5", day="2026-10-04"),
            ops_record(qty="3", day="2026-10-05"),
            ops_record(qty="-1", day="2026-10-06"),
            ops_record(lot=LOT_B, qty="4", day="2026-10-07"),
            ops_record(lot=LOT_C, qty="6", day="2026-10-08"),
            ops_record(lot="", qty="2", day="2026-10-08"),
            ops_record(lot=LOT_A, qty="99", day="2026-11-04"),
        ]
        model = issue_check.reconcile_ops(
            general, [], records, ops_meta=META, as_of="2026-11-03")
        product = model["items"].iloc[0]
        # 7 do lote A + 4 do B + 6 de C + 2 sem lote = 19,
        # frente a 20 conferidas. Há 1 baixa pendente no produto,
        # com 9 unidades distribuídas incorretamente entre lotes.
        self.assertEqual(product.baixada, Decimal("19"))
        self.assertEqual(product.pendente, Decimal("1"))
        self.assertEqual(product.pendente_lotes, Decimal("9"))
        self.assertEqual(product.baixa_outros_lotes, Decimal("6"))
        self.assertEqual(product.baixa_sem_lote, Decimal("2"))
        self.assertEqual(product.lotes_baixados_divergentes, LOT_C)
        self.assertEqual(model["movimentos_apos_base"], 1)
        lots = model["lots"].set_index("lote")
        self.assertEqual(lots.loc[LOT_A, "pendente"], Decimal("3"))
        self.assertEqual(lots.loc[LOT_B, "pendente"], Decimal("6"))
        self.assertEqual(lots.loc[LOT_A, "pendente_minima"], Decimal("3"))
        self.assertEqual(lots.loc[LOT_B, "pendente_maxima"], Decimal("6"))
        final = stages.apply(model)
        self.assertEqual(final["items"].iloc[0].qtd_faltante_operacional, Decimal("1"))
        self.assertEqual(final["items"].iloc[0].status, stages.BAIXA_LOTE_DIVERGENTE)
        self.assertTrue(final["items"].iloc[0].divergente)

    def test_project_lot_swap_2_vs_3_keeps_total_pending_zero(self):
        source = issue_check.parse_general(pd.DataFrame([
            {"Projeto": OP, "Código": CODE, "Lote": LOT_A,
             "Qtd. necessária": 2, "Qtd. atendida": 2,
             "Data de separação": "02/10/26 08:00",
             "Data de conferência": "03/10/26 08:00",
             "Resp. Conferencia": "CONFERENTE"},
            {"Projeto": OP, "Código": CODE, "Lote": LOT_B,
             "Qtd. necessária": 3, "Qtd. atendida": 3,
             "Data de separação": "02/10/26 08:00",
             "Data de conferência": "03/10/26 08:00",
             "Resp. Conferencia": "CONFERENTE"},
        ]))
        snapshot = issue_check.reconcile_ops(
            source, [],
            [ops_record(lot=LOT_A, qty="3"),
             ops_record(lot=LOT_B, qty="2")],
            ops_meta=META, as_of="2026-11-03")
        item = snapshot["items"].iloc[0]
        self.assertEqual((item.conferida, item.baixada, item.pendente),
                         (Decimal("5"), Decimal("5"), Decimal("0")))
        self.assertEqual(item.pendente_lotes, Decimal("1"))
        self.assertEqual(item.excesso_lotes, Decimal("1"))
        self.assertIn(LOT_A, item.divergencia_lotes)
        self.assertIn(LOT_B, item.divergencia_lotes)
        lot = snapshot["lots"].set_index("lote")
        self.assertEqual(lot.loc[LOT_A, "excesso"], Decimal("1"))
        self.assertEqual(lot.loc[LOT_B, "pendente"], Decimal("1"))
        final = stages.apply(snapshot)
        self.assertEqual(final["items"].iloc[0].qtd_faltante_operacional,
                         Decimal("0"))
        self.assertEqual(final["items"].iloc[0].status,
                         stages.BAIXA_LOTE_DIVERGENTE)
        self.assertTrue(final["items"].iloc[0].divergente)
        import reports
        rows = reports.issue_rows(final)
        # OP + produto + LOTE é a chave visual/exportada: duas linhas,
        # preservando baixas 3/2, conferidas 2/3 e pendência total zero.
        self.assertEqual(len(rows), 2)
        self.assertEqual({r[14] for r in rows}, {LOT_A, LOT_B})
        self.assertEqual(sum(r[17] for r in rows), Decimal("5"))
        self.assertEqual(sum(r[18] for r in rows), Decimal("5"))
        self.assertEqual(sum(r[19] for r in rows), Decimal("0"))
        self.assertTrue(all("BAIXA A" in r[-1] for r in rows))

    def test_same_total_wrong_lot_is_divergence_not_unpaid_quantity(self):
        model = issue_check.reconcile_ops(
            general_rows(), [],
            [ops_record(lot=LOT_A, qty="10"),
             ops_record(lot=LOT_C, qty="10")],
            ops_meta=META, as_of="2026-11-03")
        product = model["items"].iloc[0]
        self.assertEqual(product.baixada, Decimal("20"))
        self.assertEqual(product.pendente, Decimal("0"))
        self.assertEqual(product.pendente_lotes, Decimal("10"))
        self.assertEqual(stages.apply(model)["items"].iloc[0].status,
                         stages.BAIXA_LOTE_DIVERGENTE)

    def test_missing_mes_lot_is_not_misreported_as_wrong_consumed_lot(self):
        general = issue_check.parse_general(pd.DataFrame([{
            "Projeto": OP, "Código": CODE, "Lote": "",
            "Qtd. necessária": 10, "Qtd. atendida": 10,
            "Data de separação": "02/10/26 08:00",
            "Data de conferência": "03/10/26 08:00",
            "Resp. Conferencia": "CONFERENTE",
            "Descrição": "MATERIAL SEM LOTE NO GERAL",
        }]))
        model = issue_check.reconcile_ops(
            general, [], [ops_record(lot=LOT_A, qty="10")],
            ops_meta=META, as_of="2026-11-03")
        item = model["items"].iloc[0]
        self.assertTrue(item.lote_nao_informado_geral)
        self.assertEqual(item.baixada, Decimal("10"))
        self.assertEqual(item.pendente, Decimal("0"))
        resolved = stages.apply(model)["items"].iloc[0]
        self.assertEqual(resolved.status, stages.LOTE_AUSENTE_GERAL)

    def test_missing_ops_lot_is_not_misreported_as_wrong_consumed_lot(self):
        model = issue_check.reconcile_ops(
            general_rows(), [], [ops_record(lot="", qty="10")],
            ops_meta=META, as_of="2026-11-03")
        item = stages.apply(model)["items"].iloc[0]
        self.assertEqual(item.status, stages.LOTE_AUSENTE_OPS)
        self.assertEqual(item.pendente, Decimal("10"))
        self.assertEqual(item.baixa_sem_lote, Decimal("10"))

    def test_missing_source_does_not_turn_unknown_issue_into_zero(self):
        model = issue_check.reconcile_ops(
            general_rows(), [], [], ops_meta=None, as_of="2026-11-03")
        self.assertFalse(model["history_available"])
        self.assertIsNone(model["items"].iloc[0].baixada)
        self.assertIsNone(model["items"].iloc[0].pendente)

    def test_no_duplicate_when_same_file_is_reimported(self):
        parsed = src.parse(xltx_bytes([line()]), "ops.xlsx")
        with patch.object(src, "load", return_value=parsed), \
             patch.object(src.db, "rpc") as rpc:
            result = src.save(parsed)
        self.assertFalse(result["saved"])
        rpc.assert_not_called()

    def test_partial_new_export_replaces_only_covered_day_and_is_idempotent(self):
        original = src.parse(xltx_bytes([
            line(kind="RE0", tes="550", qty=10, day=42000),
            line(kind="RE0", tes="550", qty=3, day=46300),
            line(kind="RE0", tes="550", qty=5, day=46301),
        ]), "original.xlsx")
        new = src.parse(xltx_bytes([
            line(kind="RE1", tes="999", qty=16, day=46300),
        ]), "OPS.xltx")
        first = src.plan_period_replace(new, original)
        self.assertEqual(first["impact"]["preservados"], 2)
        self.assertEqual(first["impact"]["substituidos"], 1)
        self.assertEqual(first["impact"]["novos"], 1)
        second = src.plan_period_replace(new, first["candidate"])
        self.assertFalse(second["impact"]["alterou"])
        self.assertEqual(second["impact"]["apos_substituicao"], 3)
        self.assertEqual(
            src._rows_hash(first["candidate"]["rows"]),
            src._rows_hash(second["candidate"]["rows"]),
        )

    def test_partial_month_overlap_erases_only_days_in_new_file_window(self):
        old = src.parse(xltx_bytes([
            line(kind="RE0", tes="550", qty=1, day=46299),
            line(kind="RE0", tes="550", qty=2, day=46300),
            line(kind="RE0", tes="550", qty=3, day=46301),
            line(kind="RE0", tes="550", qty=4, day=46302),
            line(kind="RE0", tes="550", qty=5, day=46303),
        ]), "old.xlsx")
        new = src.parse(xltx_bytes([
            line(kind="RE1", tes="999", qty=7, day=46300),
            line(kind="RE1", tes="999", qty=8, day=46302),
        ]), "new.xlsx")
        final = src.plan_period_replace(new, old)
        self.assertEqual(final["impact"]["preservados"], 2)
        self.assertEqual(final["impact"]["substituidos"], 3)
        self.assertEqual(final["impact"]["novos"], 2)
        records = final["candidate"]["rows"]
        self.assertEqual(len(records), 4)
        self.assertEqual({r["data"] for r in records}, {
            old["rows"][0]["data"], new["rows"][0]["data"],
            new["rows"][1]["data"], old["rows"][-1]["data"],
        })
        self.assertEqual(final["candidate"]["meta"]["politica"],
                         "SUBSTITUIR_SOMENTE_PERIODO_INCLUSIVO")

    def test_old_snapshot_not_replaced_when_backup_fails(self):
        before = src.parse(xltx_bytes([
            line(kind="RE0", tes="550", qty=4, day=42000),
        ]), "before.xlsx")
        parsed = src.parse(xltx_bytes([
            line(kind="RE1", tes="999", qty=16, day=46300),
        ]), "new.xlsx")
        with patch.object(src, "load", return_value=before), \
             patch.object(src.db, "rpc", side_effect=RuntimeError("backup falhou")) as rpc:
            with self.assertRaisesRegex(RuntimeError, "backup falhou"):
                src.save(parsed)
        self.assertEqual(rpc.call_count, 1)
        self.assertEqual(rpc.call_args.args[1]["p_chave"], src.BACKUP_KEY)

    def test_invalid_negative_request_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "quantidade negativa"):
            src.parse(xltx_bytes([line(qty=-4)]), "ops.xlsx")

    def test_identifiers_keep_leading_zeroes(self):
        parsed = src.parse(xltx_bytes([
            line(op="00019101001", code="00060006", lot="0000000001", qty=2)
        ]), "OPS.xltx")
        self.assertEqual(parsed["rows"][0]["op"], "00019101001")
        self.assertEqual(parsed["rows"][0]["codigo"], "00060006")
        self.assertEqual(parsed["rows"][0]["lote"], "0000000001")


if __name__ == "__main__":
    unittest.main()
