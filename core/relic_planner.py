"""
Relíquias, Fase 2 (§8.77): o planejador. Lógica pura, sem rede e sem POST.

Responde três perguntas, a partir do estado que a Fase 1 grava
(`cache/relics.json`) e do que o bot já mede em disco:

1. Quanto vale, em recurso/h, cada atributo em cada aldeia
   (`village_inputs` + `attribute_rate`). A função de valor não conhece
   relíquia: recebe um atributo e uma aldeia, e serve também para a escolha de
   bandeira por valor que vem depois (memória bandeiras-recalcular-por-valor).
2. Quanto vale pôr a relíquia R na anfitriã H: o valor MARGINAL nas aldeias
   cobertas (distância euclidiana <= `range`, a anfitriã inclusa, a mesma regra
   de `core/relics.py`), com o teto de 20% por atributo sobre a parte das
   relíquias (`Model.value` da alocação com e sem R).
3. Qual alocação maximiza o total, e o ganho de cada mudança em relação à
   alocação atual (`plan`): busca local a partir da alocação atual, um passo
   de cada vez, o de maior ganho primeiro.

Fonte de cada número (5º padrão). Todas em disco, 0 GET:

- Produção: base sem bônus = fórmula do jogo pelo nível da mina
  (`cache/managed/<vid>.json` -> `buidling_levels`, medido a cada ciclo), com
  a base do nível 1 do mundo (`<base_production>`, br143 = 60, §8.78) e a
  velocidade (`<speed>`), ambas de `get_config`, em
  `cache/world/config_<server>.json`. A relíquia soma ao percentual, então
  +x% vale `base * x / 100` (leitura aditiva: o quadro da BBM 001 mostra +55%
  de ferro = itens 30 + paladino 15 + relíquia 10). Não usei a produção lida
  dividida pelo total do quadro porque o quadro não traz tudo: os "Efeitos
  ativos" de modificação de aldeia ("Trabalhadores eficientes +3%") ficam
  fora dos totais `benefit`. A produção lida do `game_data`
  (`village_prod` em `cache/relics.json`) entra como conferência da fórmula.
  Produção só vale onde cabe no armazém: o valor é multiplicado pela fração
  das leituras `TWB_PRE_RESOURCE` (reporter, `cache/logs/twb_*.log`, 7 dias)
  com aquele recurso abaixo de 99% do armazém (`storage` do `cache/managed`).
  Recurso no teto é censurado (11º padrão): a produção a mais transborda.
- Desconto de recrutamento por prédio: gasto/h do bot naquele prédio = unidades
  das linhas `TWB_RECRUIT` (7 dias) vezes o custo NOMINAL da unidade. O custo
  vem de `unit_costs` em `cache/relics.json`, lido pelo próprio bot na tela de
  recrutamento de aldeia sem desconto de relíquia; enquanto não houver leitura,
  a tabela padrão do jogo (`STANDARD_UNIT_COST`, marcada como não medida). Só
  o gasto do BOT: recrutamento manual do jogador não deixa log (9º padrão).
- Desconto de nobre: nobres que o Hunter mandou de cada aldeia em 14 dias
  (`cache/hunter/schedules.json`, ataques `sent` com `snob`), vezes o custo em
  recurso do nobre lido na academia (`next_snob` 40.000/50.000/50.000, §8.52).
  A tela da relíquia fala em "recursos": a moeda não entra.
- Velocidade de recrutamento: só vale com a fila do prédio como gargalo,
  medida pela fração do tempo em que ela esteve ocupada (intervalos
  `[envio, idle till]` das linhas `TWB_RECRUIT`, 7 dias). Abaixo de
  `BOTTLENECK_BUSY` vale 0, com a fração escrita. Com gargalo, vale o gasto do
  prédio por ponto (leitura "tempo / (1 + S)" não medida, 19º padrão).
- Velocidade de construção: a mesma medição sobre `TWB_BUILD` (início e
  "finishes"). Mesmo com gargalo vale 0: o bot não registra o custo das obras,
  e sem ele não há conversão em recurso.
- Valor 0, com o motivo escrito, nunca peso inventado: poder de ataque/defesa
  de unidade, dano de catapulta/aríete, explorador escondido, bárbaro
  (`combat`), velocidade do mercador e atributo não reconhecido.

Nada aqui equipa ou remove: isso é a Fase 3 (histerese, teto de trocas/dia).
Fase 4 (§8.79): `plan_from_disk` também avalia as fusões possíveis
(`core/relic_fusion.py`), refazendo este plano sobre o estado hipotético.
"""
import ast
import glob
import json
import math
import os
import re
import time

