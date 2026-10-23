"""Testa aplicação sequencial das dez condições confirmadas do KARDEX."""
from __future__ import annotations
import unittest
import pandas as pd

import kardex_group_config as cfg
import kardex_conditions as cond


def row(label, tes, *, kind="MP", cc="", op="", qty=0, amount=0, code="00000001",
        cf="", desc="MATERIAL", group=""):
    return {"id_registro": label, "codigo": code, "tes": tes, "tipo": kind,
            "cc_identificado": cc, "op_identificada": op, "qtd_saida": qty,
            "valor_saida": amount, "valor_entrada": 1, "liquido_valor": 1-amount,
            "descricao": desc, "grupo": group, "cf": cf, "descricao_tes": "TESTE"}


class ConditionsTests(unittest.TestCase):
    def setUp(self):
        self.data = cfg.empty()
        self.known = {"010","020","030","040","499","520","540","550","999"}
        self.data = cfg.create_group(self.data, "FLUXO DE ESTOQUE", known_tes=self.known)
        self.data = cfg.assign_group(self.data, self.data["grupos"][0]["id"],
                                     ["020","030","040","520","540","550"], known_tes=self.known)
        self.sheet = next(iter(cond.sheet_bar_codes()))

    def test_first_matching_condition_excludes_all_following_conditions(self):
        frame = pd.DataFrame([
            row("1", "020", kind="PA", op="OP123", qty=1),        # prioriza produção interna
            row("2", "040", kind="PI"),                           # também produção interna
            row("3", "550", kind="II", cc="123456", qty=3),      # acerto antecede consumo
            row("4", "520", kind="II", cc="600307"),             # material consumo
            row("5", "030", cc="600307", code=self.sheet),       # chapas/barras antecede custo
            row("6", "540", cc="600307", code=self.sheet),       # idem
            row("7", "030", cc="600307", code="00999999"),       # custo sem chapa
            row("8", "540"),                                     # custo
            row("9", "520", cc="123456"),                        # acerto gerencial
            row("10", "999", op="OP123", amount=2),              # saída com valor e OP
            row("11", "520", op="OP123", qty=4),                 # consumo OP antes de II
            row("12", "520", kind="MP", cc="600307"),            # nenhum -> grupo
            row("13", "499"),                                   # nenhum -> SEM GRUPO
            row("14", "999", op="OP123"),                        # sem saída -> SEM GRUPO
            row("15", "550", kind="II", cc="000600307"),         # CC normalizado 600307
        ])
        tagged = cond.classify(frame, self.data).set_index("id_registro")
        expected = {
            "1":cond.PRODUCTION, "2":cond.PRODUCTION,
            "3":cond.MANAGEMENT, "4":cond.CONSUMABLE,
            "5":cond.SHEET_BAR, "6":cond.SHEET_BAR,
            "7":cond.COST, "8":cond.COST, "9":cond.MANAGEMENT,
            "10":cond.CONSUMPTION, "11":cond.CONSUMPTION,
            "12":cond.STOCK_ADJUSTMENT, "13":"SEM GRUPO",
            "14":"SEM GRUPO", "15":cond.CONSUMABLE,
        }
        self.assertEqual(tagged["subgrupo_usuario"].to_dict(), expected)
        self.assertEqual(len(tagged), len(frame))
        self.assertEqual(tagged["valor_saida"].sum(), frame["valor_saida"].sum())
        self.assertEqual(tagged["valor_entrada"].sum(), frame["valor_entrada"].sum())
        self.assertEqual(tagged.loc["1", "condicao_ordem"], 1)
        self.assertEqual(tagged.loc["11", "condicao_ordem"], 2)
        self.assertEqual(tagged.loc["12", "condicao_id"], "kardex_cond_09_ajuste_estoque")
        self.assertEqual(tagged.loc["13", "condicao_id"], "")
        self.assertTrue(pd.isna(tagged.loc["13", "condicao_ordem"]))

    def test_reordering_priority_changes_first_match_only(self):
        original = pd.DataFrame([row("x","550",kind="II",cc="123456")])
        self.assertEqual(cond.classify(original,self.data).iloc[0].subgrupo_usuario,cond.MANAGEMENT)
        material = next(t["id"] for t in cond.TEMPLATES if t["regra"] == "material_consumo")
        cfg2 = self.data
        cfg2 = cfg.move_condition(cfg2,material,-1,known_tes=self.known)
        self.assertEqual(cond.classify(original,cfg2).iloc[0].subgrupo_usuario,cond.CONSUMABLE)

    def test_deleted_conditions_do_not_reappear_and_can_be_restored(self):
        key = cond.TEMPLATES[1]["id"]
        removed = cfg.delete_condition(self.data,key,known_tes=self.known)
        record = pd.DataFrame([row("op","999",op="OP123",qty=4)])
        self.assertEqual(cond.classify(record,removed).iloc[0].subgrupo_usuario,"SEM GRUPO")
        self.assertNotIn(key,[x["id"] for x in cfg.validated(removed)["condicoes"]])
        restored = cfg.add_predefined_condition(removed,key,known_tes=self.known)
        self.assertEqual(cond.classify(record,restored).iloc[0].subgrupo_usuario,cond.CONSUMPTION)

    def test_cc_rule_requires_real_cc_field(self):
        rows = pd.DataFrame([row("outro","550",cc="",qty=0),
                             row("cc","550",cc="123456",qty=0),
                             row("fixo","550",cc="600307",qty=0)])
        result = cond.classify(rows,self.data)
        self.assertEqual(result["subgrupo_usuario"].tolist(),
                         ["FLUXO DE ESTOQUE",cond.MANAGEMENT,"FLUXO DE ESTOQUE"])

    def test_new_conditions_take_precedence_and_preserve_original_type(self):
        rows = pd.DataFrame([
            row("epi520", "520", cf="601401", cc="123456", qty=1),
            row("epi540", "540", cf="601401.0", qty=1),
            row("epi_over_op", "520", cf="601401", op="OP123", qty=1),
            row("tc_tp", "520", kind="MP", cc="987654", group="MATERIAL USADO TC/TP", qty=1),
            row("tc_tp_desc", "520", kind="MP", desc="MATERIAL USADO TC TP", qty=1),
            row("tp_only", "520", kind="MP", desc="TRANSFORMADOR DE POTENCIAL TP", qty=1, cc="600307"),
            row("adjust_020", "020", kind="MP", cc="600307"),
            row("adjust_520", "520", kind="MP", cc="600307"),
            row("return_040", "040", kind="MP", cc="600307"),
            row("production_precedes_return", "040", kind="PI", cc="600307"),
            row("sheet_precedes_return", "040", kind="MP", cc="600307", code=self.sheet),
            row("original_ii", "520", kind="II", cc="600307"),
        ])
        tagged = cond.classify(rows, self.data).set_index("id_registro")
        expected = {
            "epi520":cond.EPI, "epi540":cond.EPI,
            "epi_over_op":cond.CONSUMPTION,
            "tc_tp":cond.CONSUMABLE, "tc_tp_desc":cond.CONSUMABLE,
            "tp_only":cond.STOCK_ADJUSTMENT,
            "adjust_020":cond.STOCK_ADJUSTMENT, "adjust_520":cond.STOCK_ADJUSTMENT,
            "return_040":cond.PRODUCTION_RETURN,
            "production_precedes_return":cond.PRODUCTION,
            "sheet_precedes_return":cond.SHEET_BAR,
            "original_ii":cond.CONSUMABLE,
        }
        self.assertEqual(tagged["subgrupo_usuario"].to_dict(), expected)
        self.assertEqual(tagged.loc["tc_tp", "tipo_analise"], "II")
        self.assertEqual(tagged.loc["tc_tp", "tipo"], "MP")
        self.assertEqual(tagged.loc["tc_tp_desc", "tipo_analise"], "II")
        self.assertEqual(tagged.loc["tp_only", "tipo_analise"], "MP")
        self.assertEqual(tagged["valor_entrada"].sum(), rows["valor_entrada"].sum())
        self.assertEqual(tagged["valor_saida"].sum(), rows["valor_saida"].sum())
        self.assertEqual(len(tagged), len(rows))
        self.assertEqual(tagged.loc["epi520", "condicao_ordem"], 3)

    def test_v2_migration_adds_only_new_conditions_preserving_existing_order(self):
        old = {
            "versao": 2,
            "grupos": [{"id": "grp","nome":"FLUXO DE ESTOQUE","tes":["520"]}],
            "condicoes": [
                {"id": t["id"],"nome":t["nome"],"regra":t["regra"]}
                for t in cond.TEMPLATES
                if t["regra"] in ("producao_interna","consumo_op","acerto_gerencial",
                                  "material_consumo","chapas_barras","adequacao_custo")
            ],
        }
        migrated = cfg.validated(old, self.known)
        self.assertEqual(migrated["versao"], 3)
        self.assertEqual(len(migrated["condicoes"]), 10)
        self.assertEqual(migrated["grupos"], old["grupos"])
        self.assertEqual(
            [item["regra"] for item in migrated["condicoes"]],
            [item["regra"] for item in cond.TEMPLATES],
        )
        removed = cfg.delete_condition(migrated, "kardex_cond_07_consumo_epi", known_tes=self.known)
        self.assertEqual(len(cfg.validated(removed,self.known)["condicoes"]), 9)
        self.assertNotIn("kardex_cond_07_consumo_epi", [
            x["id"] for x in cfg.validated(removed,self.known)["condicoes"]
        ])

    def test_old_config_migrates_without_losing_groups_or_resurrecting_deleted_rules(self):
        old = {"versao":1,"grupos":[{"id":"old","nome":"TESTE","tes":["520"]}],
               "condicoes":[]}
        upgraded = cfg.validated(old,self.known)
        self.assertEqual(upgraded["versao"],3)
        self.assertEqual(upgraded["grupos"][0]["nome"],"TESTE")
        self.assertEqual(len(upgraded["condicoes"]),10)
        filtered = cfg.delete_condition(upgraded,cond.TEMPLATES[0]["id"],known_tes=self.known)
        self.assertEqual(len(cfg.validated(filtered)["condicoes"]),9)


if __name__ == "__main__":
    unittest.main()
