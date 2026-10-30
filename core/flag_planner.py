"""
Bandeiras por valor (§8.82): lógica pura, sem rede e sem POST.

Troca a ordem fixa de `DefenceManager.preferred_flags()` (§4.6) pelo valor em
recurso/h de cada bandeira em cada aldeia, com o mesmo modelo do planejador de
relíquias (`core/relic_planner.py`): as mesmas medições em disco, a mesma
`attribute_rate`, e "não sei" separado de "vale zero".

O que cada tipo afeta, de onde vem o número e como soma (19º padrão: medido,
não lido do texto):

- **Percentual por nível**: o `title` de cada `flag_box_T_L` da tela de
  bandeiras (`parse_flag_effects`, lido a cada leitura do bot; `FLAG_PCT` é a
  captura do br143 de 08/10, só para quando a tela não traz a tabela).
- **1, produção de recursos**: soma ao percentual, como relíquia e item.
  Medido em 30/10 sobre `village_prod` x fórmula da mina em 36 aldeias com a
  bandeira (níveis 1, 2, 3, 4, 5 e 7): produção lida = base x (1 + (itens +
  paladino + relíquia + bandeira + modificação)/100), resíduo 0,0. A leitura
  multiplicativa daria 1,508 na BBM 030 (+16%), contra 1,46 lido. Valor =
  a taxa de produção da relíquia, nos três recursos (armazém cheio censura).
- **2, velocidade de recrutamento**: aditiva com relíquia e modificação
  (§8.80, BBM 001, até a 6ª casa). Só vale com a fila como gargalo, a mesma
  regra da relíquia; recrutamento cedido ao gerente (§8.68) não deixa linha
  `TWB_RECRUIT`, e aí o valor é DESCONHECIDO, não zero.
- **6, população**: `pop_max` = piso(fazenda x (1 + %/100)). Medido em 30/10
  na BBM 062 (fazenda 17, +6%): 3.227 = piso(3.045 x 1,06); 3.045 é a fazenda
  17 sem bandeira (BBM 055, sombra do `game_data`). Só vale com a aldeia no
  teto de população; aí a tropa a mais rende o saque por população da aldeia.
- **7, custo de moeda**: custo = nominal x (1 - d) (§8.80, BBM 002). Quanto a
  aldeia cunha por hora o bot não registra (a sessão automática cunha sem
  contar), então o valor é DESCONHECIDO e a bandeira de moeda fica onde está.
- **8, capacidade de saque**: farm e coleta. Farm: a carga mandada
  (`TWB_FARM`) vezes a fração dos relatórios que voltaram cheios (só esses
  carregariam mais; os outros não estão limitados pela carga). Coleta: o JS
  do jogo (`Scavenging.dd2ec0.js`) fixa a carga no envio por
  `calcMaxLoot(unidades, village.unit_carry_factor)`. Se a bandeira entra
  nesse fator é o que `HAUL_SCAVENGE` guarda, e as coletas registradas
  (`TWB_GATHER_SQUAD`, saque lido / carga nominal) medem sozinhas. E o tempo
  da coleta cresce com a carga (expoente 0,45 sobre carga², ver
  `scavenge_elasticity`): +8% de carga rende bem menos que +8% por hora.
- **3 e 5** (ataque, sorte): manuais, o bot nunca põe nem tira.
  **4** (defesa): só pelo caminho de ataque; fora dele vale 0.

O plano (`plan`): a partir do que está equipado e do inventário que SOBRA
(bandeira equipada sai do `setFlagCounts`, §8.11), dá cada bandeira que sobra
à aldeia onde ela rende mais, uma troca por aldeia, a de maior ganho primeiro.
A bandeira que a aldeia larga volta à sobra e pode ir para outra. Aldeia cuja
bandeira atual tem valor desconhecido não entra.

Quem age é o `DefenceManager`, só no passo da própria aldeia, com o gate de
frescor e os freios de `evaluate` (§8.11 e §8.78).
"""
import ast
import glob
import json
import math
import os
import re
import time

from core import relic_planner as RP
from core.templates import UNIT_CARRY, UNIT_POP

