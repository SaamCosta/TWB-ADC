"""
O `carry_max` da coleta como o JS do jogo manda, e o registro da coleta no
envio (docs/backend.md §8.84, 2ª etapa do saque da §8.82).

O que cada caso prova, com o dado de onde veio
(`tests/fixtures/scavenge_carry_br143.json`, captura de 03/11):
- `calc_max_loot` é o `LootCalculator.calcMaxLoot` do bundle estático
  `Farming.ec8d44.js` (verbatim): soma carga x quantidade, vezes o fator,
  arredondando meio para cima; a carga por unidade da própria tela bate com
  `UNIT_CARRY`;
- o servidor NÃO guarda o `carry_max` postado: os 4 POST da BBM 005 às 11:10
  mandaram 149.145/59.658/29.829/19.886, e a tela das 17:56 mostra
  149.120/59.630/29.820/19.885 = carga das unidades, com o saque = isso x
  `loot_factor`;
- `gather()` (avançado e básico) manda `calcMaxLoot(unidades, fator)`: com
  fator 1 é exatamente o que o servidor guardou; com 1,08, +8%;
- cada coleta aceita deixa uma linha `TWB_GATHER_SQUAD` com `src: "sent"`,
  recusa não deixa; a linha do envio dá saque/h ao planejador e NÃO conta
  como prova de que a bandeira paga.

Sem rede; `time.sleep` do envio trocado por nada durante o teste.

Rodar: python tests/test_scavenge_carry.py
"""
import json
import logging
import os
import sys
import tempfile
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import flag_planner as FP
from core.extractors import Extractor
from core.templates import UNIT_CARRY
import game.troopmanager as TMmod
from game.troopmanager import TroopManager

logging.disable(logging.CRITICAL)
failures = []
HERE = os.path.dirname(os.path.abspath(__file__))
FX = json.load(open(os.path.join(HERE, "fixtures", "scavenge_carry_br143.json"), encoding="utf-8"))
NOW = 1793739360  # 03/11 17:56, a leitura da fixture


def check(cond, msg):
    if not cond:
        failures.append(msg)


def posted():
    """{opção: (unidades, carry_max postado)} dos 4 POST da fixture."""
    out = {}
    for line in FX["posted"]:
        body = urllib.parse.parse_qs(line.split(" | ", 1)[1])
        pre = "squad_requests[0][candidate_squad][unit_counts]["
        units = {k[len(pre):-1]: int(v[0]) for k, v in body.items() if k.startswith(pre) and int(v[0])}
        out[body["squad_requests[0][option_id]"][0]] = (
            units, int(body["squad_requests[0][candidate_squad][carry_max]"][0]))
    return out


def page(factor=1, free=True, home=None):
    village = json.loads(json.dumps(FX["village"]))
    village["unit_carry_factor"] = factor
    if free:
        for st in village["options"].values():
            st["scavenging_squad"] = None
    if home is not None:
        village["unit_counts_home"] = home
    return ("var village = %s;\n new ScavengeScreen(\n %s, village,\n %s,\n 10, {});"
            % (json.dumps(village), json.dumps(FX["scavenge_options"]), json.dumps(FX["sendable_units"])))


class Reporter:
    def __init__(self):
        self.lines = []

    def report(self, vid, event, msg):
        self.lines.append((vid, event, msg))


class Wrapper:
    def __init__(self, text, refuse=()):
        self.text, self.refuse, self.posts = text, set(refuse), []
        self.last_h = "h"
        self.reporter = Reporter()

    def get_url(self, url):
        return type("R", (), {"text": self.text})()

    def get_api_action(self, action, params, data, village_id):
        self.posts.append(dict(data))
        if data["squad_requests[0][option_id]"] in self.refuse:
            return {"error": ["Não existem unidades suficientes"]}
        return {"response": {"squad_responses": [{"success": True}]}, "game_data": {}}


def run_gather(text, advanced=True, selection=4, refuse=()):
    tm = TroopManager.__new__(TroopManager)
    tm.wrapper = Wrapper(text, refuse)
    tm.village_id = "38997"
    tm.logger = logging.getLogger("t")
    tm.can_gather = True
    tm.total_troops = {}
    tm.conquest_reserve = {}
    tm.keep_resources = {}
    sleep = TMmod.time.sleep
    TMmod.time.sleep = lambda s: None
    try:
        tm.gather(selection=selection, disabled_units=[], advanced_gather=advanced)
    finally:
        TMmod.time.sleep = sleep
    return tm


