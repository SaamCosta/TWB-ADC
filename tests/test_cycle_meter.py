"""
P-CICLO-MEDIDA: o medidor de ciclo (core/cycle_meter.py) e o registro por
requisicao no WebWrapper.

O que se protege aqui:
- tempo de parede EXCLUSIVO: a soma dos baldes fecha o total do ciclo, entao
  os percentuais do resumo somam 100% e nenhuma fase "contem" outra;
- a requisicao cai na fase do TOPO da pilha, e a aldeia e herdada da
  fase-mae (ou explicitamente nao herdada, no caso do Hunter);
- excecao no meio de uma fase nao deixa a pilha suja;
- wrapper sem medidor -- ou um MagicMock, que TEM `.meter` -- vira no-op;
- o WebWrapper conta GET/POST/falha sem ir a rede nem dormir;
- a poda de cache/cycles nunca toca o cache real.

Rodar: python tests/test_cycle_meter.py
"""
import os
import shutil
import sys
import tempfile
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import core.cycle_meter as cm  # noqa: E402
from core.cycle_meter import CycleMeter, meter_phase, by_phase, by_village  # noqa: E402
from core.request import WebWrapper  # noqa: E402

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def tick(self, s):
        self.t += s


def _meter():
    clock = FakeClock()
    return CycleMeter(clock=clock, wall_clock=lambda: 1790000000.0), clock


def test_exclusive_wall_time_closes_the_total():
    m, clock = _meter()
    m.begin_cycle()
    clock.tick(5)                       # sem fase
    with m.phase("aldeia", village="41123"):
        clock.tick(2)                   # aldeia (resto)
        with m.phase("farm"):
            clock.tick(30)
            with m.phase("hunter", village=False):
                clock.tick(4)
            clock.tick(6)
        clock.tick(1)
    clock.tick(3)                       # sem fase
    s = m.end_cycle()
    walls = {(r["village"], r["phase"]): r["wall"] for r in s["buckets"]}
    check(walls.get((None, cm.UNPHASED)) == 8, f"sem fase: {walls}")
    check(walls.get(("41123", "aldeia")) == 3, f"aldeia exclusiva: {walls}")
    check(walls.get(("41123", "farm")) == 36, f"farm herda a aldeia e exclui o hunter: {walls}")
    check(walls.get((None, "hunter")) == 4, f"hunter nao herda aldeia: {walls}")
    check(abs(sum(walls.values()) - s["total_seconds"]) < 1e-6,
          f"soma {sum(walls.values())} != total {s['total_seconds']}")


def test_requests_go_to_top_of_stack():
    m, clock = _meter()
    m.begin_cycle()
    m.record_request("GET", slept=10, net=1)
    with m.phase("farm", village="1"):
        m.record_request("GET", slept=12, net=0.5)
        m.record_request("POST", slept=15, net=0.5, ok=False)
        with m.phase("hunter", village=False):
            m.record_request("POST", slept=0, net=0.2)
    s = m.end_cycle()
    b = {(r["village"], r["phase"]): r for r in s["buckets"]}
    farm = b[("1", "farm")]
    check((farm["requests"], farm["gets"], farm["posts"], farm["failed"]) == (2, 1, 1, 1),
          f"farm: {farm}")
    check(farm["sleep"] == 27, f"sono da farm: {farm['sleep']}")
    check(b[(None, "hunter")]["requests"] == 1, "hunter")
    check(b[(None, cm.UNPHASED)]["requests"] == 1, "requisicao fora de fase nao some")
    check(s["requests"] == 4 and s["sleep_seconds"] == 37, f"totais: {s['requests']} {s['sleep_seconds']}")


def test_outside_requests_are_counted_not_lost():
    m, _ = _meter()
    m.record_request("GET")
    m.record_request("GET")
    check(m.begin_cycle() == 2, "begin_cycle devolve o que foi feito entre ciclos")
    m.end_cycle()
    m.record_request("GET")
    check(m.begin_cycle() == 1, "contador zera a cada ciclo")


def test_exception_does_not_leave_the_stack_dirty():
    m, clock = _meter()
    m.begin_cycle()
    try:
        with m.phase("farm", village="1"):
            with m.phase("interna"):
                clock.tick(3)
                raise ValueError("boom")
    except ValueError:
        pass
    check(m._stack == [(None, cm.UNPHASED)], f"pilha apos excecao: {m._stack}")
    m.record_request("GET")
    s = m.end_cycle()
    b = {(r["village"], r["phase"]): r for r in s["buckets"]}
    check(b[(None, cm.UNPHASED)]["requests"] == 1, "requisicao apos excecao volta para (sem fase)")
    check(b[("1", "interna")]["wall"] == 3, "tempo da fase interrompida foi contado")


def test_begin_cycle_resets_a_dirty_meter():
    m, clock = _meter()
    m.begin_cycle()
    ctx = m.phase("farm", village="1")
    ctx.__enter__()                       # ciclo abortado com fase aberta
    m.begin_cycle()
    check(m._stack == [(None, cm.UNPHASED)] and not m.buckets, "begin_cycle nao limpou")
    ctx.__exit__(None, None, None)        # sair da fase velha nao pode quebrar o novo
    check(m._stack == [(None, cm.UNPHASED)], f"fase velha desempilhou o ciclo novo: {m._stack}")


