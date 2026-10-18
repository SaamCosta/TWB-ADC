"""
Defesa automática das aldeias próprias (docs/backend.md §8.60): extratores das
telas que ela lê, o estudo do ataque (`core.own_defense.assess`), o plano
(`plan_defense`), as duas travas novas de `DefenceManager.support()`
(`arrive_by` e `clamp_to_available`) e o gatilho do `OwnDefenseManager`.
Desde 2026-10-18 (§8.69): o teto do maior ataque com nobre, o corte ao
necessário, o `trim` do `support()`, a blindagem e as leituras da praça
(`units_home_total`, `place_troop_locations`).

O caso de referência é o de 2026-10-11: BBM 048 (40808, 531|289), conquistada
às 14:50 com lealdade deixada em 25 e seis ataques chegando, um rotulado
"412- Nobre ..." a 48,4 campos. As fixtures são recortes verbatim do br143
daquele dia, com nomes de terceiros anonimizados e o `h` redigido.

Rodar: python tests/test_own_defense.py
"""
import os
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import own_defense
from core.extractors import Extractor
from game.defence_manager import DefenceManager
from game.own_defense import OwnDefenseManager

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return fh.read()


OVERVIEW = _fixture("own_defense_village_overview_br143.html")
VILLAGES = _fixture("own_defense_overview_villages_br143.html")
INFO_COMMAND = _fixture("own_defense_info_command_br143.html")
PLACE_UNITS = _fixture("own_defense_place_units_br143.html")
CONFIRM_SUPPORT = _fixture("place_confirm_support_br143.html")

# get_unit_info do br143 (min/campo efetivos), o mesmo de
# tests/test_support_urgency_gate.py.
SPEEDS = {"spear": 18.0, "sword": 22.0, "axe": 18.0, "spy": 9.0, "light": 10.0,
          "heavy": 11.0, "ram": 30.0, "catapult": 30.0, "knight": 10.0, "snob": 35.0}
NOBLE_ARRIVAL = 1791767486  # 22:11:26 de 2026-10-11, o data-endtime do widget


def _check(label, got, expected):
    assert got == expected, f"{label}: esperado {expected!r}, veio {got!r}"
    print(f"  ok  {label}: {got!r}")


# -- extratores ---------------------------------------------------------------

def test_comandos_recebidos_reais():
    print("test_comandos_recebidos_reais")
    cmds = Extractor.incoming_commands(OVERVIEW)
    _check("linhas", len(cmds), 14)
    kinds = [c["command_type"] for c in cmds]
    _check("ataques", kinds.count("attack"), 6)
    _check("apoios", kinds.count("support"), 7)
    # O paladino se mudando era "unknown" -- que o DefenceManager conta
    # como ataque.
    _check("paladino", kinds.count("relocate"), 1)
    _check("chegada absoluta do 'nobre'", cmds[-1]["arrival_at"], NOBLE_ARRIVAL)
    _check("pista do rótulo 'Nobre'", cmds[-1]["label_unit"], "snob")
    # O ataque rotulado "Aldeia de bárbaros" ganhou o ícone de bárbaro: o
    # ícone vem do texto, não de detecção do jogo.
    _check("pista do rótulo 'bárbaros'", cmds[1]["label_unit"], "axe")
    _check("rótulo sem entidade", cmds[1]["origin"], "Aldeia de bárbaros")


def test_lealdade_e_bonus():
    print("test_lealdade_e_bonus")
    _check("lealdade lida", Extractor.village_loyalty(OVERVIEW), 25)
    _check("sem widget = 100", Extractor.village_loyalty("<div id=\"show_effects\"></div>"), 100)
    broken = '<div id="show_mood"><div class="vis_item"><span>?</span></div></div>'
    _check("widget sem número = None", Extractor.village_loyalty(broken), None)
    _check("Sinal da Aflição", Extractor.incoming_support_speed_bonus(OVERVIEW), 10)


