"""
Relíquias, Fase 3 (§8.78): quando o plano vira ação. Lógica pura, sem rede.

O planejador (`core/relic_planner.py`) diz onde as relíquias valeriam mais; o
que está aqui decide SE e QUANDO um passo do plano sai de verdade, com
cautela, e reconfere o estado lido na hora de agir. Quem faz os POSTs é o
`RelicManager.act()`.

Freios, todos em `relics.*` do config:

- `manage` (padrão false): sem ele, o plano só é simulado (Fase 2).
- Histerese: ganho do passo SOZINHO (`gain_alone_h`, sobre a alocação atual)
  de pelo menos `min_gain_h` recurso/h e, num mover, de pelo menos
  `min_gain_pct`% do que a relíquia já rende onde está (`value_before_h`).
  Equipar uma parada parte de 0, então só o piso absoluto conta.
- Mesmo passo em `stable_reads` leituras seguidas do inventário (a chave do
  passo inclui origem e destino: se o jogador mexeu, a chave muda e a conta
  recomeça).
- Nunca desfaz em menos de `undo_block_h` o que o bot fez: relíquia que o bot
  equipou ou moveu fica parada esse tempo (o jogo já trava a remoção 24 h
  depois de equipar; isto cobre também o que o jogo não trava).
- Teto por dia do SERVIDOR: `max_moves_per_day` (remover + equipar) e
  `max_equips_per_day` (parada em vaga livre). O contador fica em
  `cache/relics.json` -> `exec`.
- Uma ação por leitura. Primeiro equipar parada em vaga livre (sem remove,
  risco menor); mover só depois.
- `replace` e `swap` do plano não saem nesta fase: ficam registrados.

Fase 4 (§8.79, `core/relic_fusion.py`): `fuse` e `max_fusions_per_day` são
lidos aqui também, a fusão entra no mesmo histórico, contador do dia e
contagem de leituras seguidas, e a trava de 24 h dela vale para qualquer ação
do bot (a de equipar/mover só olha equipar/mover: equipar a relíquia que o bot
acabou de fundir é o objetivo da fusão, não desfazê-la).

Reconferência na hora de agir (6º padrão): o inventário relido NA anfitriã
(o `loyalty_locked` do `Inventory.init` é da aldeia da URL), e não o do plano.
Se a relíquia não está onde o plano a viu, o jogador mexeu (9º padrão): não
age e pede releitura.
"""
import datetime

EXECUTED_ACTIONS = ("equip", "move")
HISTORY_KEEP = 60
# Recusa que não muda sozinha (lealdade, vaga) congela o passo por este tempo,
# para não reler e recusar a cada aldeia.
SKIP_SECONDS = 6 * 3600
# Divergência com o estado: o passo espera a releitura (a chave muda se o
# jogador mexeu de fato).
DIVERGE_SKIP_SECONDS = 1800

DEFAULTS = {
    "manage": False,
    "min_gain_h": 50.0,
    "min_gain_pct": 10.0,
    "stable_reads": 2,
    "confirm_after_min": 30,
    "max_moves_per_day": 2,
    "max_equips_per_day": 3,
    "undo_block_h": 24,
    # Fase 4 (§8.79): fundir. Só age com `manage` também ligado: o valor da
    # fusão só existe se o bot equipar a resultante.
    "fuse": False,
    "max_fusions_per_day": 1,
}


def settings(config):
    """`relics.*` com os padrões acima; valor ilegível cai no padrão."""
    raw = (config or {}).get("relics") or {}
    out = {}
    for key, default in DEFAULTS.items():
        value = raw.get(key, default)
        try:
            out[key] = bool(value) if isinstance(default, bool) else type(default)(value)
        except (TypeError, ValueError):
            out[key] = default
    return out


def move_key(move):
    """Chave estável do passo: ação, relíquias, origem e destino de cada uma."""
    ids = [str(i) for i in move.get("relic_ids") or []]
    return "%s|%s" % (move.get("action"), ";".join(
        "%s:%s>%s" % (i, (move.get("from") or {}).get(i), (move.get("to") or {}).get(i))
        for i in ids))


def server_day(state, now):
    """
    Dia do servidor (`YYYY-MM-DD`) agora. `server_time` é o relógio do
    servidor no instante `fetched_at`, gravado como `datetime.timestamp()` de
    um datetime ingênuo; `fromtimestamp` desfaz a mesma conversão, então o
    resultado é a parede do servidor, qualquer que seja o fuso local. Sem
    relógio do servidor: None (o teto conta como já cheio, ver `choose`).
    """
    server_time = (state or {}).get("server_time")
    fetched_at = (state or {}).get("fetched_at")
    if not server_time or not fetched_at:
        return None
    return datetime.datetime.fromtimestamp(
        float(server_time) + (float(now) - float(fetched_at))).date().isoformat()