from core import relic_fusion as F
from core import relics as R

CAP = R.RELIC_ATTRIBUTE_CAP

RECRUIT_WINDOW = 7 * 86400
STORAGE_WINDOW = 7 * 86400
BUILD_WINDOW = 7 * 86400
NOBLE_WINDOW = 14 * 86400
# Fila ocupada nesta fração do tempo = o prédio é o gargalo. Medido em 29/10:
# a fila mais ocupada da conta ficou em 22% (recrutamento) e 17% (construção).
BOTTLENECK_BUSY = 0.9
STORAGE_FULL = 0.99
# Abaixo disto (recurso/h) é empate. A Fase 3 põe a histerese de verdade.
MIN_GAIN = 1.0
MAX_STEPS = 20

# §8.52: `BuildingSnob.Modes.train.next_snob` lido no br143 em 04/10.
NOBLE_COST = {"wood": 40000, "stone": 50000, "iron": 50000}
# Lealdade depois da conquista (ConquestManager: "reiniciou em 25").
POST_CONQUEST_LOYALTY = 25.0

# Tabela padrão do jogo, NÃO medida no br143: só vale até o bot gravar o custo
# lido na tela de recrutamento (`unit_costs`). O `Simulator` diz ferro 20 para
# o lanceiro; aqui está 10. Quem decide é a leitura (§8.77).
STANDARD_UNIT_COST = {
    "spear": (50, 30, 10), "sword": (30, 30, 70), "axe": (60, 30, 40),
    "archer": (100, 30, 60), "spy": (50, 50, 20), "light": (125, 100, 250),
    "marcher": (250, 100, 150), "heavy": (200, 150, 600), "ram": (300, 200, 200),
    "catapult": (320, 400, 100),
}
UNIT_BUILDING = {
    "spear": "barracks", "sword": "barracks", "axe": "barracks", "archer": "barracks",
    "spy": "stable", "light": "stable", "marcher": "stable", "heavy": "stable",
    "ram": "garage", "catapult": "garage",
}
BUILDING_WORDS = {"Quartel": "barracks", "Estábulo": "stable", "Oficina": "garage"}
BUILDING_NAMES = {v: k for k, v in BUILDING_WORDS.items()}
RESOURCE_WORDS = {"madeira": "wood", "argila": "stone", "barro": "stone", "ferro": "iron"}
RESOURCES = ("wood", "stone", "iron")

ZERO_REASONS = {
    "combat": "atributo de combate: não há conversão defensável em recurso/h por aldeia",
    "merchant_speed": "mercador mais rápido só vale se faltar mercador, e o bot não mede isso",
    "unknown": "atributo não reconhecido pelo planejador",
}

_REPORTER_RE = re.compile(r"^(\d+) - (\d+) - (TWB_\w+) - (.*)$")
_RECRUIT_RE = re.compile(r"Recruitment of (\d+) (\w+) started \((\w+) idle till (\d+)\)")
_BUILD_RE = re.compile(r"Building (\w+) \d+ -> \d+ \(finishes: (\d+):(\d+):(\d+)\)")


# -- 1. valor de cada atributo em cada aldeia ---------------------------------

def classify(key):
    """O texto do jogo (sem número) -> {"kind", ...}. Nunca levanta."""
    key = " ".join(str(key or "").split())
    if key == "nos custos de recrutamento dos nobres":
        return {"kind": "noble_cost"}
    m = re.fullmatch(r"na produção de (\w+)", key)
    if m:
        res = RESOURCE_WORDS.get(m.group(1).lower())
        return {"kind": "production", "resource": res} if res else {"kind": "unknown"}
    m = re.fullmatch(r"(\S+) nos custos de recrutamento", key)
    if m and m.group(1) in BUILDING_WORDS:
        return {"kind": "recruit_cost", "building": BUILDING_WORDS[m.group(1)]}
    m = re.fullmatch(r"(\S+) na velocidade de recrutamento", key)
    if m and m.group(1) in BUILDING_WORDS:
        return {"kind": "recruit_speed", "building": BUILDING_WORDS[m.group(1)]}
    if key == "na velocidade de construção":
        return {"kind": "build_speed"}
    if key == "na velocidade de viagem do mercador":
        return {"kind": "merchant_speed"}
    if ":" in key:
        return {"kind": "combat"}
    return {"kind": "unknown"}


# Produção da mina no nível 1 quando o mundo não publica `<base_production>`:
# 30 é o valor dos mundos br de 29/10 que não são o br143 (§8.78).
DEFAULT_BASE_PRODUCTION = 30.0