def units_of(post):
    return TroopManager.squad_units(post)


# -- o JS e o servidor ----------------------------------------------------------

def test_port_matches_the_captured_js():
    js = FX["loot_calculator_js"]
    for piece in ("n.roundLoot=function(t){return~~(t+.50000000001)}",
                  "n.can_attack&&void 0!==o[t]&&(r+=n.carry*o[t])",
                  "n.roundLoot(r*t)"):
        check(piece in js, "o bundle capturado não tem %r" % piece)
    for unit, stats in FX["sendable_units"].items():
        if unit in UNIT_CARRY:
            check(stats["carry"] == UNIT_CARRY[unit], "carga de %s: tela %s, UNIT_CARRY %s"
                  % (unit, stats["carry"], UNIT_CARRY[unit]))
    check(FP.calc_max_loot({"light": 1441}, 1.08) == 124502, "1.441 leves x 80 x 1,08")
    check(FP.calc_max_loot({"light": 10}, 1.05) == 840, "o exemplo do fórum (10 leves, +5%)")
    check(FP.calc_max_loot({"spear": 1}, 1.02) == 26, "25,5 arredonda para cima, como ~~(t+.5)")
    for bad in (None, "x", 0, -1):
        check(FP.calc_max_loot({"axe": 7}, bad) == 70, "fator %r vale 1, como o JS" % (bad,))
    check(FP.calc_max_loot({"axe": "x", "spy": 9, "spear": "2"}, 1) == 50, "espião não carrega; lixo ignorado")


def test_server_keeps_unit_carry_not_the_posted_value():
    sent = posted()
    stored = {k: st["scavenging_squad"] for k, st in FX["village"]["options"].items()}
    check(set(sent) == set(stored) == {"1", "2", "3", "4"}, "as 4 opções nos dois lados")
    for opt, (units, carry_posted) in sent.items():
        sq = stored[opt]
        got = {u: int(n) for u, n in sq["unit_counts"].items() if int(n)}
        check(got == units, "opção %s: as unidades são as postadas" % opt)
        check(carry_posted > sq["carry_max"], "opção %s: o bot postou acima da carga" % opt)
        check(sq["carry_max"] == FP.calc_max_loot(units, 1), "opção %s: o servidor guardou a carga" % opt)
        lf = FX["scavenge_options"][opt]["loot_factor"]
        check(sum(sq["loot_res"].values()) == round(sq["carry_max"] * lf),
              "opção %s: saque = carga guardada x loot_factor" % opt)


def test_flag_paid_and_duration_stays_nominal_0411():
    """§8.85: a 8/7 na BBM 005, as 4 coletas do bot e a tela com elas em andamento."""
    day = FX["paid_0411"]
    factor = day["unit_carry_factor"]
    check(factor == 1.08, "a tela leu o fator da bandeira")
    check(len(day["posted"]) == 4, "4 POST")
    for line in day["posted"]:
        q = urllib.parse.parse_qs(line.split(" ", 1)[1])
        opt = q["squad_requests[0][option_id]"][0]
        units = {k.split("][")[-1].rstrip("]"): int(v[0]) for k, v in q.items()
                 if "[unit_counts]" in k and int(v[0])}
        sq = day["options"][opt]["scavenging_squad"]
        got = {u: int(n) for u, n in sq["unit_counts"].items() if int(n)}
        check(got == units, "opção %s: as unidades são as postadas" % opt)
        posted_cm = int(q["squad_requests[0][candidate_squad][carry_max]"][0])
        nominal, with_factor = FP.calc_max_loot(units, 1), FP.calc_max_loot(units, factor)
        check(posted_cm == with_factor == sq["carry_max"],
              "opção %s: postado = guardado = carga x 1,08 (%s, %s, %s)" % (
                  opt, posted_cm, sq["carry_max"], with_factor))
        lf = FX["scavenge_options"][opt]["loot_factor"]
        loot = sum(sq["loot_res"].values())
        check(loot == int(sq["carry_max"] * lf + 0.5), "opção %s: saque = guardado x loot_factor" % opt)
        check(loot > nominal * lf * 1.07, "opção %s: 8%% acima do nominal" % opt)
        # A duração sai da carga NOMINAL: o fator não alonga a coleta.
        elapsed = sq["return_time"] - day["sent"][opt]["sent_line_ts"]
        opt_t = FX["scavenge_options"][opt]
        d_nominal = FP.scavenge_duration(nominal, opt_t)
        d_factor = FP.scavenge_duration(with_factor, opt_t)
        check(abs(elapsed - d_nominal) <= 2, "opção %s: duração %d = a da carga nominal %.0f" % (
            opt, elapsed, d_nominal))
        check(d_factor - elapsed > 3000, "opção %s: a da carga com fator daria %.0f" % (opt, d_factor))
        check(FP.haul_scavenge_measured({"x": (0, "38997", json.loads(FP.squad_event(
            "38997", opt, sq, opt_t, factor)))}) is True, "opção %s: a linha da tela prova" % opt)
    check(FP.HAUL_SCAVENGE is True, "o valor medido está no código")
    rate, _ = FP.flag_rate(8, {"farm_carry_h": 0.0, "scav_loot_h": 1000.0, "scav_rate_h": 140.0},
                           haul_scavenge=FP.HAUL_SCAVENGE)
    check(rate == 10.0, "1%% do saque/h inteiro, sem a elasticidade: %s" % rate)