def test_visao_geral_das_aldeias():
    print("test_visao_geral_das_aldeias")
    rows = Extractor.own_villages_overview(VILLAGES)
    _check("aldeias", [r["vid"] for r in rows], ["71768", "40808"])
    _check("sem ataque", rows[0]["incomings"], 0)
    _check("sob ataque (6)", rows[1]["incomings"], 6)
    _check("coordenada", (rows[1]["x"], rows[1]["y"]), (531, 289))
    _check("nome", rows[1]["name"], "BBM 048")
    _check("página sem aldeia = None", Extractor.own_villages_overview("<html></html>"), None)


def test_origem_do_comando():
    print("test_origem_do_comando")
    origin = Extractor.command_origin(INFO_COMMAND)
    _check("aldeia de origem", origin["village_id"], "52522")
    _check("coordenada", (origin["x"], origin["y"]), (489, 265))
    _check("não confunde com o destino", origin["name"], "412- Nobre Fulano!")
    _check("sem tabela = None", Extractor.command_origin("<h2>x</h2>"), None)


def test_tropas_na_praca():
    print("test_tropas_na_praca")
    units = Extractor.place_units_available(PLACE_UNITS)
    _check("pesada", units["heavy"], 561)
    _check("lança", units["spear"], 1800)
    _check("nobre zerado ainda aparece", units["snob"], 0)
    _check("fora da praça = {}", Extractor.place_units_available("<html></html>"), {})


# -- estudo do ataque ----------------------------------------------------------

def test_nobres_necessarios():
    print("test_nobres_necessarios")
    _check("lealdade 25", own_defense.nobles_needed(25, (20, 35)), 1)
    _check("lealdade 100", own_defense.nobles_needed(100, (20, 35)), 3)
    _check("lealdade 36", own_defense.nobles_needed(36, (20, 35)), 2)
    _check("faixa ilegível usa 35", own_defense.nobles_needed(70, None), 2)


def test_quando_nao_pode_ser_nobre():
    print("test_quando_nao_pode_ser_nobre")
    # O caso real: 48,4 campos, faltando 7 h; o nobre leva 28,2 h -> pode.
    possible, _ = own_defense.noble_possible(48.37, 7 * 3600, SPEEDS, 70)
    _check("BBM 048 às 15:11", possible, True)
    possible, why = own_defense.noble_possible(80, 3600, SPEEDS, 70)
    _check("fora do alcance", possible, False)
    # 5 campos = 2h55 de nobre; faltar 5 h é impossível para um nobre.
    possible, why = own_defense.noble_possible(5, 5 * 3600, SPEEDS, 70)
    _check("tempo demais para nobre", possible, False)
    _check("origem desconhecida pode", own_defense.noble_possible(None, 60, SPEEDS, 70)[0], True)


def _attack(cid, arrival, x=None, y=None):
    return {"command_id": cid, "arrival_at": arrival,
            "origin": {"x": x, "y": y} if x is not None else None}


def test_assess_bbm048():
    print("test_assess_bbm048")
    now = NOBLE_ARRIVAL - 7 * 3600
    village = {"vid": "40808", "x": 531, "y": 289, "loyalty": 25}
    attacks = [
        _attack("far", now + 3600, 610, 289),          # 79 campos: além do alcance
        _attack("noble", NOBLE_ARRIVAL, 489, 265),       # 48 campos, 7 h: pode
        _attack("unknown", NOBLE_ARRIVAL + 600),          # sem origem: pode
    ]
    out = own_defense.assess(village, attacks, SPEEDS, 70, (20, 35), now)
    _check("protege", out["protect"], True)
    _check("1 nobre basta com lealdade 25", out["nobles_needed"], 1)
    _check("janela começa no 1º que pode ser nobre", out["first_deadline_at"], NOBLE_ARRIVAL)
    _check("janela termina no último", out["deadline_command"], "unknown")
    _check("chegadas da janela", out["threat_arrivals"], [NOBLE_ARRIVAL, NOBLE_ARRIVAL + 600])
    _check("o de fora do alcance não está na janela", out["attacks"][0]["in_window"], False)
    village["loyalty"] = 100
    out = own_defense.assess(village, attacks, SPEEDS, 70, (20, 35), now)
    _check("lealdade 100 com 2 possíveis não protege", out["protect"], False)
    # Widget de lealdade presente e ilegível: pior caso, não "100".
    village["loyalty"] = None
    out = own_defense.assess(village, attacks, SPEEDS, 70, (20, 35), now)
    _check("lealdade ilegível conta como 1 nobre", out["nobles_needed"], 1)