def mine_production(level, speed, base=DEFAULT_BASE_PRODUCTION):
    """
    Produção/h sem bônus de uma mina no nível `level`:
    `base × 1,163118^(nível−1) × speed`, com `base` = `<base_production>` do
    mundo (br143 = 60, §8.78). Nível 0 = 5/h num mundo de base 30, escalado
    pela mesma razão (não medido: nenhuma aldeia da conta tem mina 0).
    """
    base = float(base or DEFAULT_BASE_PRODUCTION)
    if not level:
        return 5.0 * speed * base / DEFAULT_BASE_PRODUCTION
    return base * (1.163118 ** (int(level) - 1)) * speed


def attribute_rate(spec, inputs):
    """
    (recurso/h por ponto percentual, motivo quando 0) do atributo `spec`
    (saída de `classify`) na aldeia descrita por `inputs` (`village_inputs`).
    Linear no percentual: o teto de 20% é aplicado por quem soma.
    """
    kind = spec.get("kind")
    inputs = inputs or {}
    if kind == "production":
        res = spec["resource"]
        base = (inputs.get("base_prod_h") or {}).get(res)
        if base is None:
            return 0.0, "produção desconhecida (%s)" % (inputs.get("base_source") or "sem nível de mina")
        free = 1.0 - (inputs.get("cap_frac") or {}).get(res, 0.0)
        if free <= 0:
            return 0.0, "armazém cheio de %s em todas as leituras" % res
        return base * free / 100.0, None
    if kind == "recruit_cost":
        spend = (inputs.get("recruit_h") or {}).get(spec["building"], 0.0)
        if not spend:
            return 0.0, "o bot não recrutou no %s em 7 dias" % BUILDING_NAMES[spec["building"]].lower()
        return spend / 100.0, None
    if kind == "noble_cost":
        nobles_h = inputs.get("nobles_h") or 0.0
        if not nobles_h:
            return 0.0, "nenhum nobre saiu desta aldeia pelo Hunter em 14 dias"
        return nobles_h * sum(NOBLE_COST.values()) / 100.0, None
    if kind == "recruit_speed":
        b = spec["building"]
        busy = (inputs.get("recruit_busy") or {}).get(b, 0.0)
        if busy < BOTTLENECK_BUSY:
            return 0.0, "fila do %s ocupada %.0f%% do tempo: não é gargalo" % (
                BUILDING_NAMES[b].lower(), 100 * busy)
        return (inputs.get("recruit_h") or {}).get(b, 0.0) / 100.0, None
    if kind == "build_speed":
        busy = inputs.get("build_busy") or 0.0
        if busy < BOTTLENECK_BUSY:
            return 0.0, "fila de construção ocupada %.0f%% do tempo: não é gargalo" % (100 * busy)
        return 0.0, "fila de construção é gargalo, mas o bot não registra o custo das obras"
    return 0.0, ZERO_REASONS.get(kind, ZERO_REASONS["unknown"])


# -- medições em disco (0 GET) --------------------------------------------------

def _busy_fraction(intervals, start, end):
    """Fração de [start, end] coberta pela união dos intervalos."""
    total, cur_s, cur_e = 0.0, None, None
    for s, e in sorted((max(s, start), min(e, end)) for s, e in intervals):
        if e <= s:
            continue
        if cur_s is None:
            cur_s, cur_e = s, e
        elif s <= cur_e:
            cur_e = max(cur_e, e)
        else:
            total += cur_e - cur_s
            cur_s, cur_e = s, e
    if cur_s is not None:
        total += cur_e - cur_s
    return total / (end - start) if end > start else 0.0


