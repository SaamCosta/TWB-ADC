"""
Portao do Hunter antes de cada tarefa (`Hunter.gate`, `core/phase_forecast.py`).

Caso real que motivou, 2026-10-08, Barbara #57033: o checkpoint olhou a fila
com 168 s de folga, a janela era 120 s, o trecho seguinte levou 174 s e o 4o
nobre saiu 6 s atrasado -- recusado. Agora, antes de cada fase, o bot compara
a duracao prevista dela com o tempo ate a proxima saida: adia o que e
adiavel, segura o que nao e, e a menos de 300 s nao comeca nada.

Sem rede e sem relogio de verdade: o `time` do modulo do Hunter e trocado por
um relogio falso, e o `cache/cycles` por um diretorio temporario.
"""

import json
import logging
import os
import sys
import tempfile
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import game.hunter as hunter_module  # noqa: E402
from core.phase_forecast import PhaseForecast  # noqa: E402
from core.request import WebWrapper  # noqa: E402
from game.hunter import Hunter  # noqa: E402
from game.village import Village  # noqa: E402

CONFIG = {"hunter": {"enabled": True}}
T0 = 1791480000.0


class FakeTime:
    def __init__(self, now=T0):
        self.now = now
        self.slept = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += max(0.0, seconds)


def _hunter(clock, schedules):
    hunter_module.time = clock
    wrapper = SimpleNamespace(priority_mode=False)
    h = Hunter(wrapper=wrapper)
    h._load_schedules = lambda: schedules
    h._save_schedules = lambda *_a: None
    h.sent = []

    def send(batch, target):
        h.sent.append((batch[0]["source_village_id"], target, clock.now))
        return True
    h._send_attack_batch = send
    return h


def _schedules(send_time, arrival=None):
    return {"57033_barb": {
        "target_id": "57033", "arrival_time": arrival or send_time + 55000,
        "status": "pending",
        "attacks": [{"source_village_id": "46676", "troops": {"snob": 1},
                     "is_fake": False, "send_time": send_time, "status": "pending"}],
    }}


def test_caso_57033_segura_e_manda_no_segundo_exato():
    """168 s ate a saida e uma fase de 174 s: o bot nao comeca a fase."""
    clock = FakeTime()
    sched = _schedules(T0 + 168)
    h = _hunter(clock, sched)
    ok = h.gate(CONFIG, "compartilhamento", 174, skippable=True, village_id="49709")
    assert h.sent == [("46676", "57033", T0 + 168)], h.sent
    assert sched["57033_barb"]["attacks"][0]["status"] == "sent"
    assert ok is True, "depois da saida nao sobra nada perto: a fase pode rodar"


def test_janela_de_silencio_segura_mesmo_fase_curta():
    """A menos de 300 s nada comeca, nem uma fase prevista em 5 s."""
    clock = FakeTime()
    h = _hunter(clock, _schedules(T0 + 290))
    h.gate(CONFIG, "missoes", 5, skippable=True, village_id="1")
    assert h.sent and h.sent[0][2] == T0 + 290, h.sent


def test_fase_que_nao_cabe_e_adiada_sem_esperar():
    clock = FakeTime()
    h = _hunter(clock, _schedules(T0 + 1000))
    ok = h.gate(CONFIG, "farm", 950, skippable=True, village_id="1")
    assert ok is False
    assert h.sent == [] and clock.slept == [], "adiar nao pode bloquear o bot"


def test_fase_que_cabe_roda():
    clock = FakeTime()
    h = _hunter(clock, _schedules(T0 + 1000))
    assert h.gate(CONFIG, "farm", 100, skippable=True, village_id="1") is True
    assert h.sent == []


def test_prep_conta_na_decisao():
    """Previsao + PREP_SECONDS tem que caber, nao so a previsao."""
    clock = FakeTime()
    h = _hunter(clock, _schedules(T0 + 1000))
    tight = 1000 - Hunter.PREP_SECONDS
    assert h.gate(CONFIG, "farm", tight, skippable=True) is False
    assert h.gate(CONFIG, "farm", tight - 1, skippable=True) is True


def test_fase_nao_adiavel_segura_ate_a_saida():
    clock = FakeTime()
    h = _hunter(clock, _schedules(T0 + 1000))
    ok = h.gate(CONFIG, "init", 950, skippable=False, village_id="1")
    assert ok is True
    assert h.sent == [("46676", "57033", T0 + 1000)], h.sent


def test_sem_saida_ou_desligado_nao_interfere():
    clock = FakeTime()
    h = _hunter(clock, {})
    assert h.gate(CONFIG, "farm", 99999) is True
    h = _hunter(clock, _schedules(T0 + 10))
    assert h.gate({"hunter": {"enabled": False}}, "farm", 99999) is True
    h._running = True
    assert h.gate(CONFIG, "farm", 99999) is True, "reentrada nao pode prender"
    assert h.sent == []


