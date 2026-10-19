"""
Reserva do próximo nobre que segue o NobleRecruitGate (docs/backend.md §8.68).

O defeito: a reserva para nobre era estática (`village.keep_resources` em 9
aldeias escolhidas à mão), e o recrutamento do bot nem a lia. Em 18/10 o
portão (§8.48) escolheu como recrutadoras BBM 008, 012, 013, 014, 017, 018,
024..., e as aldeias com `keep_resources` estavam em "só cunha moeda": quem
poupava de verdade não tinha proteção nenhuma, e quem tinha não poupava.

O que se protege aqui:
- `SnobManager` lê o custo do próximo nobre da academia em qualquer ramo, e
  `needs_noble` só é verdadeiro quando a aldeia ainda quer nobre (não em
  "só cunha" nem com os nobres completos);
- `Village.noble_reserve()` só reserva na aldeia que o portão pôs entre as
  recrutadoras, com o custo da academia + 100 de população, e solta quando o
  portão a tira; loga só a troca;
- `TroopManager.get_min_possible` recruta só com o que passa da reserva;
- o compartilhamento não doa abaixo da reserva (maior entre ela e o
  `keep_resources` do config), e a população não entra na doação;
- a reserva chega ao recrutamento mesmo quando ele está cedido ao gerente.

Fixture da academia: `tests/fixtures/snob_train_short_br143.html` (verbatim,
br143, 2026-10-04), a mesma de tests/test_snob_train_gate.py.

Rodar: python tests/test_noble_reserve.py
"""
import logging
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from game.resource_sharing import ResourceSharingManager  # noqa: E402
from game.snobber import SnobManager  # noqa: E402
from game.troopmanager import TroopManager  # noqa: E402
from game.village import Village  # noqa: E402

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


with open(os.path.join(ROOT, "tests", "fixtures", "snob_train_short_br143.html"),
          encoding="utf-8") as fh:
    ACADEMY = fh.read()

NOBLE_COST = {"wood": 40000, "stone": 50000, "iron": 50000}


class FakeResponse:
    def __init__(self, text):
        self.text = text


class FakeWrapper:
    last_h = "redacted"

    def get_action(self, action, village_id):
        return FakeResponse(ACADEMY)

    def get_url(self, url):
        return FakeResponse("")

    def post_url(self, url, data):
        return FakeResponse("")


class FakeResman:
    def __init__(self, actual):
        self.actual = dict(actual)
        self.requested = {}

    def update(self, game_state):
        pass

    def request(self, source="building", resource="wood", amount=1):
        self.requested.setdefault(source, {})[resource] = amount


def snob(snobs_home=0, wanted=4, mint_only=False):
    man = SnobManager(wrapper=FakeWrapper(), village_id="40314")
    man.resman = FakeResman({"wood": 125501, "stone": 58805, "iron": 11546, "pop": 1618})
    man.troop_manager = types.SimpleNamespace(wanted={}, total_troops={"snob": snobs_home})
    man.building_level = 1
    man.wanted = wanted
    man.mint_only = mint_only
    man.mint_coins = lambda: False
    return man


def test_snob_reads_cost_and_need():
    man = snob()
    man.run()
    check(man.needs_noble is True, "0 de 4 nobres: a aldeia quer nobre")
    check(man.noble_cost == NOBLE_COST, "custo do nobre da academia -> %r" % (man.noble_cost,))
    man = snob(snobs_home=4)
    man.run()
    check(man.needs_noble is False, "4 de 4 nobres: nao quer mais")
    man = snob(mint_only=True)
    man.needs_noble = True
    man.run()
    check(man.needs_noble is False, "so cunha: nao quer nobre (e o run zera o ciclo anterior)")


class Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def village(recruit=True, needs=True, cost=NOBLE_COST):
    v = Village.__new__(Village)
    v.village_id = "40314"
    v.config = {"villages": {"40314": {"snobs": 4}}, "conquest": {"max_noble_recruiters": 8}}
    v.builder = types.SimpleNamespace(get_level=lambda b: 1)
    v.noble_recruit_plan = {"40314": {"recruit": recruit, "distance": 66.0, "hours": 38.5,
                                      "rank": 4 if recruit else 15, "of": 28}}
    v._noble_mode_logged = None
    v._noble_reserve_logged = {}
    v.snobman = types.SimpleNamespace(needs_noble=needs, noble_cost=cost)
    cap = Capture()
    v.logger = logging.getLogger("test_noble_reserve.%d" % id(v))
    v.logger.addHandler(cap)
    v.logger.setLevel(logging.INFO)
    v.logger.propagate = False
    return v, cap