def read_reporter(log_dir, now, window=max(RECRUIT_WINDOW, STORAGE_WINDOW, BUILD_WINDOW)):
    """
    Eventos do reporter (`cache/logs/twb_*.log`) dentro de `window`:
    {"recruit": [(ts, vid, building, unit, n, idle_till)],
     "pre": [(ts, vid, {res: n})], "build": [(ts, vid, finish_ts)]}.
    Só arquivos modificados dentro da janela (o reporter abre um por processo).
    """
    since = now - window
    out = {"recruit": [], "pre": [], "build": []}
    for path in glob.glob(os.path.join(log_dir, "twb_*.log")):
        try:
            if os.path.getmtime(path) < since:
                continue
            fh = open(path, "r", encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                m = _REPORTER_RE.match(line.strip())
                if not m:
                    continue
                ts, vid, event, msg = int(m.group(1)), m.group(2), m.group(3), m.group(4)
                if ts < since or ts > now:
                    continue
                if event == "TWB_RECRUIT":
                    r = _RECRUIT_RE.match(msg)
                    if r:
                        out["recruit"].append((ts, vid, r.group(3), r.group(2), int(r.group(1)),
                                               int(r.group(4))))
                elif event == "TWB_PRE_RESOURCE":
                    try:
                        res = ast.literal_eval(msg)
                    except (ValueError, SyntaxError):
                        continue
                    if isinstance(res, dict):
                        out["pre"].append((ts, vid, res))
                elif event == "TWB_BUILD":
                    b = _BUILD_RE.match(msg)
                    if b:
                        # "finishes" é só a hora do dia: a próxima ocorrência
                        # depois do início (obra de mais de 24 h não se distingue).
                        lt = time.localtime(ts)
                        fin = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, int(b.group(2)),
                                           int(b.group(3)), int(b.group(4)), 0, 0, -1))
                        while fin < ts:
                            fin += 86400
                        out["build"].append((ts, vid, fin))
    return out


def noble_departures(schedules, now, window=NOBLE_WINDOW):
    """{vid: nobres} que o Hunter mandou (ataque `sent` com `snob`) na janela."""
    out = {}
    for sched in (schedules or {}).values():
        for atk in (sched or {}).get("attacks") or []:
            n = int((atk.get("troops") or {}).get("snob", 0) or 0)
            when = atk.get("sent_at") or atk.get("send_time") or 0
            if atk.get("status") == "sent" and n > 0 and now - window <= float(when) <= now:
                vid = str(atk.get("source_village_id"))
                out[vid] = out.get(vid, 0) + n
    return out


def unit_cost(unit, measured):
    """((madeira, argila, ferro), fonte) do custo nominal de `unit`."""
    m = (measured or {}).get(unit)
    if m and all(m.get(r) for r in RESOURCES):
        return (m["wood"], m["stone"], m["iron"]), "tela de recrutamento (%s)" % m.get("vid")
    if unit in STANDARD_UNIT_COST:
        return STANDARD_UNIT_COST[unit], "tabela padrão (não medida)"
    return None, "unidade sem custo conhecido"


def village_inputs(vids, managed, reporter, nobles, now, speed=None, unit_costs=None,
                   village_prod=None, base_production=None):
    """
    {vid: inputs} do que se sabe de cada aldeia, com `missing` dizendo o que
    falta (aldeia sem `cache/managed`, como a recém-conquistada, entra só com
    o que se sabe dela).
    """
    recruits, pre, builds = {}, {}, {}
    for ts, vid, building, unit, n, idle in reporter.get("recruit") or []:
        if ts >= now - RECRUIT_WINDOW:
            recruits.setdefault(vid, []).append((ts, building, unit, n, idle))
    for ts, vid, res in reporter.get("pre") or []:
        if ts >= now - STORAGE_WINDOW:
            pre.setdefault(vid, []).append(res)
    for ts, vid, fin in reporter.get("build") or []:
        if ts >= now - BUILD_WINDOW:
            builds.setdefault(vid, []).append((ts, fin))
    cost_sources = set()
    out = {}
    for vid in vids:
        vid = str(vid)
        data = (managed or {}).get(vid)
        entry = {"missing": [], "recruit_h": {}, "recruit_busy": {}, "recruit_units": {},
                 "cap_frac": {}, "base_prod_h": None, "base_source": None}
        if not data:
            entry["missing"].append("sem cache/managed (aldeia ainda não rodou): "
                                    "nível de mina, armazém e leituras de recurso")
        levels = (data or {}).get("buidling_levels") or {}
        if data and speed:
            base = base_production or DEFAULT_BASE_PRODUCTION
            entry["base_prod_h"] = {r: mine_production(levels.get(r, 0), speed, base)
                                    for r in RESOURCES}
            entry["base_source"] = "fórmula do nível da mina, base %g%s x velocidade %g" % (
                base, "" if base_production else " (padrão, <base_production> não lido)", speed)
            entry["mine_levels"] = {r: levels.get(r, 0) for r in RESOURCES}
        elif data:
            entry["base_source"] = "velocidade do mundo não lida"
            entry["missing"].append("velocidade do mundo (<speed> do get_config)")
        prod = (village_prod or {}).get(vid)
        if prod and entry["base_prod_h"]:
            entry["prod_h"] = prod.get("prod_h")
            entry["prod_ratio"] = {r: round(prod["prod_h"][r] / entry["base_prod_h"][r], 3)
                                   for r in RESOURCES if entry["base_prod_h"].get(r)
                                   and (prod.get("prod_h") or {}).get(r) is not None}
        storage = (data or {}).get("storage")
        reads = pre.get(vid) or []
        entry["storage_reads"] = len(reads)
        if storage and reads:
            entry["cap_frac"] = {r: sum(1 for x in reads if (x.get(r) or 0) >= storage * STORAGE_FULL)
                                 / float(len(reads)) for r in RESOURCES}
        elif data:
            entry["missing"].append("leituras de recurso do reporter em 7 dias")
        busy_iv = {}
        for ts, building, unit, n, idle in recruits.get(vid) or []:
            cost, src = unit_cost(unit, unit_costs)
            units = entry["recruit_units"].setdefault(building, {})
            units[unit] = units.get(unit, 0) + n
            busy_iv.setdefault(building, []).append((ts, idle))
            if cost:
                cost_sources.add(src)
                entry["recruit_h"][building] = entry["recruit_h"].get(building, 0.0) + n * sum(cost)
        for building in list(entry["recruit_h"]):
            entry["recruit_h"][building] /= RECRUIT_WINDOW / 3600.0
        for building, iv in busy_iv.items():
            entry["recruit_busy"][building] = _busy_fraction(iv, now - RECRUIT_WINDOW, now)
        entry["build_busy"] = _busy_fraction(builds.get(vid) or [], now - BUILD_WINDOW, now)
        n_nobles = (nobles or {}).get(vid, 0)
        entry["nobles"] = n_nobles
        entry["nobles_h"] = n_nobles / (NOBLE_WINDOW / 3600.0)
        out[vid] = entry
    return out


