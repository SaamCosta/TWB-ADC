"""Nobre extra multi-origem (docs/backend.md §8.41).

Caso real que motivou: o trem de 4 nobres contra a Barbara #61947 (583|285)
pousou as 07:27:43 de 2026-09-30 deixando lealdade 1. O nobre extra so saia da
aldeia dona (`reserved_by`, BBM 010), cujos 3 nobres estavam voltando, enquanto
a BBM 001 -- tambem origem do trem -- tinha 1 nobre em casa. Com regen 1/h,
queda minima 20 e ~12h44 de voo, um nobre so bastava com certeza saindo ate
~13:43. O usuario mandou a mao as 08:05:34 (pouso 20:49:58).

Cobre:
- as funcoes puras (`single_noble_deadline`, `rank_extra_noble_origins`,
  `extra_noble_worth_sending`) com os numeros reais -- coordenadas, velocidade
  do nobre e o relatorio;
- `_send_extra_noble` escolhendo a origem que pousa primeiro entre as que tem
  nobre livre e escolta, descontando reservas de outros sistemas (PvP e
  `tribe_support`) pela regra de verdade do `TroopManager`;
- os portoes de origem (`conquest_enabled: false`, origem de PvP) barrando
  quem MANDA, e nao mais o acompanhamento;
- a trava de nobre em voo valendo venha o nobre de onde vier;
- chegada 0 do jogo virando `null` (em voo indefinidamente), nunca "ja pousou";
- envio que falha: segue para a proxima origem so quando o comando
  certamente nao foi criado (falha antes do POST final);
- o aviso sem origem saindo UMA vez por pouso;
- o sem-progresso (voo que regenera mais que a queda minima) nao manda;
- sem o dict de aldeias, so a dona -- o comportamento antigo.

Nada toca cache/ nem a rede. Roda sem pytest:
    python tests/test_conquest_extra_origin.py
"""
import logging
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import game.attack as attack_module
import game.village as village_module
from game.attack import (
    EXTRA_CERTAIN, EXTRA_CHANCE, EXTRA_SHORT, ConquestCache, ConquestManager,
    extra_noble_worth_sending, rank_extra_noble_origins, single_noble_deadline,
)
from game.troopmanager import TroopManager
from game.village import Village

logging.disable(logging.CRITICAL)

checks = 0


def check(condition, message):
    global checks
    checks += 1
    if not condition:
        raise AssertionError(message)


# Numeros reais (cache/conquest/61947.json, relatorios 166237693..697,
# cache/world/units_br143.json, cache/managed).
TARGET = "61947"
TARGET_LOC = (583, 285)
REPORT_WHEN = 1790764063          # 07:27:43, os quatro relatorios do trem
TRAIN_ARRIVAL = 1790764062        # scheduled_arrival do registro
MANUAL_DEPARTURE = 1790766334     # 08:05:34 (pouso 20:49:58 menos o voo)
SPEEDS = {"spear": 18.0, "axe": 18.0, "light": 10.0, "ram": 30.0,
          "catapult": 30.0, "snob": 35.0}
NOBLE_RANGE = 70
DROP = (20, 35)

BBM001 = ("41123", (577, 306))
BBM010 = ("74689", (578, 306))


# --------------------------------------------------------------------------
# Funcoes puras
# --------------------------------------------------------------------------
deadline = single_noble_deadline(1.0, REPORT_WHEN, 1, 20)
check(deadline == REPORT_WHEN + 19 * 3600,
      "lealdade 1, regen 1/h, queda 20: pouso ate 19 h depois do relatorio")
check(single_noble_deadline(21.0, REPORT_WHEN, 1, 20) is None,
      "acima da queda minima ja no relatorio: nenhum pouso garante")
check(single_noble_deadline(5.0, REPORT_WHEN, 0, 20) == float("inf"),
      "sem regeneracao o prazo nao vence")

