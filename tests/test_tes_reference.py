"""Regressão do cadastro TES Protheus — descrições sem alterar regras operacionais."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import movements as mv


class TESReferenceTests(unittest.TestCase):
    def test_catalog_completeness_and_missing_sales_tes_descriptions(self):
        reference = mv.tes_reference()
        self.assertEqual(len(reference), 342)
        expected = {
            "815": "REMESSA DE VENDA DE ENTREGA FUTURA SEM ST 5.116 - CONTRIBUIN",
            "823": "VENDA PRODUCAO DO ESTABELECIMENTO - NAO CONTRIBUINTE",
            "825": "REMESSA DE VENDA DE ENTREGA FUTURA SEM ST 5.116 - NAO CONTRI",
            "836": "VENDA PRODUCAO DO ESTABELECIMENTO CONTRIBUINTE REIDI/RECAP",
            "837": "REMESSA DE VENDA DE ENTREGA FUTURA SEM ST 5.116 - CONTRIBUIN",
        }
        rules = mv.rules()
        for tes, description in expected.items():
            with self.subTest(tes=tes):
                self.assertEqual(reference[tes], description)
                self.assertEqual(rules["tes"][tes]["descricao"], description)
                self.assertEqual(rules["tes"][tes]["grupo"], "VENDAS")
                self.assertFalse(rules["tes"][tes]["provisorio"])

    def test_confirmed_descriptions_and_groups_are_not_overwritten(self):
        rules = mv.rules()["tes"]
        for code, group, description in (
            ("040", mv.FLOW, "DEVOLUCAO MES"),
            ("520", mv.ADJUSTMENT, "BAIXA SA TOTVS"),
            ("550", mv.FLOW, "BAIXA PRODUCAO MES"),
            ("999", mv.FLOW, "ORDEM DE PRODUÇÃO"),
        ):
            with self.subTest(code=code):
                self.assertEqual(rules[code]["grupo"], group)
                self.assertEqual(rules[code]["descricao"], description)
        self.assertNotEqual(mv.tes_reference()["520"], rules["520"]["descricao"])

    def test_other_new_tes_have_real_description_but_provisional_classification(self):
        rules = mv.rules()["tes"]
        self.assertEqual(rules["001"]["descricao"], "COMPRA ENERGIA ELETRICA IND")
        self.assertEqual(rules["001"]["grupo"], "TES A CLASSIFICAR")
        self.assertTrue(rules["001"]["provisorio"])

    def test_sales_tes_grouping_preserves_movement_count_and_values(self):
        rows = []
        for i, tes in enumerate(("815", "823", "825", "836", "837")):
            rows.append(mv.clean_record({
                "codigo": "00001000", "descricao": "PRODUTO DE TESTE",
                "armazem": "EP", "tes": tes, "data": "2026-10-21",
                "documento": f"NF{i}", "um": "UN", "qtd_saida": "2",
                "valor_saida": "100.00", "ae_original": "OP123456789",
            }))
        imported = {
            "meta": {"sha256": "f" * 64, "arquivo_nome": "tes.xlsx",
                     "lancamentos": len(rows), "periodo_inicio": "2026-10-01",
                     "periodo_fim": "2026-10-21"},
            "rows": rows,
        }
        result = mv.build_model([imported])
        frame = result["frame"]
        self.assertEqual(len(frame), 5)
        self.assertEqual(set(frame["grupo_analise"]), {"VENDAS"})
        self.assertEqual(set(frame["descricao_tes"]),
                         {mv.rules()["tes"][tes]["descricao"] for tes in ("815", "823", "825", "836", "837")})
        self.assertEqual(float(frame["valor_saida"].sum()), 500.0)
        self.assertEqual(float(frame["qtd_saida"].sum()), 10.0)
        self.assertEqual(result["duplicates"], 0)


if __name__ == "__main__":
    unittest.main()
