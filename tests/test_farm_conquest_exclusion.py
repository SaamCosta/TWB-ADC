"""O farm nunca ataca aldeia da lista de conquista (docs/backend.md §8.24).

Incidente de 2026-09-22 (Barbara #51540): um farm mandado com o trem de nobres
ja agendado chegou 25 min depois da conquista e bateu na escolta que ficou de
guarnicao. Cobre:

- `ConquestCache.farm_blocked_targets()`: barbara ativa (inclusive nobre no ar
  com status errado) e PvP em preparacao/agendado entram; conquista resolvida
  e PvP concluido/falhado nao;
- `AttackManager.get_targets()`: o alvo sai da lista de farm com o codigo
  `alvo_de_conquista`, mesmo estando em `additional_farms`, e entra de novo
  quando a conquista termina;
- `AttackManager.run()`: se a lista nao puder ser lida, o farm da aldeia NAO
  roda (falha fechada).

Nada toca o `cache/` real: as tres leituras de disco sao trocadas por fixtures.

Roda sem pytest:
    python tests/test_farm_conquest_exclusion.py
"""
import logging
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import game.attack as attack_mod
import game.pvp_conquest as pvp_mod
from game.attack import AttackCache, AttackManager, ConquestCache
from game.farm_exclusions import FarmExclusionLog, REASONS

logging.disable(logging.CRITICAL)

checks = 0


def check(condition, message):
    global checks
    checks += 1
    if not condition:
        raise AssertionError(message)


NOW = time.time()

# Formato real de cache/conquest/51540.json no momento do incidente.
CONQUEST_FILES = {
    "51540": {"status": "train_sent", "noble_arrivals": [NOW + 3600] * 4},
    # status errado ("complete") com nobre no ar: a chegada manda (8/12).
    "40314": {"status": "complete", "noble_arrivals": [NOW + 600]},
    # resolvida de verdade: nobre pousado, status final.
    "39000": {"status": "complete", "noble_arrivals": [NOW - 600]},
    "39001": {"status": "failed"},
}
PVP_FILES = {
    "70001": {"status": "scheduled"},
    "70002": {},  # sem status = pending_scout
    "70003": {"status": "complete"},
    "70004": {"status": "failed"},
}


def fake_list_directory(path, ends_with=None):
    if path == "cache/conquest":
        return ["%s.json" % k for k in CONQUEST_FILES]
    raise AssertionError("list_directory inesperado: %s" % path)


def fake_load_json_file(path, **_):
    tid = os.path.basename(path).replace(".json", "")
    return CONQUEST_FILES.get(tid)


attack_mod.FileManager.list_directory = staticmethod(fake_list_directory)
attack_mod.FileManager.load_json_file = staticmethod(fake_load_json_file)
pvp_mod.PvpConquestCache.all = staticmethod(lambda: dict(PVP_FILES))
AttackCache.cache_grab = staticmethod(lambda: {})


# --------------------------------------------------------------------------
# farm_blocked_targets
# --------------------------------------------------------------------------
blocked = ConquestCache.farm_blocked_targets()
check("51540" in blocked, "conquista em voo tem que bloquear o farm")
check("40314" in blocked, "nobre no ar com status 'complete' tem que bloquear")
check("39000" not in blocked, "conquista resolvida nao bloqueia")
check("39001" not in blocked, "conquista falhada nao bloqueia")
check("70001" in blocked and "70002" in blocked, "PvP agendado/sem status bloqueia")
check("70003" not in blocked and "70004" not in blocked, "PvP concluido/falhado nao bloqueia")
check("barbara" in blocked["51540"] and "PvP" in blocked["70001"], "motivo diz o tipo")
check("alvo_de_conquista" in REASONS, "codigo novo existe no vocabulario do painel")


# --------------------------------------------------------------------------
# get_targets
# --------------------------------------------------------------------------
class FakeMap:
    def __init__(self, villages):
        self.villages = villages

    def get_dist(self, location):
        return 5.0


def make_manager(villages, extra_farm=()):
    am = AttackManager.__new__(AttackManager)
    am.logger = logging.getLogger("test")
    am.village_id = "41123"
    am.map = FakeMap(villages)
    am.extra_farm = list(extra_farm)
    am.ignored = []
    am._unknown_ignored = []
    am.exclusions = FarmExclusionLog("41123").begin()
    am.farm_maxpoints = 99999
    am.farm_minpoints = 0
    am.target_high_points = True
    am.farm_radius = 50
    am.conquest_targets = {}
    return am