# -- o bot ------------------------------------------------------------------------

HOME = {"spear": 115, "sword": 0, "axe": 5310, "spy": 45, "light": 2531, "heavy": 0,
        "ram": 250, "catapult": 50, "knight": 1, "snob": 0, "militia": 0}


def test_advanced_gather_posts_js_carry_max():
    for factor in (1, 1.08):
        tm = run_gather(page(factor, home=HOME))
        posts = tm.wrapper.posts
        check(len(posts) == 4, "fator %s: 4 envios, veio %d" % (factor, len(posts)))
        for p in posts:
            units = units_of(p)
            want = FP.calc_max_loot(units, factor)
            got = int(p["squad_requests[0][candidate_squad][carry_max]"])
            check(got == want, "fator %s, opção %s: carry_max %s, JS daria %s"
                  % (factor, p["squad_requests[0][option_id]"], got, want))
        if factor == 1:
            nominal = [FP.calc_max_loot(units_of(p), 1) for p in posts]
            check([int(p["squad_requests[0][candidate_squad][carry_max]"]) for p in posts] == nominal,
                  "fator 1: exatamente a carga que o servidor guardaria")


def test_basic_gather_posts_js_carry_max():
    tm = run_gather(page(1.08, home=HOME), advanced=False)
    check(len(tm.wrapper.posts) == 1, "básico: um envio")
    p = tm.wrapper.posts[0]
    check(int(p["squad_requests[0][candidate_squad][carry_max]"]) == FP.calc_max_loot(units_of(p), 1.08),
          "básico: carga x 1,08")


def test_sent_squads_are_recorded_and_refused_are_not():
    tm = run_gather(page(1.08, home=HOME), refuse={"3"})
    lines = tm.wrapper.reporter.lines
    events = [json.loads(m) for _, ev, m in lines if ev == "TWB_GATHER_SQUAD"]
    check(sorted(e["option"] for e in events) == [1, 2, 4], "3 aceitas, a recusada fora: %s"
          % [e["option"] for e in events])
    check(all(e["src"] == "sent" and e["factor"] == 1.08 for e in events), "src sent, com o fator")
    for e in events:
        p = next(p for p in tm.wrapper.posts if p["squad_requests[0][option_id]"] == str(e["option"]))
        check(e["carry_max"] == int(p["squad_requests[0][candidate_squad][carry_max]"]),
              "o carry_max registrado é o postado")
        check(e["nominal"] == FP.calc_max_loot(units_of(p), 1), "nominal sem o fator")
        check(e["loot"] == round(e["nominal"] * e["lf"]), "saque pela carga nominal, não pelo fator")
    check(len({e["squad"] for e in events}) == 3, "uma chave por coleta")


