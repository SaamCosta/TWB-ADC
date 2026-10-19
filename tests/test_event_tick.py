"""
§8.71 fase 2: tick de eventos. O acompanhamento da conquista barbara e a
promocao do trem rodam no checkpoint em que o fato acontece (pouso do nobre,
Hunter acabou de mandar), nao no inicio do proximo ciclo.

Caso que motivou: o trem contra a Barbara 81800 pousa em 21/10 07:11:05 com 2
de 4 nobres. Antes, o relatorio era lido no init de alguma aldeia, mas a
decisao do extra so saia no inicio do ciclo seguinte -- ate ~4 h depois, com
a lealdade regenerando 1/h.

Sem rede e sem disco: `ConquestCache` e `FileManager` do modulo trocados por
dublês, relogio passado por argumento.
"""

import logging
import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import game.event_tick as event_module  # noqa: E402
from game.event_tick import EventTick  # noqa: E402

logging.disable(logging.CRITICAL)

LANDING = 1792577465  # 21/10 07:11:05
SCHED = "81800_2026-10-21T07-11-05_barb"


def conquest(status="extra_pending", arrivals=(LANDING, LANDING), **extra):
    data = {"status": status, "reserved_by": "41140", "noble_arrivals": list(arrivals),
            "hunter_schedule_key": SCHED}
    data.update(extra)
    return data


class Fakes:
    def __init__(self, conquests, schedules=None, managed=None):
        self.conquests = conquests
        self.schedules = schedules or {}
        self.managed = managed or {}

    def __enter__(self):
        self.saved = (event_module.ConquestCache, event_module.FileManager)
        fakes = self
        event_module.ConquestCache = SimpleNamespace(
            active_conquests=lambda: dict(fakes.conquests))

        def load(path):
            if path.endswith("schedules.json"):
                return fakes.schedules
            vid = os.path.basename(path).replace(".json", "")
            return fakes.managed.get(vid)
        event_module.FileManager = SimpleNamespace(load_json_file=load)
        return self

    def __exit__(self, *exc):
        event_module.ConquestCache, event_module.FileManager = self.saved
        return False


class Reports:
    """ReportManager de mentira: `read()` conta e, se mandado, 'chega' o relatorio."""

    def __init__(self, arrive=None):
        self.last_reports = {}
        self.last_list_read = None
        self.reads = 0
        self.arrive = arrive

    def read(self, full_run=False):
        self.reads += 1
        self.last_list_read = LANDING + 10_000
        if self.arrive:
            self.last_reports.update(self.arrive)


def noble_report(loyalty, when=LANDING + 1, dest="81800"):
    return {"r1": {"type": "attack", "dest": dest,
                   "extra": {"when": when, "loyalty_after": loyalty,
                             "units_sent": {"snob": 1, "axe": 100}}}}


class Anchor:
    def __init__(self, units=True, config=True):
        self.runs = 0
        self.units = SimpleNamespace(troops={"snob": "0"}) if units else None
        self.area = object() if units else None
        self.config = {"conquest": {"enabled": True}} if config else None

    def run_conquest(self):
        self.runs += 1


CONFIG = {"conquest": {"enabled": True}}


# --- 1. O que esta pendente --------------------------------------------------------

def test_pouso_vencido_e_devido_e_futuro_nao():
    t = EventTick()
    conquests = {"81800": conquest(), "1": conquest(arrivals=(LANDING + 3600,)),
                 "2": conquest(arrivals=(LANDING, None)), "3": conquest(status="train_scheduled")}
    due = t.due_landings(LANDING + EventTick.LANDING_MARGIN, conquests)
    assert [d[0] for d in due] == ["81800"], due
    assert t.due_landings(LANDING + 5, conquests) == [], "antes da margem, nao"
    assert t.next_landing(LANDING + 60, conquests) == LANDING + 3600 + EventTick.LANDING_MARGIN


def test_promocao_so_quando_o_hunter_encerrou():
    conquests = {"81800": conquest(status="train_scheduled")}
    pending = {SCHED: {"status": "pending", "arrival_time": LANDING,
                       "attacks": [{"status": "sent"}, {"status": "pending"}]}}
    done = {SCHED: {"status": "failed", "arrival_time": LANDING,
                    "attacks": [{"status": "sent"}, {"status": "failed"}]}}
    assert EventTick.promotions_due(conquests, pending) == []
    assert EventTick.promotions_due(conquests, done) == ["81800"]


# --- 2. O tick ------------------------------------------------------------------------

def test_pouso_com_relatorio_acompanha_uma_vez():
    anchor = Anchor()
    reports = Reports(arrive=noble_report(45))
    t = EventTick()
    with Fakes({"81800": conquest()}):
        now = LANDING + 60
        assert t.tick(CONFIG, {"41140": anchor}, reports, now=now) is True
        assert anchor.runs == 1 and reports.reads == 1
        assert t.tick(CONFIG, {"41140": anchor}, reports, now=now + 60) is False
        assert anchor.runs == 1, "o mesmo pouso nao e acompanhado duas vezes"