far = ("99999", (500, 285))       # 83 campos: alem do alcance de 70
ranked, dropped = rank_extra_noble_origins(
    [BBM001, far, ("88888", None), BBM010], TARGET_LOC, SPEEDS, NOBLE_RANGE,
    MANUAL_DEPARTURE, 1.0, REPORT_WHEN, 1, *DROP,
)
check([e["vid"] for e in ranked] == ["74689", "41123"],
      "ordem pela chegada: BBM 010 (21,59) antes da BBM 001 (21,84): %r" % ranked)
check({vid for vid, _ in dropped} == {"99999", "88888"},
      "fora do alcance e sem coordenada saem com motivo: %r" % dropped)
bbm001 = ranked[1]
check(bbm001["travel_seconds"] == 45864,
      "12h44m24s, o voo medido no envio manual: %r" % bbm001["travel_seconds"])
check(bbm001["latest_departure"] - REPORT_WHEN == 19 * 3600 - 45864,
      "ultima saida da BBM 001 = 13:43:19 (6h15m36s depois do pouso)")
check(ranked[0]["latest_departure"] - REPORT_WHEN == 19 * 3600 - 45332,
      "a BBM 010 tinha ate 13:52:11")
check(bbm001["verdict"] == EXTRA_CERTAIN
      and abs(bbm001["loyalty_at_arrival"] - (1 + (45864 + 2271) / 3600.0)) < 1e-6,
      "saindo as 08:05:34 pousa a ~14,4: basta com certeza (%r)" % bbm001)
check(bbm001["arrival_ts"] == MANUAL_DEPARTURE + 45864,
      "chegada prevista = saida + voo")

# Saindo tarde: 14:00 da a ~20,3 na chegada -- so com sorte (faixa 20..35).
late, _ = rank_extra_noble_origins([BBM001], TARGET_LOC, SPEEDS, NOBLE_RANGE,
                                   REPORT_WHEN + 6 * 3600 + 32 * 60, 1.0,
                                   REPORT_WHEN, 1, *DROP)
check(late[0]["verdict"] == EXTRA_CHANCE, "depois do prazo vira chance: %r" % late[0])
check(extra_noble_worth_sending(late[0]), "chance: manda (nobre que nao conquista volta)")

# Lealdade 30 no relatorio: 12h44 de voo pousa a ~42,7 -> insuficiente, mas
# derruba 20 e a viagem so regenera 12,7: progride, manda.
short, _ = rank_extra_noble_origins([BBM001], TARGET_LOC, SPEEDS, NOBLE_RANGE,
                                    REPORT_WHEN, 30.0, REPORT_WHEN, 1, *DROP)
check(short[0]["verdict"] == EXTRA_SHORT and short[0]["progress"],
      "insuficiente com progresso: %r" % short[0])
check(extra_noble_worth_sending(short[0]), "insuficiente que progride: manda")

# 36 campos -> 21 h de voo: regenera 21 > queda minima 20. Nunca fecha.
slow, _ = rank_extra_noble_origins([("77777", (583, 321))], TARGET_LOC, SPEEDS,
                                   NOBLE_RANGE, REPORT_WHEN, 30.0, REPORT_WHEN,
                                   1, *DROP)
check(slow[0]["verdict"] == EXTRA_SHORT and not slow[0]["progress"],
      "voo que regenera mais que a queda: sem progresso (%r)" % slow[0])
check(not extra_noble_worth_sending(slow[0]), "sem progresso: nao manda")

# Sem tabela de velocidade: a ordem continua pela distancia, e o veredito e
# "nao sei" -- nao um numero inventado.
blind, _ = rank_extra_noble_origins([BBM001, BBM010], TARGET_LOC, {}, NOBLE_RANGE,
                                    MANUAL_DEPARTURE, 1.0, REPORT_WHEN, 1, *DROP)
check([e["vid"] for e in blind] == ["74689", "41123"]
      and all(e["arrival_ts"] is None and e["verdict"] is None for e in blind),
      "sem velocidade: ordem por distancia, chegada/veredito None: %r" % blind)
check(extra_noble_worth_sending(blind[0]), "veredito desconhecido: manda, como antes")


# --------------------------------------------------------------------------
# _send_extra_noble com aldeias de mentira e reservas de verdade
# --------------------------------------------------------------------------
class Recorder:
    def __init__(self):
        self.messages = []

    def send(self, message):
        self.messages.append(message)


