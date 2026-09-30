"""
Plano de apoio a membros da tribo: de QUAIS aldeias próprias tirar tropa, e
quanto mandar para cada aldeia que pediu (docs/backend.md §8.39).

"Mais segura para enviar" é uma propriedade da ORIGEM (decisão do usuário em
2026-09-29): a aldeia que pode abrir mão de defesa sem se expor. Critérios,
em ordem de peso:

1. Ataque chegando (`under_attack` no cache/managed) exclui a aldeia. Tirar
   defesa de quem está para ser atacado é o erro que não tem volta.
2. Ameaça em volta: aldeias de jogador hostil num raio (padrão 15 campos),
   pesadas por relação (inimigo 3, "outros" 1 -- aliado, PNA, amigo e a
   própria tribo não contam), pelo tamanho (pontos/5.000, até 1) e pela
   proximidade (1 - d/raio). Soma 0 = "segura"; abaixo de `exposed_threat` =
   "atenção"; a partir dele (padrão 2,0) = "exposta", fora do plano salvo pedido explícito.
3. Reserva: de cada unidade fica em casa `reserve_pct` do que está lá.

Distância até o alvo NÃO entra na segurança: com o pedido a 213-293 campos
(o de referência, K57, visto de K25/K35), toda origem fica a dias de viagem e
a diferença entre elas é pequena perto do risco local. Ela entra como teto
opcional (`max_travel_hours`), aplicado por unidade: um pacote que estoura o
teto perde primeiro a unidade mais lenta, porque o comando anda na velocidade
dela.

Tudo puro: recebe dicts, devolve dicts. Quem lê cache é o webmanager; quem
envia é `Village.run_tribe_support()`.
"""
import math

from core.support_store import DEFAULT_GATHER_SHARE
from core.templates import GATHER_UNITS, UNIT_POP
from core.world_config import WorldConfig

RELATION_WEIGHT = {"enemy": 3.0, "other": 1.0}

DEFAULT_OPTIONS = {
    "reserve_pct": 0.2,
    "danger_radius": 15,
    # 2,0 = uma aldeia inimiga de 5.000+ pontos a até 5 campos já expõe a
    # origem sozinha (3 x 1 x (1 - 5/15) = 2,0). Com 3,0 nem uma inimiga a 2
    # campos bastava (2,6) -- achado no primeiro teste.
    "exposed_threat": 2.0,
    "include_exposed": False,
    "max_travel_hours": None,
    # 100 de população: menos que isso não vale um comando. Sem piso, o
    # primeiro plano real (2026-09-29) saiu com 111 envios, vários de 10-50.
    "min_package_pop": 100,
    # Aldeia hostil abaixo disto não conta. As 175 "hostis" em volta das
    # aldeias do usuário eram quase todas de 26 pontos, de contas sem tribo
    # abandonadas no início: punham tudo em "atenção" e mostravam "hostil a
    # 1 campo" sem ameaçar nada.
    "min_hostile_points": 500,
    # Lança/espada (18-22 min/campo) num comando e pesada/explorador (9-11)
    # noutro. Juntos, tudo anda na velocidade da espada: a pesada que chegaria
    # em ~50 h chega em ~100 h. Custa um comando a mais por par.
    "split_fast": False,
    # Fatia das unidades da coleta que uma aldeia que coleta pode ceder de
    # apoio, sobre o total dela. Ver donatable().
    "gather_share": DEFAULT_GATHER_SHARE,
    "units": ["spear", "sword", "spy", "heavy"],
}

FAST_UNITS = ("spy", "heavy", "knight")


def _dist(ax, ay, bx, by):
    return math.hypot(ax - bx, ay - by)


