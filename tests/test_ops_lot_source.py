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
         "Data de conferência": "03/10/26 08:00", "Descrição": "MATERIAL TESTE"},
        {"Projeto": OP, "Código": CODE, "Lote": LOT_B,
         "Qtd. necessária": 10, "Qtd. atendida": 10,
         "Data de separação": "02/10/26 08:00",
         "Data de conferência": "03/10/26 08:00", "Descrição": "MATERIAL TESTE"},
    ]))


def ops_record(lot=LOT_A, qty="1", day="2026-10-05", code=CODE, op=OP):
    return {"op": op, "codigo": code, "lote": lot, "data": day,
            "tipo_movimento": "RE0", "tes": "550", "quantidade": qty,
            "documento": "DOC", "linha_origem": 3}


class OpsSourceTests(unittest.TestCase):
    def test_reader_captures_lots_and_does_not_count_produced_or_transferred(self):
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
        self.assertEqual(parsed["meta"]["movimentos_validos"], 5)
        self.assertEqual(parsed["meta"]["outros_movimentos_ignorados"], 2)
        self.assertEqual(parsed["meta"]["movimentos_sem_lote"], 1)
        self.assertEqual(len(parsed["rows"]), 5)
        day = (date(1899, 12, 30) + timedelta(days=46220)).isoformat()
        self.assertEqual(
            sum(Decimal(r["quantidade"]) for r in parsed["rows"]
                if r["codigo"] == CODE and r["lote"] == LOT_A), Decimal("7"))
        self.assertEqual(next(r for r in parsed["rows"] if r["data"] == day)["lote"], LOT_A)
        self.assertEqual(src._unpack(src._pack(parsed)), parsed)

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
        # Lot A: 5+3-1=7; lot B: 4 -> 9 remaining.
        self.assertEqual(product.baixada, Decimal("11"))
        self.assertEqual(product.pendente, Decimal("9"))
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
        self.assertEqual(final["items"].iloc[0].qtd_faltante_operacional, Decimal("9"))
        self.assertEqual(final["items"].iloc[0].status, stages.BAIXA_LOTE_DIVERGENTE)
        self.assertTrue(final["items"].iloc[0].divergente)

    def test_same_quantity_wrong_lot_must_remain_pending(self):
        model = issue_check.reconcile_ops(
            general_rows(), [],
            [ops_record(lot=LOT_A, qty="10"),
             ops_record(lot=LOT_C, qty="10")],
            ops_meta=META, as_of="2026-11-03")
        product = model["items"].iloc[0]
        self.assertEqual(product.baixada, Decimal("10"))
        self.assertEqual(product.pendente, Decimal("10"))
        self.assertEqual(stages.apply(model)["items"].iloc[0].status,
                         stages.BAIXA_LOTE_DIVERGENTE)

    def test_missing_mes_lot_is_not_misreported_as_wrong_consumed_lot(self):
        general = issue_check.parse_general(pd.DataFrame([{
            "Projeto": OP, "Código": CODE, "Lote": "",
            "Qtd. necessária": 10, "Qtd. atendida": 10,
            "Data de separação": "02/10/26 08:00",
            "Data de conferência": "03/10/26 08:00",
            "Descrição": "MATERIAL SEM LOTE NO GERAL",
        }]))
        model = issue_check.reconcile_ops(
            general, [], [ops_record(lot=LOT_A, qty="10")],
            ops_meta=META, as_of="2026-11-03")
        item = model["items"].iloc[0]
        self.assertTrue(item.lote_nao_informado_geral)
        self.assertEqual(item.baixada, Decimal("0"))
        self.assertEqual(item.pendente, Decimal("10"))
        resolved = stages.apply(model)["items"].iloc[0]
        self.assertEqual(resolved.status, stages.LOTE_AUSENTE_GERAL)

    def test_missing_ops_lot_is_not_misreported_as_wrong_consumed_lot(self):
        model = issue_check.reconcile_ops(
            general_rows(), [], [ops_record(lot="", qty="10")],
            ops_meta=META, as_of="2026-11-03")
        item = stages.apply(model)["items"].iloc[0]
        self.assertEqual(item.status, stages.LOTE_AUSENTE_OPS)
        self.assertEqual(item.pendente, Decimal("20"))
        self.assertEqual(item.baixa_sem_lote, Decimal("10"))

    def test_missing_source_does_not_turn_unknown_issue_into_zero(self):
        model = issue_check.reconcile_ops(
            general_rows(), [], [], ops_meta=None, as_of="2026-11-03")
        self.assertFalse(model["history_available"])
        self.assertIsNone(model["items"].iloc[0].baixada)
        self.assertIsNone(model["items"].iloc[0].pendente)

    def test_no_duplicate_when_same_file_is_reimported(self):
        parsed = src.parse(xltx_bytes([line()]), "ops.xlsx")
        old = {**parsed["meta"], "atualizado_em": "2026-11-03T15:00:00Z"}
        with patch.object(src.db, "rpc") as rpc:
            result = src.save(parsed, current=old)
        self.assertFalse(result["saved"])
        rpc.assert_not_called()

    def test_partial_new_export_cannot_replace_previous_complete_history(self):
        parsed = src.parse(xltx_bytes([line()]), "ops.xlsx")
        meta = parsed["meta"]
        older = {
            "sha256": "outro-arquivo", "periodo_inicio": "2014-01-01",
            "periodo_fim": meta["periodo_fim"],
        }
        with patch.object(src.db, "rpc") as rpc:
            with self.assertRaisesRegex(ValueError, "histórico completo"):
                src.save(parsed, current=older)
        rpc.assert_not_called()

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