class FakeAttack:
    def __init__(self, vid, duration=45864, result=True):
        self.vid = vid
        self.duration = duration
        self.result = result
        self.calls = []
        self.last_attack_duration = None
        self.last_attack_failure = None

    def attack(self, target, troops=None):
        self.calls.append((target, dict(troops)))
        if not self.result:
            # Sem marcador, como o POST final do AttackManager.attack() que
            # volta sem resposta: o caso ambiguo.
            return False
        self.last_attack_duration = self.duration
        return {"ok": True}


NAMES = {"74689": "BBM 010", "41123": "BBM 001", "55647": "BBM 037",
         "51540": "BBM 032", "55553": "BBM 038", "57689": "BBM 036"}


class FakeFileManager:
    @staticmethod
    def load_json_file(path, **k):
        vid = os.path.basename(path).replace(".json", "")
        if "managed" in path and vid in NAMES:
            return {"name": NAMES[vid]}
        return None


def village(vid, location, troops, reserve=None, pvp_source=False, duration=45864,
            result=True):
    units = TroopManager(wrapper=None, village_id=vid)
    units.troops = dict(troops)
    units.conquest_reserve = dict(reserve or {})
    return SimpleNamespace(
        village_id=vid,
        units=units,
        area=SimpleNamespace(my_location=list(location), villages={}),
        attack=FakeAttack(vid, duration=duration, result=result),
        rep_man=None,
        _pvp_troop_spending_suspended=lambda: pvp_source,
    )


def empire(**overrides):
    """
    A vizinhanca da 61947, com coordenadas reais e tropas de cenario:

      BBM 037 (3,0 campos)  -- nobre, mas origem de PvP        -> portao
      BBM 032 (4,1)         -- nobre, mas conquest_enabled off  -> portao
      BBM 036 (8,2)         -- nobre, mas toda a tropa esta em apoio a tribo
      BBM 038 (11,2)        -- 1 nobre, reservado por um trem PvP
      BBM 010 (21,59)       -- a dona, nobres voltando (0 em casa)
      BBM 001 (21,84)       -- 1 nobre livre e escolta: e ela que manda
    """
    army = {"axe": 800, "light": 400}
    vs = {
        "55647": village("55647", (583, 288), dict(army, snob=1), pvp_source=True),
        "51540": village("51540", (582, 289), dict(army, snob=1)),
        "57689": village("57689", (585, 293), dict(army, snob=1),
                         reserve={"tribe_support": dict(army)}),
        "55553": village("55553", (586, 296), dict(army, snob=1),
                         reserve={"pvp:44155": {"snob": 1}}),
        "74689": village("74689", BBM010[1], dict(army, snob=0)),
        "41123": village("41123", BBM001[1], dict(army, snob=1)),
    }
    vs.update(overrides)
    return vs


CONFIG = {"villages": {"51540": {"conquest_enabled": False}}}
CFG = {"loyalty_regen_per_hour": 1, "barbarian_escort_ratio": 0.5,
       "min_escort_total": 50}


def anchor(villages, now):
    cm = ConquestManager.__new__(ConquestManager)
    cm.village_id = "74689"
    cm.config = CONFIG
    cm.logger = logging.getLogger("test")
    cm.wrapper = SimpleNamespace(reporter=SimpleNamespace(report=lambda *a, **k: None))
    cm.villages = villages
    anchor_v = (villages or {}).get("74689") or village("74689", BBM010[1], {"snob": 0})
    cm.troopmanager = anchor_v.units
    cm.map = anchor_v.area
    cm._attack_manager = FakeAttack("74689-own")
    cm._drop_min, cm._drop_max = DROP
    cm.repman = None
    cm._world_travel_params = lambda: (SPEEDS, NOBLE_RANGE)
    return cm


