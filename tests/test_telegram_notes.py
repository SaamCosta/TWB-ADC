"""Avisos de Telegram de Hunter, conquista e rede (docs/backend.md §8.34).

Em 2026-09-27 o 4o nobre do trem contra a 55647 foi recusado as 14:40 e
ninguem ficou sabendo ate olhar o log -- o `Notification` existia, mas so
avisava captcha, queda e inicio. Cobre:

- o Hunter avisa comando que nao saiu (recusa por atraso, envio falho) e
  operacao que expirou, e so manda DEPOIS do run(), fora da janela de envio;
- o planejador avisa trem agendado, trem completo, trem incompleto e trem que
  nao saiu;
- `_handle_existing()` avisa conquista confirmada;
- a queda de rede e avisada uma vez, na volta, com a duracao;
- e a trava que protege o canal real: sem `arm()` (so `twb.main()` chama),
  nada sai -- a suite roda contra o `config.json` de verdade.

Roda sem pytest:
    python tests/test_telegram_notes.py
"""
import logging
import os
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import core.notification as notification_module
import game.attack as attack_module
import game.conquest_planner as planner_module
import game.hunter as hunter_module
import twb
from game.attack import ConquestManager
from game.conquest_planner import BarbarianTrainPlanner
from game.hunter import Hunter


checks = 0


def check(condition, message):
    global checks
    checks += 1
    if not condition:
        raise AssertionError(message)


class Recorder:
    def __init__(self, probe=None):
        self.messages = []
        self.probe = probe
        self.probed = []

    def send(self, message):
        self.messages.append(message)
        if self.probe:
            self.probed.append(self.probe())


# --------------------------------------------------------------------------
# A trava: importar tudo isto nao arma o singleton
# --------------------------------------------------------------------------
check(notification_module.Notification.armed is False,
      "importar twb/hunter/attack nao pode armar o Telegram")


# --------------------------------------------------------------------------
# Hunter
# --------------------------------------------------------------------------
now = time.time()
schedules = {
    "55647_2026-09-27T23-59-47_barb": {
        "status": "pending", "target_id": "55647", "arrival_time": now + 3600,
        "attacks": [{
            "status": "pending", "source_village_id": "74690",
            "troops": {"snob": 1, "spear": 162}, "send_time": now - 102,
        }],
    },
    "velho": {
        "status": "pending", "target_id": "1", "arrival_time": now - 10,
        "attacks": [{"status": "pending", "source_village_id": "74690",
                     "troops": {"axe": 1}, "send_time": now - 500}],
    },
}
Hunter._load_schedules = lambda self: schedules
Hunter._save_schedules = lambda self, s: None

h = Hunter(wrapper=SimpleNamespace(priority_mode=False))
h.villages = {"74690": SimpleNamespace(
    attack=object(), game_data={"village": {"name": "BBM 011"}})}
rec = Recorder(probe=lambda: h._running)
hunter_module.Notification = rec
h.run({"hunter": {"enabled": True}})

joined = "\n".join(rec.messages)
check(len(rec.messages) == 2, "um aviso por problema (%d)" % len(rec.messages))
check("BBM 011 (74690) -> 55647" in joined and "com nobre" in joined
      and "102 s" in joined,
      "recusa por atraso diz quem, contra quem, que era nobre e quanto: %r" % joined)
check("velho expirou" in joined, "operacao expirada com comando pendente e avisada")
check(rec.probed == [False, False],
      "avisos saem depois do run(), nunca dentro da janela de envio")

# Segundo run: tudo ja esta failed, nada de repetir aviso.
rec.messages.clear()
h.run({"hunter": {"enabled": True}})
check(rec.messages == [], "o mesmo problema nao e avisado duas vezes")


# --------------------------------------------------------------------------
# Planejador: promocao do trem
# --------------------------------------------------------------------------
class MemoryFM:
    def __init__(self, files):
        self.files = files

    def load_json_file(self, path):
        return self.files.get(path.replace("\\", "/"))

    def list_directory(self, path, ends_with=None):
        prefix = path.rstrip("/") + "/"
        return [k[len(prefix):] for k in self.files if k.startswith(prefix)]


def promote(sent, total):
    attacks = ([{"status": "sent"}] * sent) + ([{"status": "failed"}] * (total - sent))
    fm = MemoryFM({
        Hunter.SCHEDULE_CACHE: {"k": {"arrival_time": now + 30000, "attacks": attacks}},
        "cache/conquest/55647.json": {
            "status": "train_scheduled", "hunter_schedule_key": "k",
            "target_name": "Bárbara #55647", "target_location": [582, 288],
            "loyalty_drop_per_noble": 20,
        },
    })
    planner_module.FileManager = fm
    written = []
    saved_set = planner_module.ConquestCache.set
    planner_module.ConquestCache.set = staticmethod(lambda t, e: written.append(e))
    rec = Recorder()
    planner_module.Notification = rec
    p = BarbarianTrainPlanner.__new__(BarbarianTrainPlanner)
    p.logger = logging.getLogger("test")
    p.config = {}
    p._release = lambda target_id: None
    try:
        p._promote_scheduled_trains()
    finally:
        planner_module.ConquestCache.set = saved_set
    return rec.messages


msgs = promote(3, 4)
check(len(msgs) == 1 and "INCOMPLETA" in msgs[0] and "3 de 4" in msgs[0]
      and "(582|288)" in msgs[0],
      "trem incompleto e avisado com a conta e a coordenada: %r" % msgs)
msgs = promote(4, 4)
check(len(msgs) == 1 and "os 4 nobres" in msgs[0], "trem completo: %r" % msgs)
msgs = promote(0, 4)
check(len(msgs) == 1 and "FALHOU" in msgs[0], "trem que nao saiu: %r" % msgs)


# --------------------------------------------------------------------------
# Conquista confirmada
# --------------------------------------------------------------------------
rec = Recorder()
attack_module.Notification = rec
saved_set = attack_module.ConquestCache.set
attack_module.ConquestCache.set = staticmethod(lambda t, e: None)
cm = ConquestManager.__new__(ConquestManager)
cm.village_id = "41123"
cm.config = {"villages": {"41123": {}, "55647": {}}}
cm.logger = logging.getLogger("test")
cm.wrapper = SimpleNamespace(reporter=SimpleNamespace(report=lambda *a, **k: None))
cm._drop_min = 20
try:
    cm._handle_existing({"target_id": "55647", "target_name": "Bárbara #55647",
                         "target_location": [582, 288]}, {})
finally:
    attack_module.ConquestCache.set = saved_set
check(len(rec.messages) == 1 and "Bárbara #55647 (582|288) e nossa" in rec.messages[0],
      "conquista confirmada e avisada: %r" % rec.messages)


# --------------------------------------------------------------------------
# Queda de rede: um aviso, na volta
# --------------------------------------------------------------------------
rec = Recorder()
twb.Notification = rec
twb._mark_online()
check(rec.messages == [], "sem queda nao ha aviso")
twb._mark_offline()
first = twb._offline_since
twb._offline_since = first - 660  # 11 min fora
twb._mark_offline()
check(twb._offline_since == first - 660,
      "a queda guarda o INICIO, passos seguintes da espera nao o empurram")
twb._mark_online()
check(len(rec.messages) == 1 and "11 min" in rec.messages[0],
      "volta avisa uma vez, com a duracao: %r" % rec.messages)
twb._mark_online()
check(len(rec.messages) == 1, "e so uma vez")


print("OK: %d checks" % checks)
