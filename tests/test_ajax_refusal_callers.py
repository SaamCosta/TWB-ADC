"""A26-09, o resto: recusa AJAX nao conta como acao feita fora da coleta.

A coleta foi fechada na §8.63 (`tests/test_ajax_refusal.py`). Este arquivo
cobre os outros consumidores de `get_api_action`/`post_api_data` que tratavam
`{"error": [...]}` -- um dict verdadeiro, status 200 -- como sucesso:

- `AttackManager.attack()` (popup_command): farm, Hunter, conquista e PvP
  contavam o comando como criado. Agora devolve False com
  `last_attack_failure = "recusado_pelo_jogo"` e o texto em `last_refusal`,
  igual a recusa da etapa `try=confirm`;
- `DefenceManager.support()`: logava "enviado e confirmado pelo jogo";
- `flag_logic()`: gravava `current_flag` e logava `Setting flag` (a linha que
  a validacao do Bug 1 conta) para uma bandeira que nao foi equipada;
- `attempt_research()`: armava `_research_wait` pelo tempo da pesquisa;
- troca premium (`exchange_confirm`) e missao (`quest_complete`,
  `claim_reward`; este levantava KeyError em `qres['response']`).

Por que a recusa vale para todo endpoint e nao so para o da coleta: o cliente
do jogo passa toda resposta AJAX por `TribalWars.handleResponse`
(`game.47097f.js`, br143), e `error` verdadeiro vai para o callback de erro.
Objeto vira `Object.values(...)`; o detector faz o mesmo.

A recusa e verbatim do br143 (2026-10-17, §8.63). Nada toca cache/ nem a rede.
Roda sem pytest:
    python tests/test_ajax_refusal_callers.py
"""
import json
import logging
import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.extractors import Extractor  # noqa: E402
from game.attack import AttackManager  # noqa: E402
from game.defence_manager import DefenceManager  # noqa: E402
from game.troopmanager import TroopManager  # noqa: E402
from game.village import Village  # noqa: E402

logging.disable(logging.CRITICAL)

REFUSAL = json.loads(
    '{"error":["\\u00c9 necess\\u00e1rio que tenha conta premium para utilizar esta fun\\u00e7\\u00e3o."]}')
REFUSAL_TEXT = REFUSAL["error"][0]
OK = {"response": {"success": True}, "game_data": {"village": {"id": 1}}}

checks = 0


def check(condition, message):
    global checks
    checks += 1
    if not condition:
        raise AssertionError(message)


# --- O detector: o formato objeto do handleResponse -------------------------

check(Extractor.ajax_error({"error": {"0": "a", "1": "b"}}) == "a; b",
      "erro em objeto vira os valores, como Object.values do cliente")
check(Extractor.ajax_error({"error": {}}) is None, "objeto vazio nao e recusa")
check(Extractor.ajax_error(OK) is None, "envelope bom nao e recusa")
check(Extractor.ajax_error({"bot_protect": "forced"}) is None,
      "bot_protect fica como desconhecido, nao como recusa (nobre extra)")


# --- attack(): popup_command ------------------------------------------------

PRE_ATTACK_HTML = '<form><input type="hidden" name="token" value="pre"></form>'
CONFIRM_HTML = """
<form id="command-data-form">
  <input type="hidden" name="attack" value="">
  <input type="hidden" name="ch" value="command-token">
  <input type="hidden" name="x" value="578">
  <input type="hidden" name="y" value="297">
  <input type="hidden" name="source_village" value="41123">
  <input type="hidden" name="axe" value="98">
  <input type="hidden" name="h" value="page-token">
</form>
<span class="relative_time" data-duration="9780">2:43:00</span>
"""


class AttackWrapper:
    def __init__(self, final):
        self.last_h = "csrf"
        self.final = final
        self.api_actions = []

    def get_url(self, url):
        return SimpleNamespace(text=PRE_ATTACK_HTML, status_code=200)

    def post_url(self, url, data):
        return SimpleNamespace(text=CONFIRM_HTML, status_code=200)

    def get_api_action(self, village_id, action, params=None, data=None):
        self.api_actions.append(action)
        return self.final


def attack_with(final):
    manager = AttackManager(
        wrapper=AttackWrapper(final),
        village_id="41123",
        troopmanager=SimpleNamespace(troops={"axe": "1000"}),
        map=SimpleNamespace(map_pos={"42248": (578, 297)}),
    )
    manager.logger = logging.getLogger("test.ajax_callers")
    return manager, manager.attack("42248", troops={"axe": 98})


manager, result = attack_with(REFUSAL)
check(manager.wrapper.api_actions == ["popup_command"], "o envio final foi tentado")
check(result is False, "recusa no envio final nao e comando criado: %r" % (result,))
check(manager.last_attack_failure == "recusado_pelo_jogo",
      "marcador de recusa (o nobre extra so tenta outra origem com ele): %r"
      % manager.last_attack_failure)
check(manager.last_refusal == REFUSAL_TEXT, "texto do jogo em last_refusal: %r" % manager.last_refusal)

manager, result = attack_with(OK)
check(result == OK, "resposta boa segue devolvida como antes")
check(manager.last_attack_failure is None, "sucesso nao tem marcador")

# Sem resposta continua desconhecido: falso SEM marcador, e e isso que faz o
# nobre extra parar em vez de mandar de outra origem (pode ter saido).
manager, result = attack_with(None)
check(not result and manager.last_attack_failure is None,
      "None segue sem marcador: %r / %r" % (result, manager.last_attack_failure))


# --- support(): popup_command de apoio ---------------------------------------

