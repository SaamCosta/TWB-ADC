"""
Bandeiras por valor (docs/backend.md §8.82): `core/flag_planner.py` e o
caminho de `DefenceManager.flag_value_logic`.

O que cada caso prova, com o dado de onde veio:
- a tabela de percentual por nível sai do `title` da tela (fixture verbatim);
- a bandeira de produção SOMA ao percentual (BBM 030, 1/7, lido 1,46; o
  produto daria 1,508) e o valor dela é a taxa de produção da relíquia;
- `pop_max` com a bandeira de população = piso(fazenda x 1,06) (BBM 062) e
  ela vale 0 com a fazenda com folga;
- a coleta: `unit_carry_factor` 1,08 com a bandeira de saque, a duração da
  fórmula do JS bate com o `return_time` do servidor em ~1 s, a elasticidade
  e a coleta só entrando no valor quando uma coleta do bot paga a mais;
- o plano (moeda e manual intocadas, desconhecido não troca, a bandeira
  largada volta à sobra) e os freios (piso, %, leituras, teto do dia, 48 h);
- `DefenceManager`: dry-run não posta e a ordem fixa segue agindo; ligado
  posta uma vez, lê o inventário antes se não estiver fresco, e não posta
  quando a bandeira mudou desde o plano ou quando o jogo recusa.

Sem rede, relógio injetado; `cache/flags.json` vai para um diretório
temporário (21º padrão: teste não escreve no artefato que o bot tem aberto).

Rodar: python tests/test_flag_value.py
"""
import json
import logging
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import flag_planner as FP
from core import relic_planner as RP
from core.extractors import Extractor
import game.defence_manager as DMmod
from game.defence_manager import DefenceManager

logging.disable(logging.CRITICAL)
failures = []
HERE = os.path.dirname(os.path.abspath(__file__))
FX = json.load(open(os.path.join(HERE, "fixtures", "flag_value_br143.json"), encoding="utf-8"))
NOW = time.mktime((2026, 10, 30, 15, 0, 0, 0, 0, -1))
TMP = tempfile.mkdtemp(prefix="flagvalue_")
DMmod.FLAG_VALUE_PATH = os.path.join(TMP, "flags.json")


def check(cond, msg):
    if not cond:
        failures.append(msg)


def opts():
    return FX["scavenge_options"]


# -- medições ---------------------------------------------------------------

def test_effects_table_comes_from_the_screen():
    eff = FP.parse_flag_effects("\n".join(FX["flag_boxes"]))
    check(sorted(eff) == list(range(1, 9)), "8 tipos: %s" % sorted(eff))
    check(all(len(v) == 9 for v in eff.values()), "9 níveis por tipo")
    check(eff == {t: {l: float(p) for l, p in lv.items()} for t, lv in FP.FLAG_PCT.items()},
          "FLAG_PCT é a mesma captura")
    check(eff[8][7] == 8.0 and eff[1][7] == 16.0 and eff[7][9] == 24.0, "saque 7, produção 7, moeda 9")
    check(FP.parse_flag_effects("<div>sem tabela</div>") == {}, "tela sem tabela: {}")


def test_production_flag_is_additive():
    b = FX["bbm030"]
    base = {r: RP.mine_production(b["mines"][r], 1.0, 60) for r in RP.RESOURCES}
    pct = FP.flag_pct(None, *b["flag"])
    for r in RP.RESOURCES:
        ratio = b["prod_h"][r] / base[r]
        additive = 1 + (b["board_pct"] + pct) / 100.0
        multiplicative = (1 + b["board_pct"] / 100.0) * (1 + pct / 100.0)
        check(abs(ratio - additive) < 0.002, "%s: lido %.4f, aditiva %.4f" % (r, ratio, additive))
        check(abs(ratio - multiplicative) > 0.04, "%s: a multiplicativa tem que errar" % r)
    inputs = {"base_prod_h": base, "cap_frac": {"wood": 0.5}}
    rate, why = FP.flag_rate(1, inputs)
    want = sum(RP.attribute_rate({"kind": "production", "resource": r}, inputs)[0]
               for r in RP.RESOURCES)
    check(why is None and abs(rate - want) < 1e-9, "taxa de produção = a da relíquia")
    check(FP.flag_rate(1, {})[0] is None, "sem nível de mina: desconhecido, não zero")


