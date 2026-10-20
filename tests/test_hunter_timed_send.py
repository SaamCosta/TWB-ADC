"""
Envio cronometrado e reserva do ataque manual no Hunter (docs/backend.md §8.72).

Cobre: a conta do relogio (`core/send_clock.py`: deslocamento local ->
servidor pelo `time_generated` da confirmacao, latencia de ida, instante de
soltar o POST final), o `AttackManager.attack(send_time=...)` segurando so o
envio final e estimando a chegada carimbada, o Hunter acordando
`PREARM_SECONDS` antes da saida (e o apoio, que nao tem pre-armado, no
`send_time`), e a reserva da tropa de schedule cadastrado a mao no painel
(`sync_schedule_reserves`), sem reservar de novo o que PvP e planejador
barbaro ja reservam.

Sem rede, sem relogio real e sem tocar o `cache/hunter/schedules.json`.

Rodar: python tests/test_hunter_timed_send.py
"""
import datetime
import json
import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import send_clock
import game.attack as attack_module
import game.hunter as hunter_module
from game.attack import AttackManager
from game.hunter import Hunter

FAILS = []


def _check(name, got, want):
    if got == want:
        print("ok   %s" % name)
    else:
        print("FALHA %s: %r != %r" % (name, got, want))
        FAILS.append(name)


def _near(name, got, want, tol=1e-6):
    if got is not None and abs(got - want) <= tol:
        print("ok   %s" % name)
    else:
        print("FALHA %s: %r != %r (+-%s)" % (name, got, want, tol))
        FAILS.append(name)


class FakeTime:
    def __init__(self, now):
        self.now = float(now)
        self.slept = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += max(0.0, seconds)


def _game_data_html(generated_ms):
    return "<script>TribalWars.updateGameData(%s);</script>" % json.dumps(
        {"village": {"id": 41123}, "time_generated": generated_ms})


# ----------------------------------------------------------------------
# core/send_clock
# ----------------------------------------------------------------------

def test_conta_do_relogio():
    print("test_conta_do_relogio")
    # Servidor gerou em 1000,500; resposta voltou em 1000,700 local com ida e
    # volta de 0,2 s: o meio local e 1000,600, o servidor esta 0,1 s atras.
    _near("deslocamento", send_clock.server_offset(1000500, 1000.7, 0.2), -0.1)
    _check("sem time_generated", send_clock.server_offset(None, 1000.7, 0.2), None)
    # send_time 2000 (hora do servidor), alvo 0,4 s dentro do segundo, ida
    # de 0,1 s, servidor 0,1 s atras: solta em 2000 + 0,4 + 0,1 - 0,1.
    _near("instante local", send_clock.local_fire_time(2000, -0.1, 0.1), 2000.4)
    _near("sem deslocamento medido", send_clock.local_fire_time(2000, None, 0.1), 2000.3)


def test_time_generated_html_e_ajax():
    print("test_time_generated_html_e_ajax")
    html = SimpleNamespace(text=_game_data_html(1792533087123))
    _check("HTML", send_clock.time_generated(html), 1792533087123.0)
    _check("JSON do popup_command",
           send_clock.time_generated({"response": {}, "game_data": {"time_generated": 5}}), 5.0)
    _check("sem game_data", send_clock.time_generated({"ok": True}), None)
    _check("resposta vazia", send_clock.time_generated(None), None)


# ----------------------------------------------------------------------
# AttackManager.attack(send_time=...)
# ----------------------------------------------------------------------

CONFIRM_FORM = """
<form id="command-data-form">
  <input type="hidden" name="ch" value="command-token">
  <input type="hidden" name="x" value="489">
  <input type="hidden" name="y" value="284">
  <input type="hidden" name="axe" value="6000">
</form>
<span class="relative_time" data-duration="163260">45:21:00</span>
"""


class TimedWrapper:
    """Confirmacao com ida e volta de 0,2 s e servidor 1,5 s a frente."""

    OFFSET = 1.5
    RTT = 0.2

    def __init__(self, clock):
        self.clock = clock
        self.last_h = "h"
        self.final_at = None

    def get_url(self, url):
        self.clock.now += self.RTT
        return SimpleNamespace(text="<form></form>", status_code=200)

    def post_url(self, url, data):
        self.clock.now += self.RTT
        generated = (self.clock.now - self.RTT / 2 + self.OFFSET) * 1000
        return SimpleNamespace(
            text=CONFIRM_FORM + _game_data_html(generated), status_code=200,
            elapsed=datetime.timedelta(seconds=self.RTT))

    def get_api_action(self, village_id, action, params=None, data=None):
        # O servidor processa o envio final meia ida e volta depois de soltar.
        self.final_at = self.clock.now + self.RTT / 2 + self.OFFSET
        self.clock.now += self.RTT
        return {"response": {}, "game_data": {"time_generated": self.final_at * 1000}}


def _manager(wrapper):
    return AttackManager(
        wrapper=wrapper, village_id="41123",
        troopmanager=SimpleNamespace(troops={"axe": "6000"}),
        map=SimpleNamespace(map_pos={"48451": (489, 284)}))


