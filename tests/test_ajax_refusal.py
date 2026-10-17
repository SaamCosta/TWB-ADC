"""A26-09 na coleta: recusa de acao AJAX nao conta como envio (§8.63).

`get_api_action` devolve o JSON da resposta, e a recusa do jogo vem com status
200 como `{"error": [...]}` -- um dict verdadeiro. O `if sent:` da coleta
descontava a tropa e logava "Using troops" para um esquadrao que nao saiu, e o
`start_unlock` descontava o custo de um desbloqueio recusado.

A resposta abaixo e verbatim do br143 (2026-10-17, `send_squads` com dois
esquadroes da BBM 012 num POST, conta sem premium). A resposta boa de
referencia e o envelope `{"response": ..., "game_data": ...}` do
`TribalWars-Ajax: 1`.

Runs without pytest:
    python tests/test_ajax_refusal.py
"""
import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from core.extractors import Extractor
from game.troopmanager import TroopManager

REFUSAL = json.loads(
    '{"error":["\\u00c9 necess\\u00e1rio que tenha conta premium para utilizar esta fun\\u00e7\\u00e3o."]}')
OK = {"response": {"squad_responses": []}, "game_data": {"village": {"id": 1}}}

checks = 0


def check(condition, message):
    global checks
    checks += 1
    if not condition:
        raise AssertionError(message)


# --- O detector ------------------------------------------------------------

check(Extractor.ajax_error(REFUSAL).startswith("É necessário que tenha conta premium"),
      "a recusa capturada deve ser reconhecida: %r" % Extractor.ajax_error(REFUSAL))
check(Extractor.ajax_error(OK) is None, "envelope bom nao e recusa")
check(Extractor.ajax_error(None) is None, "sem resposta e outro caso (None)")
check(Extractor.ajax_error({"error": []}) is None, "lista vazia nao e recusa")
check(Extractor.ajax_error({"error": "x"}) == "x", "texto solto tambem conta")
check(Extractor.ajax_error(object()) is None, "Response nao-JSON nao e recusa")


# --- gather() com recusa -----------------------------------------------------

class FakeWrapper:
    def __init__(self, answers):
        self.last_h = "csrf"
        self.answers = list(answers)
        self.sent = []

    def get_url(self, url):
        return object()

    def get_api_action(self, **kwargs):
        self.sent.append(dict(kwargs["data"]))
        return self.answers.pop(0)


IDLE = {"is_locked": False, "scavenging_squad": None}
LOCKED = {"is_locked": True, "scavenging_squad": None}


def run_gather(options, home, answers, advanced):
    original_vd = Extractor.village_data
    original_unlock = TroopManager.unlock_scavenge
    original_sleep = time.sleep
    Extractor.village_data = staticmethod(lambda _r: {"options": options, "unit_counts_home": home})
    TroopManager.unlock_scavenge = lambda self, result, options: False
    time.sleep = lambda _s: None
    try:
        manager = TroopManager.__new__(TroopManager)
        manager.wrapper = FakeWrapper(answers)
        manager.village_id = "41140"
        manager.logger = logging.getLogger("test.ajax_refusal")
        manager.can_gather = True
        manager.total_troops = {"spear": 1000}
        manager.conquest_reserve = {}
        manager.last_gather = 0
        manager.gather(selection=2, disabled_units=[], advanced_gather=advanced)
        return manager
    finally:
        Extractor.village_data = staticmethod(original_vd)
        TroopManager.unlock_scavenge = original_unlock
        time.sleep = original_sleep


prefix = "squad_requests[0][candidate_squad][unit_counts]"

# Basico: a opcao 2 recusa, a tropa inteira tenta a opcao 1.
mgr = run_gather({"1": IDLE, "2": IDLE, "3": LOCKED, "4": LOCKED},
                 {"spear": 1000}, [REFUSAL, OK], advanced=False)
check(len(mgr.wrapper.sent) == 2, "recusada a 2, a 1 deve ser tentada: %r" % mgr.wrapper.sent)
check(mgr.wrapper.sent[1][prefix + "[spear]"] == "1000",
      "a tropa da recusa nao saiu e vai inteira para a 1: %r" % mgr.wrapper.sent[1])
check(mgr.troops.get("spear") == "0", "so o envio aceito desconta: %r" % mgr.troops)

# Basico: tudo recusado -> nada descontado, last_gather intocado.
mgr = run_gather({"1": IDLE, "2": LOCKED, "3": LOCKED, "4": LOCKED},
                 {"spear": 1000}, [REFUSAL], advanced=False)
check(mgr.troops.get("spear") == "1000", "recusa nao desconta tropa: %r" % mgr.troops)
check(mgr.last_gather == 0, "recusa nao conta como coleta feita")

# Avancado: a 2 recusa; a 1 sai com a fatia dela, e so ela desconta.
mgr = run_gather({"1": IDLE, "2": IDLE, "3": LOCKED, "4": LOCKED},
                 {"spear": 1000}, [REFUSAL, OK], advanced=True)
check(len(mgr.wrapper.sent) == 2, "as duas opcoes devem ser tentadas")
first = int(mgr.wrapper.sent[0][prefix + "[spear]"])
second = int(mgr.wrapper.sent[1][prefix + "[spear]"])
check(mgr.troops.get("spear") == str(1000 - second),
      "so a fatia aceita sai de self.troops: %r (recusada %d, aceita %d)"
      % (mgr.troops, first, second))

# Sem recusa nada muda: as duas saem e as duas descontam.
mgr = run_gather({"1": IDLE, "2": IDLE, "3": LOCKED, "4": LOCKED},
                 {"spear": 1000}, [OK, OK], advanced=True)
total = sum(int(p[prefix + "[spear]"]) for p in mgr.wrapper.sent)
check(mgr.troops.get("spear") == str(1000 - total), "envio aceito desconta como antes")

print("OK - %d checks" % checks)