def update_streaks(exec_state, plan, fetched_at):
    """
    Conta em quantas leituras seguidas cada passo apareceu. Uma leitura é um
    `fetched_at`: chamar de novo com o mesmo não conta duas vezes. Passo que
    sumiu do plano zera.
    """
    if exec_state.get("streak_fetch") == fetched_at:
        return exec_state.get("streak") or {}
    prev = exec_state.get("streak") or {}
    fresh = {}
    for move in list((plan or {}).get("moves") or []) + list((plan or {}).get("fusions") or []):
        key = move_key(move)
        old = prev.get(key) or {}
        fresh[key] = {"count": int(old.get("count", 0)) + 1,
                      "first_at": old.get("first_at", fetched_at)}
    exec_state["streak"] = fresh
    exec_state["streak_fetch"] = fetched_at
    return fresh


def day_counts(exec_state, day):
    counts = (exec_state.get("days") or {}).get(day) or {}
    return int(counts.get("moves", 0)), int(counts.get("equips", 0))


def touched_recently(exec_state, relic_ids, now, hours, actions=EXECUTED_ACTIONS):
    """
    {id: horas desde a última ação do bot} das relíquias tocadas há menos de
    `hours`, contando só as ações em `actions` (None = todas, inclusive fundir).
    """
    out = {}
    for entry in exec_state.get("history") or []:
        if not entry.get("ok") or (actions is not None and entry.get("action") not in actions):
            continue
        age = (now - float(entry.get("at") or 0)) / 3600.0
        if age >= hours:
            continue
        for rid in entry.get("relic_ids") or []:
            if str(rid) in relic_ids:
                out[str(rid)] = min(age, out.get(str(rid), age))
    return out


def evaluate(plan, exec_state, cfg, now, day):
    """
    [(move, motivo ou None)] de cada passo do plano, na ordem de execução:
    equipar primeiro (maior ganho antes), depois mover. Motivo None = o passo
    pode sair agora.
    """
    moves = list((plan or {}).get("moves") or [])
    order = {"equip": 0, "move": 1}
    moves.sort(key=lambda m: (order.get(m.get("action"), 2), -(m.get("gain_alone_h") or 0)))
    streak = exec_state.get("streak") or {}
    skip = exec_state.get("skip") or {}
    moves_today, equips_today = day_counts(exec_state, day) if day else (None, None)
    out = []
    for move in moves:
        key = move_key(move)
        action = move.get("action")
        gain = move.get("gain_alone_h")
        before = float(move.get("value_before_h") or 0.0)
        ids = {str(i) for i in move.get("relic_ids") or []}
        touched = touched_recently(exec_state, ids, now, cfg["undo_block_h"])
        seen = int((streak.get(key) or {}).get("count", 0))
        until = float((skip.get(key) or {}).get("until") or 0)
        if action not in EXECUTED_ACTIONS:
            why = "%s não sai nesta fase (só equipar e mover)" % action
        elif gain is None:
            why = "depende de outro passo do plano antes (anfitriã ocupada ou sem vaga)"
        elif gain < cfg["min_gain_h"]:
            why = "ganho %.0f/h abaixo do piso de %.0f/h" % (gain, cfg["min_gain_h"])
        elif action == "move" and gain < before * cfg["min_gain_pct"] / 100.0:
            why = "ganho %.0f/h abaixo de %.0f%% dos %.0f/h que ela já rende" % (
                gain, cfg["min_gain_pct"], before)
        elif touched:
            why = "o bot mexeu nela há %.1f h (nada se desfaz antes de %d h)" % (
                min(touched.values()), cfg["undo_block_h"])
        elif until > now:
            why = "recusado antes: %s (até %s)" % (
                (skip.get(key) or {}).get("why"),
                datetime.datetime.fromtimestamp(until).strftime("%d/%m %H:%M"))
        elif day is None:
            why = "sem relógio do servidor: o teto do dia não pode ser contado"
        elif action == "equip" and equips_today >= cfg["max_equips_per_day"]:
            why = "teto do dia: %d de %d equipar" % (equips_today, cfg["max_equips_per_day"])
        elif action == "move" and moves_today >= cfg["max_moves_per_day"]:
            why = "teto do dia: %d de %d mover" % (moves_today, cfg["max_moves_per_day"])
        elif seen < cfg["stable_reads"]:
            why = "visto em %d de %d leituras seguidas" % (seen, cfg["stable_reads"])
        else:
            why = None
        out.append((move, why))
    return out