# -- plano --------------------------------------------------------------------

def _source(vid, x, y, **troops):
    return {"vid": vid, "name": vid, "x": x, "y": y, "troops": troops, "under_attack": False}


def test_plano_bbm048():
    print("test_plano_bbm048")
    now = 1791742480  # 15:14:40, quando o primeiro apoio manual saiu
    target = {"vid": "40808", "x": 531, "y": 289}
    sources = [
        # BBM 026 (565|302), 36,4 campos: pesada chega, lança não.
        _source("39449", 565, 302, spear=2440, sword=2200, heavy=431, light=200, spy=10),
        # BBM 025 (571|299), 41,2 campos: só chega com o Sinal (+10%).
        _source("42134", 571, 299, heavy=601),
    ]
    plan = own_defense.plan_defense(target, NOBLE_ARRIVAL, sources, SPEEDS, now, bonus_pct=10)
    by_vid = {l["source_vid"]: l for l in plan["lines"]}
    _check("BBM 026 manda pesada e explorador, sem lança/espada/leve",
           by_vid["39449"]["troops"], {"heavy": 431, "spy": 10})
    # O jogo deu 6,07 h para esse envio; a conta com o bônus tem que bater.
    _check("viagem da BBM 026 ~ 6,07 h", round(by_vid["39449"]["travel_sec"] / 3600, 2), 6.07)
    _check("BBM 025 entra com o Sinal", "42134" in by_vid, True)
    plan = own_defense.plan_defense(target, NOBLE_ARRIVAL, sources, SPEEDS, now, bonus_pct=0)
    _check("sem o Sinal a BBM 025 fica de fora",
           "42134" in {l["source_vid"] for l in plan["lines"]}, False)


def test_smoke_15h40_primeiro_inalcancavel():
    """
    O cenário do smoke de 2026-10-11 15:40, que pegou a primeira versão: o
    primeiro ataque que pode ser nobre pousa em 1 min (nada chega), os
    seguintes em 16 min, 2 h e 3h40. Mirar só no primeiro deixava o plano
    vazio; a janela manda o que vence os seguintes.
    """
    print("test_smoke_15h40_primeiro_inalcancavel")
    now = 1791744031  # 15:40:31
    village = {"vid": "40808", "x": 531, "y": 289, "loyalty": 25}
    attacks = [_attack("a", now + 60, 548, 274), _attack("b", now + 960, 552, 281),
               _attack("c", now + 7482, 549, 278), _attack("d", now + 13259, 533, 259)]
    verdict = own_defense.assess(village, attacks, SPEEDS, 70, (20, 35), now)
    sources = [_source("44167", 552, 283, heavy=100)]  # ~21 campos: pesada em ~3h30
    plan = own_defense.plan_defense({"vid": "40808", "x": 531, "y": 289},
                                    verdict["deadline_at"], sources, SPEEDS, now, bonus_pct=10,
                                    threat_arrivals=verdict["threat_arrivals"])
    _check("o plano não fica vazio", len(plan["lines"]), 1)
    _check("vence só o último dos quatro", plan["lines"][0]["beats"], 1)


def test_plano_exclusoes_e_teto():
    print("test_plano_exclusoes_e_teto")
    now = 0
    target = {"vid": "1", "x": 0, "y": 0}
    attacked = dict(_source("2", 3, 0, heavy=100), under_attack=True)
    sources = [attacked, _source("3", 4, 0, heavy=100), _source("4", 5, 0, heavy=3),
               _source("5", 6, 0, heavy=100), _source("1", 0, 0, heavy=999)]
    plan = own_defense.plan_defense(target, 10 ** 6, sources, SPEEDS, now,
                                    options={"max_pop_per_target": 600},
                                    skip_sources={"5": "tentada há 2 min"})
    vids = [l["source_vid"] for l in plan["lines"]]
    _check("o próprio alvo nunca manda", "1" in vids, False)
    _check("origem atacada fica", "2" in vids, False)
    _check("abaixo do piso (18 pop) fica", "4" in vids, False)
    _check("tentada há pouco fica", "5" in vids, False)
    _check("só a 3 cabe no teto", vids, ["3"])
    plan = own_defense.plan_defense(target, 10 ** 6, [_source("6", 4, 0, spy=500)], SPEEDS, now)
    _check("só explorador não vira envio", plan["lines"], [])
    plan = own_defense.plan_defense(target, 10 ** 6, [_source("3", 4, 0, heavy=100)], SPEEDS,
                                    now, options={"reserve_pct": 0.25})
    _check("reserva fica em casa", plan["lines"][0]["troops"], {"heavy": 75})


