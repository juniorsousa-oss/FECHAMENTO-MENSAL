from decimal import Decimal
from unittest import TestCase
from unittest.mock import patch

import pandas as pd

import issue_check_ui as issue_ui
import movement_analysis_ui as movement_ui


class QueueWarehouseTest(TestCase):
    def test_keeps_whole_op_and_requires_positive_exact_lot_when_known(self):
        frame = pd.DataFrame([
            {"op": "A", "codigo": "001", "lote": "L1", "baixada": 3},
            {"op": "A", "codigo": "005", "lote": "L5", "baixada": 1},
            {"op": "B", "codigo": "001", "lote": "L9", "baixada": 2},
            {"op": "C", "codigo": "002", "lote": "", "baixada": 4},
            {"op": "D", "codigo": "003", "lote": "L3", "baixada": 5},
            {"op": "E", "codigo": "004", "lote": "L4", "baixada": 8},
        ])
        stock = [
            {"codigo": "001", "lote": "L1", "armazem": "S2", "saldo": Decimal("5")},
            {"codigo": "001", "lote": "L9", "armazem": "E2", "saldo": Decimal("8")},
            {"codigo": "002", "lote": "L2", "armazem": "S2", "saldo": Decimal("2")},
            {"codigo": "003", "lote": "L3", "armazem": "S2", "saldo": Decimal("0")},
            {"codigo": "004", "lote": "L4", "armazem": "S2", "saldo": Decimal("-1")},
        ]
        expected = frame.loc[frame["op"].isin(["A", "C"])]
        actual = issue_ui._filter_warehouse_evidence(frame, stock, "S2")
        pd.testing.assert_frame_equal(actual, expected)
        self.assertIs(issue_ui._filter_warehouse_evidence(frame, stock, "Todos os armazéns"), frame)
        self.assertTrue(issue_ui._filter_warehouse_evidence(frame, stock, "EP").empty)


class MissingTesDetailsTest(TestCase):
    def test_does_not_render_table_until_requested_and_does_not_modify_source_rows(self):
        frame = pd.DataFrame([
            {"data": "2026-11-26", "tes": "711", "codigo": "001", "armazem": "S2",
             "documento": "D1", "ae_original": "OP 1", "descricao_tes": "NI - TES não localizada no cadastro"},
            {"data": "2026-11-27", "tes": "520", "codigo": "002", "armazem": "E2",
             "documento": "D2", "ae_original": "OP 2", "descricao_tes": "Baixa"},
        ])
        original = frame.copy(deep=True)
        with patch.object(movement_ui.st, "toggle", return_value=False), \
             patch.object(movement_ui.st, "dataframe") as display:
            movement_ui._show_missing_tes(frame, "unique")
            display.assert_not_called()
        with patch.object(movement_ui.st, "toggle", return_value=True), \
             patch.object(movement_ui.st, "dataframe") as display:
            movement_ui._show_missing_tes(frame, "unique")
            self.assertEqual(display.call_args.args[0]["TES"].tolist(), ["711"])
            self.assertEqual(display.call_args.args[0]["Documento"].tolist(), ["D1"])
        pd.testing.assert_frame_equal(frame, original)
