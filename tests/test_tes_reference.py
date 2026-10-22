"""Descrições TES prioritárias fornecidas pelo usuário prevalecem sobre a base."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import movements as mv


DESCRIPTIONS = {
    "010": "MOV PRODUCAO MES PA",
    "020": "DEVOLUCAO TOTVS",
    "030": "ENTR CUSTO E QTD ZER",
    "040": "DEVOLUCAO MES",
    "520": "BAIXA SA TOTVS",
    "540": "BAIX CUSTO E QTD ZER",
    "550": "BAIXA PRODUCAO MES",
    "499": "ENTRADA DE INVENTÁRIO/ENTRADA OP",
    "999": "SAÍDA DE INVENTÁRIO/CONSUMO OP",
}


class TESReferenceTests(unittest.TestCase):
    def test_nine_descriptions_are_exact_and_override_base(self):
        self.assertEqual(mv.tes_overrides(), DESCRIPTIONS)
        rules = mv.rules()
        self.assertEqual(rules["modo"], "CADASTRO_TES_SOMENTE")
        for code, description in DESCRIPTIONS.items():
            with self.subTest(code=code):
                self.assertEqual(rules["tes"][code], {"descricao": description})
        # Verifica que a TES 520 ignora a descrição divergente na base.
        self.assertNotEqual(mv.tes_reference().get("520"), DESCRIPTIONS["520"])

    def test_all_other_base_descriptions_remain_unchanged(self):
        base = mv.tes_reference()
        self.assertEqual(len(base), 342)
        rules = mv.rules()["tes"]
        self.assertEqual(set(rules), set(base) | set(DESCRIPTIONS))
        for code, description in base.items():
            if code not in DESCRIPTIONS:
                with self.subTest(code=code):
                    self.assertEqual(rules[code], {"descricao": description})
        self.assertTrue(all(set(v) == {"descricao"} for v in rules.values()))

    def test_old_management_groups_and_tm_types_not_present(self):
        rules = mv.rules()
        for name in ("materiais_h001", "materiais_fechamento", "ordem_grupos",
                     "grupos_confirmados", "regras_confirmadas"):
            self.assertNotIn(name, rules)
        self.assertTrue(all("tipo_tm" not in val for val in rules["tes"].values()))

    def test_no_movement_value_or_quantity_changes_from_description_override(self):
        from test_movement_analysis import record, imported
        movements = [
            record(tes=code, armazem="EP", documento=f"DOC-{code}",
                   valor_saida="100", qtd_saida="2") for code in DESCRIPTIONS
        ]
        frame = mv.build_model([imported(movements)])["frame"]
        self.assertEqual(len(frame), 9)
        self.assertEqual(
            frame["descricao_tes"].tolist(),
            [DESCRIPTIONS[code] for code in frame["tes"]],
        )
        self.assertNotIn("tipo_tm", frame.columns)
        self.assertTrue((frame["grupo_analise"] == "").all())
        self.assertEqual(frame["valor_saida"].sum(), 900)
        self.assertEqual(frame["qtd_saida"].sum(), 18)

    def test_missing_tes_uses_explicit_ni_not_guess(self):
        from test_movement_analysis import record, imported
        frame = mv.build_model([imported([record(tes="998")])])["frame"]
        if "998" not in mv.tes_reference():
            self.assertEqual(frame.iloc[0]["descricao_tes"],
                             "NI - TES não localizada no cadastro")


if __name__ == "__main__":
    unittest.main()
