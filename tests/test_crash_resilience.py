"""Queda de rede sem perder comando agendado (docs/backend.md §8.33).

Em 2026-09-27 o 4o nobre do trem contra a Barbara #55647 nao saiu. A cadeia:
a rede caiu as 14:26, `go_manage_market()` gravou `None` em `game_data` e
`set_cache_vars()` derrubou o processo (A26-02 e, A26-01); o reinicio viu a
rede fora e dormiu 11 min sem olhar o Hunter, acordando 4 s antes da saida; e
o processo novo levou ~100 s ate o primeiro `Hunter.run()`, que recusou o
comando por 102 s de atraso.

Cobre cada elo:

- `Hunter.nearest_send_time(after=)` ignora horario vencido;
- `TWB._hunter_capped_sleep()` encurta o sono cego para acordar
  `window + WAKE_MARGIN` antes da saida, com piso so quando ha schedule;
- o Hunter prima a aldeia de origem que ainda nao rodou (processo novo) e
  reconfere o atraso depois do prime;
- o Hunter nao reentra nem deixa `priority_mode` preso numa excecao;
- `main()` conta so quedas SEGUIDAS e encerra numa volta normal;
- `Village`: GET falho zera `game_data` em vez de manter o do ciclo anterior,
  a releitura do mercado nao grava `None`, e a missao sem resposta nao quebra;
- `_target_is_mine()` aceita a lista de aldeias da conta como prova de posse.

Roda sem pytest:
    python tests/test_crash_resilience.py
"""
import logging
import os
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import twb
from game.attack import ConquestManager
from game.hunter import Hunter
from game.village import Village


checks = 0


def check(condition, message):
    global checks
    checks += 1
    if not condition:
        raise AssertionError(message)


def with_schedules(schedules):
    """Troca a leitura/escrita de schedules por memoria, sem tocar cache/."""
    saved = []
    Hunter._load_schedules = lambda self: schedules
    Hunter._save_schedules = lambda self, s, *_: saved.append(s)
    return saved


ORIG_LOAD = Hunter._load_schedules
ORIG_SAVE = Hunter._save_schedules
HUNTER_ON = {"hunter": {"enabled": True}}


def restore():
    Hunter._load_schedules = ORIG_LOAD
    Hunter._save_schedules = ORIG_SAVE


# --------------------------------------------------------------------------
# nearest_send_time(after=)
# --------------------------------------------------------------------------
now = time.time()
with_schedules({
    "a": {"status": "pending", "attacks": [
        {"status": "pending", "send_time": now - 50},
        {"status": "pending", "send_time": now + 600},
    ]},
    "b": {"status": "failed", "attacks": [{"status": "pending", "send_time": now + 10}]},
})
h = Hunter()
check(h.nearest_send_time() == now - 50, "sem `after` o comportamento historico e o mesmo")
check(h.nearest_send_time(after=now) == now + 600,
      "horario vencido nao pode encurtar o sono -- o Hunter so vai marca-lo como falho")
restore()


# --------------------------------------------------------------------------
# _hunter_capped_sleep
# --------------------------------------------------------------------------
t = twb.TWB()
margin = Hunter.window + Hunter.WAKE_MARGIN

with_schedules({})
check(t._hunter_capped_sleep(660, HUNTER_ON, "x") == 660, "sem schedule nao mexe no sono")

now = time.time()
with_schedules({"s": {"status": "pending", "attacks": [
    {"status": "pending", "send_time": now + 700}]}})
capped = t._hunter_capped_sleep(660, HUNTER_ON, "x")
check(abs(capped - (700 - margin)) < 2,
      "acorda window + WAKE_MARGIN antes da saida (%.1f)" % capped)
check(t._hunter_capped_sleep(660, {"hunter": {"enabled": False}}, "x") == 660,
      "Hunter desligado nao encurta nada")
check(t._hunter_capped_sleep(100, HUNTER_ON, "x") == 100,
      "sono que ja acaba antes da janela fica como esta")

# O caso de 2026-09-27: queda as 14:27:23, saida as 14:38:41 (678 s depois),
# sono de 11 min. Antes acordava 4 s antes da saida; agora tem que sobrar
# pelo menos o custo medido de voltar (~100 s) mais a janela.
now = time.time()
with_schedules({"s": {"status": "pending", "attacks": [
    {"status": "pending", "send_time": now + 678}]}})
capped = t._hunter_capped_sleep(664, HUNTER_ON, "rede fora")
check(678 - capped >= Hunter.window + 100,
      "no caso real sobra janela + custo de voltar (%.0f s)" % (678 - capped))

