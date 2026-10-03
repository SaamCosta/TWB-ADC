"""
§8.44 P-MISSAO-POPUP: o GET do popup de recompensas de missao so quando a
tela do jogo diz que ha recompensa pronta (`core/reward_gate.py`).

Medido antes: 946 GETs de `new_quests ajax=quest_popup` em 50 ciclos de
`cache/cycles/`, para 5 resgates.

Sem rede. A fixture do contador e o recorte verbatim de
`cache/debug/place_command_41123.html` (2026-09-29); a variante com N > 0 so
troca o digito, porque nenhuma captura em disco tinha N > 0.
"""

import json
import logging
import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.extractors import Extractor  # noqa: E402
from core.request import WebWrapper  # noqa: E402
from core.reward_gate import RewardGate  # noqa: E402
from game.village import Village  # noqa: E402

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


# Recorte verbatim (tabs do original).
COUNTER_SNIPPET = (
    "\t\t\t\t\tsetTimeout(function() {\n"
    "\t\t\t\t\t\t$('#quickbar_contents').find('.quickbar_image').each(function() {\n"
    "\t\t\t\t\t\t\tthis.src = $(this).data('src');\n"
    "\t\t\t\t\t\t});\n"
    "\t\t\t\t\t\tRewardSystem.setUnlockableRewardsCount(0);\n"
    "\t\t\t\t\t}, 1);\n"
    "\t\t\t\t</script>\n"
)

GAME_DATA = {
    "village": {"id": 32056, "wood": 10120, "wood_prod": 0.41, "wood_float": 10120.07,
                "stone": 10252, "stone_prod": 0.41, "stone_float": 10252.07,
                "iron": 3265, "iron_prod": 0.31, "iron_float": 3264.54,
                "pop": 5987, "pop_max": 6737, "storage_max": 18037, "trader_away": 0},
    "screen": "place", "time_generated": 1789884583710,
}


def page(count=0, village_id=32056):
    gd = json.loads(json.dumps(GAME_DATA))
    gd["village"]["id"] = village_id
    snippet = COUNTER_SNIPPET.replace("(0)", "(%d)" % count)
    return ("<html><script>TribalWars.updateGameData(%s);</script>\n<script>%s"
            % (json.dumps(gd), snippet))


class FakeResponse:
    def __init__(self, text, url="https://x/game.php", content_type="text/html"):
        self.text = text
        self.url = url
        self.headers = {"content-type": content_type}


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------

def test_parser():
    check(Extractor.unlocked_rewards_count(COUNTER_SNIPPET) == 0, "recorte verbatim nao deu 0")
    check(Extractor.unlocked_rewards_count(page(3)) == 3, "N = 3 nao lido")
    check(Extractor.unlocked_rewards_count(SimpleNamespace(text=page(12))) == 12,
          "Response nao lido")
    # Ausencia nao e zero: AJAX, login, rede fora.
    check(Extractor.unlocked_rewards_count('{"response": {}, "game_data": {}}') is None,
          "JSON sem a chamada virou numero")
    check(Extractor.unlocked_rewards_count("<html>login</html>") is None, "login virou numero")
    check(Extractor.unlocked_rewards_count(None) is None, "None virou numero")


# --------------------------------------------------------------------------
# Decisao
# --------------------------------------------------------------------------

def test_decisao():
    clock = Clock()
    gate = RewardGate(clock=clock)
    check(gate.decide("1") == (True, "sem_contador"), "sem N deveria buscar")

    gate.observe("1", page(0))
    check(gate.decide("1") == (True, "conferencia"), "primeira vez com 0 e conferencia")
    check(gate.decide("1") == (False, "contador_zero"), "0 fresco depois da conferencia pula")
    check(gate.decide("2") == (True, "sem_contador"), "N de outra aldeia nao vale aqui")

    clock.t += RewardGate.MAX_AGE + 1
    check(gate.decide("1") == (True, "contador_velho"), "N velho deveria buscar")

    gate.observe("1", page(2))
    check(gate.decide("1") == (True, "contador_positivo"), "N > 0 deveria buscar")

    gate.observe("1", page(0))
    check(gate.decide("1") == (False, "contador_zero"), "conferencia nao deveria repetir antes da janela")
    clock.t += RewardGate.VERIFY_EVERY
    gate.observe("1", page(0))
    check(gate.decide("1") == (True, "conferencia"), "conferencia deveria voltar depois da janela")

    # Resposta sem a chamada (AJAX) nao apaga o N anterior.
    gate.observe("1", '{"response": {}}')
    check(gate.seen["1"][0] == 0, "resposta sem contador sobrescreveu o anterior")


