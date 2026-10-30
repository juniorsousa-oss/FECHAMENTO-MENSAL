"""Totais e apresentação dos saldos da conferência em precisão decimal."""
from __future__ import annotations

from decimal import Decimal
import unittest

from cb_balance_math import numero_br, saldo_categoria


def normalizar(value):
    return str(value or "").strip().zfill(8)


class BalancePrecisionTests(unittest.TestCase):
    def setUp(self):
        self.catalog = {
            "00110004": {"categoria": "BARRA_COBRE"},
            "00110005": {"categoria": "BARRA_COBRE"},
            "06000005": {"categoria": "CHAPA"},
        }
        self.codes = set(self.catalog)

    def test_exact_half_millimeter_displays_same_on_both_paths(self):
        current = [
            {"codigo": "00110004", "saldo": 5000.0934},
            {"codigo": "00110005", "saldo": 70.0001},
        ]
        closing = [
            {"codigo": "00110005", "saldo": "70.000100"},
            {"codigo": "00110004", "saldo": "5000.093400"},
        ]
        a = saldo_categoria(current, "BARRA_COBRE", self.codes, self.catalog, normalizar)
        b = saldo_categoria(closing, "BARRA_COBRE", self.codes, self.catalog, normalizar)
        self.assertEqual(a, Decimal("5070.0935"))
        self.assertEqual(a, b)
        self.assertEqual(numero_br(a), "5.070,094")
        self.assertEqual(numero_br(b), "5.070,094")
        # Python float quebrava esse empate (diferença real = zero).
        self.assertEqual(numero_br(5070.0935), "5.070,094")

    def test_other_values_and_negative_balances_unchanged(self):
        rows = [
            {"codigo": "00110004", "saldo": "10.123456"},
            {"codigo": "00110005", "saldo": "-5"},
            {"codigo": "06000005", "saldo": "200"},
            {"codigo": "00000001", "saldo": "900"},
        ]
        total = saldo_categoria(rows, "BARRA_COBRE", self.codes, self.catalog, normalizar)
        self.assertEqual(total, Decimal("10.123456"))
        self.assertEqual(numero_br(total), "10,123")
        self.assertEqual(numero_br(Decimal("5.0100"), 3), "5,010")
        self.assertEqual(numero_br(-1.2345), "-1,235")
        self.assertEqual(numero_br(None), "—")

    def test_each_row_keeps_original_saldo(self):
        rows = [{"codigo": "00110004", "saldo": "5070.093500"}]
        old = rows[0]["saldo"]
        saldo_categoria(rows, "BARRA_COBRE", self.codes, self.catalog, normalizar)
        self.assertEqual(rows[0]["saldo"], old)


if __name__ == "__main__":
    unittest.main()