# -- 2. valor de uma alocação ---------------------------------------------------

def _stats(relic):
    return [(s["key"], float(s["value"])) for s in R._stats(relic) if s.get("key")]


class Model:
    """Aldeias, coordenadas e taxas fixas; a alocação é o que varia."""

    def __init__(self, coords, rates):
        self.coords = {str(v): tuple(xy) for v, xy in (coords or {}).items()}
        self.rates = rates          # {vid: {key: recurso/h por ponto}}
        self._cover = {}

    def cover(self, host, rng):
        key = (str(host), rng)
        if key not in self._cover:
            xy = self.coords.get(str(host))
            if xy is None or rng is None:
                self._cover[key] = []
            else:
                lim = float(rng) + 1e-9
                self._cover[key] = sorted(v for v, p in self.coords.items()
                                          if R.distance(xy, p) <= lim)
        return self._cover[key]

    def sums(self, alloc, relics):
        out = {}
        for rid, host in alloc.items():
            relic = relics[rid]
            if host is None or relic.get("inactive"):
                continue
            for vid in self.cover(host, relic.get("range")):
                acc = out.setdefault(vid, {})
                for key, val in relic["stats"]:
                    acc[key] = acc.get(key, 0.0) + val
        return out

    def value(self, alloc, relics):
        total = 0.0
        for vid, acc in self.sums(alloc, relics).items():
            rates = self.rates.get(vid) or {}
            for key, pct in acc.items():
                rate = rates.get(key, 0.0)
                if rate:
                    total += rate * min(CAP, pct)
        return total


# -- 3. o plano -----------------------------------------------------------------

def _estimated_loyalty(record, now, regen):
    hit = record.get("last_hit_timestamp")
    if not hit:
        return None
    return min(100.0, POST_CONQUEST_LOYALTY + regen * max(0.0, (now - float(hit)) / 3600.0))


def low_loyalty_hosts(state, conquests, now, regen=1.0):
    """
    {vid: motivo} das aldeias com lealdade < 100 (relíquia equipada lá não
    sairia): relíquia com `locked_state` de lealdade, ou conquista recente
    (`cache/conquest`, status `conquered`, 25 + regen x horas desde o pouso).
    """
    out = {}
    for relic in (state or {}).get("relics") or []:
        if relic.get("village_id") and "lealdade" in (relic.get("locked_state") or ""):
            out[str(relic["village_id"])] = relic["locked_state"]
    for vid, record in (conquests or {}).items():
        if (record or {}).get("status") != "conquered":
            continue
        loyalty = _estimated_loyalty(record, now, regen)
        if loyalty is not None and loyalty < 100:
            out.setdefault(str(vid), "lealdade estimada %.0f (conquistada há %.0f h)" % (
                loyalty, (now - float(record["last_hit_timestamp"])) / 3600.0))
    return out