def test_phase_outside_cycle_is_noop_and_end_without_begin_is_none():
    m, _ = _meter()
    with m.phase("farm"):
        pass
    check(m.end_cycle() is None, "end_cycle sem ciclo aberto")
    check(not m.buckets, "fase fora de ciclo criou balde")


def test_meter_phase_tolerates_wrappers_without_meter():
    for w in (None, object(), mock.MagicMock()):
        try:
            with meter_phase(w, "farm"):
                pass
        except Exception as exc:
            failures.append(f"meter_phase({type(w).__name__}) levantou {exc!r}")


class _Resp:
    def __init__(self, text="<html></html>", status=200):
        self.text = text
        self.status_code = status
        self.url = "https://x/game.php"


def test_webwrapper_records_get_post_and_failures():
    w = WebWrapper("https://x/", endpoint="https://x/")
    w.priority_mode = True                # sem sono: o teste nao dorme
    w.meter.begin_cycle()
    w.web = mock.MagicMock()
    w.web.get.return_value = _Resp()
    w.web.post.return_value = _Resp()
    with w.meter.phase("farm", village="9"):
        w.get_url("game.php?screen=place")
        w.post_url("game.php?screen=place", data={"a": 1})
        w.web.get.side_effect = OSError("rede")
        check(w.get_url("game.php") is None, "GET com excecao devolve None")
    s = w.meter.end_cycle()
    b = {(r["village"], r["phase"]): r for r in s["buckets"]}[("9", "farm")]
    check((b["requests"], b["gets"], b["posts"], b["failed"]) == (3, 2, 1, 1), f"wrapper: {b}")
    check(b["sleep"] == 0, "priority_mode nao dorme")


def test_webwrapper_without_meter_attribute_still_works():
    # Testes antigos montam o wrapper por __new__; o registro nao pode quebrar.
    w = WebWrapper.__new__(WebWrapper)
    w.web = mock.MagicMock()
    w.web.get.return_value = _Resp()
    w.priority_mode = True
    w.endpoint = "https://x/"
    w.headers = {}
    check(w.get_url("game.php") is not None, "get_url sem medidor")


def test_summary_format_and_pruning_use_a_temp_dir():
    m, clock = _meter()
    m.begin_cycle()
    with m.phase("farm", village="1"):
        clock.tick(60)
        m.record_request("GET", slept=50)
    with m.phase("construcao", village="2"):
        clock.tick(40)
    s = m.end_cycle(extra={"next_sleep_seconds": 600})
    head, phases = cm.format_summary(s)
    check("2 aldeia(s)" in head and "1 requisicao" in head, head)
    check(phases.startswith("Ciclo por fase: farm 60% (1 req), construcao 40%"), phases)
    check([p for p, _ in by_phase(s)][:2] == ["farm", "construcao"], "by_phase ordena por tempo")
    check(by_village(s)[0][0] == "1", "by_village ordena por tempo")
    check(s["next_sleep_seconds"] == 600, "extra entra no resumo")

    tmp = tempfile.mkdtemp()
    old_dir, old_keep = cm.CACHE_DIR, cm.KEEP_FILES
    try:
        cm.CACHE_DIR, cm.KEEP_FILES = tmp, 3
        for i in range(5):
            s["started_at"] = 1790000000 + i
            cm.save_summary(s)
        left = sorted(os.listdir(tmp))
        check(left == ["1790000002.json", "1790000003.json", "1790000004.json"],
              f"poda manteve os mais novos: {left}")
    finally:
        cm.CACHE_DIR, cm.KEEP_FILES = old_dir, old_keep
        shutil.rmtree(tmp, ignore_errors=True)


def test_close_and_report_never_raises():
    m, _ = _meter()
    check(cm.close_and_report(m) is None, "sem ciclo aberto devolve None")
    m.begin_cycle()
    with mock.patch.object(cm, "save_summary", side_effect=OSError("disco")):
        check(cm.close_and_report(m) is None, "falha ao gravar nao levanta")


for fn in [
    test_exclusive_wall_time_closes_the_total,
    test_requests_go_to_top_of_stack,
    test_outside_requests_are_counted_not_lost,
    test_exception_does_not_leave_the_stack_dirty,
    test_begin_cycle_resets_a_dirty_meter,
    test_phase_outside_cycle_is_noop_and_end_without_begin_is_none,
    test_meter_phase_tolerates_wrappers_without_meter,
    test_webwrapper_records_get_post_and_failures,
    test_webwrapper_without_meter_attribute_still_works,
    test_summary_format_and_pruning_use_a_temp_dir,
    test_close_and_report_never_raises,
]:
    try:
        fn()
    except Exception as exc:  # um teste que levanta vira falha, nao aborta a suite
        failures.append(f"{fn.__name__} levantou {exc!r}")

if failures:
    print(f"FALHOU ({len(failures)} problema(s)):")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("OK: medidor de ciclo")