now = time.time()
with_schedules({"s": {"status": "pending", "attacks": [
    {"status": "pending", "send_time": now + 60}]}})
check(t._hunter_capped_sleep(660, HUNTER_ON, "x") == t.BLIND_SLEEP_FLOOR,
      "dentro da margem o sono cai no piso, nao em zero (rede fora = laco sem pausa)")
restore()


# --------------------------------------------------------------------------
# Hunter: prime preguicoso da origem num processo novo
# --------------------------------------------------------------------------
class FakeAttack:
    def __init__(self):
        self.calls = []

    def attack(self, target_id, troops=None):
        self.calls.append((target_id, troops))
        return True


class FreshVillage:
    """Village que ainda nao rodou neste processo: sem `attack`."""

    def __init__(self, prime_delay=0.0):
        self.attack = None
        self.units = None
        self.primed = 0
        self.prime_delay = prime_delay
        self.made = FakeAttack()

    def prime_for_conquest(self, config=None):
        self.primed += 1
        time.sleep(self.prime_delay)
        self.attack = self.made
        return True


def one_attack_schedule(send_in):
    now = time.time()
    return {"k": {
        "status": "pending", "target_id": "55647", "arrival_time": now + 3600,
        "attacks": [{
            "status": "pending", "source_village_id": "74690",
            "troops": {"snob": 1}, "send_time": now + send_in,
        }],
    }}


sched = one_attack_schedule(0.3)
with_schedules(sched)
village = FreshVillage()
wrapper = SimpleNamespace(priority_mode=False)
h = Hunter(wrapper=wrapper)
h.villages = {"74690": village}
h.run(HUNTER_ON)
atk = sched["k"]["attacks"][0]
check(village.primed == 1, "origem sem AttackManager e primada antes do envio")
check(atk["status"] == "sent", "e o comando sai (status %s)" % atk["status"])
check(village.made.calls == [("55647", {"snob": 1})], "pelo AttackManager recem-criado")
check(wrapper.priority_mode is False, "priority_mode volta a False no fim")

# O prime custa tempo: se ele mesmo cruzar a saida, a regra estrita vale.
sched = one_attack_schedule(0.1)
with_schedules(sched)
village = FreshVillage(prime_delay=0.3)
h = Hunter(wrapper=SimpleNamespace(priority_mode=False))
h.villages = {"74690": village}
h.run(HUNTER_ON)
atk = sched["k"]["attacks"][0]
check(atk["status"] == "failed" and atk.get("fail_reason") == "send_time_missed",
      "prime que atravessa a saida resulta em recusa, nao em ataque atrasado")
check(village.made.calls == [], "nenhum ataque atrasado sai")

# Aldeia ja pronta nao e primada de novo.
sched = one_attack_schedule(0.2)
with_schedules(sched)
village = FreshVillage()
village.attack = village.made
h = Hunter(wrapper=SimpleNamespace(priority_mode=False))
h.villages = {"74690": village}
h.run(HUNTER_ON)
check(village.primed == 0, "aldeia com AttackManager nao paga prime")
restore()

# Reentrada e priority_mode preso.
calls = []
h = Hunter(wrapper=SimpleNamespace(priority_mode=False))


def reentrant_run(config):
    calls.append(1)
    h.wrapper.priority_mode = True
    h.run(config)  # um checkpoint chamando o Hunter de volta
    raise RuntimeError("falha no meio do schedule")


h._run = reentrant_run
try:
    h.run(HUNTER_ON)
except RuntimeError:
    pass
check(calls == [1], "Hunter nao reentra (%d chamadas)" % len(calls))
check(h.wrapper.priority_mode is False, "excecao nao deixa priority_mode preso")
check(h._running is False, "a trava e solta depois da excecao")


