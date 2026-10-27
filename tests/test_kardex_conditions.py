"""Testa aplicação sequencial das treze condições do KARDEX, incluindo ajuste 520 sem OP."""
from __future__ import annotations
import unittest
import pandas as pd

import kardex_group_config as cfg
import kardex_conditions as cond


def row(label, tes, *, kind="MP", cc="", op="", qty=0, amount=0, code="00000001",
        cf="", desc="MATERIAL", group="", warehouse="S2"):
    return {"id_registro": label, "codigo": code, "tes": tes, "tipo": kind,
            "cc_identificado": cc, "op_identificada": op, "qtd_saida": qty,
            "valor_saida": amount, "valor_entrada": 1, "liquido_valor": 1-amount,
            "descricao": desc, "grupo": group, "cf": cf, "armazem": warehouse, "descricao_tes": "TESTE"}


class ConditionsTests(unittest.TestCase):
    def setUp(self):
        self.data = cfg.empty()
        self.known = {"010","020","030","040","499","520","540","550","999","547"}
        self.data = cfg.create_group(self.data, "FLUXO DE ESTOQUE", known_tes=self.known)
        self.data = cfg.assign_group(self.data, self.data["grupos"][0]["id"],
                                     ["020","030","040","520","540","550","547"], known_tes=self.known)
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
            "3":cond.MANAGEMENT, "4":cond.STOCK_ADJUSTMENT,
            "5":cond.SHEET_BAR, "6":cond.SHEET_BAR,
            "7":cond.COST, "8":cond.COST, "9":cond.STOCK_ADJUSTMENT,
            "10":cond.CONSUMPTION, "11":cond.CONSUMPTION,
            "12":cond.STOCK_ADJUSTMENT, "13":"SEM GRUPO",
            "14":"SEM GRUPO", "15":cond.CONSUMABLE,
        }
        self.assertEqual(tagged["subgrupo_usuario"].to_dict(), expected)
        self.assertEqual(len(tagged), len(frame))
        self.assertEqual(tagged["valor_saida"].sum(), frame["valor_saida"].sum())
        self.assertEqual(tagged["valor_entrada"].sum(), frame["valor_entrada"].sum())
        self.assertEqual(tagged.loc["1", "condicao_ordem"], 4)
        self.assertEqual(tagged.loc["11", "condicao_ordem"], 5)
        self.assertEqual(tagged.loc["12", "condicao_id"], "kardex_cond_09_ajuste_estoque")
        self.assertEqual(tagged.loc["13", "condicao_id"], "")
        self.assertTrue(pd.isna(tagged.loc["13", "condicao_ordem"]))

    def test_520_without_op_is_stock_adjustment_before_every_other_condition(self):
        """Corrige 00703452 e os demais lançamentos 520 sem OP, inclusive tipo II."""
        self.assertEqual(self.data["condicoes"][0]["regra"], "ajuste_520_sem_op")
        samples = pd.DataFrame([
            row("bucha_1", "520", code="00703452", kind="II",
                cc="600307", amount=3554.16, qty=2),
            row("bucha_2", "520", code="00703452", kind="II",
                cc="600307", amount=4343.97, qty=2),
            row("bucha_3", "520", code="00703452", kind="II",
                cc="600307", amount=1974.53, qty=2),
            row("cc_diferente", "520", cc="123456", kind="II", qty=2),
            row("epi_ep", "520", warehouse="EP", cc="601401", qty=3),
            row("tc_tp", "520", group="MATERIAL USADO TC/TP", qty=1),
            row("chapa", "520", cc="600307", code=self.sheet, qty=2),
            row("outro_codigo", "520", code="00999888", kind="MP", cc="", qty=2),
            row("com_op", "520", code="00703452", op="OP20261234",
                kind="II", cc="600307", qty=1),
            row("outra_tes", "550", cc="123456", qty=2),
            row("com_op_sem_saida", "520", code="00703452", op="OP123456", qty=0),
        ])
        original_total = samples["valor_saida"].sum()
        result = cond.classify(samples, self.data).set_index("id_registro")
        for label in (
            "bucha_1", "bucha_2", "bucha_3", "cc_diferente",
            "epi_ep", "tc_tp", "chapa", "outro_codigo",
        ):
            self.assertEqual(result.loc[label, "grupo_usuario"], "FLUXO DE ESTOQUE")
            self.assertEqual(result.loc[label, "subgrupo_usuario"], cond.STOCK_ADJUSTMENT)
            self.assertEqual(int(result.loc[label, "condicao_ordem"]), 1)
            self.assertEqual(result.loc[label, "condicao_id"],
                             "kardex_cond_14_ajuste_520_sem_op")
        self.assertEqual(result.loc["com_op", "subgrupo_usuario"], cond.CONSUMPTION)
        self.assertEqual(result.loc["outra_tes", "subgrupo_usuario"], cond.MANAGEMENT)
        self.assertNotEqual(result.loc["com_op_sem_saida", "condicao_ordem"], 1)
        self.assertEqual(result["valor_saida"].sum(), original_total)
        self.assertEqual(len(result), len(samples))

    def test_v5_migration_replaces_old_consumable_exception_once(self):
        old = cfg.empty()
        old["versao"] = 5
        old["condicoes"][0] = {
            "id": "kardex_cond_13_consumo_lista_520_sem_op",
            "nome": "MATERIAL DE CONSUMO — LISTA 520 SEM OP",
            "regra": "consumo_lista_520_sem_op",
        }
        original_groups = old["grupos"]
        old["condicoes"] = [item for item in old["condicoes"]
                            if item["regra"] != "consumo_epi"]
        converted = cfg.validated(old, self.known)
        self.assertEqual(converted["versao"], 6)
        self.assertEqual(converted["condicoes"][0]["regra"], "ajuste_520_sem_op")
        self.assertEqual(converted["grupos"], original_groups)
        self.assertNotIn("consumo_lista_520_sem_op",
                         [x["regra"] for x in converted["condicoes"]])
        self.assertNotIn("consumo_epi", [x["regra"] for x in converted["condicoes"]])
        self.assertEqual(len(converted["condicoes"]), len(old["condicoes"]))
        self.assertEqual(cfg.validated(converted, self.known), converted)
        removed = cfg.delete_condition(
            converted, converted["condicoes"][0]["id"], known_tes=self.known
        )
        self.assertNotIn("ajuste_520_sem_op",
                         [x["regra"] for x in cfg.validated(removed, self.known)["condicoes"]])

    def test_reordering_priority_changes_first_match_only(self):
        original = pd.DataFrame([row("x","550",kind="II",cc="123456")])
        self.assertEqual(cond.classify(original,self.data).iloc[0].subgrupo_usuario,cond.MANAGEMENT)
        material = next(t["id"] for t in cond.TEMPLATES if t["regra"] == "material_consumo")
        cfg2 = self.data
        cfg2 = cfg.move_condition(cfg2,material,-1,known_tes=self.known)
        self.assertEqual(cond.classify(original,cfg2).iloc[0].subgrupo_usuario,cond.CONSUMABLE)

    def test_deleted_conditions_do_not_reappear_and_can_be_restored(self):
        key = next(t["id"] for t in cond.TEMPLATES if t["regra"] == "consumo_op")
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
                         [cond.FALLBACK_STOCK,cond.MANAGEMENT,cond.FALLBACK_STOCK])

    def test_new_conditions_take_precedence_and_preserve_original_type(self):
        rows = pd.DataFrame([
            row("epi520", "520", cf="RE0", cc="601401", qty=1),
            row("epi540", "540", cf="RE0", cc="601401", qty=1),
            row("epi_over_op", "520", cc="601401", op="OP123", qty=1),
            row("tc_tp", "520", kind="MP", cc="987654", group="MATERIAL USADO TC/TP", qty=1),
            row("tc_tp_desc", "520", kind="MP", desc="MATERIAL USADO TC TP", qty=1),
            row("tp_only", "520", kind="MP", desc="TRANSFORMADOR DE POTENCIAL TP", qty=1, cc="600307"),
            row("not_epi", "520", cc="123456", cf="601401", qty=1),
            row("adjust_020", "020", kind="MP", cc="600307"),
            row("adjust_520", "520", kind="MP", cc="600307"),
            row("return_040", "040", kind="MP", cc="600307"),
            row("production_precedes_return", "040", kind="PI", cc="600307"),
            row("sheet_precedes_return", "040", kind="MP", cc="600307", code=self.sheet),
            row("original_ii", "520", kind="II", cc="600307"),
        ])
        tagged = cond.classify(rows, self.data).set_index("id_registro")
        expected = {
            "epi520":cond.STOCK_ADJUSTMENT, "epi540":cond.EPI,
            "epi_over_op":cond.CONSUMPTION,
            "tc_tp":cond.STOCK_ADJUSTMENT, "tc_tp_desc":cond.STOCK_ADJUSTMENT,
            "tp_only":cond.STOCK_ADJUSTMENT, "not_epi":cond.STOCK_ADJUSTMENT,
            "adjust_020":cond.STOCK_ADJUSTMENT, "adjust_520":cond.STOCK_ADJUSTMENT,
            "return_040":cond.PRODUCTION_RETURN,
            "production_precedes_return":cond.PRODUCTION,
            "sheet_precedes_return":cond.SHEET_BAR,
            "original_ii":cond.STOCK_ADJUSTMENT,
        }
        self.assertEqual(tagged["subgrupo_usuario"].to_dict(), expected)
        self.assertEqual(tagged.loc["tc_tp", "tipo_analise"], "II")
        self.assertEqual(tagged.loc["tc_tp", "tipo"], "MP")
        self.assertEqual(tagged.loc["tc_tp_desc", "tipo_analise"], "II")
        self.assertEqual(tagged.loc["tp_only", "tipo_analise"], "MP")
        self.assertEqual(tagged["valor_entrada"].sum(), rows["valor_entrada"].sum())
        self.assertEqual(tagged["valor_saida"].sum(), rows["valor_saida"].sum())
        self.assertEqual(len(tagged), len(rows))
        self.assertEqual(tagged.loc["epi520", "condicao_ordem"], 1)

    def test_new_warehouse_and_sheet_rules_override_lower_priority(self):
        frame = pd.DataFrame([
            row("epi_ep", "520", warehouse="EP", cc="999999", qty=2),
            row("epi_ep_with_op", "520", warehouse="ep", op="OP456", qty=3),
            row("epi_ep_ii", "520", warehouse="EP", kind="II", cc="600307", qty=3),
            row("epi_ep_no_baixa", "520", warehouse="EP", cc="999999", qty=0),
            row("epi_s2", "520", warehouse="S2", cc="999999", qty=2),
            row("transfer", "547", warehouse="EP", qty=1, op="OP456"),
            row("transfer_no_saida", "547", warehouse="S2"),
            row("sheet520", "520", cc="600307", qty=2, code=self.sheet),
            row("sheet520_no_baixa", "520", cc="600307", qty=0, code=self.sheet),
            row("sheet520_ii", "520", cc="600307", kind="II", qty=4, code=self.sheet),
            row("sheet550", "550", cc="600307", qty=3, code=self.sheet),
            row("default_547_untouched", "020", cc="", kind="MP"),
        ])
        tagged = cond.classify(frame, self.data).set_index("id_registro")
        self.assertEqual(tagged.loc["epi_ep", "subgrupo_usuario"], cond.STOCK_ADJUSTMENT)
        self.assertEqual(tagged.loc["epi_ep_with_op", "subgrupo_usuario"], cond.EPI)
        self.assertEqual(tagged.loc["epi_ep_ii", "subgrupo_usuario"], cond.STOCK_ADJUSTMENT)
        self.assertEqual(tagged.loc["epi_ep_no_baixa", "subgrupo_usuario"], cond.STOCK_ADJUSTMENT)
        self.assertEqual(tagged.loc["epi_s2", "subgrupo_usuario"], cond.STOCK_ADJUSTMENT)
        self.assertEqual(tagged.loc["transfer", "subgrupo_usuario"], cond.TRANSFER)
        self.assertEqual(tagged.loc["transfer_no_saida", "subgrupo_usuario"], cond.TRANSFER)
        self.assertEqual(tagged.loc["sheet520", "subgrupo_usuario"], cond.STOCK_ADJUSTMENT)
        self.assertEqual(tagged.loc["sheet520_ii", "subgrupo_usuario"], cond.STOCK_ADJUSTMENT)
        self.assertEqual(tagged.loc["sheet520_no_baixa", "subgrupo_usuario"], cond.STOCK_ADJUSTMENT)
        self.assertEqual(tagged.loc["sheet550", "subgrupo_usuario"], cond.SHEET_BAR)
        self.assertEqual(tagged.loc["default_547_untouched", "subgrupo_usuario"], cond.STOCK_ADJUSTMENT)
        self.assertEqual(tagged["valor_saida"].sum(), frame["valor_saida"].sum())
        self.assertEqual(len(tagged), len(frame))

    def test_fallback_stock_group_is_renamed_without_changing_group(self):
        active = cfg.delete_condition(self.data, "kardex_cond_09_ajuste_estoque", known_tes=self.known)
        tagged = cond.classify(pd.DataFrame([
            row("fallback", "020", cc="600307"),
            row("other_group", "999")
        ]), active).set_index("id_registro")
        self.assertEqual(tagged.loc["fallback", "grupo_usuario"], "FLUXO DE ESTOQUE")
        self.assertEqual(tagged.loc["fallback", "subgrupo_usuario"], cond.FALLBACK_STOCK)
        self.assertEqual(tagged.loc["other_group", "subgrupo_usuario"], "SEM GRUPO")

    def test_v3_migration_prepends_two_new_conditions_only_once(self):
        old = {"versao":3, "grupos": self.data["grupos"],
               "condicoes": [dict(x) for x in self.data["condicoes"]
                            if x["regra"] not in ("consumo_epi_ep", "transferencia_armazem", "ajuste_520_sem_op")]}
        converted = cfg.validated(old, self.known)
        self.assertEqual(converted["versao"], 6)
        self.assertEqual(
            [x["regra"] for x in converted["condicoes"][:3]],
            ["ajuste_520_sem_op", "consumo_epi_ep", "transferencia_armazem"]
        )
        self.assertEqual(converted["condicoes"][3:], old["condicoes"])
        self.assertEqual(cfg.validated(converted, self.known), converted)

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
        self.assertEqual(migrated["versao"], 6)
        self.assertEqual(len(migrated["condicoes"]), 13)
        self.assertEqual(migrated["grupos"], old["grupos"])
        self.assertEqual(
            [item["regra"] for item in migrated["condicoes"]],
            [item["regra"] for item in cond.TEMPLATES],
        )
        removed = cfg.delete_condition(migrated, "kardex_cond_07_consumo_epi", known_tes=self.known)
        self.assertEqual(len(cfg.validated(removed,self.known)["condicoes"]), 12)
        self.assertNotIn("kardex_cond_07_consumo_epi", [
            x["id"] for x in cfg.validated(removed,self.known)["condicoes"]
        ])

    def test_old_config_migrates_without_losing_groups_or_resurrecting_deleted_rules(self):
        old = {"versao":1,"grupos":[{"id":"old","nome":"TESTE","tes":["520"]}],
               "condicoes":[]}
        upgraded = cfg.validated(old,self.known)
        self.assertEqual(upgraded["versao"],6)
        self.assertEqual(upgraded["grupos"][0]["nome"],"TESTE")
        self.assertEqual(len(upgraded["condicoes"]),13)
        filtered = cfg.delete_condition(upgraded,cond.TEMPLATES[0]["id"],known_tes=self.known)
        self.assertEqual(len(cfg.validated(filtered)["condicoes"]),12)


if __name__ == "__main__":
    unittest.main()
