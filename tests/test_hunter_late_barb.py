"""
§8.71 fase 4: nobre ATRASADO de trem barbaro ainda sai -- vira um extra util.
Trem PvP, snipe, fake e apoio continuam recusados, como sempre (§8.58).

Caso real, 19/10/2026: trem de 4 nobres contra a Barbara 81800, chegada comum
21/10 07:11:05. Os 2 da BBM 008 (41114) deviam sair as 15:25:41; o init da
BBM 002 segurou o bot ate 15:32:22 e o Hunter recusou os dois ("send_time
passed 401.8s ago"). Com a regra nova, saem atrasados: os 2 da BBM 012 derrubam
no maximo 70 (2 x 35), entao os da BBM 008 pousam depois sem risco de
autoconquista e ainda tiram 20 a 35 cada.

Sem rede: relogio falso no modulo do Hunter, schedules em memoria, envio
falso. O registro da conquista e o dono do alvo vem de metodos trocados.
"""

import logging
import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import game.hunter as hunter_module  # noqa: E402
from game.hunter import Hunter  # noqa: E402

logging.disable(logging.CRITICAL)

KEY = "81800_2026-10-21T07-11-05_barb"
ARRIVAL = 1792577465.0
SEND_008 = 1792434341.0   # 19/10 15:25:41
SEND_012 = 1792438658.0   # 19/10 16:37:38
NOW = SEND_008 + 401.8    # 15:32:22
CONFIG = {"hunter": {"enabled": True}, "villages": {"41114": {}, "41140": {}}}
NOBLE = {"snob": 1, "axe": 300, "light": 100}


class FakeTime:
    def __init__(self, now):
        self.now = now

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += max(0.0, seconds)


def schedule(label="barb", s008=SEND_008, s012=SEND_012):
    def atk(src, st):
        return {"source_village_id": src, "troops": dict(NOBLE), "is_fake": False,
                "kind": "attack", "send_time": st, "status": "pending"}
    return {"target_id": "81800", "arrival_time": ARRIVAL, "status": "pending", "label": label,
            "attacks": [atk("41114", s008), atk("41114", s008),
                        atk("41140", s012), atk("41140", s012)]}


def record(**over):
    data = {"status": "train_scheduled", "hunter_schedule_key": KEY,
            "loyalty_drop_range": [20, 35]}
    data.update(over)
    return data


def hunter(clock, schedules, rec=None, owners=("0", "0")):
    hunter_module.time = clock
    h = Hunter(wrapper=SimpleNamespace(priority_mode=False))
    h._load_schedules = lambda: schedules
    h._save_schedules = lambda *_a: None
    h._conquest_record = lambda target: record() if rec is None else rec
    h._target_owners = lambda target: list(owners)
    h.sent = []
    village = SimpleNamespace(attack=SimpleNamespace(last_attack_duration=136723.0),
                              units=None, prime_for_conquest=None)
    h.villages = {"41114": village, "41140": village}

    def send(batch, target):
        h.sent.append((batch[0]["source_village_id"], len(batch), clock.now))
        return True
    h._send_attack_batch = send
    return h


def run(sched, rec=None, owners=("0", "0"), now=NOW, config=CONFIG):
    clock = FakeTime(now)
    schedules = {KEY: sched}
    h = hunter(clock, schedules, rec=rec, owners=owners)
    h._run(config)
    return h, sched


def bbm008(sched):
    return [a for a in sched["attacks"] if a["source_village_id"] == "41114"]


# --- 1. O caso real --------------------------------------------------------------

def test_caso_81800_os_dois_da_bbm_008_saem_atrasados_num_lote():
    h, sched = run(schedule())
    assert h.sent == [("41114", 2, NOW)], h.sent
    for atk in bbm008(sched):
        assert atk["status"] == "sent", atk
        assert atk["late_by_seconds"] == 401.8
        assert atk["arrival_real"] == int(NOW + 136723.0), atk
    assert all(a["status"] == "pending" for a in sched["attacks"] if a["source_village_id"] == "41140")
    assert any("atrasado" in n for n in h._notes), h._notes