def test_attack_segura_so_o_envio_final():
    print("test_attack_segura_so_o_envio_final")
    original = attack_module.time
    clock = FakeTime(1000.0)
    attack_module.time = clock
    try:
        wrapper = TimedWrapper(clock)
        manager = _manager(wrapper)
        # Saida as 1011,5 do servidor = 1010 local; o Hunter chama 10 s antes.
        send_time = 1011.5
        result = manager.attack("48451", troops={"axe": 6000}, send_time=send_time)
        _check("enviado", bool(result), True)
        _near("servidor processa no alvo do segundo", wrapper.final_at,
              send_time + send_clock.AIM_SECONDS, tol=1e-6)
        _near("deslocamento medido", manager.last_send_clock["offset"], 1.5)
        _near("chegada estimada = processamento + duracao", manager.last_arrival_estimate,
              send_time + send_clock.AIM_SECONDS + 163260)

        # Chamado tarde (prep engoliu a folga): solta na hora, sem dormir.
        clock2 = FakeTime(1020.0)
        attack_module.time = clock2
        wrapper2 = TimedWrapper(clock2)
        _manager(wrapper2).attack("48451", troops={"axe": 6000}, send_time=1011.5)
        _check("atrasado nao dorme", clock2.slept, [])

        # Sem send_time, caminho de sempre: nenhuma espera.
        clock3 = FakeTime(1000.0)
        attack_module.time = clock3
        _manager(TimedWrapper(clock3)).attack("48451", troops={"axe": 6000})
        _check("sem send_time nao dorme", clock3.slept, [])
    finally:
        attack_module.time = original


# ----------------------------------------------------------------------
# Hunter: pre-armado e reserva
# ----------------------------------------------------------------------

def _sched(send_time, kind=None, label=None, source="41123", troops=None):
    atk = {"source_village_id": source, "troops": troops or {"axe": 6000, "knight": 1},
           "is_fake": False, "send_time": send_time, "status": "pending"}
    if kind:
        atk["kind"] = kind
    sched = {"target_id": "48451", "arrival_time": send_time + 163260,
             "status": "pending", "attacks": [atk]}
    if label:
        sched["label"] = label
    return sched


def test_hunter_acorda_antes_e_passa_send_time():
    print("test_hunter_acorda_antes_e_passa_send_time")
    original = hunter_module.time
    clock = FakeTime(1000.0)
    hunter_module.time = clock
    try:
        schedules = {"manual": _sched(1100.0)}
        hunter = Hunter(wrapper=SimpleNamespace(priority_mode=False))
        hunter._load_schedules = lambda: schedules
        hunter._save_schedules = lambda *_a, **_kw: None
        hunter._ensure_source_ready = lambda *_a, **_kw: None
        hunter._schedule_deleted = lambda *_a: False
        calls = []

        def send(batch, target, send_time=None):
            calls.append((clock.now, send_time))
            return True
        hunter._send_attack_batch = send
        hunter._run({"hunter": {"enabled": True}})
        _check("chamou PREARM_SECONDS antes, com o send_time",
               calls, [(1100.0 - Hunter.PREARM_SECONDS, 1100.0)])
    finally:
        hunter_module.time = original


def test_apoio_nao_pre_arma():
    print("test_apoio_nao_pre_arma")
    original = hunter_module.time
    clock = FakeTime(1000.0)
    hunter_module.time = clock
    try:
        schedules = {"apoio": _sched(1100.0, kind="support", troops={"heavy": 300})}
        hunter = Hunter(wrapper=SimpleNamespace(priority_mode=False))
        hunter._load_schedules = lambda: schedules
        hunter._save_schedules = lambda *_a, **_kw: None
        hunter._ensure_source_ready = lambda *_a, **_kw: None
        hunter._schedule_deleted = lambda *_a: False
        seen = []
        hunter._send_support = lambda atk, sched, all_: seen.append(clock.now) or True
        hunter._run({"hunter": {"enabled": True}})
        _check("apoio sai no send_time", seen, [1100.0])
    finally:
        hunter_module.time = original


def test_reserva_do_ataque_manual():
    print("test_reserva_do_ataque_manual")
    hunter = Hunter(wrapper=None)
    village = SimpleNamespace(units=SimpleNamespace(conquest_reserve={
        "hunter_manual:velho": {"axe": 1}, "pvp:999": {"axe": 9}}))
    hunter.villages = {"41123": village}
    schedules = {
        "manual": _sched(1e12),
        "pvp": _sched(1e12, label="nobles"),
        "barb": _sched(1e12, label="barb"),
    }
    # Dois comandos da mesma origem no mesmo schedule somam.
    schedules["manual"]["attacks"].append(dict(schedules["manual"]["attacks"][0]))
    hunter.sync_schedule_reserves(schedules)
    reserve = village.units.conquest_reserve
    _check("manual reservado (somado)", reserve.get("hunter_manual:manual"),
           {"axe": 12000, "knight": 2})
    _check("PvP e barbaro nao reservam de novo",
           sorted(k for k in reserve if k.startswith("hunter_manual")), ["hunter_manual:manual"])
    _check("reserva manual que sumiu solta", "hunter_manual:velho" in reserve, False)
    _check("reserva alheia intacta", reserve.get("pvp:999"), {"axe": 9})
    for atk in schedules["manual"]["attacks"]:
        atk["status"] = "sent"
    hunter.sync_schedule_reserves(schedules)
    _check("enviado solta", "hunter_manual:manual" in reserve, False)


if __name__ == "__main__":
    test_conta_do_relogio()
    test_time_generated_html_e_ajax()
    test_attack_segura_so_o_envio_final()
    test_hunter_acorda_antes_e_passa_send_time()
    test_apoio_nao_pre_arma()
    test_reserva_do_ataque_manual()
    if FAILS:
        print("\n%d falha(s): %s" % (len(FAILS), ", ".join(FAILS)))
        sys.exit(1)
    print("\ntodos ok")
