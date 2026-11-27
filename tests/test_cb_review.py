from __future__ import annotations

import unittest

import pandas as pd

from cb_review import (
    confirmation_key,
    effective_adjustments,
    finalization_rows,
    missing_zero_preview,
)


class ChapasReviewTest(unittest.TestCase):
    def test_zero_preview_is_explicit_and_matches_saved_adjustment(self):
        frame = pd.DataFrame([
            {"Código": "001", "Descrição": "Chapa", "Status": "SEM CONTAGEM",
             "Saldo base ajuste": 3, "Custo unitário": 2.5, "Físico": None},
            {"Código": "002", "Descrição": "Barra", "Status": "SEM CONTAGEM",
             "Saldo base ajuste": 0, "Custo unitário": 8, "Físico": None},
            {"Código": "003", "Descrição": "Outra chapa", "Status": "DIVERGÊNCIA",
             "Saldo base ajuste": 4, "Custo unitário": 2, "Físico": 3,
             "Diferença Qtd": -1, "Diferença R$": -2},
        ])
        preview = missing_zero_preview(frame)
        self.assertEqual(preview["Código"].tolist(), ["001", "002"])
        self.assertEqual(preview["Físico"].tolist(), [0, 0])
        self.assertEqual(preview["Diferença Qtd"].tolist(), [-3, 0])
        self.assertEqual(preview["Diferença R$"].tolist(), [-7.5, 0])
        self.assertTrue(frame["Físico"].isna().iloc[0])
        counted = frame[frame["Físico"].notna()]
        self.assertEqual(
            finalization_rows(counted, preview, False)["Código"].tolist(), ["003"],
        )
        register = finalization_rows(counted, preview, True)
        self.assertEqual(register["Código"].tolist(), ["003", "001"])
        shown = effective_adjustments(register).set_index("Código")
        self.assertEqual(shown.loc["001", "Diferença R$"], -7.5)
        self.assertTrue(shown.loc["001", "Contagem assumida zero"])

    def test_tolerated_difference_is_preserved_in_history_without_adjustment(self):
        counted = pd.DataFrame([{
            "Código": "001", "Status": "CONFERIDO", "Físico": 8,
            "Diferença Qtd": 0.9, "Diferença R$": 3.92,
        }])
        register = finalization_rows(counted, pd.DataFrame(), False)
        self.assertEqual(len(register), 1)
        self.assertEqual(register["Físico"].tolist(), [8])
        self.assertEqual(register["Diferença Qtd"].tolist(), [0])
        self.assertEqual(register["Diferença R$"].tolist(), [0])
        self.assertTrue(effective_adjustments(register).empty)

    def test_confirmation_does_not_survive_relevant_changes(self):
        snapshot = pd.DataFrame([{"Código": "1", "Diferença Qtd": -1}])
        approved = confirmation_key("2026-11-01", snapshot, False)
        self.assertEqual(approved, confirmation_key("2026-11-01", snapshot.copy(), False))
        self.assertNotEqual(approved, confirmation_key("2026-10-01", snapshot, False))
        self.assertNotEqual(approved, confirmation_key("2026-11-01", snapshot, True))
        snapshot.loc[0, "Diferença Qtd"] = -2
        self.assertNotEqual(approved, confirmation_key("2026-11-01", snapshot, False))
