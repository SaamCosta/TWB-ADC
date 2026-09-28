"""Lote B da auditoria de 2026-09-26 (docs/backend.md §8.32 e §8.35).

A26-03 -- a lealdade real do relatorio do nobre nunca era lida: nenhum
construtor de `ConquestManager` passava `repman`, e os 28 registros de
`cache/conquest` tinham `loyalty_source: "estimate"`. Cobre:

- `Village.run_conquest()` entrega um `ReportManager` (criado se faltar);
- `_get_real_loyalty()` atualiza a lista de relatorios UMA vez antes de ler,
  porque a leitura da ancora no inicio do ciclo e do ciclo anterior;
- o caso que importa, ponta a ponta em `_handle_existing()`: o relatorio que
  so aparece na leitura nova diz lealdade <= 0 e a conquista fecha como
  `noble_report`, sem nobre extra;
- leitura de relatorio que falha nao derruba nada.

A26-04 -- o Hunter expirava o schedule mas deixava os ataques `pending`. Cobre
a marcacao `failed/arrival_passed` sem tocar nos que sairam, e o aviso unico.

(A promocao do planejador e o A26-14 estao em tests/test_conquest_planner.py.)

Nada toca cache/ nem a rede. Roda sem pytest:
    python tests/test_conquest_loyalty_and_expiry.py
"""
import logging
import os
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import game.attack as attack_module
import game.hunter as hunter_module
import game.village as village_module
from game.attack import ConquestManager
from game.hunter import Hunter
from game.village import Village


checks = 0


def check(condition, message):
    global checks
    checks += 1
    if not condition:
        raise AssertionError(message)


class Recorder:
    def __init__(self):
        self.messages = []

    def send(self, message):
        self.messages.append(message)


# --------------------------------------------------------------------------
# A26-04: Hunter fecha os ataques pendentes de um schedule vencido
# --------------------------------------------------------------------------
now = time.time()
schedules = {
    "55647_barb": {
        "status": "pending", "target_id": "55647", "arrival_time": now - 60,
        "attacks": [
            {"status": "sent", "source_village_id": "41123", "troops": {"snob": 1}},
            {"status": "pending", "source_village_id": "74690",
             "troops": {"snob": 1}, "send_time": now - 5000},
        ],
    },
    "futuro": {
        "status": "pending", "target_id": "1", "arrival_time": now + 86400,
        "attacks": [{"status": "pending", "source_village_id": "74690",
                     "troops": {"axe": 1}, "send_time": now + 80000}],
    },
}
Hunter._load_schedules = lambda self: schedules
Hunter._save_schedules = lambda self, s, *_: None
rec = Recorder()
hunter_module.Notification = rec
h = Hunter(wrapper=SimpleNamespace(priority_mode=False))
h.villages = {}
h.run({"hunter": {"enabled": True}})

old = schedules["55647_barb"]
check(old["status"] == "failed", "schedule vencido vira failed")
check(old["attacks"][0]["status"] == "sent", "o que saiu continua sent")
check(old["attacks"][1]["status"] == "failed"
      and old["attacks"][1]["fail_reason"] == "arrival_passed",
      "o pendente vira failed/arrival_passed: %r" % old["attacks"][1])
check(schedules["futuro"]["attacks"][0]["status"] == "pending",
      "schedule no futuro nao e tocado")
check(len(rec.messages) == 1 and "55647_barb expirou" in rec.messages[0],
      "um aviso de expiracao: %r" % rec.messages)
rec.messages.clear()
h.run({"hunter": {"enabled": True}})
check(rec.messages == [], "sem pendente sobrando, nao avisa de novo")


# --------------------------------------------------------------------------
# A26-03: Village.run_conquest() entrega o repman
# --------------------------------------------------------------------------
captured = {}


class CaptureManager:
    def __init__(self, **kwargs):
        captured.update(kwargs)

    def run(self):
        captured["ran"] = True


saved_cm = village_module.ConquestManager
village_module.ConquestManager = CaptureManager
try:
    v = Village.__new__(Village)
    v.village_id = "41123"
    v.config = {"conquest": {"enabled": True}, "villages": {"41123": {}}}
    v.logger = logging.getLogger("test")
    v.wrapper = object()
    v.units = object()
    v.area = object()
    v.rep_man = None
    v.reservation_board = None
    v._pvp_troop_spending_suspended = lambda: False
    v.run_conquest()
