"""Testa aplicação sequencial das seis condições confirmadas do KARDEX."""
from __future__ import annotations
import unittest
import pandas as pd

import kardex_group_config as cfg
import kardex_conditions as cond


def row(label, tes, *, kind="MP", cc="", op="", qty=0, amount=0, code="00000001"):
    return {"id_registro": label, "codigo": code, "tes": tes, "tipo": kind,
            "cc_identificado": cc, "op_identificada": op, "qtd_saida": qty,
            "valor_saida": amount, "valor_entrada": 1, "liquido_valor": 1-amount,
            "descricao": "MATERIAL", "descricao_tes": "TESTE"}


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
            "12":"FLUXO DE ESTOQUE", "13":"SEM GRUPO",
            "14":"SEM GRUPO", "15":cond.CONSUMABLE,
        }
        self.assertEqual(tagged["subgrupo_usuario"].to_dict(), expected)
        self.assertEqual(len(tagged), len(frame))
        self.assertEqual(tagged["valor_saida"].sum(), frame["valor_saida"].sum())
        self.assertEqual(tagged["valor_entrada"].sum(), frame["valor_entrada"].sum())
        self.assertEqual(tagged.loc["1", "condicao_ordem"], 1)
        self.assertEqual(tagged.loc["11", "condicao_ordem"], 2)
        self.assertEqual(tagged.loc["12", "condicao_id"], "")
        self.assertTrue(pd.isna(tagged.loc["12", "condicao_ordem"]))

    def test_reordering_priority_changes_first_match_only(self):
        original = pd.DataFrame([row("x","550",kind="II",cc="123456")])
        self.assertEqual(cond.classify(original,self.data).iloc[0].subgrupo_usuario,cond.MANAGEMENT)
        material = cond.TEMPLATES[3]["id"]
        cfg2 = self.data
        cfg2 = cfg.move_condition(cfg2,material,-1,known_tes=self.known)
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

    def test_old_config_migrates_without_losing_groups_or_resurrecting_deleted_rules(self):
        old = {"versao":1,"grupos":[{"id":"old","nome":"TESTE","tes":["520"]}],
               "condicoes":[]}
        upgraded = cfg.validated(old,self.known)
        self.assertEqual(upgraded["versao"],2)
        self.assertEqual(upgraded["grupos"][0]["nome"],"TESTE")
        self.assertEqual(len(upgraded["condicoes"]),6)
        filtered = cfg.delete_condition(upgraded,cond.TEMPLATES[0]["id"],known_tes=self.known)
        self.assertEqual(len(cfg.validated(filtered)["condicoes"]),5)


if __name__ == "__main__":
    unittest.main()