def barb(vid, owner="0"):
    return {"id": vid, "owner": owner, "points": 1000, "location": [582, 289]}


VILLAGES = {
    "41123": {"id": "41123", "owner": "1", "points": 9898, "location": [577, 306]},
    "51540": barb("51540"),
    "52000": barb("52000"),
    "70001": barb("70001", owner="999"),
}

am = make_manager(VILLAGES, extra_farm=["70001"])
am.conquest_targets = ConquestCache.farm_blocked_targets()
am.get_targets()
ids = [t[0]["id"] for t in am.targets]
check("51540" not in ids, "o alvo da conquista nao pode entrar na lista de farm, veio %s" % ids)
check("70001" not in ids, "alvo PvP em additional_farms continua fora -- a conquista vence")
check("52000" in ids, "barbara comum continua sendo farmada")
check(am.exclusions.entries["51540"]["code"] == "alvo_de_conquista", "motivo registrado para o painel")
check("51540" in am.ignored, "entra na contagem de ignorados do log")

# A assinatura do bug: sem a lista, o alvo da conquista volta a ser farmado.
am = make_manager(VILLAGES)
am.get_targets()
check("51540" in [t[0]["id"] for t in am.targets], "sem lista de conquista o alvo e farmado (o incidente)")

# Conquista terminada: o alvo volta ao farm e sai da lista de ignorados.
am = make_manager(VILLAGES)
am.conquest_targets = {"51540": "conquista barbara, status train_sent"}
am.get_targets()
am.conquest_targets = {}
am.exclusions.begin()
am.get_targets()
check("51540" in [t[0]["id"] for t in am.targets], "fim da conquista libera o alvo")
check("51540" not in am.ignored, "e ele sai da lista de ignorados")


# Incidente de 2026-09-23: a 50833 conquistada as 18:15, marcada "conquered"
# as 19:19:30, e o mapa da BBM 001 ainda dizia barbara -- a BBM 001 farmou a
# propria aldeia as 19:31. A lista da conta vence o dono no mapa.
am = make_manager({**VILLAGES, "50833": barb("50833")})
am.own_villages = {"41123", "50833"}
am.get_targets()
check("50833" not in [t[0]["id"] for t in am.targets], "aldeia propria com mapa velho nao e alvo")
check(am.exclusions.entries["50833"]["code"] == "aldeia_propria", "motivo aldeia_propria")
check("aldeia_propria" in REASONS, "codigo no vocabulario do painel")
check("52000" in [t[0]["id"] for t in am.targets], "barbara comum segue farmada")

# Conquista recem-concluida bloqueia mesmo antes de a aldeia entrar no config;
# a antiga nao carrega para sempre.
CONQUEST_FILES["50833"] = {"status": "conquered", "scheduled_arrival": NOW - 3600}
CONQUEST_FILES["30000"] = {"status": "conquered", "scheduled_arrival": NOW - 10 * 86400}
CONQUEST_FILES["30001"] = {"status": "assumed_done", "last_hit_timestamp": NOW - 7200}
blocked = ConquestCache.farm_blocked_targets()
check("50833" in blocked and "recente" in blocked["50833"], "conquista de 1h atras bloqueia")
check("30001" in blocked, "assumed_done recente tambem bloqueia")
check("30000" not in blocked, "conquista de 10 dias atras nao bloqueia mais")
check("39000" not in blocked, "complete sem nobre no ar continua liberado")
for k in ("50833", "30000", "30001"):
    del CONQUEST_FILES[k]


# --------------------------------------------------------------------------
# run(): falha fechada
# --------------------------------------------------------------------------
class FakeTroops:
    can_attack = True
    troops = {"light": "100"}


am = make_manager(VILLAGES)
am.troopmanager = FakeTroops()
called = []
am.get_targets = lambda: called.append(True)
original = ConquestCache.farm_blocked_targets


def boom():
    raise OSError("disco")


ConquestCache.farm_blocked_targets = staticmethod(boom)
try:
    result = am.run()
finally:
    ConquestCache.farm_blocked_targets = staticmethod(original)
check(result is False and not called, "lista ilegivel: o farm da aldeia nao roda")

print("test_farm_conquest_exclusion: %d checks OK" % checks)