# `title` de `flag_box_T_L` na tela de bandeiras do br143, captura de 08/10
# (cache/feature_map/free_20261008_2315/pages/flags.html.gz). Percentual
# positivo: o sinal de "-10% nos custos de moedas" é o sentido do efeito.
FLAG_PCT = {
    1: {1: 4, 2: 6, 3: 8, 4: 10, 5: 12, 6: 14, 7: 16, 8: 17, 9: 18},
    2: {1: 6, 2: 8, 3: 10, 4: 12, 5: 14, 6: 16, 7: 18, 8: 19, 9: 20},
    3: {1: 2, 2: 3, 3: 4, 4: 5, 5: 6, 6: 7, 7: 8, 8: 9, 9: 10},
    4: {1: 2, 2: 3, 3: 4, 4: 5, 5: 6, 6: 7, 7: 8, 8: 9, 9: 10},
    5: {1: 6, 2: 8, 3: 10, 4: 12, 5: 14, 6: 16, 7: 18, 8: 19, 9: 20},
    6: {1: 2, 2: 3, 3: 4, 4: 5, 5: 6, 6: 7, 7: 8, 8: 9, 9: 10},
    7: {1: 10, 2: 12, 3: 14, 4: 16, 5: 18, 6: 20, 7: 22, 8: 23, 9: 24},
    8: {1: 2, 2: 3, 3: 4, 4: 5, 5: 6, 6: 7, 7: 8, 8: 9, 9: 10},
}
MANUAL_TYPES = (3, 5)
DEFENCE_TYPE = 4
COIN_TYPE = 7

# A bandeira de saque aumenta a coleta QUE O BOT MANDA? Metade medida em
# 30/10: com a 8/7 equipada à mão na BBM 005, a tela de coleta leu
# `unit_carry_factor` 1,08 (1 em todas as leituras sem a bandeira), então o
# jogo aplica a bandeira à carga da coleta. A outra metade não: o JS manda
# `carry_max` = carga x fator, e o bot manda a carga nominal
# (`TroopManager.gather`). Se o servidor recalcula, o bot ganha os 8%; se
# confia no `carry_max` do cliente, não. Fica None até uma coleta do bot pagar
# a mais (`haul_scavenge_measured`, sobre as linhas `TWB_GATHER_SQUAD`).
HAUL_SCAVENGE = None

POP_CAPPED = 0.98
SCAV_MIN_SPAN = 6 * 3600
FARM_WINDOW = 7 * 86400
SCAV_WINDOW = 7 * 86400
FARM_FULL_MIN_REPORTS = 5
FULL_RETURN = 0.99

_REPORTER_RE = re.compile(r"^(\d+) - (\d+) - (TWB_\w+) - (.*)$")
_FARM_RE = re.compile(r"Attacking (\d+) -> (\d+) \((\{.*\})\)")
_FLAG_BOX_RE = re.compile(
    r'id="flag_box_(\d+)_(\d+)"[^>]*?title="([^"]*)"')
_PCT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")


def parse_flag_effects(html):
    """{tipo: {nível: %}} dos `title` da tela de bandeiras, ou {} sem tabela."""
    out = {}
    for t, lvl, title in _FLAG_BOX_RE.findall(html or ""):
        m = _PCT_RE.search(title)
        if m:
            out.setdefault(int(t), {})[int(lvl)] = float(m.group(1).replace(",", "."))
    return out


def flag_pct(effects, flag_type, level):
    """Percentual da bandeira (tipo, nível): da tela, senão de `FLAG_PCT`."""
    table = (effects or {}).get(int(flag_type)) or FLAG_PCT.get(int(flag_type)) or {}
    return float(table.get(int(level), 0.0) or 0.0)


# -- coleta ---------------------------------------------------------------------

def scavenge_duration(carry, opt):
    """
    Segundos da coleta com carga `carry` (efetiva), pela fórmula do
    `Scavenging.dd2ec0.js`: (pow(t * 100*lf * t * lf, exp) + inicial) * fator.
    """
    lf = float(opt.get("loot_factor") or 0)
    exp = float(opt.get("duration_exponent") or 0.45)
    initial = float(opt.get("duration_initial_seconds") or 1800)
    factor = float(opt.get("duration_factor") or 1)
    return (math.pow(carry * 100 * lf * carry * lf, exp) + initial) * factor


