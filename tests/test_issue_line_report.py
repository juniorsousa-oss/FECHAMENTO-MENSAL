"""Regressões: Relatório Geral preservado linha por linha; OPS só acrescenta baixa."""
from __future__ import annotations

from io import BytesIO
import unittest

from openpyxl import load_workbook
import pandas as pd

import reports
from issue_line_report import COLUMNS, build_rows


def row(op="26017801001", code="06050080", lot="000000000", *,
        required=16, attended=16, conferente="MOISES", source_line=1):
    return {
        "op": op, "codigo": code, "lote": lot,
        "descricao": "PUXADOR PLANO GRANDE 168X28 MM PRETO",
        "necessaria": required, "atendida": attended,
        "responsavel_conferencia": conferente,
        "separacao": "2026-10-19T08:00:00",
        "conferencia": "2026-10-20T08:00:00",
        "linha_origem": source_line,
    }


def movement(qty, day, *, op="26017801001", code="06050080",
             lot="000000000", kind="RE1", tes="999"):
    return {
        "op": op, "codigo": code, "lote": lot, "data": day,
        "quantidade": str(qty),
        "qtd_saida": str(max(qty, 0)), "qtd_entrada": str(max(-qty, 0)),
        "tipo_movimento": kind, "tes": tes,
        "natureza": "BAIXA / DEVOLUÇÃO",
    }


def model(general, movements):
    ops = sorted({r["op"] for r in general})
    return {
        "general": general, "movements": movements,
        "history_available": True, "baixas_fonte": "OPS",
        "ops": pd.DataFrame([{
            "op": op, "status_op": "NF EMITIDA", "divergencias": 0,
            "data_faturamento": "2026-10-21",
        } for op in ops]),
        "items": pd.DataFrame([{
            "op": r["op"], "codigo": r["codigo"], "tipo_material": "MP",
        } for r in general]),
        "as_of": "2026-10-31",
    }


class GeneralBaseTests(unittest.TestCase):
    def test_one_general_row_with_corresponding_16_ops(self):
        m = model([row()], [
            movement(10, "2026-10-20"),
            movement(6, "2026-10-21"),
        ])
        result = build_rows(m, {"26017801001"})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][:4], ["26017801001", "06050080",
                                        "PUXADOR PLANO GRANDE 168X28 MM PRETO",
                                        "000000000"])
        self.assertEqual(result[0][4:9], [16, 0, 16, 16, 0])
        self.assertEqual(result[0][9], "CONFERIDO — BAIXA CORRESPONDENTE")

    def test_no_conferente_means_only_separated_even_with_conference_date(self):
        r = row(required=12, attended=7, conferente="")
        result = build_rows(model([r], []), {"26017801001"})
        self.assertEqual(result[0][4:9], [12, 7, 0, 0, None])
        self.assertEqual(result[0][-1], "APENAS SEPARADO")

    def test_multi_general_lines_same_key_never_duplicate_issued_total(self):
        rows = [row(attended=5, required=5, source_line=2),
                row(attended=11, required=11, source_line=3)]
        m = model(rows, [movement(10, "2026-10-20"),
                         movement(6, "2026-10-21")])
        result = build_rows(m, {"26017801001"})
        self.assertEqual(len(result), 2)
        self.assertEqual(sum(r[6] for r in result), 16)
        self.assertEqual(sum(r[7] for r in result), 16)
        self.assertEqual(sum(r[8] for r in result), 0)
        self.assertEqual([r[7] for r in result], [5, 11])

    def test_same_product_wrong_lot_is_flagged_without_false_pending_total(self):
        m = model([row(lot="001")], [movement(16, "2026-10-20", lot="002")])
        result = build_rows(m, {"26017801001"})
        self.assertEqual(result[0][7:9], [0, 0])
        self.assertIn("DIVERGÊNCIA ENTRE LOTES", result[0][-1])

    def test_quantity_excess_is_not_hidden(self):
        m = model([row()], [movement(18, "2026-10-20")])
        output = build_rows(m, {"26017801001"})
        self.assertEqual(output[0][7], 18)
        self.assertEqual(output[0][-1], "BAIXA SUPERIOR AO CONFERIDO")

    def test_missing_ops_is_not_reported_as_zero(self):
        m = model([row()], [])
        m["history_available"] = False
        with self.assertRaisesRegex(ValueError, "Relatório OPS"):
            build_rows(m, {"26017801001"})

    def test_export_uses_screen_fields_while_general_reconciliation_stays_intact(self):
        m = model([row()], [movement(16, "2026-10-20")])
        m["ops"]["itens"] = 1
        m["ops"]["separados"] = 1
        m["ops"]["conferidos"] = 1
        m["ops"]["baixados"] = 1
        m["items"]["necessaria"] = 16
        m["items"]["separada"] = 16
        m["items"]["conferida"] = 16
        m["items"]["baixada"] = 16
        m["items"]["pendente"] = 0
        m["items"]["lotes"] = "000000000"
        m["items"]["status"] = "PRODUTO CONSUMIDO"
        m["items"]["divergente"] = False
        blob = reports.export_issues(m)
        wb = load_workbook(BytesIO(blob), read_only=True, data_only=True)
        try:
            self.assertEqual(wb.sheetnames, ["Conferência de Baixas"])
            cells = list(wb.active.values)
            self.assertEqual(cells[0], tuple(reports.OP_COLUMNS))
            self.assertEqual(len(cells), 2)
            self.assertEqual(cells[1][0], "26017801001")
            self.assertEqual(cells[1][12], "06050080")
            self.assertEqual(cells[1][18], 16)
            self.assertEqual(wb.active["S2"].number_format, "General")
        finally:
            wb.close()


if __name__ == "__main__":
    unittest.main()
