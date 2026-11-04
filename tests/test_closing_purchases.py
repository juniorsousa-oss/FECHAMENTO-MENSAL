"""Regressões do cálculo gerencial de baixas por variação do estoque."""
import unittest

from closing_purchases import (
    closing_write_off, purchase_classification, summarize_purchases,
)


def source_row(month="2026-10", cf="1101", tes="001", description="",
               amount="100", armazem="S2"):
    return {
        "data": month + "-10", "cf": cf, "tes": tes,
        "descricao_tes": description, "valor_entrada": amount,
        "armazem": armazem,
    }


class ClosingPurchasesTests(unittest.TestCase):
    def test_only_identified_purchases_are_summed(self):
        model = {
            "coverage_metas": [
                {"competencia": "2026-10", "armazem": "S2"},
                {"competencia": "2026-10", "armazem": "EP"},
            ],
            "rows": [
                source_row(amount="100.00"),
                source_row(cf="2102", amount="200.00", armazem="EP"),
                source_row(cf="1152", description="TRANSFERENCIA DE ARMAZEM", amount="300"),
                source_row(cf="1202", description="DEVOLUCAO DE VENDA", amount="50"),
                source_row(cf="5102", description="", amount="80"),
            ],
        }
        summary = summarize_purchases(model)["2026-10"]
        self.assertEqual(summary["compras"], 300.0)
        self.assertEqual(summary["status"], "VALIDADO")
        self.assertEqual(closing_write_off(1000.0, 850.0, summary), 450.0)

    def test_missing_warehouse_blocks_definitive_write_off(self):
        model = {
            "coverage_metas": [
                {"competencia": "2026-09", "armazem": "S2"},
                {"competencia": "2026-10", "armazem": "S2"},
                {"competencia": "2026-10", "armazem": "EP"},
            ],
            "rows": [source_row(month="2026-09", amount="20")],
        }
        september = summarize_purchases(model)["2026-09"]
        self.assertEqual(september["armazens_pendentes"], ["EP"])
        self.assertIsNone(closing_write_off(100, 90, september))

    def test_unidentified_inbound_must_be_reviewed(self):
        model = {
            "coverage_metas": [{"competencia": "2026-10", "armazem": "S2"}],
            "rows": [source_row(cf="", description="ENTRADA SEM NATUREZA", amount="80")],
        }
        october = summarize_purchases(model)["2026-10"]
        self.assertEqual(october["registros_revisar"], 1)
        self.assertEqual(october["sem_classificacao"], 80.0)
        self.assertIsNone(closing_write_off(1000, 900, october))

    def test_imports_and_tes_descriptions(self):
        self.assertEqual(purchase_classification(source_row(cf="3101.0")), "compra")
        self.assertEqual(purchase_classification(
            source_row(cf="", description="IMPORTACAO DE MATERIA PRIMA")
        ), "compra")
        self.assertEqual(purchase_classification(
            source_row(cf="1101", description="DEVOLUCAO DE COMPRA")
        ), "nao_compra")
        self.assertEqual(purchase_classification(
            source_row(cf="1152", description="TRANSFERENCIA")
        ), "nao_compra")

    def test_missing_initial_balance_and_kardex_not_zeroed(self):
        self.assertIsNone(closing_write_off(None, 900, {"compras": 80, "status": "VALIDADO"}))
        self.assertIsNone(closing_write_off(1000, 900, None))


if __name__ == "__main__":
    unittest.main()