def scavenge_elasticity(carry, opt, wait=0.0):
    """
    d ln(saque/h) / d ln(carga) de uma opção que o bot reenvia `wait` s depois
    de voltar: 1 - 2*exp*P/(D + wait), P = a parte da duração que cresce com a
    carga. +x% de carga vira ~elasticidade*x% de saque por hora.
    """
    exp = float(opt.get("duration_exponent") or 0.45)
    factor = float(opt.get("duration_factor") or 1)
    initial = float(opt.get("duration_initial_seconds") or 1800)
    total = scavenge_duration(carry, opt)
    power = total - initial * factor
    return max(0.0, 1.0 - 2 * exp * power / (total + max(0.0, wait)))


def squad_event(village_id, option_id, squad, opt, carry_factor):
    """
    Mensagem `TWB_GATHER_SQUAD` de uma coleta em andamento, lida da tela que o
    bot já baixou (0 GET): carga nominal pelas unidades (`UNIT_CARRY`), saque
    que o servidor promete (`loot_res`) e o fator da aldeia. None se faltar
    campo. JSON numa linha: o reporter é texto.
    """
    try:
        units = {u: int(n) for u, n in (squad.get("unit_counts") or {}).items() if int(n)}
        loot = sum(int(v) for v in (squad.get("loot_res") or {}).values())
        nominal = sum(UNIT_CARRY.get(u, 0) * n for u, n in units.items())
        payload = {
            "squad": int(squad["unit_id"]), "option": int(option_id),
            "return": int(squad["return_time"]), "carry_max": int(squad.get("carry_max") or 0),
            "nominal": nominal, "loot": loot,
            "lf": float(opt.get("loot_factor") or 0),
            "exp": float(opt.get("duration_exponent") or 0.45),
            "init": float(opt.get("duration_initial_seconds") or 1800),
            "dfac": float(opt.get("duration_factor") or 1),
            "factor": float(carry_factor) if carry_factor is not None else None,
            "premium": bool(squad.get("is_premium")),
        }
    except (KeyError, TypeError, ValueError):
        return None
    return json.dumps(payload, sort_keys=True)


def read_events(log_dir, now, window=max(FARM_WINDOW, SCAV_WINDOW)):
    """
    `TWB_FARM` e `TWB_GATHER_SQUAD` do reporter dentro de `window`:
    {"farm": [(ts, vid, carry)], "squads": {squad_id: (ts_visto, vid, dict)},
     "squads_since": primeiro registro de coleta (o instrumento começou ali)}.
    """
    since = now - window
    out = {"farm": [], "squads": {}, "squads_since": None}
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
                if event == "TWB_FARM":
                    f = _FARM_RE.match(msg)
                    if not f:
                        continue
                    try:
                        units = ast.literal_eval(f.group(3))
                    except (ValueError, SyntaxError):
                        continue
                    carry = sum(UNIT_CARRY.get(u, 0) * int(n) for u, n in units.items())
                    out["farm"].append((ts, vid, carry))
                elif event == "TWB_GATHER_SQUAD":
                    try:
                        sq = json.loads(msg)
                    except ValueError:
                        continue
                    if out["squads_since"] is None or ts < out["squads_since"]:
                        out["squads_since"] = ts
                    out["squads"].setdefault(sq.get("squad"), (ts, vid, sq))
    return out


def haul_scavenge_measured(squads):
    """
    True se alguma coleta registrada voltou com saque acima da carga nominal
    (fator > 1); senão o `HAUL_SCAVENGE` medido à mão. Coletas com fator 1 não
    refutam nada: a aldeia pode não ter a bandeira.
    """
    for _, _, sq in (squads or {}).values():
        nominal, lf = sq.get("nominal") or 0, sq.get("lf") or 0
        if nominal and lf and not sq.get("premium") and sq.get("loot", 0) > nominal * lf * 1.005:
            return True
    return HAUL_SCAVENGE