def test_recruit_flag_unknown_when_ceded():
    # BBM 064 em 30/10: recrutamento cedido ao gerente, com linhas antigas do
    # bot (fila 3% ocupada). As linhas do bot não contam a fila do gerente.
    seen = {"recruit_busy": {"barracks": 0.03}, "recruit_h": {"barracks": 40.0}}
    check(FP.flag_rate(2, seen)[0] == 0.0, "o bot recruta e a fila não é gargalo: 0")
    check(FP.flag_rate(2, dict(seen, recruit_ceded=True))[0] is None, "cedido: desconhecido")


def test_population_flag_measured_and_worth_zero_with_room():
    p = FX["pop"]["bbm062"]
    check(int(FX["pop"]["farm17_no_flag"] * 1.06) == p["pop_max"], "piso(3045 x 1,06) = 3227")
    check(FP.pop_base(p["pop_max"], p["flag"]) == FX["pop"]["farm17_no_flag"], "pop_max sem a bandeira")
    rate, why = FP.flag_rate(6, {"pop": p["pop"], "pop_max": p["pop_max"]})
    check(rate == 0.0 and "folga" in why, "BBM 062 usa 1541 de 3227: vale 0 (%s)" % why)
    check(FP.flag_rate(6, {})[0] is None, "sem população lida: desconhecido")
    capped = {"pop": 3200, "pop_max": 3227, "pop_max_base": 3045, "troop_pop": 3000,
              "farm_carry_h": 1000.0, "farm_full": 0.5}
    rate, _ = FP.flag_rate(6, capped, haul_scavenge=False)
    check(abs(rate - 500.0 / 3000 * 3045 / 100) < 1e-6, "no teto: saque por pop x 1%% da fazenda (%s)" % rate)


def test_scavenge_carry_factor_and_duration():
    village = json.loads(FX["scavenge_village"])
    check(village["unit_carry_factor"] == 1.08, "fator 1,08 com a bandeira 8/7")
    sent = time.mktime(tuple(FX["sent_at_local"]) + (0, 0, -1))
    for option, state in village["options"].items():
        sq = state["scavenging_squad"]
        opt = opts()[option]
        d = FP.scavenge_duration(sq["carry_max"], opt)
        check(abs((sq["return_time"] - sent) - d) <= 2.0,
              "opção %s: duração %.0f contra %d do servidor" % (option, d, sq["return_time"] - sent))
        msg = json.loads(FP.squad_event("38997", option, sq, opt, village["unit_carry_factor"]))
        check(msg["nominal"] == sq["carry_max"], "carga nominal pelas unidades (opção %s)" % option)
        check(abs(msg["loot"] - msg["nominal"] * opt["loot_factor"]) <= 3,
              "saiu antes da bandeira: saque nominal (opção %s)" % option)
        check(msg["factor"] == 1.08, "o fator vai junto")
    e0 = FP.scavenge_elasticity(115280, opts()["1"])
    e2 = FP.scavenge_elasticity(115280, opts()["1"], wait=7200)
    check(0.13 < e0 < 0.16 and 0.26 < e2 < 0.30, "elasticidade 0,14 sem espera, 0,28 com 2 h (%s, %s)" % (e0, e2))


def test_scavenge_counts_only_when_a_bot_squad_paid_more():
    village = json.loads(FX["scavenge_village"])
    sq = village["options"]["1"]["scavenging_squad"]
    nominal_only = {1: (0, "1", json.loads(FP.squad_event("1", 1, sq, opts()["1"], 1.08)))}
    check(FP.haul_scavenge_measured(nominal_only) is FP.HAUL_SCAVENGE, "saque nominal não prova nada")
    paid = dict(sq, unit_id=2, loot_res={"wood": 4150, "stone": 4150, "iron": 4150})
    more = {2: (0, "1", json.loads(FP.squad_event("1", 1, paid, opts()["1"], 1.08)))}
    check(FP.haul_scavenge_measured(more) is True, "saque 1,08x: entra")
    inputs = {"farm_carry_h": 0.0, "farm_full": 0.2, "scav_rate_h": 1000.0}
    check(FP.flag_rate(8, inputs, haul_scavenge=None)[0] is None, "não medido: desconhecido")
    check(FP.flag_rate(8, inputs, haul_scavenge=True)[0] == 10.0, "medido: 1%% da taxa com elasticidade")
    check(FP.flag_rate(8, inputs, haul_scavenge=False)[0] == 0.0, "refutado: só o farm (0)")