def test_sem_relatorio_insiste_e_depois_desiste():
    anchor = Anchor()
    reports = Reports()
    t = EventTick()
    with Fakes({"81800": conquest()}):
        t.tick(CONFIG, {"41140": anchor}, reports, now=LANDING + 60)
        t.tick(CONFIG, {"41140": anchor}, reports, now=LANDING + 600)
        assert anchor.runs == 0, "sem relatorio do pouso nao age por estimativa"
        assert t.due_landings(LANDING + 600, {"81800": conquest()}), "segue devido"
        t.tick(CONFIG, {"41140": anchor}, reports, now=LANDING + EventTick.REPORT_WAIT + 61)
        assert anchor.runs == 0
        assert not t.due_landings(LANDING + EventTick.REPORT_WAIT + 120, {"81800": conquest()}), \
            "passado o prazo, fica para o inicio do ciclo"


def test_relatorio_velho_de_outro_pouso_nao_vale():
    anchor = Anchor()
    reports = Reports(arrive=noble_report(45, when=LANDING - 3 * 3600))
    t = EventTick()
    with Fakes({"81800": conquest()}):
        t.tick(CONFIG, {"41140": anchor}, reports, now=LANDING + 60)
    assert anchor.runs == 0


def test_empate_no_mesmo_segundo_fica_a_menor_lealdade():
    t = EventTick()
    reports = Reports()
    reports.last_reports = {**noble_report(79), "r2": noble_report(45)["r1"]}
    assert t.landing_report(reports, "81800", LANDING) == (45.0, LANDING + 1)


def test_gate_fechado_nao_comeca():
    anchor = Anchor()
    reports = Reports(arrive=noble_report(45))
    t = EventTick()
    with Fakes({"81800": conquest()}):
        t.tick(CONFIG, {"41140": anchor}, reports, gate=lambda phase: False, now=LANDING + 60)
    assert anchor.runs == 0 and reports.reads == 0


def test_extra_a_caminho_prima_quem_pode_ter_nobre_e_nao_leu():
    anchor = Anchor()
    holder = Anchor(units=False)
    empty = Anchor(units=False)
    reports = Reports(arrive=noble_report(45))
    primed = []
    t = EventTick()
    with Fakes({"81800": conquest()}, managed={"41114": {"troops": {"snob": 2}}}):
        t.tick(CONFIG, {"41140": anchor, "41114": holder, "39975": empty}, reports,
               prime=primed.extend, now=LANDING + 60)
    assert primed == ["41114"], "so quem tem nobre e nao tem leitura: %s" % primed
    assert anchor.runs == 1


def test_conquistada_nao_prima_ninguem():
    anchor = Anchor()
    reports = Reports(arrive=noble_report(-7))
    primed = []
    t = EventTick()
    with Fakes({"81800": conquest()}, managed={"41114": {"troops": {"snob": 2}}}):
        t.tick(CONFIG, {"41140": anchor, "41114": Anchor(units=False)}, reports,
               prime=primed.extend, now=LANDING + 60)
    assert primed == [] and anchor.runs == 1, "o acompanhamento marca conquistada e avisa"


def fake_planner(calls):
    return SimpleNamespace(
        _promote_scheduled_trains=lambda: calls.append("promote"),
        promote_reinforcements=lambda: calls.append("promote_reforco"),
        _sync_reinforcement_reserves=lambda: calls.append("sync"),
        plan_reinforcements=lambda now=None: calls.append("plan") or [])


def test_promocao_chama_o_planejador():
    calls = []
    done = {SCHED: {"status": "failed", "arrival_time": LANDING,
                    "attacks": [{"status": "sent"}, {"status": "failed"}]}}
    t = EventTick()
    with Fakes({"81800": conquest(status="train_scheduled")}, schedules=done):
        t.tick(CONFIG, {}, None, planner_factory=lambda: fake_planner(calls), now=LANDING - 3600)
    assert calls == ["promote", "promote_reforco", "sync"], calls


def test_trem_incompleto_no_ar_avalia_reforco_a_cada_30_min():
    calls = []
    incomplete = conquest(hits_done=2, hits_needed=4, loyalty_drop_range=[20, 35])
    t = EventTick()
    now = LANDING - 36 * 3600
    with Fakes({"81800": incomplete}):
        t.tick(CONFIG, {}, None, planner_factory=lambda: fake_planner(calls), now=now)
        t.tick(CONFIG, {}, None, planner_factory=lambda: fake_planner(calls), now=now + 600)
        assert calls == ["plan"], "uma tentativa a cada 30 min, nao a cada checkpoint: %s" % calls
        t.tick(CONFIG, {}, None, planner_factory=lambda: fake_planner(calls),
               now=now + EventTick.REINFORCE_RETRY + 1)
    assert calls == ["plan", "plan"], calls