def farm_full_fraction(reports_dir):
    """
    ({origem: fração}, fração da conta) dos ataques com saque que voltaram
    cheios (saque >= 99% da carga dos sobreviventes). Só esses carregariam
    mais com a bandeira; o resto já voltou com tudo o que o alvo tinha.
    """
    per, total = {}, [0, 0]
    for path in glob.glob(os.path.join(reports_dir, "*.json")):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                rep = json.load(fh)
        except (OSError, ValueError):
            continue
        if rep.get("type") != "attack":
            continue
        extra = rep.get("extra") or {}
        loot = extra.get("loot") or {}
        if not loot:
            continue
        lost = extra.get("units_losses") or {}
        try:
            cap = sum((int(n) - int(lost.get(u, 0))) * UNIT_CARRY.get(u, 0)
                      for u, n in (extra.get("units_sent") or {}).items())
            got = sum(int(v) for v in loot.values())
        except (TypeError, ValueError):
            continue
        if cap <= 0:
            continue
        full = 1 if got >= cap * FULL_RETURN else 0
        acc = per.setdefault(str(rep.get("origin")), [0, 0])
        acc[0] += full
        acc[1] += 1
        total[0] += full
        total[1] += 1
    overall = total[0] / float(total[1]) if total[1] else None
    return {o: (f, n) for o, (f, n) in per.items()}, overall