def test_gather_reports_every_squad_underway():
    from game.troopmanager import TroopManager

    class Reporter:
        def __init__(self):
            self.lines = []

        def report(self, vid, event, msg):
            self.lines.append((vid, event, msg))

    page = ("var village = %s;\n new ScavengeScreen(\n %s, {}, 1, {});" % (
        FX["scavenge_village"], json.dumps(FX["scavenge_options"])))
    tm = TroopManager.__new__(TroopManager)
    tm.village_id = "38997"
    tm.logger = logging.getLogger("t")
    tm.wrapper = type("W", (), {"reporter": Reporter()})()
    tm.report_scavenge_squads(page, Extractor.village_data(page))
    lines = tm.wrapper.reporter.lines
    check(len(lines) == 4 and {l[1] for l in lines} == {"TWB_GATHER_SQUAD"}, "4 coletas: %s" % len(lines))
    parsed = [json.loads(l[2]) for l in lines]
    check({p["option"] for p in parsed} == {1, 2, 3, 4} and all(p["factor"] == 1.08 for p in parsed),
          "uma por opção, com o fator")
    tm.report_scavenge_squads("<html>markup novo</html>", None)
    check(len(lines) == 4, "tela sem coleta: nada, sem exceção")


def test_haul_inputs_from_recorded_squads():
    sq = json.loads(FX["scavenge_village"])["options"]["1"]["scavenging_squad"]
    events = {"farm": [(NOW - 3600, "38997", 800)], "squads_since": NOW - 24 * 3600, "squads": {}}
    for k in range(3):
        s = dict(sq, unit_id=k, return_time=int(NOW - 24 * 3600 + 40000 * (k + 1)))
        events["squads"][k] = (NOW, "38997", json.loads(FP.squad_event("38997", 1, s, opts()["1"], 1)))
    out = FP.haul_inputs(["38997"], events, ({}, 0.25), NOW)["38997"]
    check(abs(out["scav_loot_h"] - 3 * 11528 / 24.0) < 1, "saque/h = soma / 24 h (%s)" % out["scav_loot_h"])
    check(out["scav_rate_h"] < out["scav_loot_h"] * 0.4, "elasticidade aplicada")
    check(abs(out["farm_carry_h"] - 800 / 168.0) < 1e-9 and out["farm_full"] == 0.25, "farm")
    early = FP.haul_inputs(["38997"], dict(events, squads_since=NOW - 3600), ({}, 0.25), NOW)["38997"]
    check(early["scav_rate_h"] is None, "menos de 6 h de registro: desconhecido")


# -- plano e freios ---------------------------------------------------------

def base_inputs():
    return {
        "a": {"recruit_busy": {"barracks": 0.1}, "recruit_h": {"barracks": 50.0},
              "farm_carry_h": 0.0, "farm_full": 0.2, "scav_rate_h": 90000.0},
        "b": {"base_prod_h": {"wood": 4800.0, "stone": 4800.0, "iron": 4800.0}},
        "c": {"farm_carry_h": 0.0, "scav_rate_h": 90000.0},
        "d": {"scav_rate_h": 90000.0},
    }