def test_escolta_que_volta_para_casa_reavalia_antes_dos_30_min():
    """
    A escolta da BBM 008 estava fora (coleta, apoio voltando da BBM 055) e
    volta na vez dela no laco. A releitura da praca muda a tropa em casa, e o
    tick reavalia na hora, antes de a coleta sair de novo.
    """
    calls = []
    incomplete = conquest(hits_done=2, hits_needed=4, loyalty_drop_range=[20, 35])
    bbm008 = SimpleNamespace(units=SimpleNamespace(troops={"snob": "2", "light": "1"}),
                             area=object())
    villages = {"41114": bbm008}
    t = EventTick()
    now = LANDING - 36 * 3600
    with Fakes({"81800": incomplete}):
        t.tick(CONFIG, villages, None, planner_factory=lambda: fake_planner(calls), now=now)
        t.tick(CONFIG, villages, None, planner_factory=lambda: fake_planner(calls), now=now + 60)
        assert calls == ["plan"], "nada mudou: espera os 30 min (%s)" % calls
        bbm008.units.troops = {"snob": "2", "spear": "900", "sword": "900", "heavy": "200"}
        t.tick(CONFIG, villages, None, planner_factory=lambda: fake_planner(calls), now=now + 120)
    assert calls == ["plan", "plan"], "a escolta voltou: reavalia ja (%s)" % calls


def test_trem_completo_ou_que_conquista_sozinho_nao_pede_reforco():
    calls = []
    t = EventTick()
    now = LANDING - 36 * 3600
    for data in (conquest(hits_done=4, hits_needed=4),
                 conquest(arrivals=(LANDING,) * 3, hits_done=3, hits_needed=4,
                          loyalty_drop_range=[20, 35])):
        with Fakes({"81800": data}):
            t.tick(CONFIG, {}, None, planner_factory=lambda: fake_planner(calls), now=now)
    assert calls == [], calls


def test_conquista_desligada_ou_reentrada_nao_faz_nada():
    anchor = Anchor()
    reports = Reports(arrive=noble_report(45))
    t = EventTick()
    with Fakes({"81800": conquest()}):
        assert t.tick({"conquest": {"enabled": False}}, {"41140": anchor}, reports,
                      now=LANDING + 60) is False
        t._busy = True
        assert t.tick(CONFIG, {"41140": anchor}, reports, now=LANDING + 60) is False
    assert anchor.runs == 0


def test_tick_parado_ate_a_conquista_do_inicio_do_ciclo():
    """
    19/10 19:08: o tick primou 12 aldeias num checkpoint do inicio do ciclo e o
    prime da conquista releu as mesmas logo depois (11 req/min). Ate o bloco da
    conquista rodar, o tick nao faz nada.
    """
    from twb import TWB

    bot = TWB()
    calls = []
    bot.event_tick.tick = lambda *a, **k: calls.append(1)
    bot.wrapper = SimpleNamespace(meter=None)
    events = bot._event_tick_callback(CONFIG, {"41140": Anchor()}, None, None, None)
    bot._events_armed = False
    events()
    assert calls == [], "antes da conquista do inicio do ciclo, nada"
    bot._events_armed = True
    events()
    assert calls == [1]


# --- 3. O sono acorda no pouso --------------------------------------------------------

def test_sono_acorda_no_pouso_e_roda_o_tick():
    import twb as twb_module
    from twb import TWB

    clock = SimpleNamespace(now=LANDING - 1000.0)
    sleeps, ticks = [], []

    def sleep(seconds):
        sleeps.append(round(seconds))
        clock.now += seconds

    saved = twb_module.time
    twb_module.time = SimpleNamespace(time=lambda: clock.now, sleep=sleep)
    try:
        bot = TWB()
        bot.own_defense = None
        bot.event_tick.next_landing = (
            lambda now: LANDING + 30 if now < LANDING + 30 else None)
        bot._defended_sleep(3000, {"own_defense": {"enabled": False}},
                            events=lambda: ticks.append(clock.now))
    finally:
        twb_module.time = saved
    assert sleeps[0] == 1030, "a primeira fatia termina no pouso + margem: %s" % sleeps
    assert ticks and ticks[0] == LANDING + 30, ticks
    assert sum(sleeps) >= 2970, "o sono total nao encurta: %s" % sleeps


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok   %s" % name)
            except Exception as exc:
                failures += 1
                print("FALHA %s: %r" % (name, exc))
    sys.exit(1 if failures else 0)