RECORD = {
    "target_id": TARGET, "status": "train_sent", "reserved_by": "74689",
    "sources": {"74689": 3, "41123": 1}, "hits_done": 4, "hits_needed": 4,
    "target_name": "Bárbara #61947", "target_location": list(TARGET_LOC),
    "noble_arrivals": [TRAIN_ARRIVAL] * 4, "last_hit_timestamp": TRAIN_ARRIVAL,
}


class Env:
    """Troca os colaboradores do modulo attack e desfaz na saida."""

    def __init__(self, now):
        self.now = now
        self.written = []
        self.notes = Recorder()

    def __enter__(self):
        self.saved = (attack_module.ConquestCache.set, attack_module.Notification,
                      attack_module.FileManager, attack_module.time,
                      ConquestManager.world_drop_range)
        attack_module.ConquestCache.set = staticmethod(
            lambda t, e: self.written.append((t, dict(e))))
        attack_module.Notification = self.notes
        attack_module.FileManager = FakeFileManager
        attack_module.time = SimpleNamespace(time=lambda: self.now)
        ConquestManager.world_drop_range = staticmethod(lambda cfg: DROP)
        return self

    def __exit__(self, *exc):
        (attack_module.ConquestCache.set, attack_module.Notification,
         attack_module.FileManager, attack_module.time,
         ConquestManager.world_drop_range) = self.saved
        return False


def send(cm, record=None, loyalty=1.0, loyalty_at=REPORT_WHEN, now=MANUAL_DEPARTURE):
    record = dict(record or RECORD)
    current = min(100.0, loyalty + max(0, now - loyalty_at) / 3600.0)
    return cm._send_extra_noble(TARGET, record, CFG, loyalty=loyalty,
                                loyalty_at=loyalty_at, current_loyalty=current,
                                loyalty_source="report", regen=1)


# 1. O caso da 61947: sai da BBM 001, e so dela.
vs = empire()
with Env(MANUAL_DEPARTURE) as env:
    sent = send(anchor(vs, MANUAL_DEPARTURE))
check(sent is True, "o nobre extra saiu")
callers = {vid: v.attack.calls for vid, v in vs.items() if v.attack.calls}
check(list(callers) == ["41123"],
      "so a BBM 001 mandou -- portao, reserva PvP, apoio a tribo e dona sem "
      "nobre ficaram de fora: %r" % callers)
_, troops = callers["41123"][0]
check(troops["snob"] == 1 and troops.get("axe") == 100 and troops.get("light") == 50,
      "um nobre com a escolta da propria aldeia: %r" % troops)
tid, rec = env.written[-1]
check(tid == TARGET and rec["reserved_by"] == "74689",
      "a dona continua acompanhando: %r" % rec.get("reserved_by"))
check(rec["extra_source_village_id"] == "41123", "origem registrada")
check(rec["noble_arrivals"] == [MANUAL_DEPARTURE + 45864],
      "chegada da confirmacao do jogo, so este nobre: %r" % rec["noble_arrivals"])
check(rec["status"] == "extra_pending" and rec["hits_done"] == 5, "extra pendente, 5o golpe")
check(rec["extra_prediction"]["verdict"] == EXTRA_CERTAIN
      and rec["extra_prediction"]["single_noble_deadline"] == REPORT_WHEN + 19 * 3600,
      "previsao gravada: %r" % rec["extra_prediction"])
check("target_id" not in rec, "o target_id de memoria nao vai para o arquivo")
check(ConquestCache.nobles_in_flight(rec, now=MANUAL_DEPARTURE + 60),
      "e a trava ve o nobre no ar")
check(len(env.notes.messages) == 1 and "BBM 001" in env.notes.messages[0]
      and "basta com certeza" in env.notes.messages[0],
      "aviso de envio com a origem: %r" % env.notes.messages)

# 2. A trava vale venha o nobre de onde vier: com esse registro, nada sai.
vs = empire()
with Env(MANUAL_DEPARTURE + 60) as env:
    cm = anchor(vs, MANUAL_DEPARTURE + 60)
    cm._target_is_mine = lambda t: False
    cm._target_taken_by_other = lambda t: None
    cm._claim_block_reason = lambda t, loc: None
    cm._get_village_meta = lambda t: {}
    result = cm._handle_existing(dict(rec, target_id=TARGET), CFG)