def test_conferencia_que_desmente_desliga_o_gate():
    gate = RewardGate(clock=Clock())
    gate.observe("1", page(0))
    fetch, reason = gate.decide("1")
    gate.check("1", reason, 0)
    check(not gate.disabled, "conferencia que concorda nao pode desligar")
    check(gate.decide("1") == (False, "contador_zero"), "deveria pular depois de conferir")

    gate.last_verify = None
    fetch, reason = gate.decide("1")
    gate.check("1", reason, 2)
    check(gate.disabled, "contador 0 com recompensa pronta deveria desligar o gate")
    check(gate.decide("1") == (True, "gate_desligado"), "gate desligado deveria buscar sempre")

    # N > 0 sem recompensa no popup nao desliga (nao perderia nada).
    gate = RewardGate(clock=Clock())
    gate.observe("1", page(3))
    gate.check("1", "contador_positivo", 0)
    check(not gate.disabled, "positivo sem recompensa nao deveria desligar")


# --------------------------------------------------------------------------
# Fio: wrapper -> gate -> Village.get_quest_rewards
# --------------------------------------------------------------------------

def test_wrapper_anota_de_toda_resposta_html():
    w = WebWrapper("https://x/", endpoint="https://x/")
    w.post_process(FakeResponse(page(0, village_id=41123)))
    check(w.reward_gate.seen.get("41123", (None,))[0] == 0, "wrapper nao anotou N da tela")
    w.post_process(FakeResponse(page(4, village_id=41123)))
    check(w.reward_gate.seen["41123"][0] == 4, "wrapper nao atualizou N")
    # Envelope AJAX (sem a chamada) nao apaga.
    envelope = json.dumps({"response": {}, "game_data": GAME_DATA})
    w.post_process(FakeResponse(envelope, content_type="application/json"))
    check(w.reward_gate.seen["41123"][0] == 4, "envelope AJAX apagou o N")


class QuestWrapper:
    def __init__(self, gate, rewards_dialog=""):
        self.reward_gate = gate
        self.calls = 0
        self.dialog = rewards_dialog

    def get_api_data(self, **_kwargs):
        self.calls += 1
        return {"response": {"dialog": self.dialog}}


def _village(wrapper):
    v = Village(village_id="41123", wrapper=wrapper)
    v.logger = logging.getLogger("test")
    return v


def test_village_pula_o_get_com_zero():
    gate = RewardGate(clock=Clock())
    gate.observe("41123", page(0, village_id=41123))
    gate.last_verify = gate._clock()  # conferencia ja feita nesta janela
    w = QuestWrapper(gate)
    check(_village(w).get_quest_rewards() is False, "deveria devolver False")
    check(w.calls == 0, "fez o GET do popup com N = 0 fresco")

    gate.observe("41123", page(1, village_id=41123))
    _village(w).get_quest_rewards()
    check(w.calls == 1, "nao fez o GET com N > 0")

    # Sem gate (wrapper antigo/mock): GET como antes.
    w2 = SimpleNamespace(calls=0)
    w2.get_api_data = lambda **_k: setattr(w2, "calls", w2.calls + 1)
    _village(w2).get_quest_rewards()
    check(w2.calls == 1, "wrapper sem gate deveria fazer o GET")


def test_village_conferencia_desligando_com_recompensa_real():
    gate = RewardGate(clock=Clock())
    gate.observe("41123", page(0, village_id=41123))
    dialog = ('RewardSystem.setRewards([{"id":7,"status":"unlocked",'
              '"reward":{"wood":10,"stone":10,"iron":10}}], [], "", 1);')
    w = QuestWrapper(gate, dialog)
    v = _village(w)
    v.resman = SimpleNamespace(storage=0, actual={"wood": 0, "stone": 0, "iron": 0})
    v.get_quest_rewards()  # sem espaco: nao resgata, mas o popup foi lido
    check(w.calls == 1, "conferencia nao fez o GET")
    check(gate.disabled, "recompensa pronta com contador 0 deveria desligar o gate")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except Exception as exc:
                failures.append("%s: %r" % (name, exc))
    for f in failures:
        print("FALHA", f)
    print("OK" if not failures else "%d falha(s)" % len(failures))
    sys.exit(1 if failures else 0)
