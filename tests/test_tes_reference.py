"""Regressão do reset: TES e descrição literal, sem classificação gerencial."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import movements as mv


class TESReferenceTests(unittest.TestCase):
    def test_catalog_complete_and_covers_previously_missing_tes(self):
        catalog = mv.tes_reference()
        self.assertEqual(len(catalog), 342)
        configuration = mv.rules()
        self.assertEqual(configuration["modo"], "CADASTRO_TES_SOMENTE")
        for code in ("815", "823", "825", "836", "837", "040", "520", "550", "999"):
            with self.subTest(code=code):
                self.assertEqual(configuration["tes"][code], {"descricao": catalog[code]})
                self.assertTrue(catalog[code])
        self.assertTrue(all(set(value) == {"descricao"} for value in configuration["tes"].values()))

    def test_previous_business_rules_not_loaded_into_active_configuration(self):
        config = mv.rules()
        for obsolete in ("materiais_h001", "materiais_fechamento", "ordem_grupos",
                         "grupos_confirmados", "regras_confirmadas"):
            self.assertNotIn(obsolete, config)
        self.assertEqual(config["tes"]["520"]["descricao"], mv.tes_reference()["520"])

    def test_source_values_and_descriptions_remain_unchanged_without_sales_group(self):
        from test_movement_analysis import record, imported
        rows = [
            record(tes=code, armazem="EP", documento=f"DOC-{code}",
                   valor_saida="100", qtd_saida="2")
            for code in ("815", "823", "825", "836", "837")
        ]
        frame = mv.build_model([imported(rows)])["frame"]
        self.assertEqual(len(frame), 5)
        self.assertEqual(frame["tes"].tolist(), ["815", "823", "825", "836", "837"])
        self.assertEqual(frame["descricao_tes"].tolist(),
                         [mv.tes_reference()[code] for code in frame["tes"]])
        self.assertTrue((frame["grupo_analise"] == "").all())
        self.assertTrue((frame["subgrupo_analise"] == "").all())
        self.assertEqual(float(frame["valor_saida"].sum()), 500.0)
        self.assertEqual(float(frame["qtd_saida"].sum()), 10.0)

    def test_missing_tes_is_explicitly_unavailable_not_guessed(self):
        from test_movement_analysis import record, imported
        frame = mv.build_model([imported([record(tes="998")])])["frame"]
        if "998" not in mv.tes_reference():
            self.assertEqual(frame.iloc[0]["descricao_tes"], "NI - TES não localizada no cadastro")


if __name__ == "__main__":
    unittest.main()