check(result is False and not any(v.attack.calls for v in vs.values()),
      "nobre no ar: nenhuma origem manda")

# 3. Chegada 0 do jogo nao e "ja pousou": vira null, em voo indefinidamente.
vs = empire()
vs["41123"].attack.duration = 0
with Env(MANUAL_DEPARTURE) as env:
    send(anchor(vs, MANUAL_DEPARTURE))
rec0 = env.written[-1][1]
check(rec0["noble_arrivals"] == [None], "duracao 0 -> null: %r" % rec0["noble_arrivals"])
check(ConquestCache.nobles_in_flight(rec0) == [float("inf")],
      "null trava por tempo indeterminado")

# 4a. O POST final sem resposta e ambiguo -- o comando pode ter saido. A dona
# tem nobre e pousa primeiro; a BBM 001 mandaria com sucesso, e justamente por
# isso nao pode ser tentada: um segundo nobre por cima e o incidente de 12/08.
vs = empire()
vs["74689"].units.troops["snob"] = 1
vs["74689"].attack.result = False                 # sem marcador: ambiguo
with Env(MANUAL_DEPARTURE) as env:
    sent = send(anchor(vs, MANUAL_DEPARTURE))
check(sent is False, "falhou")
tried = [vid for vid, v in vs.items() if v.attack.calls]
check(tried == ["74689"], "ambiguo: uma tentativa so, na que pousa primeiro: %r" % tried)
check(not env.written, "nada gravado sem envio")

# 4b. Recusa ANTES do POST final (confirmacao recusada, rede fora na etapa
# try=confirm): o comando nao existe, e a proxima origem manda no mesmo ciclo
# -- esperar custaria horas de um prazo de ~6 h.
class RefusedAttack(FakeAttack):
    def attack(self, target, troops=None):
        self.calls.append((target, dict(troops)))
        self.last_attack_failure = "recusado_pelo_jogo"
        return False


vs = empire()
vs["74689"].units.troops["snob"] = 1
vs["74689"].attack = RefusedAttack("74689")
with Env(MANUAL_DEPARTURE) as env:
    sent = send(anchor(vs, MANUAL_DEPARTURE))
tried = [vid for vid, v in vs.items() if v.attack.calls]
check(sent is True and tried == ["74689", "41123"],
      "recusa na confirmacao: segue para a BBM 001: %r" % tried)
check(env.written[-1][1]["extra_source_village_id"] == "41123"
      and len(env.written[-1][1]["noble_arrivals"]) == 1,
      "um nobre so registrado, o que saiu")

# 5. Nenhuma origem com nobre: avisa UMA vez por pouso, com o prazo.
vs = empire()
vs["41123"].units.troops["snob"] = 0
with Env(MANUAL_DEPARTURE) as env:
    first = send(anchor(vs, MANUAL_DEPARTURE))
    stored = dict(env.written[-1][1], target_id=TARGET)
    second = send(anchor(vs, MANUAL_DEPARTURE + 1800), record=stored,
                  now=MANUAL_DEPARTURE + 1800)
check(first is False and second is False, "sem nobre, nada sai")
check(len(env.notes.messages) == 1,
      "um aviso so para o mesmo pouso: %r" % env.notes.messages)
msg = env.notes.messages[0]
# A mais rapida que passa no portao e a BBM 036 (8,2 campos): e dela que o
# prazo de saida vale a pena saber, mesmo sem nobre agora.
check("nenhuma aldeia tem nobre livre" in msg and "BBM 036" in msg,
      "o aviso nomeia a origem mais rapida com alcance: %r" % msg)
check(stored["extra_alert"]["key"] == "sem_origem:%d" % REPORT_WHEN,
      "marca do aviso atrelada ao relatorio: %r" % stored.get("extra_alert"))
# Pouso novo (outro relatorio) e outra situacao: avisa de novo.
with Env(MANUAL_DEPARTURE + 3600) as env:
    send(anchor(vs, MANUAL_DEPARTURE + 3600), record=stored,
         loyalty_at=REPORT_WHEN + 3600, now=MANUAL_DEPARTURE + 3600)
