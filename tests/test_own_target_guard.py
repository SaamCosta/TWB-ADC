"""
§8.81: nenhum ataque sai contra aldeia que ja e nossa (`core/own_villages.py`).

Caso real, 29-30/10/2026: a Barbara 88755 virou nossa (BBM 067) as 00:37:51
de 29/10. As 01:40:48 o planejador agendou contra ela o trem
`88755_2026-10-30T11-47-26_barb` -- `cache/villages/88755.json` era de 23/10 e
dizia `owner '0'`. O Hunter mandou o nobre da BBM 013 (44620) as 01:50:48 sem
reconferir o dono; ele pousou as 11:47:26 de 30/10 contra a nossa guarnicao e
morreu com os 2.264 da escolta (relatorio 227831832). Os outros tres (BBM 012
x2 as 03:50:05, BBM 029 as 04:37:58) o jogo recusou.

Cobre:
- o registro (fonte, lista vazia, `stale` pelo `player.villages`);
- o envio no horario do Hunter: cancela o schedule inteiro, com aviso, e nao
  manda nada -- pelo config, pela visao geral da defesa, e quando a aldeia
  vira nossa DURANTE a espera ate o segundo exato (6o padrao);
- o controle: sem lista nenhuma dizendo "nossa", o mesmo trem sai (15o
  padrao: guarda que dispara sempre nao detecta);
- apoio para aldeia nossa continua saindo;
- a releitura da visao geral quando o jogo diz que ha mais aldeias, com a
  fixture verbatim `own_defense_overview_villages_br143.html`, o teto de uma
  por `OWN_REFRESH_SECONDS` e o veto colado numa saida;
- a selecao automatica e a fila manual pulam aldeia nossa que o mapa da como
  barbara;
- a promocao do trem cancelado ("ja era nosso", nao "FALHOU" nem
  "train_sent") e a vaga de trem que o nobre no ar deixa de ocupar.

Sem rede, sem relogio de parede e sem tocar cache real: relogio falso nos
modulos, FileManager trocado por dicionario.

Rodar: python tests/test_own_target_guard.py
"""

import copy
import logging
import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import game.attack as attack_mod  # noqa: E402
import game.conquest_planner as planner_mod  # noqa: E402
import game.hunter as hunter_module  # noqa: E402
from core import own_villages  # noqa: E402
from core.own_villages import OwnVillages, own_target_reason  # noqa: E402
from game.attack import ConquestCache, ConquestManager  # noqa: E402
from game.conquest_planner import BarbarianTrainPlanner  # noqa: E402
from game.hunter import Hunter  # noqa: E402

logging.disable(logging.CRITICAL)

TARGET = "88755"
KEY = "88755_2026-10-30T11-47-26_barb"
CONQUERED_AT = 1793245071.0   # 29/10 00:37:51, a BBM 027 conquista a 88755
PLANNED_AT = 1793248848.0     # 29/10 01:40:48, o trem e agendado
SEND_013 = 1793249448.0       # 29/10 01:50:48, BBM 013 (44620)
SEND_012 = 1793256605.0       # 29/10 03:50:05, BBM 012 (41140) x2
SEND_029 = 1793259478.0       # 29/10 04:37:58, BBM 029 (49709)
ARRIVAL = 1793371646.0        # 30/10 11:47:26
OURS_BEFORE = {"41140": {}, "44620": {}, "49709": {}, "46676": {}}
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "own_defense_overview_villages_br143.html")


class FakeTime:
    def __init__(self, now, on_sleep=None):
        self.now = now
        self.on_sleep = on_sleep

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += max(0.0, seconds)
        if self.on_sleep:
            self.on_sleep()


def train():
    """O schedule real, como estava no `cache/hunter/schedules.json`."""
    def atk(src, troops, send):
        return {"source_village_id": src, "troops": troops, "is_fake": False,
                "send_time": send, "status": "pending"}
    small = {"spear": 314, "sword": 366, "light": 18, "heavy": 54, "snob": 1}
    return {"target_id": TARGET, "label": "barb", "arrival_time": ARRIVAL,
            "arrival_str": "2026-10-30 11:47:26", "status": "pending", "attacks": [
                atk("49709", {"spear": 492, "sword": 540, "light": 36, "heavy": 136, "snob": 1},
                    SEND_029),
                atk("41140", dict(small), SEND_012),
                atk("41140", dict(small), SEND_012),
                atk("44620", {"spear": 1008, "sword": 1016, "light": 48, "heavy": 192,
                              "snob": 1}, SEND_013)]}