def source_safety(source, hostiles, options):
    """
    Segurança de uma aldeia de origem. `hostiles`: [{x, y, points, relation}]
    só com relação que pesa. Devolve {threat, nearest_hostile, tier, reasons}.
    """
    radius = float(options["danger_radius"])
    min_points = int(options.get("min_hostile_points") or 0)
    threat = 0.0
    nearest = None
    close = 0
    for h in hostiles:
        weight = RELATION_WEIGHT.get(h.get("relation"))
        if not weight or int(h.get("points") or 0) < min_points:
            continue
        d = _dist(source["x"], source["y"], h["x"], h["y"])
        if nearest is None or d < nearest:
            nearest = d
        if d <= radius:
            close += 1
            size = min(1.0, float(h.get("points") or 0) / 5000.0)
            threat += weight * size * (1.0 - d / radius)
    reasons = []
    if source.get("under_attack"):
        tier = "excluded"
        eta = source.get("incoming_eta")
        reasons.append("ataque chegando" + (" em %.1f h" % (eta / 3600.0) if eta else ""))
    elif threat >= float(options["exposed_threat"]):
        tier = "exposed"
        reasons.append("%d aldeias hostis a até %d campos" % (close, radius))
    elif threat > 0:
        tier = "caution"
        reasons.append("%d aldeias hostis a até %d campos" % (close, radius))
    else:
        tier = "safe"
        reasons.append("nenhuma aldeia hostil a até %d campos" % radius)
    return {
        "threat": round(threat, 2),
        "nearest_hostile": round(nearest, 1) if nearest is not None else None,
        "hostiles_in_radius": close,
        "tier": tier,
        "reasons": reasons,
    }


def donatable(home, options, gather_enabled=False, total=None, sent=None, pending=None):
    """
    O que pode sair de cada unidade.

    - Unidade que a coleta não usa (explorador): o que está em casa menos
      `reserve_pct`.
    - Em aldeia com coleta ligada, unidade da coleta (`GATHER_UNITS`): até
      `gather_share` do TOTAL da aldeia. "A coleta é prioridade", mas pode
      ceder uma fatia (usuário, 2026-09-29). Sobre o total, e não sobre o que
      está em casa, porque entre ciclos a tropa da coleta passa 6-7 h fora --
      em casa quase sempre há ~0. Com 20% nas 38 aldeias, pela fórmula do
      próprio jogo (Scavenging.js: duração = (100·cap²·fator²)^0,45 + 1800),
      a coleta perde 2,7% de recurso/h e libera ~9,7 mil lanças, ~9,6 mil
      espadas e ~2,5 mil pesadas (§8.39).

    `sent` e `pending` ({unidade: qtd}) são o que esta aldeia já tem no
    plano, enviado e aprovado-ainda-não-enviado. Apoio enviado continua no
    TOTAL da aldeia (fica fora, não some), então sem descontá-lo cada novo
    plano ofereceria mais uma fatia por cima: a fatia é um teto acumulado.
    Para unidade fora da coleta, o enviado já saiu de casa; só o pendente
    desconta.
    """
    reserve = float(options["reserve_pct"])
    share = float(options.get("gather_share") or 0)
    sent = sent or {}
    pending = pending or {}
    out = {}
    for unit in options["units"]:
        if gather_enabled and unit in GATHER_UNITS:
            give = int(math.floor(int((total or {}).get(unit) or 0) * share))
            give -= int(sent.get(unit, 0)) + int(pending.get(unit, 0))
            if give > 0:
                out[unit] = give
            continue
        have = int(home.get(unit) or 0)
        give = have - int(math.ceil(have * reserve)) - int(pending.get(unit, 0))
        if give > 0:
            out[unit] = give
    return out


def _fit_travel(package, distance, speeds, max_seconds):
    """Tira do pacote as unidades cuja viagem sozinha estoura o teto."""
    if not max_seconds:
        return package
    kept = {}
    for unit, qty in package.items():
        t = WorldConfig.travel_seconds(speeds, distance, {unit: qty})
        if t is not None and t <= max_seconds:
            kept[unit] = qty
    return kept