# -- travas do support() --------------------------------------------------------

class _Wrapper:
    last_h = "csrf"

    def __init__(self, place_html=""):
        self.place_html = place_html
        self.confirm_payload = None
        self.final_payload = None

    def get_url(self, url):
        return SimpleNamespace(text=self.place_html + (
            '<input id="target_support" class="support btn" name="support" type="submit" '
            'value="Apoio" />'))

    def post_url(self, url, data):
        self.confirm_payload = dict(data)
        return SimpleNamespace(text=CONFIRM_SUPPORT)  # duração real: 764 s

    def get_api_action(self, village_id, action, params, data):
        self.final_payload = data
        return {"success": True}


def test_support_respeita_prazo():
    print("test_support_respeita_prazo")
    dm = DefenceManager(village_id="49709", wrapper=_Wrapper())
    ok = dm.support("40808", troops={"heavy": 5}, position=(531, 289),
                    arrive_by=time.time() + 700)
    _check("764 s de viagem com 700 s de prazo não sai", ok, False)
    _check("passo final não foi chamado", dm.wrapper.final_payload, None)
    _check("motivo", dm.last_support_error.startswith("chegaria"), True)
    dm = DefenceManager(village_id="49709", wrapper=_Wrapper())
    ok = dm.support("40808", troops={"heavy": 5}, position=(531, 289),
                    arrive_by=time.time() + 900)
    _check("dentro do prazo sai", bool(ok), True)
    _check("chegada registrada", dm.last_support_arrival is not None, True)


def test_support_limita_ao_que_esta_em_casa():
    print("test_support_limita_ao_que_esta_em_casa")
    dm = DefenceManager(village_id="49709", wrapper=_Wrapper(PLACE_UNITS))
    ok = dm.support("40808", troops={"heavy": 900, "sword": 10, "archer": 50},
                    position=(531, 289), clamp_to_available=True)
    _check("enviado", bool(ok), True)
    _check("pesada limitada a 561", dm.wrapper.confirm_payload["heavy"], 561)
    _check("unidade sem campo na praça sai do pedido", "archer" in dm.wrapper.confirm_payload, False)
    _check("o que foi registrado", dm.last_support_troops, {"heavy": 561, "sword": 10})
    dm = DefenceManager(village_id="49709", wrapper=_Wrapper(PLACE_UNITS))
    ok = dm.support("40808", troops={"knight": 1}, position=(531, 289), clamp_to_available=True)
    _check("nada em casa não posta", (ok, dm.wrapper.confirm_payload), (False, None))
    dm = DefenceManager(village_id="49709", wrapper=_Wrapper(""))
    ok = dm.support("40808", troops={"heavy": 1}, position=(531, 289), clamp_to_available=True)
    _check("praça ilegível não posta", (ok, dm.wrapper.confirm_payload), (False, None))


# -- gatilho ------------------------------------------------------------------

def test_gatilho():
    print("test_gatilho")
    clock = [1000.0]
    wrapper = SimpleNamespace(account_pulse=SimpleNamespace(last=None))
    mgr = OwnDefenseManager(wrapper, clock=lambda: clock[0])
    mgr.origins, mgr.attempts, mgr.history = {}, {}, []
    cfg = {"own_defense": {"enabled": True, "rescan_minutes": 10}}
    import game.own_defense as od
    original = od.load_force
    od.load_force = lambda now=None: {}
    try:
        _check("sem pulso não varre", mgr.due(cfg)[0], False)
        wrapper.account_pulse.last = {"incomings": 0}
        _check("zero ataques não varre", mgr.due(cfg)[0], False)
        wrapper.account_pulse.last = {"incomings": 6}
        _check("ataque novo varre", mgr.due(cfg)[0], True)
        mgr.last_incomings, mgr.last_scan_at = 6, clock[0]
        _check("mesmo número logo depois não varre", mgr.due(cfg)[0], False)
        clock[0] += 601
        _check("revarredura depois de 10 min", mgr.due(cfg)[0], True)
        wrapper.account_pulse.last = {"incomings": 5}
        mgr.last_scan_at = clock[0]
        _check("ataque que pousou varre (lealdade pode ter caído)", mgr.due(cfg)[0], True)
        _check("desligada não varre", mgr.due({"own_defense": {"enabled": False}})[0], False)
    finally:
        od.load_force = original