def test_plan_moves_spare_haul_to_zero_value_recruit():
    villages = {"a": {"current": [2, 2]}, "b": {"current": [7, 5]},
                "c": {"current": [3, 1]}, "d": {"current": [2, 1], "under_attack": True}}
    p = FP.plan(villages, {"8": {"7": 1}, "7": {"3": 1}}, base_inputs(), haul_scavenge=True)
    check(len(p["steps"]) == 1, "um passo: %s" % p["steps"])
    s = p["steps"][0]
    check(s["vid"] == "a" and s["to"] == [8, 7] and s["from"] == [2, 2], "recrutamento 0 -> saque 7")
    check(abs(s["gain_h"] - 7200.0) < 0.1, "900/h por ponto x 8 = 7200 (%s)" % s["gain_h"])
    check(p["values"]["b"]["value"] is None, "moeda: desconhecido, fica")
    check(all(st["vid"] != "c" for st in p["steps"]), "manual intocada")
    check(all(st["vid"] != "d" for st in p["steps"]), "sob ataque não entra")
    p2 = FP.plan(villages, {"8": {"7": 1}}, base_inputs(), haul_scavenge=None)
    check(p2["steps"] == [], "saque não medido: nada troca")


def test_plan_chain_returns_dropped_flag_to_supply():
    inputs = {"x": {"base_prod_h": {"wood": 4800.0, "stone": 4800.0, "iron": 4800.0}},
              "y": {"base_prod_h": {"wood": 1000.0, "stone": 1000.0, "iron": 1000.0}}}
    villages = {"x": {"current": [1, 1]}, "y": {"current": None}}
    p = FP.plan(villages, {"1": {"7": 1}}, inputs)
    check([s["vid"] for s in p["steps"]] == ["x", "y"], "x pega a 1/7, y a 1/1 que x largou: %s" % p["steps"])
    check(p["steps"][1]["to"] == [1, 1], "a largada volta à sobra")


def test_plan_ignores_villages_outside_the_account():
    managed = {"a": {"flags": {"flag_state_confirmed": True, "current_flag": [2, 2]}},
               "lost": {"flags": {"flag_state_confirmed": True, "current_flag": [2, 2]}}}
    inputs = {"a": dict(base_inputs()["a"], scav_rate_h=1000.0), "lost": base_inputs()["a"]}
    cache = FakeCache(managed, inputs)
    p = FP.plan_for_village("a", {"current": [2, 2], "can_change": True}, {8: {7: 1}},
                            cache=cache, now=NOW, vids=["a"])
    check(p["step"] and p["step"]["to"] == [8, 7], "sem a perdida, a 8/7 vai para a: %s" % p["steps"])
    p = FP.plan_for_village("a", {"current": [2, 2], "can_change": True}, {8: {7: 1}},
                            cache=cache, now=NOW)
    check(p["step"] is None, "controle: com a perdida no plano, ela leva a 8/7")


def cfg(**kw):
    c = FP.settings({})
    c.update(kw)
    return c


def test_brakes():
    step = {"vid": "a", "from": [2, 2], "to": [8, 7], "gain_h": 80.0, "value_before_h": 0.0, "text": "x"}
    st = {}
    check(not FP.evaluate(dict(step, gain_h=40.0), st, cfg(), NOW)[0], "abaixo do piso")
    check(not FP.evaluate(dict(step, value_before_h=1000.0), st, cfg(), NOW)[0], "abaixo de 10% da atual")
    FP.note_read(st, "a", step, NOW)
    ok, why = FP.evaluate(step, st, cfg(), NOW)
    check(not ok and "1 de 2" in why, "1 leitura não basta: %s" % why)
    FP.note_read(st, "a", step, NOW + 4 * 3600)
    check(FP.evaluate(step, st, cfg(), NOW + 4 * 3600)[0], "2 leituras seguidas: sai")
    FP.note_read(st, "a", dict(step, to=[8, 6]), NOW + 8 * 3600)
    check(not FP.evaluate(step, st, cfg(), NOW + 8 * 3600)[0], "passo diferente recomeça a conta")
    st = {"streak": {"a": {"key": FP.step_key(step), "count": 5}},
          "days": {FP.server_day(NOW): {"changes": 3}}}
    ok, why = FP.evaluate(step, st, cfg(), NOW)
    check(not ok and "teto do dia" in why, "teto do dia: %s" % why)
    st = {"streak": {"a": {"key": FP.step_key(step), "count": 5}}}
    FP.record(st, step, True, "aceita", NOW)
    check(st["days"][FP.server_day(NOW)]["changes"] == 1 and "a" not in st["streak"], "registro")
    st["streak"]["a"] = {"key": FP.step_key(step), "count": 5}
    ok, why = FP.evaluate(step, st, cfg(), NOW + 3600)
    check(not ok and "trocou" in why, "48 h sem trocar de novo: %s" % why)
    check(FP.evaluate(step, st, cfg(), NOW + 49 * 3600)[0], "depois das 48 h, sim")
    rec = {}
    FP.record(rec, step, False, "recusa", NOW)
    check("days" not in rec, "recusa não conta no teto")
    check(FP.settings({"flag_value": {"mode": "bogus", "min_gain_h": "x"}})["mode"] == "dry_run",
          "modo ilegível cai no padrão")