def test_village_reserve_follows_gate():
    v, cap = village()
    want = dict(NOBLE_COST, pop=100)
    check(v.noble_reserve() == want, "recrutadora que quer nobre reserva custo + 100 pop")
    check(any("reserva do próximo nobre" in line for line in cap.lines), "log da reserva -> %r" % cap.lines)
    n = len(cap.lines)
    v.noble_reserve()
    check(len(cap.lines) == n, "mesma reserva nao loga de novo")
    # O portao tira a aldeia das recrutadoras: a reserva some sozinha.
    v.noble_recruit_plan["40314"]["recruit"] = False
    check(v.noble_reserve() == {}, "so cunha: sem reserva")
    check(any("sem reserva" in line for line in cap.lines), "log da reserva solta")
    v, _ = village(needs=False)
    check(v.noble_reserve() == {}, "nobres completos: sem reserva")
    v, _ = village(cost=None)
    check(v.noble_reserve() == {}, "custo nao lido: sem reserva (nao chuta numero)")
    v, cap = village(recruit=False)
    check(v.noble_reserve() == {} and not any("Nobre: sem reserva" in l for l in cap.lines),
          "estado de sempre (sem reserva) nao loga no primeiro ciclo")
    v, _ = village()
    v.snobman = None
    check(v.noble_reserve() == {}, "sem academia/snobman: sem reserva")


def troop_manager(wood, stone, iron, pop, pop_max, reserve=None):
    tm = TroopManager.__new__(TroopManager)
    tm.game_data = {"village": {"wood": wood, "stone": stone, "iron": iron,
                                "pop": pop, "pop_max": pop_max}}
    tm.noble_reserve = reserve
    return tm


def test_recruit_only_above_reserve():
    axe = {"wood": 50, "stone": 30, "iron": 60, "pop": 1}
    tm = troop_manager(60000, 80000, 70000, 1000, 2000)
    check(tm.get_min_possible(axe) == 1000, "sem reserva: limitado pela populacao (1000)")
    tm = troop_manager(60000, 80000, 70000, 1000, 2000, dict(NOBLE_COST, pop=100))
    check(tm.get_min_possible(axe) == 333, "com reserva: so o que passa do nobre (20000/60)")
    tm = troop_manager(30000, 80000, 70000, 1000, 2000, dict(NOBLE_COST, pop=100))
    check(tm.get_min_possible(axe) == 0, "madeira abaixo da reserva: nada")
    tm = troop_manager(900000, 900000, 900000, 1950, 2000, dict(NOBLE_COST, pop=100))
    check(tm.get_min_possible(axe) == 0, "populacao do nobre fica livre")
    check(TroopManager.noble_reserve is None, "padrao de classe imutavel")


def test_sharing_keeps_reserve():
    cfg = {"villages": {"40314": {"keep_resources": {"stone": 30000}}}, "resource_sharing": {}}
    rs = ResourceSharingManager(wrapper=None, current_village_id="40314", config=cfg)
    check(rs._keep_resources() == {"stone": 30000}, "sem reserva: so o config")
    rs.noble_reserve = dict(NOBLE_COST, pop=100)
    check(rs._keep_resources() == NOBLE_COST, "vale o maior, e pop nao e recurso doavel -> %r"
          % rs._keep_resources())
    cfg["villages"]["40314"]["keep_resources"] = {"stone": 90000}
    check(rs._keep_resources()["stone"] == 90000, "config maior que a reserva prevalece")


def test_reserve_reaches_ceded_recruitment():
    v, _ = village()
    v.config["units"] = {"recruit": True}
    v.am_widget = {"troops": {"active": True, "template": "ADC - OFENSIVA"},
                   "research": {"active": False, "template": ""}}
    v._am_cession, v._am_cession_at = {}, {}
    v.wrapper = types.SimpleNamespace(paid_features=types.SimpleNamespace(active=lambda n: True))
    v.units = types.SimpleNamespace(noble_reserve=None, research_ceded=False)
    v.resman = types.SimpleNamespace(requested={})
    v.do_recruit()
    check(v.units.noble_reserve == dict(NOBLE_COST, pop=100),
          "reserva posta antes da cessao -> %r" % (v.units.noble_reserve,))


for fn in [
    test_snob_reads_cost_and_need,
    test_village_reserve_follows_gate,
    test_recruit_only_above_reserve,
    test_sharing_keeps_reserve,
    test_reserve_reaches_ceded_recruitment,
]:
    try:
        fn()
    except Exception as exc:
        failures.append(f"{fn.__name__} levantou {exc!r}")

if failures:
    print(f"FALHOU ({len(failures)} problema(s)):")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("OK: reserva do nobre segue o portao")