def hunter(clock, schedules, registry, pulse=None, page=None):
    hunter_module.time = clock
    gets = []

    def get_url(url):
        gets.append(url)
        return page
    wrapper = SimpleNamespace(priority_mode=False, get_url=get_url,
                              account_pulse=SimpleNamespace(last=pulse))
    h = Hunter(wrapper=wrapper)
    h.own_registry = registry
    h._load_schedules = lambda: schedules
    h._save_schedules = lambda *_a: None
    h.sent = []
    h.gets = gets
    village = SimpleNamespace(attack=SimpleNamespace(last_arrival_estimate=None),
                              units=None, prime_for_conquest=None)
    h.villages = {vid: village for vid in OURS_BEFORE}

    def send(batch, target, send_time=None):
        h.sent.append((batch[0]["source_village_id"], len(batch), clock.now))
        return True
    h._send_attack_batch = send
    h._send_support = lambda atk, sched, schedules: h.sent.append(("apoio", 1, clock.now)) or True
    return h


def config(*extra):
    villages = dict(OURS_BEFORE)
    for vid in extra:
        villages[vid] = {}
    return {"hunter": {"enabled": True}, "conquest": {"enabled": True}, "villages": villages}


failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


# --- 1. O registro -------------------------------------------------------------

def test_registro_fontes_e_lista_vazia():
    reg = OwnVillages(clock=lambda: 100.0)
    check(own_target_reason(TARGET, config(), reg) is None, "sem lista nenhuma nao e nosso")
    check(own_target_reason(TARGET, config(TARGET), reg) == "o alvo ja e nosso (config.json)",
          own_target_reason(TARGET, config(TARGET), reg))
    check(reg.note(own_villages.SOURCE_DEFENSE, []) is False, "lista vazia nao entra")
    check(reg.newest() is None, "lista vazia nao pode virar 'nenhuma aldeia'")
    reg.note(own_villages.SOURCE_DEFENSE, [88755, "44620"], at=50.0)
    check(reg.owner_source(TARGET) == own_villages.SOURCE_DEFENSE, "id int vira str")
    # O farm (`AttackManager.own_villages`) recebe a uniao: config + listas.
    check(reg.ids(config()) == set(OURS_BEFORE) | {TARGET}, reg.ids(config()))
    # Leitura nova da mesma fonte SUBSTITUI: aldeia perdida sai.
    reg.note(own_villages.SOURCE_DEFENSE, ["44620"], at=60.0)
    check(reg.owner_source(TARGET) is None, "lista nova substitui a anterior")


def test_stale_pelo_player_villages():
    reg = OwnVillages(clock=lambda: 100.0)
    cfg = config()
    check(reg.stale(5, cfg) is True, "jogo diz 5, config conhece 4")
    check(reg.stale(4, cfg) is False, "igual nao e velho")
    check(reg.stale(None, cfg) is False and reg.stale("x", cfg) is False,
          "ilegivel nao manda ninguem a rede")
    reg.note(own_villages.SOURCE_CYCLE, list(OURS_BEFORE) + [TARGET], at=10.0)
    check(reg.stale(5, cfg) is False, "a lista mais nova (5) vence o config (4)")


# --- 2. O envio no horario do Hunter ----------------------------------------------

def test_caso_88755_config_ja_sabia_nada_sai_e_o_schedule_e_cancelado():
    # As 01:50 o config ja tinha a 88755: a visao geral do ciclo das ~00:55
    # rodou depois da conquista e `add_new_villages` e true.
    clock = FakeTime(SEND_013 - 30)
    sched = train()
    h = hunter(clock, {KEY: sched}, OwnVillages(clock=clock.time))
    h._run(config(TARGET))
    check(h.sent == [], "nenhum comando sai contra aldeia nossa: %s" % h.sent)
    check(all(a["status"] == "failed" and a["fail_reason"] == "target_is_ours"
              for a in sched["attacks"]), sched["attacks"])
    check(sched["status"] == "failed", sched["status"])
    check("config.json" in sched.get("cancel_reason", ""), sched.get("cancel_reason"))
    check(len(h._notes) == 1 and "88755" in h._notes[0] and "4 nobre(s)" in h._notes[0]
          and "ja e nosso" in h._notes[0], h._notes)