finally:
    village_module.ConquestManager = saved_cm

check(captured.get("ran") is True, "o ConquestManager rodou")
check(captured.get("repman") is v.rep_man and v.rep_man is not None,
      "run_conquest cria o ReportManager e passa O MESMO objeto da aldeia")
check(v.rep_man.last_reports == {},
      "criar o repman nao le nada (quem le e _get_real_loyalty)")


# --------------------------------------------------------------------------
# A26-03: _get_real_loyalty le a lista nova uma vez
# --------------------------------------------------------------------------
NOBLE_REPORT = {
    "type": "attack", "dest": "55647",
    "extra": {"loyalty_after": -7.0, "units_sent": {"snob": 1, "axe": 100},
              "when": int(now) - 120},
}


class FakeRepman:
    """Antes do read(): so o que a ancora viu no ciclo anterior."""

    def __init__(self, fail=False):
        self.last_reports = {"1": {"type": "attack", "dest": "55647",
                                   "extra": {"units_sent": {"axe": 5}}}}
        self.reads = 0
        self.fail = fail

    def read(self, full_run=False):
        self.reads += 1
        if self.fail:
            raise AttributeError("'NoneType' object has no attribute 'text'")
        self.last_reports["2"] = NOBLE_REPORT


def manager(repman):
    cm = ConquestManager.__new__(ConquestManager)
    cm.village_id = "41123"
    cm.config = {"villages": {"41123": {}}}
    cm.logger = logging.getLogger("test")
    cm.repman = repman
    cm.wrapper = SimpleNamespace(reporter=SimpleNamespace(report=lambda *a, **k: None))
    cm._drop_min = 20
    return cm


rm = FakeRepman()
cm = manager(rm)
check(cm._get_real_loyalty("55647") == -7.0,
      "o relatorio do nobre so existe depois da leitura nova, e e achado")
check(cm._get_real_loyalty("55647") == -7.0 and rm.reads == 1,
      "uma leitura por instancia (%d)" % rm.reads)

rm = FakeRepman(fail=True)
check(manager(rm)._get_real_loyalty("55647") is None,
      "leitura que falha nao derruba: fica o que havia em memoria")
check(manager(None)._get_real_loyalty("55647") is None, "sem repman, None como antes")


# --------------------------------------------------------------------------
# A26-03 ponta a ponta: pouso lido pelo relatorio, sem nobre extra
# --------------------------------------------------------------------------
written = []
rec = Recorder()
saved_set = attack_module.ConquestCache.set
saved_note = attack_module.Notification
attack_module.ConquestCache.set = staticmethod(lambda t, e: written.append(e))
attack_module.Notification = rec
try:
    rm = FakeRepman()
    cm = manager(rm)
    # A cena do incidente de 12/08: o cache de mapa ainda diz barbara e a
    # conta ainda nao lista a aldeia (visao geral lida antes do pouso).
    cm._target_is_mine = lambda tid: False
    cm._target_taken_by_other = lambda tid: None
    cm._get_village_meta = lambda tid: {}
    cm._claim_block_reason = lambda tid, loc: None
    cm._noble_flight_guard = lambda tid, data: False

    def no_extra(*a, **k):
        raise AssertionError("mandou nobre extra contra aldeia ja conquistada")

    cm._available_nobles = no_extra
    cm._handle_existing({
        "target_id": "55647", "status": "train_sent", "hits_done": 4,
        "loyalty_after_train": 20, "last_hit_timestamp": int(now) - 3 * 3600,
        "target_name": "Bárbara #55647", "target_location": [582, 288],
    }, {"loyalty_regen_per_hour": 1})
finally:
    attack_module.ConquestCache.set = saved_set
    attack_module.Notification = saved_note

check(written and written[-1]["status"] == "conquered"
      and written[-1]["confirmed_by"] == "noble_report",
      "fecha pelo relatorio: %r" % (written[-1] if written else None))
check(rm.reads == 1, "a leitura aconteceu no caminho do _handle_existing")


print("OK: %d checks" % checks)
