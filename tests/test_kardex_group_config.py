from __future__ import annotations
import unittest

import pandas as pd

import kardex_group_config as cg


KNOWN = {"010", "020", "040", "499", "520", "550", "999"}

def frame():
    return pd.DataFrame([
        {"tes":"010","id_registro":"a","codigo":"1","valor_entrada":100.0,"valor_saida":0.0,"liquido_valor":100.0},
        {"tes":"020","id_registro":"b","codigo":"2","valor_entrada":0.0,"valor_saida":20.0,"liquido_valor":-20.0},
        {"tes":"520","id_registro":"c","codigo":"3","valor_entrada":0.0,"valor_saida":25.0,"liquido_valor":-25.0},
        {"tes":"999","id_registro":"d","codigo":"4","valor_entrada":0.0,"valor_saida":30.0,"liquido_valor":-30.0},
    ])


class KardexGroupConfigTests(unittest.TestCase):
    def test_create_assign_rename_delete_preserves_all_movements(self):
        data = cg.create_group(cg.empty(), "Produção", known_tes=KNOWN)
        ident = data["grupos"][0]["id"]
        data = cg.assign_group(data, ident, ["010","520"], name="Saídas da fábrica", known_tes=KNOWN)
        self.assertEqual(data["grupos"][0]["tes"], ["010","520"])
        summary = cg.summarize(frame(), data).set_index("grupo_usuario")
        self.assertEqual(set(summary.index), {"Saídas da fábrica", "SEM GRUPO"})
        self.assertEqual(summary["lancamentos"].sum(), 4)
        self.assertEqual(summary["valor_entrada"].sum(), 100)
        self.assertEqual(summary["valor_saida"].sum(), 75)
        self.assertEqual(summary.loc["Saídas da fábrica", "tes_distintas"], 2)
        data = cg.delete_group(data, ident, known_tes=KNOWN)
        after = cg.summarize(frame(), data)
        self.assertEqual(after["lancamentos"].sum(), 4)
        self.assertEqual(after.iloc[0]["grupo_usuario"], "SEM GRUPO")

    def test_conflicting_tes_never_double_count(self):
        first = cg.create_group(cg.empty(), "Grupo 1", known_tes=KNOWN)
        second = cg.create_group(first, "Grupo 2", known_tes=KNOWN)
        id1, id2 = [g["id"] for g in second["grupos"]]
        second = cg.assign_group(second, id1, ["520"], known_tes=KNOWN)
        with self.assertRaisesRegex(ValueError, "mais de um grupo"):
            cg.assign_group(second, id2, ["520"], known_tes=KNOWN)

    def test_conditions_are_saved_and_removed_without_affecting_group_summaries(self):
        cfg = cg.create_group(cg.empty(), "Estoque", known_tes=KNOWN)
        cfg = cg.assign_group(cfg, cfg["grupos"][0]["id"], ["020"], known_tes=KNOWN)
        before = cg.summarize(frame(), cfg)
        cfg = cg.create_condition(cfg, "Verificar ajuste de inventário", known_tes=KNOWN)
        self.assertEqual(len(cfg["condicoes"]), 13)
        cond_id = cfg["condicoes"][-1]["id"]
        self.assertTrue(before.equals(cg.summarize(frame(), cfg)))
        cfg = cg.delete_condition(cfg, cond_id, known_tes=KNOWN)
        self.assertEqual(len(cfg["condicoes"]), 12)
        self.assertTrue(before.equals(cg.summarize(frame(), cfg)))

    def test_invalid_names_codes_duplicate_groups_are_rejected(self):
        with self.assertRaises(ValueError):
            cg.create_group(cg.empty(), "", known_tes=KNOWN)
        with self.assertRaises(ValueError):
            cg.create_group(cg.empty(), "SEM GRUPO", known_tes=KNOWN)
        data = cg.create_group(cg.empty(), "Estoque", known_tes=KNOWN)
        with self.assertRaises(ValueError):
            cg.create_group(data, "estoque", known_tes=KNOWN)
        with self.assertRaises(ValueError):
            cg.assign_group(data, data["grupos"][0]["id"], ["9999"], known_tes=KNOWN)
        with self.assertRaises(ValueError):
            cg.delete_condition(data, "invalid", known_tes=KNOWN)

    def test_tes_zero_padding_and_unassigned(self):
        cfg = cg.create_group(cg.empty(), "Grupo", known_tes=KNOWN)
        cfg = cg.assign_group(cfg, cfg["grupos"][0]["id"], ["10", "020"], known_tes=KNOWN)
        self.assertEqual(cfg["grupos"][0]["tes"], ["010","020"])
        self.assertEqual(cg.normalize_tes("9999"), "")


if __name__ == "__main__":
    unittest.main()