def test_gate_publica_proxima_saida_e_hunter_active():
    clock = FakeTime()
    h = _hunter(clock, _schedules(T0 + 5000))
    h.gate(CONFIG, "farm", 10)
    assert h.wrapper.hunter_next_send == T0 + 5000
    seen = []
    h2 = _hunter(clock, _schedules(clock.now + 10))
    h2._send_attack_batch = lambda *_a: seen.append(h2.wrapper.hunter_active) or True
    h2.run(CONFIG)
    assert seen == [True] and h2.wrapper.hunter_active is False


def test_village_gate_nao_adiavel_nunca_pula():
    v = Village.__new__(Village)
    v.village_id = "1"
    v.hunter_gate = lambda phase, vid, skippable: False
    assert v._gate("init", skippable=False) is True
    assert v._gate("farm") is False
    v.hunter_gate = None
    assert v._gate("farm") is True


def _cycles_dir(cycles):
    tmp = tempfile.mkdtemp(prefix="twb-cycles-")
    for i, buckets in enumerate(cycles):
        with open(os.path.join(tmp, "%010d.json" % (1000 + i)), "w", encoding="utf-8") as fh:
            json.dump({"buckets": buckets}, fh)
    return tmp


def test_previsao_maximo_recente_da_mesma_aldeia():
    cycles = [[{"village": "1", "phase": "compartilhamento", "wall": w, "captcha": 0}]
              for w in [9000] + [100] * 10]
    cycles[-1].append({"village": "2", "phase": "compartilhamento", "wall": 50, "captcha": 0})
    cycles[-2][0]["wall"] = 400
    f = PhaseForecast(cache_dir=_cycles_dir(cycles))
    f.reload()
    assert f.predict("compartilhamento", "1") == 400, "so as 10 ultimas amostras contam"
    assert f.predict("compartilhamento", 2) == 50


def test_previsao_desconta_captcha_e_cai_no_p90_ou_default():
    cycles = [[{"village": "1", "phase": "mercado", "wall": 700, "captcha": 600}]]
    cycles += [[{"village": str(v), "phase": "coleta", "wall": float(v), "captcha": 0}]
               for v in range(1, 11)]
    cycles += [[{"village": None, "phase": "conquista_barbara", "wall": 586, "captcha": 0}]]
    f = PhaseForecast(cache_dir=_cycles_dir(cycles))
    f.reload()
    assert f.predict("mercado", "1") == 100
    assert f.predict("coleta", "99") == 10, "aldeia sem historico usa o p90 da fase"
    assert f.predict("conquista_barbara") == 586
    assert f.predict("fase_nova", "1") == PhaseForecast.DEFAULT_SECONDS


def test_fase_com_checkpoint_interno_usa_o_teto_da_iteracao():
    """Farm e defesa chamam o Hunter a cada iteracao: a fase inteira nao conta."""
    cycles = [[{"village": "57689", "phase": "farm", "wall": 1300, "captcha": 0},
               {"village": "52876", "phase": "defesa", "wall": 1831, "captcha": 0},
               {"village": "52876", "phase": "coleta", "wall": 400, "captcha": 0}]]
    f = PhaseForecast(cache_dir=_cycles_dir(cycles))
    f.reload()
    assert f.predict("farm", "57689") == PhaseForecast.INTERRUPTIBLE_CAP["farm"]
    assert f.predict("defesa", "52876") == PhaseForecast.INTERRUPTIBLE_CAP["defesa"]
    assert f.predict("coleta", "52876") == 400, "coleta nao tem checkpoint interno"


def test_detector_de_furo_avisa_uma_vez_por_saida():
    w = WebWrapper("https://example.invalid/")
    records = []

    class _H(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())
    handler = _H()
    w.logger.addHandler(handler)
    try:
        import core.request as request_module
        clock = FakeTime()
        orig = request_module.time
        request_module.time = clock
        try:
            w.hunter_next_send = T0 + 200
            w._check_hunter_silence("GET", "a")
            w._check_hunter_silence("GET", "b")
            w.hunter_active = True
            w.hunter_next_send = T0 + 100
            w._check_hunter_silence("GET", "c")
            w.hunter_active = False
            w.hunter_next_send = T0 + 4000
            w._check_hunter_silence("GET", "d")
        finally:
            request_module.time = orig
    finally:
        w.logger.removeHandler(handler)
    furos = [r for r in records if "FURO" in r]
    assert len(furos) == 1 and "GET a" in furos[0], furos


if __name__ == "__main__":
    original_time = hunter_module.time
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok   %s" % name)
            except Exception as exc:
                failures += 1
                print("FALHA %s: %r" % (name, exc))
            finally:
                hunter_module.time = original_time
    sys.exit(1 if failures else 0)