def test_sent_lines_feed_the_rate_but_never_prove_the_flag():
    tmp = tempfile.mkdtemp(prefix="scavcarry_")
    opt = FX["scavenge_options"]["1"]
    with open(os.path.join(tmp, "twb_1.log"), "w", encoding="utf-8") as fh:
        for k in range(3):
            ts = NOW - 30 * 3600 + k * 40000
            msg = FP.sent_squad_event("38997", 1, {"light": 1864}, 161050, opt, 1.08, ts)
            fh.write("%d - 38997 - TWB_GATHER_SQUAD - %s\n" % (ts, msg))
    ev = FP.read_events(tmp, NOW)
    check(len(ev["squads"]) == 3, "3 envios lidos: %d" % len(ev["squads"]))
    # Sem o valor posto à mão (True desde §8.85), senão prova e não-prova
    # dão o mesmo True e os três casos abaixo não distinguem nada.
    saved, FP.HAUL_SCAVENGE = FP.HAUL_SCAVENGE, None
    try:
        check(FP.haul_scavenge_measured(ev["squads"]) is None,
              "linha de envio com carry_max x 1,08 não prova a bandeira")
        # Mesmo que um dia a linha do envio traga saque acima do nominal (a conta
        # do bot, não a do servidor), ela não vira prova (13º padrão).
        inflated = dict(json.loads(FP.sent_squad_event("38997", 1, {"light": 1864}, 161050, opt, 1.08, NOW)))
        inflated["loot"] = round(inflated["nominal"] * 1.08 * inflated["lf"])
        check(FP.haul_scavenge_measured({"x": (NOW, "38997", inflated)}) is None,
              "envio com saque x 1,08 não prova a bandeira")
        proof = dict(inflated)
        proof.pop("src")
        check(FP.haul_scavenge_measured({"x": (NOW, "38997", proof)}) is True,
              "controle: a mesma linha vinda da tela prova")
    finally:
        FP.HAUL_SCAVENGE = saved
    out = FP.haul_inputs(["38997"], ev, ({}, 0.25), NOW)["38997"]
    check(out["scav_loot_h"] and out["scav_loot_h"] > 0, "saque/h da coleta sai das linhas de envio")
    # A mesma aldeia com uma linha da tela: o saque/h usa só as do envio.
    seen = dict(json.loads(FP.squad_event("38997", 1, FX["village"]["options"]["1"]["scavenging_squad"],
                                          opt, 1)))
    ev["squads"]["seen"] = (NOW, "38997", seen)
    again = FP.haul_inputs(["38997"], ev, ({}, 0.25), NOW)["38997"]
    check(abs(again["scav_loot_h"] - out["scav_loot_h"]) < 1e-9, "a linha da tela não soma de novo")
    # Sem linha de envio, a da tela ainda vale (o caminho de antes).
    only_seen = {"squads": {"seen": (NOW, "38997", seen)}, "squads_since": ev["squads_since"], "farm": []}
    alone = FP.haul_inputs(["38997"], only_seen, ({}, 0.25), NOW)["38997"]
    check(alone["scav_loot_h"] and alone["scav_loot_h"] > 0, "só a da tela: ainda conta")


def test_sent_event_without_option_table_is_silent():
    check(FP.sent_squad_event("1", 1, {"light": 3}, 240, {}, 1, NOW) is None, "sem loot_factor: None")
    check(FP.sent_squad_event("1", 1, {"spy": 3}, 0, {"loot_factor": 0.1}, 1, NOW) is None, "carga 0: None")
    tm = TroopManager.__new__(TroopManager)
    tm.village_id, tm.logger = "1", logging.getLogger("t")
    tm.wrapper = Wrapper("")
    tm._report_squad_sent("1", {"squad_requests[0][candidate_squad][unit_counts][light]": "3"})
    check(tm.wrapper.reporter.lines == [], "sem tabela lida: nada, sem exceção")


for fn in [
    test_port_matches_the_captured_js,
    test_server_keeps_unit_carry_not_the_posted_value,
    test_flag_paid_and_duration_stays_nominal_0411,
    test_advanced_gather_posts_js_carry_max,
    test_basic_gather_posts_js_carry_max,
    test_sent_squads_are_recorded_and_refused_are_not,
    test_sent_lines_feed_the_rate_but_never_prove_the_flag,
    test_sent_event_without_option_table_is_silent,
]:
    fn()

if failures:
    print("FALHOU (%d problema(s)):" % len(failures))
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("OK: carry_max da coleta como o JS, e o registro do envio")