# -- teto e blindagem (2026-10-18) ---------------------------------------------

TRANSIT = _fixture("place_units_transit_br143.html")
GAME_DATA = _fixture("game_data_village_br143.html")


def _sim():
    from game.simulator import Simulator
    return Simulator().simulate


def test_maior_ataque_com_nobre():
    print("test_maior_ataque_com_nobre")
    # pop_max do game_data da BBM 016 (fazenda 30) em 2026-10-18.
    _check("fazenda 30", own_defense.FARM_MAX_POP, 24000)
    _check("ofensiva máxima com nobre", own_defense.max_noble_nuke_pop(), 24000 - 702 - 100)
    nukes = own_defense.noble_nukes()
    _check("três composições sem arqueiro", sorted(nukes), ["cavalaria", "infantaria", "mista"])
    _check("cada uma leva um nobre", {n: t["snob"] for n, t in nukes.items()},
           {"cavalaria": 1, "infantaria": 1, "mista": 1})
    pops = {n: own_defense._pop({u: q for u, q in t.items() if u != "snob"})
            for n, t in nukes.items()}
    _check("população de cada uma perto do teto",
           all(23000 < p <= 23198 for p in pops.values()), True)
    _check("mundo com arqueiro ganha a quarta",
           "arqueiros" in own_defense.noble_nukes(archers=True), True)


def test_teto_corta_ao_necessario():
    print("test_teto_corta_ao_necessario")
    sim, nukes = _sim(), own_defense.noble_nukes()
    one_d = {"spear": 4000, "sword": 3400, "heavy": 900}
    _check("uma aldeia de defesa não segura",
           own_defense.assess_defense(one_d, 20, sim, nukes)["holds"], False)
    big = {"spear": 20000, "sword": 20000, "heavy": 4000}
    part = own_defense.fit_package(big, one_d, 20, sim, nukes)
    _check("corte segura", own_defense.assess_defense(
        own_defense._add(one_d, part), 20, sim, nukes)["holds"], True)
    _check("corte é menos que tudo", own_defense._pop(part) < own_defense._pop(big), True)
    smaller = {u: int(q * 0.9) for u, q in part.items()}
    _check("10% a menos já não segura", own_defense.assess_defense(
        own_defense._add(one_d, smaller), 20, sim, nukes)["holds"], False)
    _check("mesma proporção do que estava em casa",
           round(part["spear"] / part["heavy"], 1), round(big["spear"] / big["heavy"], 1))
    _check("se nem tudo segura, vai tudo",
           own_defense.fit_package({"heavy": 100}, {}, 0, sim, nukes), {"heavy": 100})
    _check("já seguro, o corte é vazio", own_defense.fit_package(
        {"heavy": 100}, own_defense._add(one_d, part), 20, sim, nukes), {})