def test_cancela_logo_que_sabe_sem_esperar_a_hora_da_saida():
    # 01:41, um minuto depois de agendar: a primeira saida e daqui a 9 min,
    # fora da janela. O cancelamento nao espera a hora -- solta a reserva de
    # tropa e o nobre dos tres que sairiam horas depois.
    clock = FakeTime(PLANNED_AT + 60)
    sched = train()
    h = hunter(clock, {KEY: sched}, OwnVillages(clock=clock.time))
    h._run(config(TARGET))
    check(clock.now == PLANNED_AT + 60, "nao dormiu ate a saida: %s" % (clock.now - PLANNED_AT))
    check(all(a["fail_reason"] == "target_is_ours" for a in sched["attacks"]), sched["attacks"])


def test_controle_sem_lista_dizendo_nossa_o_trem_sai():
    # 15o padrao: a mesma situacao com o alvo fora das listas manda o nobre.
    clock = FakeTime(SEND_013 - 30)
    sched = train()
    h = hunter(clock, {KEY: sched}, OwnVillages(clock=clock.time))
    h._run(config())
    # O envio falso nao espera o POST: o instante e o do pre-armamento.
    check(h.sent == [("44620", 1, SEND_013 - Hunter.PREARM_SECONDS)], h.sent)
    check(sched["attacks"][3]["status"] == "sent", sched["attacks"][3])
    check(all(a["status"] == "pending" for a in sched["attacks"][:3]), "os outros esperam a hora")


def test_lista_da_defesa_propria_cobre_a_aldeia_fora_do_config():
    clock = FakeTime(SEND_013 - 30)
    reg = OwnVillages(clock=clock.time)
    reg.note(own_villages.SOURCE_DEFENSE, list(OURS_BEFORE) + [TARGET], at=CONQUERED_AT + 600)
    sched = train()
    h = hunter(clock, {KEY: sched}, reg)
    h._run(config())
    check(h.sent == [], h.sent)
    check("visao geral da defesa" in sched.get("cancel_reason", ""), sched.get("cancel_reason"))


def test_vira_nossa_durante_a_espera_reconfere_no_segundo_exato():
    # 6o padrao: decidido as 01:45:48, a aldeia entra na lista no meio da
    # espera (o checkpoint da defesa le a visao geral). Nada sai.
    reg = OwnVillages()
    clock = FakeTime(SEND_013 - 200, on_sleep=lambda: reg.note(
        own_villages.SOURCE_DEFENSE, list(OURS_BEFORE) + [TARGET], at=clock.now))
    reg.clock = clock.time
    sched = train()
    h = hunter(clock, {KEY: sched}, reg)
    h._run(config())
    check(h.sent == [], "decidiu antes da espera e mandou depois: %s" % h.sent)
    check(sched["attacks"][3]["fail_reason"] == "target_is_ours", sched["attacks"][3])


def test_nobre_ja_no_ar_nao_se_mexe_e_o_aviso_diz():
    clock = FakeTime(SEND_012 - 30)
    sched = train()
    sched["attacks"][3].update(status="sent", sent_at=SEND_013 + 1, arrival_real=ARRIVAL + 0.412)
    h = hunter(clock, {KEY: sched}, OwnVillages(clock=clock.time))
    h._run(config(TARGET))
    check(sched["attacks"][3]["status"] == "sent", "o que saiu continua 'sent'")
    check([a["status"] for a in sched["attacks"][:3]] == ["failed"] * 3, sched["attacks"])
    check("1 ja no ar nao voltam" in h._notes[0] and "3 nobre(s)" in h._notes[0], h._notes)


def test_apoio_para_aldeia_nossa_continua_saindo():
    clock = FakeTime(SEND_013 - 30)
    sched = {"target_id": TARGET, "arrival_time": ARRIVAL, "status": "pending", "attacks": [
        {"source_village_id": "44620", "troops": {"spear": 100}, "kind": "support",
         "send_time": SEND_013, "status": "pending"}]}
    h = hunter(clock, {"apoio": sched}, OwnVillages(clock=clock.time))
    h._run(config(TARGET))
    check(h.sent == [("apoio", 1, SEND_013)], h.sent)


def test_atrasado_diz_o_mesmo_motivo():
    reg = OwnVillages(clock=lambda: SEND_013)
    reg.note(own_villages.SOURCE_CYCLE, [TARGET])
    hunter_module.time = FakeTime(SEND_013 + 60)
    h = Hunter(wrapper=None)
    h.own_registry = reg
    h._conquest_record = lambda t: {"status": "train_scheduled", "hunter_schedule_key": KEY}
    sched = train()
    ok, why = h.late_barbarian_verdict(config(), KEY, sched, sched["attacks"][3], 60)
    check(not ok and why == "o alvo ja e nosso (visao geral do ciclo)", why)


