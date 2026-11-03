"""Regressões de contagem de barramentos por Código/Modelo/Total.

O modelo de outubro é sintetizado em memória; nenhuma planilha real ou
registro de estoque é publicado no repositório ou alterado em produção.
"""
from __future__ import annotations

from io import BytesIO
import unittest

from openpyxl import Workbook

from cb_parser import parse_barramentos_excel


def workbook_bytes(rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Plan1"
    for row in rows:
        ws.append(row)
    stream = BytesIO()
    wb.save(stream)
    wb.close()
    return stream.getvalue()


class BarramentosFormatsTests(unittest.TestCase):
    def test_outubro_2026_codigo_modelo_total_with_blank_first_row(self):
        raw = workbook_bytes([
            ["FECHAMENTO", None, None],
            ["Código", "Modelo de Barra", "Total "],
            [110004, "1/2X1/4", 4],
            [110158, "20X5", 23.155],
            [110061, "50x10", 91.898],
            [110001, "1/4X1/8", 0],
        ])
        result = parse_barramentos_excel(raw, "contagem fechamento outubro.xlsx")
        self.assertEqual(result["total_rows"], 4)
        self.assertEqual(result["criterio"], "TOTAL · MODELO DE BARRA")
        self.assertFalse(result["consumo_disponivel"])
        by_code = {entry["codigo"]: entry for entry in result["rows"]}
        self.assertEqual(by_code["00110004"]["quantidade_fisica"], 4)
        self.assertEqual(by_code["00110158"]["quantidade_fisica"], 23.155)
        self.assertEqual(by_code["00110001"]["quantidade_fisica"], 0)
        self.assertAlmostEqual(result["total_metros"], 119.053, places=6)
        self.assertEqual(by_code["00110061"]["modelo"], "50x10")

    def test_duplicate_code_is_consolidated_and_zero_remains_valid(self):
        raw = workbook_bytes([
            ["Código", "Modelo de Barra", "Total"],
            ["00110004", "1/2X1/4", 3.25],
            [110004, "1/2X1/4", 2.5],
            [110003, "REDONDA", 0],
        ])
        result = parse_barramentos_excel(raw, "contagem.xlsx")
        self.assertEqual(result["total_rows"], 2)
        by_code = {entry["codigo"]: entry for entry in result["rows"]}
        self.assertEqual(by_code["00110004"]["quantidade_fisica"], 5.75)
        self.assertEqual(by_code["00110003"]["quantidade_fisica"], 0)
        self.assertEqual(result["total_metros"], 5.75)

    def test_old_total_fechamento_remains_supported(self):
        raw = workbook_bytes([
            ["CODIGO", "TOTAL FECHAMENTO OUTUBRO"],
            ["00110004", 17.5],
        ])
        result = parse_barramentos_excel(raw, "antigo.xlsx")
        self.assertEqual(result["criterio"], "TOTAL FECHAMENTO")
        self.assertEqual(result["total_metros"], 17.5)

    def test_old_barras_processado_remains_supported(self):
        raw = workbook_bytes([
            ["CODIGO", "BARRAS", "PROCESSADO", "CONSUMO"],
            ["00110004", 11, 2.5, 3],
        ])
        result = parse_barramentos_excel(raw, "barras_processado.xlsx")
        self.assertEqual(result["criterio"], "BARRAS + PROCESSADO")
        self.assertEqual(result["total_metros"], 13.5)
        self.assertEqual(result["total_consumo"], 3)
        self.assertTrue(result["consumo_disponivel"])

    def test_generic_codigo_total_without_bar_model_not_accepted(self):
        raw = workbook_bytes([
            ["CODIGO", "TOTAL"],
            ["00110004", 400],
        ])
        with self.assertRaisesRegex(ValueError, "MODELO DE BARRA"):
            parse_barramentos_excel(raw, "relatorio_nao_barramentos.xlsx")


if __name__ == "__main__":
    unittest.main()