def test_praca_total_e_transito():
    print("test_praca_total_e_transito")
    _check("Total da BBM 026", Extractor.units_home_total(TRANSIT), {"sword": 1, "light": 200})
    _check("Total com explorador de fora", Extractor.units_home_total(
        _fixture("place_units_support_away_br143.html")), {"sword": 5, "spy": 150})
    _check("página que não é a praça", Extractor.units_home_total("<html></html>"), None)
    loc = Extractor.place_troop_locations(TRANSIT)
    _check("8 comandos em trânsito", len(loc["transit"]), 8)
    back = loc["transit"][0]
    _check("apoio voltando", (back["kind"], back["vid"], back["name"], back["troops"]),
           ("back", "45215", "BBM 049", {"spy": 2}))
    big = loc["transit"][5]
    _check("o apoio grande a caminho da BBM 055",
           (big["kind"], big["vid"], big["x"], big["y"], big["troops"]),
           ("support", "74966", 579, 257, {"spear": 2615, "sword": 2475, "spy": 48, "heavy": 613}))
    _check("2 apoios pousados em outros jogadores", len(loc["away"]), 2)
    first = loc["away"][0]
    _check("rótulo decomposto",
           (first["vid"], first["name"], first["player_name"], first["player_id"],
            first["x"], first["y"], first["distance"], first["troops"]),
           ("58044", "Aldeia Aliada", "JogadorA", "1001", 734, 533, 286.2,
            {"spy": 40, "heavy": 10}))
    _check("ninguém apoiando a BBM 026", loc["home_support"], [])
    _check("não é a praça", Extractor.place_troop_locations(""), None)