# --- 3. Releitura da visao geral pelo player.villages ------------------------------

def _fixture():
    with open(FIXTURE, encoding="utf-8") as fh:
        return fh.read()


def _fixture_case(now, pulse_villages=2):
    # A fixture tem 2 aldeias (40808 e 71768). O ciclo so conhece a 40808; o
    # jogo diz que a conta tem 2 -- a 71768 e a recem-conquistada.
    reg = OwnVillages(clock=lambda: now)
    reg.note(own_villages.SOURCE_CYCLE, ["40808"], at=now - 3600)
    clock = FakeTime(now)
    sched = train()
    sched["target_id"] = "71768"
    h = hunter(clock, {KEY: sched}, reg, pulse={"villages": pulse_villages}, page=_fixture())
    return h, sched, reg, {"hunter": {"enabled": True}, "villages": {"40808": {}}}


def test_jogo_diz_mais_aldeias_hunter_rele_e_cancela():
    h, sched, reg, cfg = _fixture_case(SEND_013 - 120)
    h._run(cfg)
    check(len(h.gets) == 1 and "overview_villages" in h.gets[0], h.gets)
    check(reg.owner_source("71768") == own_villages.SOURCE_HUNTER, reg.newest())
    check(h.sent == [] and sched["attacks"][3]["fail_reason"] == "target_is_ours",
          (h.sent, sched["attacks"][3]))


def test_releitura_tem_teto_e_nao_cola_na_saida():
    h, sched, reg, cfg = _fixture_case(SEND_013 - 120, pulse_villages=3)
    h._run(cfg)
    h._run(cfg)
    check(len(h.gets) == 1, "lista curta (2 de 3) nao vira 1 GET por checkpoint: %s" % h.gets)
    h, sched, reg, cfg = _fixture_case(SEND_013 - 5)
    h._refresh_own_villages(cfg, {KEY: sched}, now=SEND_013 - 5)
    check(h.gets == [], "a 5 s da saida nao se faz GET: %s" % h.gets)
    h, sched, reg, cfg = _fixture_case(SEND_013 - 120, pulse_villages=1)
    h._run(cfg)
    check(h.gets == [], "lista em dia nao vai a rede: %s" % h.gets)


# --- 4. Selecao de alvo: automatica e manual ----------------------------------------

class _Map:
    my_location = (600, 255)
    villages = {}

    @staticmethod
    def get_dist(location):
        return ((location[0] - 600) ** 2 + (location[1] - 255) ** 2) ** 0.5


def _manager(cfg):
    cm = ConquestManager.__new__(ConquestManager)
    cm.config = cfg
    cm.village_id = "41140"
    cm.logger = logging.getLogger("test")
    cm.map = _Map()
    cm.reservation_board = None
    cm.world_villages = None
    cm._effective_radius = lambda c: 30
    cm._get_managed_locations = lambda: []
    cm._get_manual_target = lambda: None
    cm._claim_block_reason = lambda vid, location=None: None
    # O pool como o planejador viu as 01:40: o cache de 23/10 dizendo barbara.
    pool = {TARGET: {"owner": "0", "points": 1032, "location": [605, 253]},
            "88800": {"owner": "0", "points": 900, "location": [610, 260]}}
    cm._candidate_pool = lambda reach_from, max_radius=None: copy.deepcopy(pool)
    return cm


def test_selecao_automatica_pula_aldeia_nossa_que_o_mapa_da_como_barbara():
    saved = (ConquestCache.all_reserved, ConquestCache.targets_with_nobles_in_flight)
    ConquestCache.all_reserved = staticmethod(lambda: set())
    ConquestCache.targets_with_nobles_in_flight = staticmethod(lambda now=None: set())
    old = own_villages.REGISTRY
    own_villages.REGISTRY = OwnVillages()
    try:
        cfg = {"conquest": {"enabled": True}, "villages": dict(OURS_BEFORE)}
        cfg_ours = dict(cfg, villages=dict(OURS_BEFORE, **{TARGET: {}}))
        got = _manager(cfg).find_target({}, reach_from=[(600, 255)])
        check(got == TARGET, "controle: sem lista dizendo nossa, a 88755 ganha: %s" % got)
        got = _manager(cfg_ours).find_target({}, reach_from=[(600, 255)])
        check(got == "88800", "com a 88755 no config: %s" % got)
        own_villages.REGISTRY.note(own_villages.SOURCE_DEFENSE, [TARGET])
        got = _manager(cfg).find_target({}, reach_from=[(600, 255)])
        check(got == "88800", "pela lista da defesa: %s" % got)
    finally:
        ConquestCache.all_reserved, ConquestCache.targets_with_nobles_in_flight = saved
        own_villages.REGISTRY = old


