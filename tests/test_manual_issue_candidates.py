"""Regressões da Conciliação Assistida (somente leitura).

Critérios estritos: TES 520/550, CC600307 sem OP, saída positiva,
produto e janela temporal. Sem alteração de pendências oficiais.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
from decimal import Decimal
from io import BytesIO
import unittest

from openpyxl import load_workbook
import pandas as pd

import manual_issue_candidates as assisted


CODE = "01040055"
ONE = "26009201001"
TWO = "26009202002"


def row(*, tes="520", ae="CC600307", code=CODE, qty="5",
        day="2026-10-25", number="E1", entry="0"):
    return {
        "data": day, "tes": tes, "codigo": code,
        "ae_original": ae,
        "qtd_saida": qty, "qtd_entrada": entry,
        "documento": "DOC-01",
        "descricao": "CONEXÃO HIDRÁULICA",
        "armazem": "S2", "arquivo_origem": "KARDEX-S2.xlsx",
        "linha_origem": 12, "id_registro": number,
    }


def fixture(*, two=True, g9="0", fulfilled=False, no_billing=False):
    items = [{
        "op": ONE, "codigo": CODE, "lote": "060919",
        "necessaria": Decimal("9"),
        "baixada": Decimal("9" if fulfilled else "3"),
    }]
    header = [{
        "op": ONE, "cliente": "SERRA VERDE",
        "data_faturamento": "31/10/2026" if not no_billing else "NI",
    }]
    general = [{
        "op": ONE, "codigo": CODE, "separacao": "2026-10-20",
        "conferencia": "2026-10-22",
    }]
    if two:
        items.append({
            "op": TWO, "codigo": CODE, "lote": "060920",
            "necessaria": Decimal("10"), "baixada": Decimal("2"),
        })
        header.append({
            "op": TWO, "cliente": "SERRA VERDE",
            "data_faturamento": "02/11/2026",
        })
        general.append({
            "op": TWO, "codigo": CODE, "separacao": "2026-10-21",
            "conferencia": "2026-10-25",
        })
    return {
        "as_of": "2026-11-03",
        "history_available": True,
        "lot_items": pd.DataFrame(items),
        "lot_ops": pd.DataFrame(header),
        "general": general,
        "stock": [
            {"codigo": CODE, "endereco": "G9-PROD", "saldo": Decimal(g9)}
        ],
    }


def compute(model, movements, **kw):
    return assisted.build(
        model, pd.DataFrame(movements),
        start=date(2026, 10, 1), end=date(2026, 11, 3),
        **kw,
    )


class ManualIssueCandidatesTests(unittest.TestCase):
    def test_one_manual_baixa_multiple_ops_is_ambiguous_not_allocated(self):
        model = fixture()
        old_general = deepcopy(model["general"])
        old_item = model["lot_items"].copy(deep=True)
        result = compute(model, [row()])
        self.assertEqual(result["summary"]["movimentos_elegiveis"], 1)
        self.assertEqual(result["summary"]["movimentos_ambiguos"], 1)
        self.assertEqual(result["summary"]["linhas_para_revisao"], 2)
        self.assertEqual({r["op"] for r in result["rows"]}, {ONE, TWO})
        self.assertEqual({r["movimento_id"] for r in result["rows"]}, {"E1"})
        self.assertTrue(all(r["qtd_ops_candidatas"] == 2
                            for r in result["rows"]))
        self.assertTrue(all(r["situacao"] == "MÚLTIPLAS OPS — VALIDAR"
                            for r in result["rows"]))
        self.assertEqual(model["general"], old_general)
        pd.testing.assert_frame_equal(model["lot_items"], old_item)
        self.assertEqual(result["rows"][0]["quantidade"], Decimal("5"))

    def test_single_valid_candidate_uses_invoice_mes_and_current_balance(self):
        result = compute(fixture(two=False), [row(qty="5")])
        self.assertEqual(len(result["rows"]), 1)
        selected = result["rows"][0]
        self.assertEqual(selected["op"], ONE)
        self.assertEqual(selected["pendente_demanda"], Decimal("6"))
        self.assertEqual(selected["faturamento"], "31/10/2026")
        self.assertEqual(selected["situacao"], "CANDIDATO ÚNICO — VALIDAR")
        self.assertIn("Lote do KARDEX não disponível", selected["justificativa"])
        self.assertEqual(selected["cr"], "600307")

    def test_only_tes_520_550_exact_cc_without_op_and_positive_exits(self):
        raw = [
            row(tes="520", number="OK1"),
            row(tes="550", number="OK2"),
            row(tes="999", number="BAD1"),
            row(tes="520", ae="OP26009201001", number="BAD2"),
            row(tes="520", ae="CC600308", number="BAD3"),
            row(tes="520", ae="CC600307 OP26009201001", number="BAD4"),
            row(tes="520", ae="", number="BAD5"),
            row(tes="520", qty="0", number="BAD6"),
            row(tes="520", qty="-3", number="BAD7"),
            row(tes="550", entry="3", number="BAD8"),
        ]
        result = compute(fixture(two=False), raw)
        self.assertEqual(result["summary"]["movimentos_elegiveis"], 2)
        self.assertEqual(len(result["rows"]), 2)
        self.assertEqual({r["tes"] for r in result["rows"]}, {"520", "550"})

    def test_no_pending_after_ops_must_not_be_recommended(self):
        result = compute(fixture(two=False, fulfilled=True), [row()])
        self.assertEqual(result["summary"]["movimentos_sem_correspondencia"], 1)
        self.assertEqual(len(result["rows"]), 1)
        self.assertEqual(result["rows"][0]["situacao"], "SEM OP CANDIDATA")
        self.assertEqual(result["rows"][0]["op"], "")

    def test_current_g9_balance_is_filter_not_historical_proof(self):
        model = fixture(two=False, g9="30")
        no_g9_shortage = compute(model, [row()])
        self.assertEqual(no_g9_shortage["rows"][0]["op"], "")
        relaxed = compute(model, [row()], require_insufficient_g9=False)
        self.assertEqual(relaxed["rows"][0]["op"], ONE)
        self.assertEqual(relaxed["rows"][0]["saldo_g9_atual"], Decimal("30"))
        self.assertIn("não comprova saldo na data histórica",
                      relaxed["rows"][0]["justificativa"])

    def test_faturamento_ni_requires_mes_event_near_baixa(self):
        close = compute(fixture(two=False, no_billing=True), [row()])
        self.assertEqual(close["rows"][0]["op"], ONE)
        self.assertEqual(close["rows"][0]["situacao"], "FATURAMENTO NI — VALIDAR")
        far = compute(fixture(two=False, no_billing=True), [
            row(day="2026-07-05")
        ])
        self.assertEqual(far["summary"]["movimentos_elegiveis"], 0)
        long_span = assisted.build(
            fixture(two=False, no_billing=True),
            pd.DataFrame([row(day="2026-07-05")]),
            start=date(2026, 7, 1), end=date(2026, 11, 3),
        )
        self.assertEqual(long_span["rows"][0]["op"], "")

    def test_duplicate_movement_id_is_not_counted_twice(self):
        result = compute(fixture(two=False), [row(), row()])
        self.assertEqual(result["summary"]["movimentos_elegiveis"], 1)
        self.assertEqual(result["summary"]["duplicados_ignorados"], 1)
        self.assertEqual(len(result["rows"]), 1)

    def test_cannot_see_events_after_mes_reference(self):
        res = compute(fixture(two=False), [
            row(day="2026-11-04"),
            row(day="2026-10-25", number="GOOD"),
        ])
        self.assertEqual(res["summary"]["movimentos_elegiveis"], 1)

    def test_error_on_missing_required_kardex_fields(self):
        with self.assertRaisesRegex(ValueError, "KARDEX sem campos"):
            assisted.build(
                fixture(two=False),
                pd.DataFrame([{"data": "2026-10-25", "tes": "520"}]),
                start=date(2026, 10, 1), end=date(2026, 10, 31),
            )

    def test_candidate_export_contains_document_and_trace_not_lote(self):
        result = compute(fixture(two=False), [row()])
        book = load_workbook(BytesIO(assisted.export_excel(result)), data_only=True)
        try:
            sheet = book.active
            self.assertEqual(sheet.title, "Baixas Manuais Candidatas")
            labels = [cell.value for cell in sheet[1]]
            self.assertIn("Documento KARDEX", labels)
            self.assertIn("CR", labels)
            self.assertIn("Quantidade manual", labels)
            self.assertIn("Linha de origem", labels)
            self.assertIn("ID movimentação", labels)
            self.assertNotIn("Lote", labels)
            self.assertEqual(sheet.max_row, 2)
            values = [cell.value for cell in sheet[2]]
            self.assertEqual(values[labels.index("Documento KARDEX")], "DOC-01")
            self.assertEqual(values[labels.index("OP candidata")], ONE)
            self.assertEqual(values[labels.index("Quantidade manual")], 5)
            self.assertEqual(values[labels.index("Linha de origem")], 12)
        finally:
            book.close()


if __name__ == "__main__":
    unittest.main()
