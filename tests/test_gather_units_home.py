"""P-COLETA-UNIDADES: a coleta le a tropa em casa da propria tela de coleta.

Antes, `TroopManager.gather()` baixava screen=place&mode=scavenge e logo em
seguida screen=place&mode=units&display=units so para saber quem estava em
casa -- e a primeira ja traz isso em `unit_counts_home`. A fixture e verbatim
do br143 (BBM 035, com apoio da BBM 010 estacionado), entao o teste prova a
equivalencia justamente no caso em que "em casa" e "na aldeia" divergem.

Runs without pytest:
    python tests/test_gather_units_home.py
"""
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from core.extractors import Extractor
from game.troopmanager import TroopManager


checks = 0


def check(condition, message):
    global checks
    checks += 1
    if not condition:
        raise AssertionError(message)


FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "fixtures", "scavenge_units_home_br143.html")
with open(FIXTURE, encoding="utf-8") as fh:
    PAGE = fh.read()

# --- Equivalencia contra o markup real --------------------------------------

village_data = Extractor.village_data(PAGE)
check(isinstance(village_data, dict) and "unit_counts_home" in village_data,
      "a linha var village da fixture deve ser lida")
from_scavenge = TroopManager.units_home_from_scavenge(village_data)
from_place = dict(Extractor.units_in_village(PAGE))
check(from_place == {"spear": "75", "sword": "244", "spy": "28", "light": "113"},
      "a linha 'Desta aldeia' da fixture mudou: %r" % from_place)
check(from_scavenge == from_place,
      "unit_counts_home deve dar exatamente a linha 'Desta aldeia': %r x %r"
      % (from_scavenge, from_place))
check("axe" not in from_scavenge,
      "os 743 machados sao apoio da BBM 010 e nao podem contar como tropa propria")

# --- Falha distinguivel de "ninguem em casa" ---------------------------------

check(TroopManager.units_home_from_scavenge(None) is None, "sem dado -> None")
check(TroopManager.units_home_from_scavenge({"options": {}}) is None,
      "campo ausente -> None (volta ao GET)")
check(TroopManager.units_home_from_scavenge({"unit_counts_home": None}) is None,
      "campo nulo (aldeia sem praca) -> None")
check(TroopManager.units_home_from_scavenge({"unit_counts_home": {}}) is None,
      "dict vazio nao prova nada -> None")
check(TroopManager.units_home_from_scavenge({"unit_counts_home": {"spear": "x"}}) is None,
      "valor ilegivel -> None, nunca um parcial")
check(TroopManager.units_home_from_scavenge({"unit_counts_home": {"spear": 0, "axe": 0}}) == {},
      "todos zero e um resultado legitimo: {} e nao None")


# --- gather() sem o GET de place/units -------------------------------------

class FakeWrapper:
    def __init__(self):
        self.last_h = "csrf"
        self.urls = []
        self.sent = []

    def get_url(self, url):
        self.urls.append(url)
        return object()

    def get_api_action(self, **kwargs):
        self.sent.append(dict(kwargs["data"]))
        return {"ok": True}


OPTIONS = {
    "1": {"is_locked": False, "scavenging_squad": None},
    "2": {"is_locked": True, "scavenging_squad": None},
    "3": {"is_locked": True, "scavenging_squad": None},
    "4": {"is_locked": True, "scavenging_squad": None},
}


def run_gather(screen_data, units_rows):
    original_vd = Extractor.village_data
    original_units = Extractor.units_in_village
    original_unlock = TroopManager.unlock_scavenge
    Extractor.village_data = staticmethod(lambda _r: screen_data)
    Extractor.units_in_village = staticmethod(lambda _r: units_rows)
    TroopManager.unlock_scavenge = lambda self, result, options: False
    try:
        manager = TroopManager.__new__(TroopManager)
        manager.wrapper = FakeWrapper()
        manager.village_id = "52876"
        manager.logger = logging.getLogger("test.gather_units_home")
        manager.can_gather = True
        manager.total_troops = {"spear": 75, "sword": 244}
        manager.conquest_reserve = {}
        manager.gather(selection=1, disabled_units=[], advanced_gather=False)
        return manager
    finally:
        Extractor.village_data = staticmethod(original_vd)
        Extractor.units_in_village = staticmethod(original_units)
        TroopManager.unlock_scavenge = original_unlock


mgr = run_gather(
    {"options": OPTIONS,
     "unit_counts_home": {"spear": 75, "sword": 244, "axe": 0, "light": 113}},
    [("spear", "999")],  # se isto aparecer, o GET antigo rodou
)
check(not any("mode=units" in u for u in mgr.wrapper.urls),
      "com unit_counts_home a coleta nao pode baixar place/units: %r" % mgr.wrapper.urls)
check(len(mgr.wrapper.urls) == 1 and "mode=scavenge" in mgr.wrapper.urls[0],
      "so a tela de coleta deve ser baixada: %r" % mgr.wrapper.urls)
check(len(mgr.wrapper.sent) == 1, "a coleta deve sair uma vez: %r" % mgr.wrapper.sent)
payload = mgr.wrapper.sent[0]
prefix = "squad_requests[0][candidate_squad][unit_counts]"
check(payload[prefix + "[spear]"] == "75" and payload[prefix + "[sword]"] == "244",
      "o esquadrao deve sair com a tropa da tela de coleta: %r" % payload)
check(payload[prefix + "[light]"] == "113",
      "cavalaria leve em casa tambem vai para a coleta no modo basico")
check(mgr.troops.get("spear") == "0" and mgr.troops.get("light") == "0",
      "o envio continua descontado de self.troops (cache/managed): %r" % mgr.troops)

# Sem o campo: o GET antigo volta, igual a antes.
mgr = run_gather({"options": OPTIONS}, [("spear", "10")])
check(any("mode=units" in u for u in mgr.wrapper.urls),
      "sem unit_counts_home a coleta deve voltar ao GET de place/units")
check(mgr.wrapper.sent and mgr.wrapper.sent[0][prefix + "[spear]"] == "10",
      "no fallback a tropa vem do place/units: %r" % mgr.wrapper.sent)

print("OK - %d checks" % checks)