# -- DefenceManager ---------------------------------------------------------

class FakeCache:
    def __init__(self, managed, inputs, haul=True):
        self.data = {"managed": managed, "inputs": inputs, "haul_scavenge": haul,
                     "squads": 4, "squads_since": NOW - 86400}

    def get(self, root, now, world=None):
        return self.data


PAGE = ('<div id="current_flag" style="margin-top: 10px">'
        '<img src="https://x/graphic/flags/big/2_2.webp"><p>+8% na velocidade</p> </div>'
        '<script>FlagsScreen.setFlagCounts({"8":{"7":"1"},"2":{"2":"0"}});</script>'
        + "\n".join(FX["flag_boxes"]))


class FakeResponse:
    def __init__(self, text):
        self.text = text


class FakeWrapper:
    def __init__(self, text=PAGE):
        self.text, self.gets, self.posts, self.last_h = text, [], [], "h"

    def get_url(self, url):
        self.gets.append(url)
        return FakeResponse(self.text)

    def get_api_action(self, village_id, action, params=None, data=None):
        self.posts.append((action, dict(data or {})))
        return {"response": {}, "game_data": {}}


def make(mode, fresh=True, streak=2, refuse=False):
    if os.path.exists(DMmod.FLAG_VALUE_PATH):
        os.remove(DMmod.FLAG_VALUE_PATH)
    step = {"vid": "38997", "from": [2, 2], "to": [8, 7]}
    with open(DMmod.FLAG_VALUE_PATH, "w", encoding="utf-8") as fh:
        json.dump({"exec": {"streak": {"38997": {"key": FP.step_key(step), "count": streak - 1}}}}, fh)
    FP.INPUTS = FakeCache({"38997": {"name": "BBM 005"}}, {"38997": base_inputs()["a"]})
    w = FakeWrapper()
    if refuse:
        w.get_api_action = lambda *a, **k: (w.posts.append(("assign_flag", k.get("data"))) or
                                            {"error": ["Você não pode trocar agora"]})
    d = DefenceManager(village_id="38997", wrapper=w)
    d.manage_flags_enabled = True
    d.has_academy = True
    d.current_flag = [2, 2]
    d._flag_state_confirmed = True
    d._can_change_flag = True
    d._flags_fresh = fresh
    d.flags = {8: 7}
    d.flag_supply = {8: {7: 1}}
    d.value_mode = mode
    d.value_cfg = cfg(mode=mode)
    return d, w


def test_dry_run_never_posts_and_order_still_acts():
    d, w = make("dry_run")
    d.flag_logic(d.preferred_flags())
    old_posts = len(w.posts)
    d.flag_value_logic(act=False)
    check(len(w.posts) == old_posts, "dry-run não posta")
    check(d.value_result and d.value_result["step"]["to"] == [8, 7], "o passo aparece no cache")
    check(d.value_result["ok"], "o freio o deixaria sair (%s)" % d.value_result["why"])
    saved = json.load(open(DMmod.FLAG_VALUE_PATH, encoding="utf-8"))
    check(saved["plan"]["steps"][0]["to"] == [8, 7] and saved["plan"]["mode"] == "dry_run", "plano gravado")