def test_support_trim():
    print("test_support_trim")
    dm = DefenceManager(village_id="49709", wrapper=_Wrapper(PLACE_UNITS))
    ok = dm.support("40808", troops={"heavy": 900}, position=(531, 289), clamp_to_available=True,
                    trim=lambda t: ({"heavy": t["heavy"] // 2}, None))
    _check("corte enviado", (bool(ok), dm.wrapper.confirm_payload["heavy"]), (True, 280))
    dm = DefenceManager(village_id="49709", wrapper=_Wrapper(PLACE_UNITS))
    ok = dm.support("40808", troops={"heavy": 900}, position=(531, 289), clamp_to_available=True,
                    trim=lambda t: ({}, "abaixo do mínimo"))
    _check("corte que desiste não posta",
           (ok, dm.wrapper.confirm_payload, dm.last_support_error),
           (False, None, "abaixo do mínimo"))


class _DefendWrapper:
    def __init__(self, place_html):
        self.place_html = place_html
        self.urls = []

    def get_url(self, url):
        self.urls.append(url)
        return self.place_html if "mode=units" in url else None


def _run_defend(home_html, shield, sources, available, history=None):
    """
    `_defend` de ponta a ponta com o que fala com o jogo trocado: veredito de
    proteção, origens, e um `_send` que faz o que o `support()` faz com o
    `trim` -- corta ao que está em casa (`available`) e chama o trim.
    """
    import game.own_defense as od
    mgr = OwnDefenseManager(_DefendWrapper(home_html), clock=lambda: 1000.0)
    mgr.origins, mgr.attempts, mgr.history = {}, {}, list(history or [])
    mgr._village_page = lambda vid: GAME_DATA  # BBM 049, muralha 9
    mgr._sources = lambda config, attacked: sources
    calls = []

    def fake_send(target_vid, village, line, arrive_by, trim=None):
        home = available.get(line["source_vid"], {})
        have = {u: min(q, home.get(u, 0)) for u, q in line["troops"].items()}
        have = {u: q for u, q in have.items() if q > 0}
        troops, why = trim(have) if have else ({}, "nada em casa")
        entry = {"source_vid": line["source_vid"], "ok": bool(troops),
                 "troops": troops or line["troops"], "error": why}
        calls.append(entry)
        return entry

    mgr._send = fake_send
    verdict = {"protect": True, "deadline_at": 1000 + 36000, "threat_arrivals": [1000 + 36000],
               "attacks": [], "reason": "teste"}
    saved = (od.own_defense.assess, od.load_shield, od.Notification.send)
    od.own_defense.assess = lambda *a, **k: dict(verdict)
    od.load_shield = lambda: {"74966": 1} if shield else {}
    od.Notification.send = lambda *a, **k: None
    try:
        result = mgr._defend({}, od.settings({}), {"vid": "74966", "name": "BBM 055", "x": 0,
                                                   "y": 0, "incomings": 0},
                             set(), SPEEDS, 70, (20, 35), False)
    finally:
        od.own_defense.assess, od.load_shield, od.Notification.send = saved
    return result, calls, mgr


def test_defesa_com_teto():
    print("test_defesa_com_teto")
    # Três aldeias de defesa cheia a 1 campo: a primeira não basta, a segunda
    # completa (cortada), a terceira não sai.
    full = {"spear": 9000, "sword": 9000, "heavy": 1800}
    sources = [_source(v, 1, 0, **full) for v in ("1", "2", "3")]
    available = {v: dict(full) for v in ("1", "2", "3")}
    result, calls, mgr = _run_defend(TRANSIT, False, sources, available)
    _check("a praça do alvo foi lida", any("mode=units" in u for u in mgr.wrapper.urls), True)
    _check("defesa lida da praça", result["defense"]["home"], {"sword": 1, "light": 200})
    _check("muralha do game_data", result["defense"]["wall"], 9)
    sent = [c for c in calls if c["ok"]]
    _check("enviou de duas das três", len(sent), 2)
    _check("terminou seguro", result["defense"]["after_holds"], True)
    _check("o último envio foi cortado",
           own_defense._pop(sent[-1]["troops"]) < own_defense._pop(full), True)


def test_ja_seguro_nao_manda():
    print("test_ja_seguro_nao_manda")
    sources = [_source("1", 1, 0, heavy=1000)]
    history = [{"ok": True, "target_vid": "74966", "arrival_at": 1000 + 3600,
                "troops": {"spear": 30000, "sword": 30000, "heavy": 6000}}]
    result, calls, _ = _run_defend(TRANSIT, False, sources, {"1": {"heavy": 1000}}, history)
    _check("apoio a caminho conta", result["defense"]["inflight_pop"], 96000)
    _check("seguro", result["defense"]["holds"], True)
    _check("nenhum envio", calls, [])
    late = [dict(history[0], arrival_at=1000 + 40000)]  # pousa depois da janela
    result, calls, _ = _run_defend(TRANSIT, False, sources, {"1": {"heavy": 1000}}, late)
    _check("apoio que pousa depois da janela não conta", result["defense"]["inflight_pop"], 0)


def test_gota_abaixo_do_piso_nao_sai():
    print("test_gota_abaixo_do_piso_nao_sai")
    # O incidente: o cache diz 2.400 pesadas, a praça tem 1 em casa.
    sources = [_source("1", 1, 0, heavy=2400, sword=3000)]
    result, calls, _ = _run_defend(TRANSIT, False, sources, {"1": {"heavy": 1, "sword": 2}})
    _check("não enviou", [c["ok"] for c in calls], [False])
    _check("motivo é o piso", "abaixo do mínimo de 30" in calls[0]["error"], True)


def test_blindagem():
    print("test_blindagem")
    history = [{"ok": True, "target_vid": "74966", "arrival_at": 1000 + 3600,
                "troops": {"spear": 30000, "sword": 30000, "heavy": 6000}}]
    sources = [_source("1", 1, 0, heavy=2000), _source("2", 1, 0, heavy=2000)]
    available = {"1": {"heavy": 2000}, "2": {"heavy": 100}}
    result, calls, _ = _run_defend(TRANSIT, True, sources, available, history)
    _check("seguro, e a blindagem manda mesmo assim", result["defense"]["holds"], True)
    by = {c["source_vid"]: c for c in calls}
    _check("vai tudo o que está em casa, sem corte", by["1"]["troops"], {"heavy": 2000})
    _check("600 pop fica abaixo do mínimo de 1000",
           (by["2"]["ok"], "da blindagem" in by["2"]["error"]), (False, True))


if __name__ == "__main__":
    test_comandos_recebidos_reais()
    test_lealdade_e_bonus()
    test_visao_geral_das_aldeias()
    test_origem_do_comando()
    test_tropas_na_praca()
    test_nobres_necessarios()
    test_quando_nao_pode_ser_nobre()
    test_assess_bbm048()
    test_plano_bbm048()
    test_smoke_15h40_primeiro_inalcancavel()
    test_plano_exclusoes_e_teto()
    test_support_respeita_prazo()
    test_support_limita_ao_que_esta_em_casa()
    test_gatilho()
    test_maior_ataque_com_nobre()
    test_teto_corta_ao_necessario()
    test_praca_total_e_transito()
    test_support_trim()
    test_defesa_com_teto()
    test_ja_seguro_nao_manda()
    test_gota_abaixo_do_piso_nao_sai()
    test_blindagem()
    print("\nOK - todos os testes da defesa própria passaram")