# --------------------------------------------------------------------------
# main(): quedas seguidas
# --------------------------------------------------------------------------
def run_main(behaviours):
    """`behaviours`: por instancia, ("crash", runs) ou ("return", runs)."""
    starts = []
    queue = list(behaviours)

    class FakeTWB:
        def __init__(self):
            self.wrapper = None
            self.runs = 0

        def start(self):
            kind, runs = queue.pop(0)
            starts.append(kind)
            self.runs = runs
            if kind == "crash":
                raise RuntimeError("boom")

    saved = (twb.TWB, twb.check_update, twb.time.sleep, twb.Notification.send,
             twb.traceback.print_exc)
    twb.TWB = FakeTWB
    twb.check_update = lambda: None
    twb.time.sleep = lambda s: None
    twb.Notification.send = staticmethod(lambda *a, **k: None)
    twb.traceback.print_exc = lambda: None
    devnull = open(os.devnull, "w")
    old_stdout, sys.stdout = sys.stdout, devnull
    try:
        twb.main()
    finally:
        sys.stdout = old_stdout
        devnull.close()
        # main() arma o Telegram de verdade; o resto da suite nao pode herdar.
        twb.Notification.armed = False
        (twb.TWB, twb.check_update, twb.time.sleep, twb.Notification.send,
         twb.traceback.print_exc) = saved
    return starts, queue


starts, _ = run_main([("return", 0), ("crash", 0)])
check(starts == ["return"], "volta normal encerra; antes gastava uma tentativa e subia outra")

starts, _ = run_main([("crash", 0), ("crash", 0), ("crash", 0), ("crash", 0)])
check(len(starts) == twb.MAX_CONSECUTIVE_CRASHES,
      "tres quedas seguidas sem ciclo completo encerram (%d)" % len(starts))

# Processo que fecha ciclo antes de cair recomeca a contagem.
starts, left = run_main([("crash", 5)] * 6 + [("crash", 0), ("crash", 0), ("crash", 0)])
check(len(starts) == 8,
      "quedas separadas por ciclos completos nao somam (%d starts)" % len(starts))
check(len(left) == 1, "e o limite ainda vale para quedas seguidas")


# --------------------------------------------------------------------------
# Village: None de rede
# --------------------------------------------------------------------------
class NoneWrapper:
    reporter = SimpleNamespace(report=lambda *a, **k: None)

    def get_url(self, url):
        return None

    def get_action(self, village_id=None, action=None):
        return None

    def get_api_data(self, **kwargs):
        return None


old_gd = {"village": {"id": 1, "name": "BBM 004", "points": 5600}}

v = Village(village_id="1", wrapper=NoneWrapper())
v.game_data = dict(old_gd)
check(v.village_init() is None, "GET falho devolve None")
check(v.game_data is None,
      "A26-02 a: game_data do ciclo anterior nao pode sobreviver a um GET falho")

# Resposta 200 que nao e tela de jogo (login, captcha).
class LoginWrapper(NoneWrapper):
    def get_url(self, url):
        return SimpleNamespace(text="<html><body>login</body></html>", status_code=200)


v = Village(village_id="1", wrapper=LoginWrapper())
v.game_data = dict(old_gd)
v.village_init()
check(v.game_data is None, "A26-02 c: tela que nao e de jogo vira game_data None, sem quebrar")


class RecordingRes:
    def __init__(self):
        self.updates = []

    def update(self, game_data):
        self.updates.append(game_data)


v = Village(village_id="1", wrapper=NoneWrapper())
v.config = {"market": {"auto_trade": False}, "world": {"trade_for_premium": False},
            "villages": {"1": {}}}
v.logger = logging.getLogger("test")
v.game_data = dict(old_gd)
v.resman = RecordingRes()
v.go_manage_market()
check(v.game_data == old_gd,
      "A26-02 e: releitura falha do mercado mantem o game_data desta execucao "
      "(era o None que derrubou o processo em 2026-09-27)")
check(v.resman.updates == [None], "e o ResourceManager recebe None, que preserva os recursos")

v = Village(village_id="1", wrapper=NoneWrapper())
v.logger = logging.getLogger("test")
check(v.get_quest_rewards() is False, "A26-02 d: missao sem resposta devolve False")


class ResponseWrapper(NoneWrapper):
    def get_api_data(self, **kwargs):
        return SimpleNamespace(text="nao e json")


v = Village(village_id="1", wrapper=ResponseWrapper())
v.logger = logging.getLogger("test")
check(v.get_quest_rewards() is False, "A26-02 d: Response cru (JSON invalido) tambem")


# --------------------------------------------------------------------------
# _target_is_mine: config["villages"] como prova de posse (A26-03)
# --------------------------------------------------------------------------
cm = ConquestManager.__new__(ConquestManager)
cm.village_id = "41123"
cm.config = {"villages": {"41123": {}, "55647": {}}}
check(cm._target_is_mine("55647") is True,
      "aldeia na lista da conta e nossa, sem esperar o cache de mapa de 8 h")
check(cm._target_is_mine(55647) is True, "id int tambem")


print("OK: %d checks" % checks)
