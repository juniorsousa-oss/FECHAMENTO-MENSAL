"""Regressões do cadastro TES acrescido dos sete tipos de TM informados."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import movements as mv


class TESReferenceTests(unittest.TestCase):
    def test_tes_tm_user_confirmed_exactly_matches_supplied_image(self):
        expected = {
            "010": ("Produção", "MOV PRODUCAO MES PA"),
            "020": ("Devolução", "DEVOLUCAO TOTVS"),
            "030": ("Devolução", "ENTR CUSTO E QTD ZER"),
            "040": ("Devolução", "DEVOLUCAO MES"),
            "520": ("Requisição", "BAIXA SA TOTVS"),
            "540": ("Requisição", "BAIX CUSTO E QTD ZER"),
            "550": ("Requisição", "BAIXA PRODUCAO MES"),
        }
        rules = mv.rules()
        self.assertEqual(set(mv.tes_confirmed()), set(expected))
        for code, (category, description) in expected.items():
            with self.subTest(code=code):
                self.assertEqual(rules["tes"][code]["tipo_tm"], category)
                self.assertEqual(rules["tes"][code]["descricao"], description)

    def test_protheus_catalog_remains_complete_and_other_tes_unchanged(self):
        base = mv.tes_reference()
        self.assertEqual(len(base), 342)
        rules = mv.rules()
        self.assertEqual(rules["modo"], "CADASTRO_TES_SOMENTE")
        for code, original in base.items():
            if code not in mv.tes_confirmed():
                with self.subTest(code=code):
                    self.assertEqual(rules["tes"][code]["descricao"], original)
                    self.assertEqual(rules["tes"][code]["tipo_tm"], "")
        for code in ("815", "823", "825", "836", "837", "999"):
            self.assertEqual(rules["tes"][code]["descricao"], base[code])

    def test_business_group_rules_stay_disabled(self):
        config = mv.rules()
        for obsolete in ("materiais_h001", "materiais_fechamento", "ordem_grupos",
                         "grupos_confirmados", "regras_confirmadas"):
            self.assertNotIn(obsolete, config)
        self.assertTrue(all(
            set(value) == {"descricao", "tipo_tm"} for value in config["tes"].values()
        ))

    def test_tm_types_are_informative_not_grouping(self):
        from test_movement_analysis import record, imported
        rows = [
            record(tes=code, armazem="EP", documento=f"DOC-{code}",
                   valor_saida="100", qtd_saida="2")
            for code in ("010", "020", "030", "040", "520", "540", "550")
        ]
        frame = mv.build_model([imported(rows)])["frame"]
        self.assertEqual(len(frame), 7)
        self.assertEqual(
            frame["tipo_tm"].tolist(),
            ["Produção", "Devolução", "Devolução", "Devolução",
             "Requisição", "Requisição", "Requisição"],
        )
        self.assertTrue((frame["grupo_analise"] == "").all())
        self.assertTrue((frame["subgrupo_analise"] == "").all())
        self.assertEqual(float(frame["valor_saida"].sum()), 700.0)
        self.assertEqual(float(frame["qtd_saida"].sum()), 14.0)

    def test_unknown_tes_is_visible_without_guessing(self):
        from test_movement_analysis import record, imported
        frame = mv.build_model([imported([record(tes="998")])])["frame"]
        if "998" not in mv.tes_reference():
            self.assertEqual(frame.iloc[0]["descricao_tes"], "NI - TES não localizada no cadastro")
            self.assertEqual(frame.iloc[0]["tipo_tm"], "NI")


if __name__ == "__main__":
    unittest.main()