check(len(env.notes.messages) == 1, "relatorio novo, aviso novo")

# 6. Sem progresso: a unica origem voa 21 h. Nao manda, avisa.
far_v = village("77777", (583, 321), {"axe": 800, "light": 400, "snob": 1})
vs = {"74689": village("74689", BBM010[1], {"snob": 0}), "77777": far_v}
with Env(REPORT_WHEN) as env:
    sent = send(anchor(vs, REPORT_WHEN), loyalty=30.0, now=REPORT_WHEN)
check(sent is False and not far_v.attack.calls, "nao manda sem progresso")
check(len(env.notes.messages) == 1 and "dois nobres juntos" in env.notes.messages[0],
      "avisa o que fazer: %r" % env.notes.messages)

# 7. Sem o dict de aldeias (testes e chamadas antigas): so a dona, sem portao.
with Env(MANUAL_DEPARTURE) as env:
    cm = anchor(None, MANUAL_DEPARTURE)
    cm.troopmanager.troops.update({"snob": 1, "axe": 800, "light": 400})
    sent = send(cm)
check(sent is True and len(cm._attack_manager.calls) == 1,
      "sem villages manda da propria aldeia, pelo AttackManager dela")
check(env.written[-1][1]["extra_source_village_id"] == "74689", "origem = dona")


# 8. Ponta a ponta pelo _handle_existing: a regen conta do POUSO que o
# relatorio registra, nao do `last_hit_timestamp`. Aqui o registro diz 3 h
# antes do relatorio; contando dele a previsao sairia 3 pontos acima.
class TrainRepman:
    last_reports = {
        rid: {"type": "attack", "dest": TARGET,
              "extra": {"loyalty_after": loy, "when": REPORT_WHEN,
                        "units_sent": {"axe": 26, "snob": 1}}}
        for rid, loy in (("166237693", 79.0), ("166237695", 49.0),
                         ("166237696", 23.0), ("166237697", 1.0))}

    def read(self, full_run=False):
        pass


vs = empire()
landed = dict(RECORD, last_hit_timestamp=REPORT_WHEN - 3 * 3600,
              noble_arrivals=[REPORT_WHEN - 3 * 3600] * 4)
with Env(MANUAL_DEPARTURE) as env:
    cm = anchor(vs, MANUAL_DEPARTURE)
    cm.repman = TrainRepman()
    cm._reports_refreshed = False
    cm._target_is_mine = lambda t: False
    cm._target_taken_by_other = lambda t: None
    cm._claim_block_reason = lambda t, loc: None
    cm._get_village_meta = lambda t: {}
    sent = cm._handle_existing(landed, CFG)
check(sent is True and vs["41123"].attack.calls, "pousou a 1: manda da BBM 001")
pred = env.written[-1][1]["extra_prediction"]["loyalty_at_arrival"]
check(abs(pred - (1 + (MANUAL_DEPARTURE + 45864 - REPORT_WHEN) / 3600.0)) < 1e-6,
      "regen a partir do relatorio (~14,4), nao do last_hit (~17,4): %r" % pred)


# --------------------------------------------------------------------------
# Village.run_conquest: portao de origem nao barra mais o acompanhamento
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
    v.village_id = "74689"
    v.config = {"conquest": {"enabled": True},
                "villages": {"74689": {"conquest_enabled": False}}}
    v.logger = logging.getLogger("test")
    v.wrapper = object()
    v.units = object()
    v.area = object()
    v.rep_man = SimpleNamespace()
    v.reservation_board = None
    v.pvp_conquest_villages = {"74689": v, "41123": object()}
    v._pvp_troop_spending_suspended = lambda: True
    v.run_conquest()
finally:
    village_module.ConquestManager = saved_cm

check(captured.get("ran") is True,
      "origem de PvP e conquest_enabled off ainda acompanham (posse, lealdade)")
check(captured.get("villages") is v.pvp_conquest_villages,
      "o dict de aldeias do twb.py chega ao manager")


print("OK: %d checks" % checks)
