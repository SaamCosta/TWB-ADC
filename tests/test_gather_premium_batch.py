"""Coleta em lote com premium ativo (docs/backend.md §8.64, camada 2).

Sem premium o jogo recusa ate dois esquadroes da mesma aldeia num
`send_squads` (§8.63). Com `game_data.features.Premium.active`, lido da propria
tela de coleta, `gather()` manda todos os esquadroes da aldeia num POST. O
lote tem de levar exatamente as mesmas fatias que o caminho gratis levaria uma
a uma, e qualquer recusa volta ao caminho gratis no mesmo ciclo.

O bloco `features` FREE e verbatim do br143 (tela de coleta da BBM 012,
2026-10-17). O ATIVO e o mesmo com `active: true`, como a §8.25 leu com
premium em 22/09. A resposta boa de um lote nunca foi vista: o OK abaixo e so
"qualquer coisa sem `error`", que e o criterio do codigo.

Runs without pytest:
    python tests/test_gather_premium_batch.py
"""
import json
import logging
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from core.extractors import Extractor
from game.troopmanager import TroopManager

FREE = json.loads('{"Premium":{"possible":true,"active":false},'
                  '"AccountManager":{"possible":false,"active":false},'
                  '"FarmAssistent":{"possible":true,"active":false}}')
ACTIVE = json.loads(json.dumps(FREE).replace(
    '"Premium": {"possible": true, "active": false}',
    '"Premium": {"possible": true, "active": true}'))
REFUSAL = {"error": ["É necessário que tenha conta premium para utilizar esta função."]}
OK = {"response": {}, "game_data": {}}

checks = 0


def check(condition, message):
    global checks
    checks += 1
    if not condition:
        raise AssertionError(message)


check(ACTIVE["Premium"]["active"] is True and ACTIVE["FarmAssistent"]["active"] is False,
      "fixture ativa mal montada: %r" % ACTIVE)
check(Extractor.feature_active({"features": ACTIVE}, "Premium") is True, "ativo deve ligar")
check(Extractor.feature_active({"features": FREE}, "Premium") is False, "conta gratis nao liga")
check(Extractor.feature_active(None, "Premium") is False, "tela que nao e do jogo nao liga")
check(Extractor.feature_active({"features": {}}, "Premium") is False, "bloco ausente nao liga")
check(Extractor.feature_active({"features": {"Premium": {"active": "1"}}}, "Premium") is False,
      "so True liga")


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
FOUR_IDLE = {"1": IDLE, "2": IDLE, "3": IDLE, "4": LOCKED}


def run_gather(features, answers, options=FOUR_IDLE, home=None):
    home = home or {"spear": 1000, "sword": 500}
    originals = (Extractor.village_data, Extractor.game_state,
                 TroopManager.unlock_scavenge, time.sleep)
    Extractor.village_data = staticmethod(lambda _r: {"options": options, "unit_counts_home": home})
    Extractor.game_state = staticmethod(lambda _r: {"features": features})
    TroopManager.unlock_scavenge = lambda self, result, options: False
    time.sleep = lambda _s: None
    try:
        manager = TroopManager.__new__(TroopManager)
        manager.wrapper = FakeWrapper(answers)
        manager.village_id = "41140"
        manager.logger = logging.getLogger("test.premium_batch")
        manager.can_gather = True
        manager.total_troops = {"spear": 1000, "sword": 500}
        manager.conquest_reserve = {}
        manager.last_gather = 0
        manager.gather(selection=3, disabled_units=[], advanced_gather=True)
        return manager
    finally:
        Extractor.village_data = staticmethod(originals[0])
        Extractor.game_state = staticmethod(originals[1])
        TroopManager.unlock_scavenge = originals[2]
        time.sleep = originals[3]


def squads_of(payload):
    """{indice: {campo: valor}} de um POST, sem o h."""
    out = {}
    for key, value in payload.items():
        m = re.match(r"squad_requests\[(\d+)\](.*)", key)
        if m:
            out.setdefault(int(m.group(1)), {})[m.group(2)] = value
    return out


# Referencia: o caminho gratis, um POST por opcao.
free = run_gather(FREE, [OK, OK, OK])
check(len(free.wrapper.sent) == 3, "sem premium: um POST por opcao: %d" % len(free.wrapper.sent))
one_by_one = [squads_of(p)[0] for p in free.wrapper.sent]

# Premium ativo: um POST, com as mesmas tres fatias na mesma ordem.
prem = run_gather(ACTIVE, [OK])
check(len(prem.wrapper.sent) == 1, "com premium: um POST so: %d" % len(prem.wrapper.sent))
batch = squads_of(prem.wrapper.sent[0])
check([batch[i] for i in sorted(batch)] == one_by_one,
      "o lote deve levar exatamente as fatias do caminho gratis:\n%r\n%r" % (batch, one_by_one))
check([batch[i]["[option_id]"] for i in sorted(batch)] == ["3", "2", "1"],
      "ordem das opcoes preservada: %r" % batch)
check(prem.wrapper.sent[0].get("h") == "csrf", "o lote leva o h")
check(prem.troops == free.troops, "o desconto deve ser o mesmo: %r x %r" % (prem.troops, free.troops))
check(prem.last_gather > 0, "lote aceito conta como coleta feita")

# Lote recusado: volta ao um por um no mesmo ciclo.
back = run_gather(ACTIVE, [REFUSAL, OK, OK, OK])
check(len(back.wrapper.sent) == 4, "recusa do lote -> 1 + 3 POSTs: %d" % len(back.wrapper.sent))
check([squads_of(p)[0] for p in back.wrapper.sent[1:]] == one_by_one,
      "o fallback manda as mesmas fatias")
check(back.troops == free.troops, "fallback desconta como o gratis")

# Lote sem resposta: nada reenviado, nada descontado.
lost = run_gather(ACTIVE, [None])
check(len(lost.wrapper.sent) == 1, "sem resposta nao reenvia: %d" % len(lost.wrapper.sent))
check(lost.troops == {"spear": "1000", "sword": "500"}, "sem resposta nao desconta: %r" % lost.troops)
check(lost.last_gather == 0, "sem resposta nao conta como coleta")

# Uma opcao so: nao ha lote, e o POST e o de sempre.
single = run_gather(ACTIVE, [OK], options={"1": IDLE, "2": LOCKED, "3": LOCKED, "4": LOCKED})
check(len(single.wrapper.sent) == 1 and list(squads_of(single.wrapper.sent[0])) == [0],
      "uma opcao: POST unico de indice 0")

print("OK - %d checks" % checks)