class _FM:
    """FileManager em memoria: {caminho: dado}."""
    def __init__(self, files):
        self.files = files

    def load_json_file(self, path, **kwargs):
        return copy.deepcopy(self.files.get(path))

    def save_json_file(self, data, path, **kwargs):
        self.files[path] = copy.deepcopy(data)

    def list_directory(self, path, ends_with=None):
        prefix = path.rstrip("/") + "/"
        return [p[len(prefix):] for p in self.files
                if p.startswith(prefix) and "/" not in p[len(prefix):]
                and (not ends_with or p.endswith(ends_with))]


def test_fila_manual_tira_alvo_nosso_sem_enviar():
    files = {"cache/conquest/%s.json" % TARGET: {"status": "manual", "queued_at": 1},
             "cache/villages/%s.json" % TARGET: {"owner": "0", "location": [605, 253]}}
    saved = attack_mod.FileManager
    attack_mod.FileManager = _FM(files)
    try:
        cm = _manager({"villages": dict(OURS_BEFORE, **{TARGET: {}})})
        del cm._get_manual_target  # o de verdade
        check(cm._get_manual_target() is None, "alvo nosso nao sai da fila")
        rec = files["cache/conquest/%s.json" % TARGET]
        check(rec["status"] == "invalid" and "ja e nosso" in rec["invalid_reason"], rec)
    finally:
        attack_mod.FileManager = saved


# --- 5. Depois do cancelamento -----------------------------------------------------

def test_promocao_do_trem_cancelado_e_a_vaga_de_trem():
    sched = train()
    for atk in sched["attacks"][:3]:
        atk.update(status="failed", fail_reason="target_is_ours",
                   cancelled_because="o alvo ja e nosso (config.json)")
    sched["attacks"][3].update(status="sent", arrival_real=ARRIVAL + 0.412)
    sched["status"] = "failed"
    files = {Hunter.SCHEDULE_CACHE: {KEY: sched},
             "cache/conquest/%s.json" % TARGET: {
                 "status": "train_scheduled", "reserved_by": "41140",
                 "hunter_schedule_key": KEY, "scheduled_at": PLANNED_AT,
                 "scheduled_arrival": ARRIVAL, "hits_needed": 4}}
    fm = _FM(files)
    saved = (attack_mod.FileManager, planner_mod.FileManager, attack_mod.time, planner_mod.Notification)
    attack_mod.FileManager = planner_mod.FileManager = fm
    sent_notes = []
    planner_mod.Notification = SimpleNamespace(send=sent_notes.append)
    try:
        planner = BarbarianTrainPlanner(wrapper=None, villages={}, config=config(TARGET))
        planner._promote_scheduled_trains()
        rec = files["cache/conquest/%s.json" % TARGET]
        check(rec["status"] == "invalid" and rec["already_ours"] is True, rec)
        check(rec["hits_done"] == 1 and rec["noble_arrivals"] == [ARRIVAL + 0.412], rec)
        check("cancelou 3" in rec["invalid_reason"], rec["invalid_reason"])
        check(sent_notes == [], "o Hunter ja avisou; nada de 'Conquista FALHOU': %s" % sent_notes)
        # Antes do pouso o nobre segue no ar, mas nao ocupa vaga de trem.
        attack_mod.time = FakeTime(SEND_029 + 3600)
        check(TARGET not in ConquestCache.active_conquests(), "ja era nosso nao ocupa vaga")
        rec2 = dict(rec)
        rec2.pop("already_ours")
        files["cache/conquest/%s.json" % TARGET] = rec2
        check(TARGET in ConquestCache.active_conquests(),
              "controle: sem a marca, nobre no ar continua ocupando (12/08)")
    finally:
        (attack_mod.FileManager, planner_mod.FileManager, attack_mod.time,
         planner_mod.Notification) = saved


if __name__ == "__main__":
    original = hunter_module.time
    count = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            before = len(failures)
            try:
                fn()
            except Exception as exc:
                import traceback
                traceback.print_exc()
                failures.append("%s: %r" % (name, exc))
            finally:
                hunter_module.time = original
            count += 1
            print("%s %s" % ("ok   " if len(failures) == before else "FALHA", name))
    for f in failures:
        print("  -", f)
    print("%d testes, %d falha(s)" % (count, len(failures)))
    sys.exit(1 if failures else 0)