def _relic_table(state, now):
    """{id: relic do planejador} + motivo de cada relíquia que não se mexe."""
    out = {}
    for relic in (state or {}).get("relics") or []:
        rid = str(relic["id"])
        host = str(relic["village_id"]) if relic.get("village_id") else None
        entry = {"id": rid, "name": relic.get("name"), "range": relic.get("range"),
                 "quality": relic.get("quality"), "stats": _stats(relic), "host": host,
                 "state": relic.get("state") or R.relic_state(relic), "inactive": False,
                 "fixed": None}
        if entry["state"] == "inactive":
            entry["inactive"] = True
            entry["fixed"] = "inativa até %s" % time.strftime(
                "%d/%m %H:%M", time.localtime(relic.get("inactive_until_at") or now))
        elif relic.get("trade_offer_id"):
            entry["fixed"] = "em oferta de troca"
        elif host and (relic.get("removable_at") or 0) > now:
            entry["fixed"] = "removível só a partir de %s" % time.strftime(
                "%d/%m %H:%M", time.localtime(relic["removable_at"]))
        elif host and relic.get("locked_state"):
            entry["fixed"] = relic["locked_state"]
        out[rid] = entry
    return out


def _label(vid, labels):
    return (labels or {}).get(str(vid)) or str(vid)