def test_on_posts_once_with_fresh_inventory():
    d, w = make("on")
    d.flag_value_logic(act=True)
    assigns = [p for p in w.posts if p[0] == "assign_flag"]
    check(len(assigns) == 1 and assigns[0][1]["flag_type"] == "8" and assigns[0][1]["level"] == "7",
          "um assign_flag 8/7: %s" % w.posts)
    check(d.current_flag == [8, 7] and w.gets == [], "estado novo, sem GET (já fresco)")
    saved = json.load(open(DMmod.FLAG_VALUE_PATH, encoding="utf-8"))
    check(saved["exec"]["days"][FP.server_day(time.time())]["changes"] == 1, "conta no teto")
    d.flag_value_logic(act=True)
    check(len([p for p in w.posts if p[0] == "assign_flag"]) == 1, "nada mais sai (ela já tem a 8/7)")


def test_on_reads_inventory_first_when_stale():
    d, w = make("on", fresh=False)
    d.runs = 5
    d.flag_value_logic(act=True)
    check(len(w.gets) == 1 and "screen=flags" in w.gets[0], "1 GET da tela de bandeiras antes")
    check(len([p for p in w.posts if p[0] == "assign_flag"]) == 1, "depois troca")


def test_on_does_not_post_when_flag_changed_since_plan():
    d, w = make("on", fresh=False)
    w.text = PAGE.replace("2_2.webp", "1_4.webp")
    d.flag_value_logic(act=True)
    check(d.current_flag == [1, 4], "a releitura viu a troca do jogador")
    check(not [p for p in w.posts if p[0] == "assign_flag"], "o jogador trocou: nenhum POST")


def test_on_waits_for_stable_reads_and_counts_refusal_out():
    d, w = make("on", streak=1)
    d.flag_value_logic(act=True)
    check(not w.posts, "visto 1 vez: não sai")
    d, w = make("on", refuse=True)
    d.flag_value_logic(act=True)
    saved = json.load(open(DMmod.FLAG_VALUE_PATH, encoding="utf-8"))
    check(d.current_flag == [2, 2], "recusa não muda o estado")
    check("days" not in saved["exec"] and saved["exec"]["history"][-1]["ok"] is False, "recusa registrada")


def test_on_leaves_manual_and_locked_alone():
    d, w = make("on")
    d.current_flag = [3, 1]
    d.flag_value_logic(act=True)
    check(not w.posts, "bandeira manual: nada")
    d, w = make("on")
    d.flag_lock_reason = "Bônus de bandeira ativo"
    d.flag_value_logic(act=True)
    check(not w.posts, "trava da cunhagem: nada")


def test_update_routes_by_mode():
    for mode, expect_value in (("off", False), ("dry_run", True), ("on", True)):
        d, w = make(mode)
        calls = []
        d.flag_logic = lambda s, c=calls: c.append("order")
        d.flag_value_logic = lambda act, c=calls: c.append("value:%s" % act)
        d.manage_flags = lambda force=False: None
        d.update("<html></html>", with_defence=False)
        want = {"off": ["order"], "dry_run": ["order", "value:False"], "on": ["value:True"]}[mode]
        check(calls == want, "%s: %s" % (mode, calls))


for fn in [
    test_effects_table_comes_from_the_screen,
    test_production_flag_is_additive,
    test_recruit_flag_unknown_when_ceded,
    test_population_flag_measured_and_worth_zero_with_room,
    test_scavenge_carry_factor_and_duration,
    test_scavenge_counts_only_when_a_bot_squad_paid_more,
    test_gather_reports_every_squad_underway,
    test_haul_inputs_from_recorded_squads,
    test_plan_moves_spare_haul_to_zero_value_recruit,
    test_plan_chain_returns_dropped_flag_to_supply,
    test_brakes,
    test_plan_ignores_villages_outside_the_account,
    test_dry_run_never_posts_and_order_still_acts,
    test_on_posts_once_with_fresh_inventory,
    test_on_reads_inventory_first_when_stale,
    test_on_does_not_post_when_flag_changed_since_plan,
    test_on_waits_for_stable_reads_and_counts_refusal_out,
    test_on_leaves_manual_and_locked_alone,
    test_update_routes_by_mode,
]:
    fn()

if failures:
    print("FALHOU (%d problema(s)):" % len(failures))
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("OK: bandeiras por valor (medições, plano, freios e DefenceManager)")