# --- 2. Quem continua recusado ----------------------------------------------------

def assert_refused(sched, h, fragment):
    assert h.sent == [], h.sent
    for atk in bbm008(sched):
        assert atk["status"] == "failed" and atk["fail_reason"] == "send_time_missed", atk
        assert fragment in atk.get("late_refused_because", ""), atk.get("late_refused_because")


def test_trem_pvp_ou_manual_nunca_sai_atrasado():
    for label in ("pvp", None, "snipe"):
        h, sched = run(schedule(label=label))
        assert_refused(sched, h, "nao e trem barbaro")


def test_registro_que_nao_aponta_para_o_schedule():
    h, sched = run(schedule(), rec=record(hunter_schedule_key="outro"))
    assert_refused(sched, h, "nao aponta")


def test_conquista_que_ja_saiu_de_agendada():
    for status in ("train_sent", "extra_pending", "lost", "blocked", "conquered"):
        h, sched = run(schedule(), rec=record(status=status))
        assert_refused(sched, h, "nao mais agendada")


def test_alvo_que_deixou_de_ser_barbaro_em_qualquer_fonte():
    h, sched = run(schedule(), owners=("0", "848912345"))
    assert_refused(sched, h, "deixou de ser barbaro")
    h, sched = run(schedule(), owners=())
    assert_refused(sched, h, "nao sei")


def test_alvo_que_ja_e_nosso():
    # §8.81: o schedule inteiro e cancelado ANTES do caminho do atrasado --
    # os 4 comandos, nao so os 2 atrasados (tests/test_own_target_guard.py).
    config = dict(CONFIG, villages={"41114": {}, "41140": {}, "81800": {}})
    h, sched = run(schedule(), config=config)
    assert h.sent == [], h.sent
    for atk in sched["attacks"]:
        assert atk["status"] == "failed" and atk["fail_reason"] == "target_is_ours", atk
    ok, why = h.late_barbarian_verdict(config, KEY, schedule(), schedule()["attacks"][0], 401.8)
    assert not ok and "ja e nosso" in why, why


def test_atraso_acima_do_teto():
    now = SEND_008 + Hunter.LATE_BARB_MAX_SECONDS + 1
    # A BBM 012 ainda no futuro: senao ela tambem estaria atrasada (e, com os
    # da 008 recusados, sairia -- o que e correto, mas e outro caso).
    h, sched = run(schedule(s012=now + 3600), now=now)
    assert_refused(sched, h, "teto")


def test_os_outros_conquistariam_sozinhos_entao_o_atrasado_autoconquistaria():
    sched = schedule()
    extra = dict(sched["attacks"][2])
    sched["attacks"].append(extra)  # 3 nobres da BBM 012 a frente: 3 x 35 = 105
    h, _ = run(sched)
    assert_refused(sched, h, "autoconquistaria")


def test_nobre_ja_falho_nao_conta_como_a_frente():
    sched = schedule()
    extra = dict(sched["attacks"][2], status="failed")
    sched["attacks"].append(extra)
    h, _ = run(sched)
    assert h.sent == [("41114", 2, NOW)], "failed nao pousa: %s" % h.sent


def test_sem_nobre_fake_ou_apoio_continuam_recusados():
    for change in ({"troops": {"axe": 300}}, {"is_fake": True}, {"kind": "support"}):
        sched = schedule()
        for atk in bbm008(sched):
            atk.update(change)
        h, _ = run(sched)
        assert h.sent == [], (change, h.sent)
        assert all(a["status"] == "failed" for a in bbm008(sched)), change


if __name__ == "__main__":
    original = hunter_module.time
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
                hunter_module.time = original
    sys.exit(1 if failures else 0)