def plan(state, coords, inputs, now=None, low_loyalty=None, labels=None,
         min_gain=MIN_GAIN, max_steps=MAX_STEPS):
    """
    O plano em dry-run. `coords` = aldeias da conta (só elas cobrem e só elas
    hospedam); `inputs` = `village_inputs`. Devolve um dict serializável.
    """
    now = now or time.time()
    low_loyalty = low_loyalty or {}
    relics = _relic_table(state, now)
    keys = sorted({k for r in relics.values() for k, _ in r["stats"]})
    specs = {k: classify(k) for k in keys}
    rates, reasons = {}, {}
    for vid in coords:
        vid = str(vid)
        for key in keys:
            rate, why = attribute_rate(specs[key], inputs.get(vid))
            if rate > 0:
                rates.setdefault(vid, {})[key] = rate
            else:
                reasons.setdefault(key, {}).setdefault(why, []).append(vid)
    model = Model(coords, rates)

    slots = (state or {}).get("slots") or {}
    can_equip = (state or {}).get("can_equip")
    active = [r for r in relics.values() if r["host"] and not r["inactive"]]
    slot_total = slots.get("total") if slots.get("total") is not None else len(active)
    if can_equip is False:
        slot_total = min(slot_total, len(active))

    current = {rid: r["host"] for rid, r in relics.items()}
    occupied_fixed = {r["host"] for r in relics.values() if r["host"] and r["fixed"]}
    hosts = sorted(v for v in model.coords if v not in low_loyalty and v not in occupied_fixed)
    host_set = set(hosts)
    movable = {rid for rid, r in relics.items() if not r["fixed"] and not r["inactive"]}

    def equipped(alloc):
        return sum(1 for rid, h in alloc.items() if h and not relics[rid]["inactive"])

    def free_hosts(alloc):
        taken = {h for h in alloc.values() if h}
        return [h for h in hosts if h not in taken]

    def candidates(alloc, touched):
        free = free_hosts(alloc)
        room = equipped(alloc) < slot_total
        parked = [rid for rid in movable if alloc[rid] is None and rid not in touched]
        placed = [rid for rid in movable if alloc[rid] is not None and rid not in touched]
        for rid in parked:
            if room:
                for h in free:
                    yield ("equip", (rid,), {rid: h})
        for rid in placed:
            for h in free:
                yield ("move", (rid,), {rid: h})
        if not room:
            for out_id in placed:
                for in_id in parked:
                    for h in free + ([alloc[out_id]] if alloc[out_id] in host_set else []):
                        yield ("replace", (out_id, in_id), {out_id: None, in_id: h})
        for i, a in enumerate(placed):
            for b in placed[i + 1:]:
                if alloc[a] in host_set and alloc[b] in host_set:
                    yield ("swap", (a, b), {a: alloc[b], b: alloc[a]})

    alloc = dict(current)
    base_value = model.value(alloc, relics)
    value_now = base_value
    touched, moves = set(), []
    for _ in range(max_steps):
        best = None
        for action, ids, change in candidates(alloc, touched):
            trial = dict(alloc)
            trial.update(change)
            gain = model.value(trial, relics) - value_now
            if best is None or gain > best[0] + 1e-9:
                best = (gain, action, ids, change, trial)
        if best is None or best[0] < min_gain:
            break
        gain, action, ids, change, trial = best
        moves.append(_describe(action, ids, change, alloc, relics, gain, labels))
        alloc, value_now = trial, value_now + gain
        touched.update(ids)

    # §8.78: o ganho de cada passo SOZINHO, sobre a alocação atual. O do plano
    # é encadeado (o passo 2 parte do que o passo 1 fez) e é o executor quem
    # escolhe a ordem: "equipar a parada" primeiro, mesmo que o plano a ponha
    # depois de um "mover". None = o passo não é possível sem outro antes
    # (a anfitriã só fica livre depois de um mover, ou não há vaga).
    for move in moves:
        trial = dict(current)
        trial.update(move["to"])
        taken = [h for h in trial.values() if h]
        fits = len(taken) == len(set(taken)) and equipped(trial) <= slot_total
        fits = fits and all(h is None or h in host_set for h in move["to"].values())
        move["gain_alone_h"] = (round(model.value(trial, relics) - base_value, 1)
                                if fits else None)
        move["value_before_h"] = round(sum(
            model.value(current, relics) - model.value(dict(current, **{i: None}), relics)
            for i in move["relic_ids"] if current.get(i)), 1)

    report = []
    for rid, r in sorted(relics.items(), key=lambda kv: (kv[1]["host"] is None, kv[1]["name"] or "")):
        without = dict(current)
        without[rid] = None
        here = model.value(current, relics) - model.value(without, relics) if r["host"] else 0.0
        best_hosts = []
        if not r["inactive"]:
            for h in hosts:
                if h != r["host"] and any(o == h for o_id, o in current.items() if o_id != rid):
                    continue
                trial = dict(without)
                trial[rid] = h
                best_hosts.append((model.value(trial, relics) - model.value(without, relics), h))
            best_hosts.sort(reverse=True)
        report.append({
            "id": rid, "name": r["name"], "quality": r["quality"], "range": r["range"],
            "state": r["state"], "host": r["host"], "target_host": alloc.get(rid),
            "fixed": r["fixed"], "value_here": round(here, 1),
            "best_hosts": [{"vid": h, "label": _label(h, labels), "value": round(v, 1)}
                           for v, h in best_hosts[:3]],
            "stats": [{"key": k, "value": v, "kind": specs[k]["kind"],
                       "valued_in": sum(1 for vr in rates.values() if k in vr)}
                      for k, v in r["stats"]],
        })

    attr = {}
    for key in keys:
        valued = {vid: round(vr[key], 2) for vid, vr in rates.items() if key in vr}
        attr[key] = {"kind": specs[key]["kind"], "villages_valued": len(valued),
                     "max_per_pct": max(valued.values()) if valued else 0.0,
                     "zero_reasons": {why: len(v) for why, v in (reasons.get(key) or {}).items()}}

    missing = {vid: e["missing"] for vid, e in (inputs or {}).items() if e.get("missing")}
    summary = summarize(moves, value_now - base_value)
    return {
        "computed_at": int(now), "dry_run": True,
        "state_fetched_at": (state or {}).get("fetched_at"),
        "slots": {"total": slot_total, "used_now": equipped(current), "used_after": equipped(alloc)},
        "value_now": round(base_value, 1), "value_after": round(value_now, 1),
        "gain": round(value_now - base_value, 1),
        "moves": moves, "summary": summary,
        "target": {rid: h for rid, h in alloc.items() if h and not relics[rid]["inactive"]},
        "relics": report, "attributes": attr,
        "rates": {vid: {k: round(v, 2) for k, v in vr.items()} for vid, vr in sorted(rates.items())},
        "low_loyalty": low_loyalty, "missing": missing,
        "hosts_eligible": len(hosts),
    }


def _describe(action, ids, change, alloc, relics, gain, labels):
    names = [relics[i]["name"] for i in ids]
    if action == "equip":
        text = "equipar %s em %s" % (names[0], _label(change[ids[0]], labels))
    elif action == "move":
        text = "mover %s de %s para %s" % (names[0], _label(alloc[ids[0]], labels),
                                         _label(change[ids[0]], labels))
    elif action == "replace":
        text = "tirar %s de %s e equipar %s em %s" % (
            names[0], _label(alloc[ids[0]], labels), names[1], _label(change[ids[1]], labels))
    else:
        text = "trocar %s (%s) e %s (%s) de lugar" % (
            names[0], _label(alloc[ids[0]], labels), names[1], _label(alloc[ids[1]], labels))
    return {"action": action, "relic_ids": list(ids), "names": names,
            "from": {i: alloc.get(i) for i in ids}, "to": {i: change.get(i) for i in ids},
            "gain_h": round(gain, 1), "text": text}