def plan_support(requests, sources, hostiles, speeds, options=None):
    """
    requests: [{num, name, x, y, village_id, player_id, missing: {unit: qtd}}]
    sources:  [{vid, name, x, y, home: {unit: qtd}, under_attack, incoming_eta,
                last_run}]
    hostiles: [{x, y, points, relation}]
    speeds:   {unit: min/campo} (WorldConfig.unit_speeds)

    Devolve {"sources": ranking, "lines": plano, "uncovered": falta que
    sobrou, "options": opções efetivas}. Os pedidos são atendidos na ordem do
    número (a prioridade do organizador) e cada um puxa das origens mais
    seguras primeiro.
    """
    opts = dict(DEFAULT_OPTIONS)
    opts.update({k: v for k, v in (options or {}).items() if v is not None or k == "max_travel_hours"})
    max_seconds = float(opts["max_travel_hours"]) * 3600 if opts.get("max_travel_hours") else None

    ranking = []
    for src in sources:
        safety = source_safety(src, hostiles, opts)
        give = donatable(src.get("home") or {}, opts, src.get("gather_enabled"),
                         src.get("total"), src.get("sent"), src.get("pending"))
        usable = safety["tier"] in ("safe", "caution") or (
            safety["tier"] == "exposed" and opts["include_exposed"])
        held = [u for u in opts["units"] if src.get("gather_enabled") and u in GATHER_UNITS]
        if held:
            safety["reasons"].append("coleta ligada: cede até %d%% de %s; o resto fica na coleta"
                                     % (round(float(opts.get("gather_share") or 0) * 100),
                                        ", ".join(held)))
        ranking.append(dict(src, **safety, donatable=give, usable=usable))
    tier_order = {"safe": 0, "caution": 1, "exposed": 2, "excluded": 3}
    ranking.sort(key=lambda s: (tier_order[s["tier"]], s["threat"],
                                -(s["nearest_hostile"] or 1e9), s["name"] or ""))

    left = {s["vid"]: dict(s["donatable"]) for s in ranking if s["usable"]}
    usable = [s for s in ranking if s["usable"]]
    min_pop = int(opts["min_package_pop"] or 0)
    lines = []
    uncovered = []
    for req in sorted(requests, key=lambda r: (r.get("num") is None, r.get("num") or 0)):
        need = {u: int(q) for u, q in (req.get("missing") or {}).items()
                if u in opts["units"] and int(q) > 0}
        while need:
            # Dentro da faixa de segurança (segura < atenção < exposta), a
            # origem que cobre MAIS do que falta vem primeiro: menos comandos
            # para o mesmo apoio. A ameaça decimal só desempata -- entre
            # 0,02 e 0,3 a diferença é ruído, a faixa é que tem significado.
            best = None
            for src in usable:
                package = {u: min(q, left[src["vid"]].get(u, 0)) for u, q in need.items()
                           if left[src["vid"]].get(u, 0) > 0}
                distance = _dist(src["x"], src["y"], req["x"], req["y"])
                package = _fit_travel(package, distance, speeds, max_seconds)
                pop = sum(UNIT_POP.get(u, 1) * q for u, q in package.items())
                # O piso não pode barrar o que falta quando isso inteiro já é
                # menor que ele (10 pesadas = 60 de população) -- contado
                # DEPOIS do teto de viagem, que pode ter tirado a lança.
                reachable = _fit_travel(need, distance, speeds, max_seconds)
                floor = min(min_pop, sum(UNIT_POP.get(u, 1) * q for u, q in reachable.items()))
                if not package or pop < floor:
                    continue
                key = (tier_order[src["tier"]], -pop, src["threat"], distance)
                if best is None or key < best[0]:
                    best = (key, src, package, distance)
            if best is None:
                break
            _, src, package, distance = best
            parts = [package]
            if opts.get("split_fast"):
                fast = {u: q for u, q in package.items() if u in FAST_UNITS}
                slow = {u: q for u, q in package.items() if u not in FAST_UNITS}
                parts = [p for p in (slow, fast) if p]
            for part in parts:
                travel = WorldConfig.travel_seconds(speeds, distance, part)
                lines.append({
                    "num": req.get("num"),
                    "target_name": req.get("name"),
                    "target_x": req["x"],
                    "target_y": req["y"],
                    "target_vid": req.get("village_id"),
                    "target_player": req.get("player_id"),
                    "source_vid": src["vid"],
                    "source_name": src.get("name"),
                    "troops": part,
                    "distance": round(distance, 1),
                    "travel_sec": int(travel) if travel is not None else None,
                })
            for u, q in package.items():
                left[src["vid"]][u] -= q
                need[u] -= q
            need = {u: q for u, q in need.items() if q > 0}
        if need:
            uncovered.append({"num": req.get("num"), "name": req.get("name"), "missing": need})
    return {"sources": ranking, "lines": lines, "uncovered": uncovered, "options": opts}