def haul_inputs(vids, events, full, now, managed=None):
    """
    {vid: {"farm_carry_h", "farm_full", "scav_loot_h", "scav_rate_h",
    "scav_span_h", "troop_pop"}}: carga de farm por hora, fração cheia, saque
    da coleta por hora e o mesmo já multiplicado pela elasticidade.
    """
    per_origin, overall = full
    farm = {}
    for ts, vid, carry in events.get("farm") or []:
        if ts >= now - FARM_WINDOW:
            farm[vid] = farm.get(vid, 0) + carry
    squads = {}
    for ts, vid, sq in (events.get("squads") or {}).values():
        squads.setdefault(vid, []).append(sq)
    since = events.get("squads_since")
    span = max(0.0, now - max(since, now - SCAV_WINDOW)) if since else 0.0
    out = {}
    for vid in vids:
        vid = str(vid)
        f_n = per_origin.get(vid)
        if f_n and f_n[1] >= FARM_FULL_MIN_REPORTS:
            frac, frac_src = f_n[0] / float(f_n[1]), "relatórios desta aldeia (%d)" % f_n[1]
        else:
            frac, frac_src = overall, "relatórios da conta"
        entry = {"farm_carry_h": farm.get(vid, 0) / (FARM_WINDOW / 3600.0),
                 "farm_full": frac, "farm_full_source": frac_src,
                 "scav_span_h": span / 3600.0, "scav_loot_h": None, "scav_rate_h": None}
        if span >= SCAV_MIN_SPAN:
            loot = rate = 0.0
            by_opt = {}
            for sq in squads.get(vid) or []:
                by_opt.setdefault(sq["option"], []).append(sq)
            for opt_id, lst in by_opt.items():
                lst.sort(key=lambda s: s["return"])
                waits = []
                for prev, nxt in zip(lst, lst[1:]):
                    opt = {"loot_factor": nxt["lf"], "duration_exponent": nxt["exp"],
                           "duration_initial_seconds": nxt["init"], "duration_factor": nxt["dfac"]}
                    eff = nxt["loot"] / nxt["lf"] if nxt["lf"] else 0
                    start = nxt["return"] - scavenge_duration(eff, opt)
                    waits.append(max(0.0, start - prev["return"]))
                wait = sorted(waits)[len(waits) // 2] if waits else 0.0
                for sq in lst:
                    opt = {"loot_factor": sq["lf"], "duration_exponent": sq["exp"],
                           "duration_initial_seconds": sq["init"], "duration_factor": sq["dfac"]}
                    eff = sq["loot"] / sq["lf"] if sq["lf"] else 0
                    loot += sq["loot"]
                    rate += sq["loot"] * scavenge_elasticity(eff, opt, wait)
            entry["scav_loot_h"] = loot / (span / 3600.0)
            entry["scav_rate_h"] = rate / (span / 3600.0)
        troops = ((managed or {}).get(vid) or {}).get("troops") or {}
        entry["troop_pop"] = sum(UNIT_POP.get(u, 0) * int(n or 0) for u, n in troops.items()
                                 if u in UNIT_POP)
        out[vid] = entry
    return out


# -- valor ----------------------------------------------------------------------

def _free_fraction(inputs):
    cap = (inputs or {}).get("cap_frac") or {}
    return 1.0 - sum(cap.get(r, 0.0) for r in RP.RESOURCES) / len(RP.RESOURCES)


def flag_rate(flag_type, inputs, haul_scavenge=None):
    """
    (recurso/h por ponto percentual, motivo) da bandeira `flag_type` na aldeia.
    Taxa None = desconhecido (a aldeia não troca o que não se sabe quanto vale);
    0 com motivo = medido e vale zero.
    """
    inputs = inputs or {}
    flag_type = int(flag_type)
    if flag_type in MANUAL_TYPES:
        return None, "bandeira manual: o bot nunca põe nem tira"
    if flag_type == DEFENCE_TYPE:
        return 0.0, "defesa: só sob ataque, pelo caminho de defesa"
    if flag_type == COIN_TYPE:
        return None, "cunhagem: o bot não registra quanto cada aldeia cunha por hora"
    if flag_type == 1:
        if not inputs.get("base_prod_h"):
            return None, "produção desconhecida (%s)" % (inputs.get("base_source") or "sem nível de mina")
        rate, why = 0.0, []
        for res in RP.RESOURCES:
            r, w = RP.attribute_rate({"kind": "production", "resource": res}, inputs)
            rate += r
            if w:
                why.append(w)
        return rate, (None if rate else "; ".join(why))
    if flag_type == 2:
        # Cedido agora: as linhas antigas do bot não contam a fila do gerente,
        # então a ocupação medida seria só uma parte dela.
        if inputs.get("recruit_ceded"):
            return None, "recrutamento cedido ao gerente: a fila não é medida"
        rate, why = 0.0, []
        for building in ("barracks", "stable", "garage"):
            r, w = RP.attribute_rate({"kind": "recruit_speed", "building": building}, inputs)
            rate += r
            if w and building in (inputs.get("recruit_busy") or {}):
                why.append(w)
        return rate, (None if rate else ("; ".join(why) or "o bot não recrutou em 7 dias"))
    if flag_type == 8:
        return _haul_rate(inputs, haul_scavenge)
    if flag_type == 6:
        return _pop_rate(inputs, haul_scavenge)
    return None, "tipo de bandeira desconhecido"


def _haul_parts(inputs, haul_scavenge):
    """(saque/h por ponto do farm, da coleta ou None, motivos)."""
    why = []
    full = inputs.get("farm_full")
    carry_h = inputs.get("farm_carry_h") or 0.0
    farm = carry_h * (full or 0.0) / 100.0
    if not carry_h:
        why.append("o bot não farmou desta aldeia em 7 dias")
    elif full is None:
        why.append("nenhum relatório de farm com saque")
    scav = None
    if haul_scavenge is False:
        why.append("medido: a bandeira não muda a coleta")
        scav = 0.0
    elif haul_scavenge is None:
        why.append("coleta: não medido se a bandeira de saque entra nela")
    elif inputs.get("scav_rate_h") is None:
        why.append("coleta: menos de %d h de registro" % (SCAV_MIN_SPAN // 3600))
    else:
        scav = inputs["scav_rate_h"] / 100.0
    return farm, scav, why


def _haul_rate(inputs, haul_scavenge):
    farm, scav, why = _haul_parts(inputs, haul_scavenge)
    if scav is None:
        # Só o farm seria um piso, e trocar a bandeira por um piso tira
        # bandeira de quem talvez estivesse certo: desconhecido.
        return None, "; ".join(why)
    rate = (farm + scav) * _free_fraction(inputs)
    return rate, (None if rate else "; ".join(why) or "saque sem efeito medido")


def _pop_rate(inputs, haul_scavenge):
    pop, pop_max = inputs.get("pop"), inputs.get("pop_max")
    if not pop or not pop_max:
        return None, "população da aldeia ainda não lida"
    if pop < POP_CAPPED * pop_max:
        return 0.0, "fazenda com folga (%d de %d)" % (pop, pop_max)
    troop_pop = inputs.get("troop_pop") or 0
    _, scav, _ = _haul_parts(inputs, haul_scavenge)
    haul_h = (inputs.get("farm_carry_h") or 0.0) * (inputs.get("farm_full") or 0.0)
    if scav is not None:
        haul_h += inputs.get("scav_rate_h") or 0.0
    if not troop_pop or not haul_h:
        return None, "no teto de população, mas sem saque por população medido"
    base_max = inputs.get("pop_max_base") or pop_max
    # Um ponto = base_max/100 de população; a tropa nova rende o saque médio
    # por população da aldeia (estimativa: o bot preenche com o mesmo modelo).
    return haul_h / troop_pop * base_max / 100.0 * _free_fraction(inputs), None


def flag_value(flag, inputs, effects=None, haul_scavenge=None):
    """(recurso/h, motivo) da bandeira [tipo, nível] na aldeia; None = não sei."""
    if not flag:
        return 0.0, "sem bandeira"
    rate, why = flag_rate(flag[0], inputs, haul_scavenge)
    if rate is None:
        return None, why
    return rate * flag_pct(effects, flag[0], flag[1]), why


# -- plano ----------------------------------------------------------------------

def plan(villages, supply, inputs, effects=None, haul_scavenge=None, min_gain=1.0, labels=None):
    """
    `villages` = {vid: {"current": [t, l] | None, "can_change": bool,
    "under_attack": bool}}; `supply` = {tipo: {nível: quantidade}} que SOBRA.
    Devolve {"steps": [...], "values": {vid: {...}}}.
    """
    supply = {int(t): {int(l): int(n) for l, n in (lv or {}).items() if int(n) > 0}
              for t, lv in (supply or {}).items()}
    values = {}
    current = {}
    for vid, v in (villages or {}).items():
        vid = str(vid)
        cur = list(v.get("current") or []) or None
        current[vid] = cur
        val, why = flag_value(cur, inputs.get(vid), effects, haul_scavenge)
        rates = {}
        for t in (1, 2, 6, 7, 8):
            r, w = flag_rate(t, inputs.get(vid), haul_scavenge)
            rates[t] = {"rate": None if r is None else round(r, 2), "why": w}
        values[vid] = {"current": cur, "value": None if val is None else round(val, 1),
                       "why": why, "rates": rates}
    eligible = {vid for vid, v in (villages or {}).items()
                if v.get("can_change", True) and not v.get("under_attack")
                and (current[str(vid)] is None or current[str(vid)][0] not in MANUAL_TYPES)
                and values[str(vid)]["value"] is not None}
    eligible = {str(v) for v in eligible}
    steps = []
    while True:
        best = None
        for vid in sorted(eligible):
            here = values[vid]["value"] or 0.0
            for t, levels in supply.items():
                if t in MANUAL_TYPES or t == DEFENCE_TYPE:
                    continue
                for lvl, n in levels.items():
                    if n <= 0:
                        continue
                    if current[vid] and current[vid][0] == t and current[vid][1] >= lvl:
                        continue
                    val, _ = flag_value([t, lvl], inputs.get(vid), effects, haul_scavenge)
                    if val is None:
                        continue
                    gain = val - here
                    if best is None or gain > best[0] + 1e-9:
                        best = (gain, vid, t, lvl, val)
        if best is None or best[0] < min_gain:
            break
        gain, vid, t, lvl, val = best
        supply[t][lvl] -= 1
        old = current[vid]
        if old and old[0] not in MANUAL_TYPES:
            supply.setdefault(old[0], {})
            supply[old[0]][old[1]] = supply[old[0]].get(old[1], 0) + 1
        steps.append({
            "vid": vid, "label": (labels or {}).get(vid) or vid,
            "from": old, "to": [t, lvl],
            "value_before_h": round(values[vid]["value"] or 0.0, 1),
            "value_after_h": round(val, 1), "gain_h": round(gain, 1),
            "text": "%s: %s -> %s" % ((labels or {}).get(vid) or vid, _flag_text(old),
                                      _flag_text([t, lvl])),
        })
        eligible.discard(vid)
    return {"steps": steps, "values": values}


def _flag_text(flag):
    return "tipo %s nível %s" % tuple(flag[:2]) if flag else "nenhuma"


def step_key(step):
    return "%s|%s>%s" % (step.get("vid"), step.get("from"), step.get("to"))


# -- freios ---------------------------------------------------------------------

DEFAULTS = {
    # "off": só a ordem fixa (§4.6). "dry_run": a ordem fixa age e o plano por
    # valor só é calculado, logado e mostrado. "on": o plano por valor age.
    "mode": "dry_run",
    "min_gain_h": 50.0,
    "min_gain_pct": 10.0,
    "stable_reads": 2,
    "max_changes_per_day": 3,
    "undo_block_h": 48.0,
}


def settings(config):
    """`flag_value.*` com os padrões acima; valor ilegível cai no padrão."""
    raw = (config or {}).get("flag_value") or {}
    out = {}
    for key, default in DEFAULTS.items():
        value = raw.get(key, default)
        try:
            out[key] = type(default)(value)
        except (TypeError, ValueError):
            out[key] = default
    if out["mode"] not in ("off", "dry_run", "on"):
        out["mode"] = DEFAULTS["mode"]
    return out


def server_day(now):
    """Dia local do bot, que roda no fuso do br143 (-03)."""
    return time.strftime("%Y-%m-%d", time.localtime(now))


def note_read(exec_state, vid, step, now):
    """Conta em quantas avaliações seguidas da aldeia o mesmo passo apareceu."""
    streaks = exec_state.setdefault("streak", {})
    key = step_key(step) if step else None
    old = streaks.get(str(vid)) or {}
    if key is None:
        streaks.pop(str(vid), None)
        return 0
    count = int(old.get("count", 0)) + 1 if old.get("key") == key else 1
    streaks[str(vid)] = {"key": key, "count": count, "last_at": int(now),
                         "first_at": old.get("first_at", int(now)) if old.get("key") == key else int(now)}
    return count


def evaluate(step, exec_state, cfg, now):
    """(pode sair?, motivo) do passo da aldeia, pelos freios."""
    if not step:
        return False, "nada a fazer"
    if step["gain_h"] < cfg["min_gain_h"]:
        return False, "ganho %.0f/h abaixo do piso de %.0f/h" % (step["gain_h"], cfg["min_gain_h"])
    before = step.get("value_before_h") or 0.0
    if before > 0 and step["gain_h"] < before * cfg["min_gain_pct"] / 100.0:
        return False, "ganho %.0f/h abaixo de %.0f%% do que a atual rende (%.0f/h)" % (
            step["gain_h"], cfg["min_gain_pct"], before)
    seen = int(((exec_state.get("streak") or {}).get(str(step["vid"])) or {}).get("count", 0))
    if seen < cfg["stable_reads"]:
        return False, "visto em %d de %d avaliações seguidas" % (seen, cfg["stable_reads"])
    day = server_day(now)
    done = int(((exec_state.get("days") or {}).get(day) or {}).get("changes", 0))
    if done >= cfg["max_changes_per_day"]:
        return False, "teto do dia: %d de %d trocas" % (done, cfg["max_changes_per_day"])
    for h in reversed(exec_state.get("history") or []):
        if str(h.get("vid")) == str(step["vid"]) and h.get("ok"):
            if now - float(h.get("at") or 0) < cfg["undo_block_h"] * 3600:
                return False, "o bot trocou a bandeira desta aldeia há %.1f h" % (
                    (now - float(h["at"])) / 3600.0)
            break
    return True, "liberado"


def record(exec_state, step, ok, detail, now):
    """Grava a troca (ou a recusa) no histórico; só a feita conta no teto."""
    if ok:
        day = server_day(now)
        days = exec_state.setdefault("days", {})
        days.setdefault(day, {"changes": 0})["changes"] += 1
        for old in sorted(days)[:-7]:
            days.pop(old, None)
        exec_state.setdefault("streak", {}).pop(str(step["vid"]), None)
    hist = exec_state.setdefault("history", [])
    hist.append({"at": int(now), "vid": str(step["vid"]), "from": step.get("from"),
                 "to": step.get("to"), "gain_h": step.get("gain_h"), "ok": bool(ok),
                 "detail": detail})
    del hist[:-50]


# -- carga do disco -------------------------------------------------------------

class InputCache:
    """
    As entradas pesadas (reporter, relatórios, cache/managed) valem por
    `ttl` s: mudam devagar, e o plano é refeito por aldeia que roda. Uma
    instância por processo, compartilhada de propósito (é o ponto dela).
    """

    def __init__(self, ttl=1200):
        self.ttl = ttl
        self.at = None
        self.data = None

    def get(self, root, now, world=None):
        if self.data is not None and self.at is not None and 0 <= now - self.at < self.ttl:
            return self.data
        speed, base_production = RP.world_speed(world), RP.world_base_production(world)
        try:
            with open(os.path.join(root, "cache", "relics.json"), "r", encoding="utf-8") as fh:
                relics = json.load(fh) or {}
        except (OSError, ValueError):
            relics = {}
        unit_costs, village_prod = relics.get("unit_costs"), relics.get("village_prod")
        managed = RP.load_managed(os.path.join(root, "cache", "managed"))
        reporter = RP.read_reporter(os.path.join(root, "cache", "logs"), now)
        events = read_events(os.path.join(root, "cache", "logs"), now)
        full = farm_full_fraction(os.path.join(root, "cache", "reports"))
        vids = sorted(managed)
        inputs = RP.village_inputs(vids, managed, reporter, {}, now, speed=speed,
                                   unit_costs=unit_costs, village_prod=village_prod,
                                   base_production=base_production)
        haul = haul_inputs(vids, events, full, now, managed)
        for vid in vids:
            entry = inputs.setdefault(vid, {})
            entry.update(haul.get(vid) or {})
            data = managed.get(vid) or {}
            pop = data.get("population") or {}
            entry["pop"], entry["pop_max"] = pop.get("used"), pop.get("max")
            entry["pop_max_base"] = pop_base(pop.get("max"),
                                             ((data.get("flags") or {}).get("current_flag")))
            cession = data.get("account_manager_cession") or {}
            entry["recruit_ceded"] = bool((cession.get("recruitment") or {}).get("ceded"))
        self.data = {"managed": managed, "inputs": inputs,
                     "haul_scavenge": haul_scavenge_measured(events.get("squads")),
                     "squads": len(events.get("squads") or {}),
                     "squads_since": events.get("squads_since")}
        self.at = now
        return self.data


INPUTS = InputCache()


def village_table(managed, own_vid=None, own=None):
    """{vid: {"current", "can_change", "under_attack"}} do cache/managed."""
    out = {}
    for vid, data in (managed or {}).items():
        flags = (data or {}).get("flags") or {}
        if not flags.get("flag_state_confirmed"):
            continue
        out[str(vid)] = {"current": flags.get("current_flag") or None,
                         "can_change": bool(flags.get("can_change_flag", True)),
                         "under_attack": bool((data or {}).get("under_attack"))}
    if own_vid is not None and own:
        out[str(own_vid)] = dict(out.get(str(own_vid)) or {}, **own)
    return out


def plan_for_village(vid, own, supply, effects=None, root=".", now=None, world=None,
                     cache=None, labels=None, vids=None):
    """
    O plano da conta visto pela aldeia `vid`, que acabou de ler o inventário:
    `own` = {"current", "can_change", "under_attack", "pop", "pop_max"} dela,
    fresco; as outras vêm do cache/managed. Devolve o plano, o passo desta
    aldeia (ou None) e o valor da bandeira dela.
    """
    now = now or time.time()
    data = (cache or INPUTS).get(root, now, world)
    inputs = dict(data["inputs"])
    mine = dict(inputs.get(str(vid)) or {})
    if own.get("pop_max"):
        mine["pop"], mine["pop_max"] = own.get("pop"), own.get("pop_max")
        mine["pop_max_base"] = pop_base(own.get("pop_max"), own.get("current"), effects)
    inputs[str(vid)] = mine
    table = village_table(data["managed"], vid, {k: own.get(k) for k in
                                                 ("current", "can_change", "under_attack")})
    if vids is not None:
        # Só aldeias da conta: o cache/managed de uma aldeia perdida fica no
        # disco, e no plano ela "reservaria" a bandeira que sobra.
        keep = {str(v) for v in vids} | {str(vid)}
        table = {v: t for v, t in table.items() if v in keep}
    if labels is None:
        labels = {v: "%s (%s)" % (m.get("name"), v) for v, m in data["managed"].items()
                  if m.get("name")}
    result = plan(table, supply, inputs, effects, data["haul_scavenge"], labels=labels)
    result["step"] = next((s for s in result["steps"] if s["vid"] == str(vid)), None)
    result["own"] = result["values"].get(str(vid))
    result["haul_scavenge"] = data["haul_scavenge"]
    result["squads"] = data["squads"]
    result["computed_at"] = int(now)
    return result


def pop_base(pop_max, current, effects=None):
    """`pop_max` sem a bandeira de população equipada (piso medido, §8.82)."""
    if not pop_max:
        return pop_max
    if current and int(current[0]) == 6:
        # O jogo arredonda para baixo: a menor fazenda que dá este piso.
        return int(math.ceil(pop_max / (1 + flag_pct(effects, 6, current[1]) / 100.0) - 1e-9))
    return pop_max