def summarize(moves, gain):
    if not moves:
        return "nada a fazer"
    return "faria: %s (total +%.0f/h)" % (
        "; ".join("%s (+%.0f/h)" % (m["text"], m["gain_h"]) for m in moves), gain)


# -- carga do disco ------------------------------------------------------------

def load_managed(managed_dir):
    out = {}
    for path in glob.glob(os.path.join(managed_dir, "*.json")):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                out[os.path.basename(path)[:-5]] = json.load(fh)
        except (OSError, ValueError):
            continue
    return out


def load_conquests(conquest_dir):
    out = {}
    for path in glob.glob(os.path.join(conquest_dir, "*.json")):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                out[os.path.basename(path)[:-5]] = json.load(fh)
        except (OSError, ValueError):
            continue
    return out


def world_speed(world_config):
    try:
        speed = float((world_config or {}).get("speed"))
    except (TypeError, ValueError):
        return None
    return speed if speed > 0 else None


def world_base_production(world_config):
    """`<base_production>` do cache do mundo (§8.78), ou None."""
    try:
        base = float((world_config or {}).get("base_production"))
    except (TypeError, ValueError):
        return None
    return base if base > 0 else None


def plan_from_disk(state, coords, root=".", now=None, speed=None, regen=1.0, labels=None,
                   base_production=None):
    """O plano a partir dos arquivos de `root` (cache/...). 0 GET."""
    now = now or time.time()
    managed = load_managed(os.path.join(root, "cache", "managed"))
    reporter = read_reporter(os.path.join(root, "cache", "logs"), now)
    # Ilegível vira 0 nobre: `sources.schedules_read` separa "não li" de
    # "nenhum nobre saiu" (6º padrão: o valor de falha não se disfarça).
    schedules_read = True
    try:
        with open(os.path.join(root, "cache", "hunter", "schedules.json"), "r",
                  encoding="utf-8") as fh:
            schedules = json.load(fh)
    except (OSError, ValueError):
        schedules, schedules_read = {}, False
    nobles = noble_departures(schedules, now)
    inputs = village_inputs(coords, managed, reporter, nobles, now, speed=speed,
                            unit_costs=(state or {}).get("unit_costs"),
                            village_prod=(state or {}).get("village_prod"),
                            base_production=base_production)
    conquests = load_conquests(os.path.join(root, "cache", "conquest"))
    low = low_loyalty_hosts(state, conquests, now, regen=regen)
    if labels is None:
        labels = {vid: "%s (%s)" % (d.get("name"), vid) for vid, d in managed.items() if d.get("name")}
    result = plan(state, coords, inputs, now=now, low_loyalty=low, labels=labels)
    # §8.79: a mesma conta, sobre o estado em que a fusão já aconteceu.
    # Falha aqui não derruba o plano de equipar/mover (Fase 3): fica sem fusão.
    try:
        fused = F.fusions(state, result, lambda hyp: plan(hyp, coords, inputs, now=now,
                                                          low_loyalty=low, labels=labels))
        result["fusions"] = fused["fusions"]
        result["fusion_info"] = {k: fused[k] for k in ("excluded", "table", "materials")}
    except Exception as exc:  # noqa: BLE001 -- dry-run nunca derruba o plano
        result["fusions"] = []
        result["fusion_info"] = {"error": repr(exc)}
    result["inputs"] = {vid: _inputs_summary(e) for vid, e in sorted(inputs.items())}
    result["sources"] = {
        "reporter_events": {k: len(v) for k, v in reporter.items()},
        "nobles_sent": sum(nobles.values()),
        "schedules_read": schedules_read,
        "world_speed": speed,
        "base_production": base_production,
        "unit_costs": "tela de recrutamento" if (state or {}).get("unit_costs") else
                      "tabela padrão (não medida)",
    }
    return result


def _inputs_summary(entry):
    out = {
        "base_prod_h": {r: round(v) for r, v in (entry.get("base_prod_h") or {}).items()},
        "cap_frac": {r: round(v, 2) for r, v in (entry.get("cap_frac") or {}).items()},
        "storage_reads": entry.get("storage_reads", 0),
        "recruit_h": {b: round(v) for b, v in entry.get("recruit_h", {}).items()},
        "recruit_busy": {b: round(v, 2) for b, v in entry.get("recruit_busy", {}).items()},
        "build_busy": round(entry.get("build_busy") or 0.0, 2),
        "nobles": entry.get("nobles", 0),
    }
    if entry.get("prod_ratio"):
        out["prod_ratio"] = entry["prod_ratio"]
    if entry.get("missing"):
        out["missing"] = entry["missing"]
    return out