def choose(plan, exec_state, cfg, now, day):
    """O primeiro passo que pode sair agora, ou None."""
    for move, why in evaluate(plan, exec_state, cfg, now, day):
        if why is None:
            return move
    return None


def awaiting_confirmation(plan, exec_state, cfg, now, day):
    """
    Passos que só esperam mais leituras seguidas: é para eles que vale a pena
    reler o inventário antes do próximo ciclo (`confirm_after_min`).
    """
    return [m for m, why in evaluate(plan, exec_state, cfg, now, day)
            if why and why.startswith("visto em ")]


def precheck(move, fresh, low_loyalty=None):
    """
    Reconfere o passo contra o inventário relido NA anfitriã (`fresh`, de
    `Extractor.relic_inventory`, com `village_id` = a aldeia da URL). Devolve
    (motivo, tipo) ou (None, None). Tipo: "diverge" (o estado não é o do
    plano: o jogador mexeu, reler) ou "recusa" (lealdade, vaga, trava: não
    muda sozinho logo).
    """
    if not fresh:
        return "inventário não relido", "diverge"
    rid = str(move["relic_ids"][0])
    target = str(move["to"][rid])
    origin = move["from"].get(rid)
    origin = str(origin) if origin else None
    if str(fresh.get("village_id")) != target:
        return "inventário relido em %s, não na anfitriã %s" % (fresh.get("village_id"), target), "diverge"
    relic = next((r for r in fresh.get("relics") or [] if str(r.get("id")) == rid), None)
    if relic is None:
        return "a relíquia %s não está mais no inventário" % rid, "diverge"
    where = relic.get("village_id")
    if (str(where) if where else None) != origin:
        return "a relíquia está em %s, e o plano a viu em %s" % (where or "inventário", origin or "inventário"), "diverge"
    occupant = next((r for r in fresh.get("relics") or [] if r.get("village_id")
                     and str(r["village_id"]) == target), None)
    if occupant is not None:
        return "a anfitriã já tem relíquia (%s)" % occupant.get("name"), "diverge"
    if fresh.get("loyalty_locked"):
        return "lealdade abaixo de 100 na anfitriã (loyalty_locked do jogo)", "recusa"
    if target in (low_loyalty or {}):
        return "lealdade estimada abaixo de 100 na anfitriã: %s" % low_loyalty[target], "recusa"
    if relic.get("trade_offer_id"):
        return "relíquia em oferta de troca", "recusa"
    if relic.get("inactive_sec"):
        return "relíquia inativa", "recusa"
    if move["action"] == "equip" and not fresh.get("can_equip"):
        return "sem vaga livre (can_equip falso)", "recusa"
    if move["action"] == "move":
        if relic.get("removal_cooldown_sec"):
            return "trava de remoção do jogo por mais %.1f h" % (relic["removal_cooldown_sec"] / 3600.0), "recusa"
        if relic.get("locked_state"):
            return relic["locked_state"], "recusa"
    return None, None


def note_skip(exec_state, move, why, kind, now):
    seconds = SKIP_SECONDS if kind == "recusa" else DIVERGE_SKIP_SECONDS
    exec_state.setdefault("skip", {})[move_key(move)] = {"why": why, "until": int(now + seconds)}
    # Entrada vencida não fica para sempre no arquivo.
    exec_state["skip"] = {k: v for k, v in exec_state["skip"].items()
                          if float(v.get("until") or 0) > now}


def record(exec_state, move, ok, detail, now, day):
    """Histórico da ação e, se saiu, o contador do dia do servidor."""
    entry = {"at": int(now), "day": day, "action": move.get("action"),
             "relic_ids": [str(i) for i in move.get("relic_ids") or []],
             "names": move.get("names"), "from": move.get("from"), "to": move.get("to"),
             "gain_h": move.get("gain_alone_h"), "ok": bool(ok), "detail": detail}
    history = exec_state.setdefault("history", [])
    history.append(entry)
    del history[:-HISTORY_KEEP]
    if ok and day:
        days = exec_state.setdefault("days", {})
        counts = days.setdefault(day, {"moves": 0, "equips": 0})
        field = {"move": "moves", "fuse": "fusions"}.get(move.get("action"), "equips")
        counts[field] = counts.get(field, 0) + 1
        for old in sorted(days)[:-14]:
            days.pop(old, None)
    # O passo feito sai da contagem de leituras: o próximo plano é outro.
    (exec_state.get("streak") or {}).pop(move_key(move), None)
    return entry