with open(os.path.join(ROOT, "tests", "fixtures", "place_confirm_support_br143.html"),
          encoding="utf-8") as fh:
    CONFIRM_SUPPORT = fh.read()


class SupportWrapper:
    last_h = "csrf"

    def __init__(self, final):
        self.final = final

    def get_url(self, url):
        return SimpleNamespace(text='<input name="support" value="Apoio">')

    def post_url(self, url, data):
        return SimpleNamespace(text=CONFIRM_SUPPORT)

    def get_api_action(self, village_id, action, params, data):
        return self.final


dm = DefenceManager(village_id="32056", wrapper=SupportWrapper(REFUSAL))
dm.logger = logging.getLogger("test.ajax_callers")
result = dm.support(None, troops={"spy": 1}, position=(578, 305))
check(result is False, "apoio recusado nao foi enviado: %r" % (result,))
check(dm.last_support_error == "recusado pelo jogo: %s" % REFUSAL_TEXT,
      "motivo para o Hunter e a defesa propria: %r" % dm.last_support_error)
check(dm.last_support_troops is None, "nada registrado como apoio em voo")

dm = DefenceManager(village_id="32056", wrapper=SupportWrapper(OK))
dm.logger = logging.getLogger("test.ajax_callers")
check(dm.support(None, troops={"spy": 1}, position=(578, 305)) == OK, "apoio aceito como antes")


# --- flag_logic(): assign_flag -----------------------------------------------

def flag_manager(answer):
    d = DefenceManager(village_id="99999", wrapper=None)
    d.logger = logging.getLogger("test.ajax_callers")
    d.manage_flags_enabled = True
    d.has_academy = False
    d.current_flag = None
    d.flags = {1: 5}
    d._can_change_flag = True
    d._flag_state_confirmed = True
    d._flags_fresh = True
    d.flag_supply = {}
    d.sent = []
    d.flag_set = lambda flag, level: d.sent.append((flag, level)) or answer
    return d


d = flag_manager(REFUSAL)
d.flag_logic(d.preferred_flags())
check(d.sent == [(1, 5)], "a troca foi tentada: %r" % d.sent)
check(d.current_flag is None, "recusa nao equipa nada: %r" % d.current_flag)

d = flag_manager(OK)
d.flag_logic(d.preferred_flags())
check(d.current_flag == [1, 5], "aceite grava o estado local como antes: %r" % d.current_flag)

d = flag_manager(None)
d.flag_logic(d.preferred_flags())
check(d.current_flag == [1, 5], "sem resposta segue o caminho antigo (pode ter equipado)")


# --- attempt_research(): research --------------------------------------------

def research_with(answer):
    tm = TroopManager.__new__(TroopManager)
    tm.wrapper = SimpleNamespace(last_h="csrf", get_api_action=lambda **kw: answer)
    tm.village_id = "41123"
    tm.logger = logging.getLogger("test.ajax_callers")
    tm._research_wait = 0
    smith = {"available": {"axe": {"can_research": True, "research_time": "1:00:00"}}}
    return tm, tm.attempt_research("axe", smith_data=smith)


tm, started = research_with(REFUSAL)
check(started is False, "pesquisa recusada nao comecou: %r" % (started,))
check(tm._research_wait == 0, "recusa nao para o ferreiro pelo tempo da pesquisa")
tm, started = research_with(OK)
check(started is True and tm._research_wait > 0, "pesquisa aceita como antes")


# --- missoes: quest_complete e claim_reward ----------------------------------

def quest_village(answer):
    v = Village.__new__(Village)
    v.village_id = "41123"
    v.logger = logging.getLogger("test.ajax_callers")
    v.wrapper = SimpleNamespace(last_response=None, get_api_action=lambda **kw: answer)
    return v


original_get_quests = Extractor.get_quests
Extractor.get_quests = staticmethod(lambda _r: "1234")
try:
    check(quest_village(REFUSAL).get_quests() is False, "missao recusada nao foi concluida")
    check(quest_village(OK).get_quests() is True, "missao aceita como antes")
finally:
    Extractor.get_quests = staticmethod(original_get_quests)


def reward_village(answer):
    v = Village.__new__(Village)
    v.village_id = "41123"
    v.logger = logging.getLogger("test.ajax_callers")
    dialog = "x"
    v.wrapper = SimpleNamespace(
        reward_gate=None,
        get_api_data=lambda **kw: {"response": {"dialog": dialog}},
        post_api_data=lambda **kw: answer,
    )
    v.resman = SimpleNamespace(storage=100000, actual={"wood": 0, "stone": 0, "iron": 0})
    return v


original_rewards = Extractor.get_quest_rewards
Extractor.get_quest_rewards = staticmethod(
    lambda _d: [{"id": "77", "reward": {"wood": 100, "stone": 0, "iron": 0}}])
try:
    v = reward_village(REFUSAL)
    try:
        claimed = v.get_quest_rewards()
    except KeyError as exc:  # o bug antigo: qres['response']
        raise AssertionError("recusa de claim_reward levantou KeyError %s" % exc)
    check(claimed is False, "recompensa recusada nao conta")
    check(v.resman.actual["wood"] == 0, "recusa nao soma recurso local")

    v = reward_village(SimpleNamespace(status_code=200, text="<html>"))
    check(v.get_quest_rewards() is False, "resposta nao-JSON nao quebra")

    v = reward_village({"response": True, "game_data": {}})
    check(v.get_quest_rewards() is True and v.resman.actual["wood"] == 100,
          "recompensa aceita soma como antes")
finally:
    Extractor.get_quest_rewards = staticmethod(original_rewards)


print("OK - %d checks" % checks)
