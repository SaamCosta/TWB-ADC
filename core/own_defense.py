"""
Defesa automática das aldeias PRÓPRIAS (docs/backend.md §8.60): estudar os
ataques que chegam numa aldeia, decidir se ela precisa de apoio e montar o
plano de envio. Tudo puro -- recebe dicts, devolve dicts. Quem lê o jogo e
envia é `game/own_defense.py`.

Origem: em 2026-10-11 a BBM 048 (40808), conquistada às 14:50 com lealdade
deixada em 25, tinha 6 ataques chegando -- um deles com ícone de nobre. Nada
no bot reagiu: a aldeia não estava no config.json, e o `support_other()` só
roda quando OUTRA aldeia gerenciada chega na vez dela no ciclo (~4 h). O apoio
saiu à mão, e só chegou porque o Sinal da Aflição (+10%) encurtou a viagem.

O QUE DECIDE "PRECISA DE APOIO"
-------------------------------
Uma aldeia cai quando a lealdade chega a 0. Com lealdade L e queda máxima por
nobre Q (35 no br143, `WorldConfig.loyalty_drop_range`), são necessários
`ceil(L/Q)` nobres no pior caso: 1 com L=25, 3 com L=100. A regeneração entre
um nobre e outro é ignorada de propósito -- ela só aumentaria o número, e o
erro tem que ser para o lado de defender.

Que ataque PODE ser nobre? O jogo não diz (o ícone ao lado do rótulo vem do
TEXTO do rótulo -- ver `Extractor.INCOMING_LABEL_UNIT_RE`). Mas a física diz
quando NÃO pode:
  - origem mais longe que `snob.max_dist` do mundo (70 no br143);
  - falta MAIS tempo para chegar do que a viagem inteira de um nobre daquela
    distância (o comando já teria chegado se fosse nobre).
Origem desconhecida conta como "pode ser": não se fabrica segurança.

A aldeia precisa de apoio quando há pelo menos `ceil(L/Q)` ataques que podem
ser nobre. Antes do N-ésimo deles (N = nobres necessários) ela não cai, mesmo
que todos os anteriores sejam nobres; depois dele, QUALQUER um dos seguintes
pode ser o que a toma. Por isso o prazo é uma janela: do N-ésimo ao último
ataque que pode ser nobre, e serve todo apoio que chega antes do último. A
primeira versão mirava só no N-ésimo e, no smoke de 2026-10-11 15:40, não
mandaria nada: o N-ésimo pousava dali a 1 minuto e os quatro seguintes (21 a
48 campos, todos podendo ser nobre) ficavam sem defesa.

O QUE O PLANO MANDA
-------------------
Tropa defensiva (`units`) de aldeias próprias que CHEGA antes do prazo menos
uma margem, unidade por unidade -- um comando anda na velocidade da mais
lenta, então a lança que não chega não vai junto com a pesada que chega.
O que está em casa só se sabe na praça; o plano usa o total do cache/managed
como teto e o envio limita ao que a praça mostrar (`clamp_to_available`).
"""
import math

from core.world_config import WorldConfig
from core.templates import UNIT_POP

DEFAULT_OPTIONS = {
    # Cavalaria leve fica de fora de propósito: é a tropa do farm, e o
    # usuário perguntou por ela no primeiro envio manual (2026-10-11).
    "units": ["spear", "sword", "archer", "heavy", "spy"],
    # Fração de cada unidade que fica na origem.
    "reserve_pct": 0.0,
    # Folga entre a chegada do apoio e o prazo. Cobre a demora entre o plano
    # e o envio de verdade; o envio ainda confere a duração do jogo.
    "arrival_margin_sec": 60,
    # Menos que isso não vale um comando.
    "min_package_pop": 30,
    # Teto de população mandada para UM alvo (0 = sem teto). Sem teto, um
    # ataque grande puxaria a defesa de todo o império para uma aldeia.
    "max_pop_per_target": 0,
    # Origem com ataque chegando não manda defesa embora.
    "exclude_attacked_sources": True,
}

NOBLE_TIME_TOLERANCE_SEC = 60

# Unidades que só vão de carona. Explorador defende 2 e serve para barrar o
# reconhecimento do atacante -- útil junto da defesa, inútil sozinho. No
# smoke de 2026-10-11 15:42, 14 dos 18 envios planejados eram só explorador:
# 42 requisições para não defender nada.
RIDE_ALONG_UNITS = ("spy",)


def _dist(ax, ay, bx, by):
    return math.hypot(ax - bx, ay - by)


def _pop(troops):
    return sum(UNIT_POP.get(u, 1) * int(q) for u, q in (troops or {}).items())


def nobles_needed(loyalty, drop_range):
    """Nobres para zerar `loyalty` no pior caso (queda máxima). Mínimo 1."""
    try:
        high = max(int(drop_range[1]), 1)
    except (TypeError, ValueError, IndexError):
        high = 35
    try:
        loyalty = int(loyalty)
    except (TypeError, ValueError):
        loyalty = 100
    return max(1, int(math.ceil(max(loyalty, 1) / float(high))))


def noble_possible(distance, eta_seconds, speeds, max_dist):
    """
    (pode_ser_nobre, motivo) para um ataque a `distance` campos que chega em
    `eta_seconds`. Distância None = origem desconhecida = pode ser.
    """
    if distance is None:
        return True, "origem desconhecida"
    if max_dist and distance > max_dist:
        return False, "origem a %.1f campos, além do alcance do nobre (%d)" % (distance, max_dist)
    travel = WorldConfig.travel_seconds(speeds, distance, {"snob": 1})
    if travel is None:
        return True, "velocidade do nobre desconhecida"
    if eta_seconds is not None and eta_seconds > travel + NOBLE_TIME_TOLERANCE_SEC:
        return False, "faltam %.1f h, mais que a viagem inteira de um nobre (%.1f h)" % (
            eta_seconds / 3600.0, travel / 3600.0)
    return True, "a %.1f campos, no alcance e no tempo de um nobre" % distance


def assess(village, attacks, speeds, max_dist, drop_range, now):
    """
    village: {vid, name, x, y, loyalty}
    attacks: [{command_id, arrival_at, origin: {x, y, ...} | None, label_unit}]
             só ataques -- apoio e paladino já filtrados.

    Devolve {attacks (anotados, por chegada), nobles_needed, possible_nobles,
    protect, first_deadline_at, deadline_at, deadline_command, threat_arrivals,
    reason}. `deadline_at` é o ÚLTIMO ataque que pode ser nobre (fim da
    janela); `threat_arrivals` são as chegadas da janela, do N-ésimo em
    diante, para dizer quantos deles cada apoio vence.
    """
    loyalty = village.get("loyalty")
    # None = o widget de lealdade existe mas o número não foi lido. O widget
    # só aparece abaixo de 100, então o pior caso (1 nobre) é o único
    # palpite que não fabrica segurança.
    needed = nobles_needed(1 if loyalty is None else loyalty, drop_range)
    rows = []
    for attack in sorted(attacks, key=lambda a: a.get("arrival_at") or 0):
        arrival = attack.get("arrival_at")
        if not arrival or arrival <= now:
            continue
        origin = attack.get("origin") or None
        distance = None
        if origin and origin.get("x") is not None:
            distance = _dist(village["x"], village["y"], origin["x"], origin["y"])
        possible, why = noble_possible(distance, arrival - now, speeds, max_dist)
        rows.append(dict(attack, distance=round(distance, 1) if distance is not None else None,
                         noble_possible=possible, noble_reason=why))
    possible = [r for r in rows if r["noble_possible"]]
    out = {"attacks": rows, "nobles_needed": needed, "possible_nobles": len(possible),
           "loyalty": loyalty, "protect": False, "first_deadline_at": None,
           "deadline_at": None, "deadline_command": None, "threat_arrivals": []}
    if len(possible) < needed:
        out["reason"] = ("%d ataque(s) podem ser nobre; com lealdade %s são precisos %d"
                         % (len(possible), loyalty if loyalty is not None else "?", needed))
        return out
    window = possible[needed - 1:]
    for row in rows:
        row["in_window"] = row in window
    out.update(protect=True, first_deadline_at=window[0]["arrival_at"],
               deadline_at=window[-1]["arrival_at"],
               deadline_command=window[-1].get("command_id"),
               threat_arrivals=[r["arrival_at"] for r in window],
               reason=("lealdade %s: %d nobre(s) tomam a aldeia e %d ataque(s) podem ser nobre; "
                       "apoio serve se chegar antes de qualquer um do %dº ao último"
                       % (loyalty if loyalty is not None else "?", needed, len(possible),
                          needed)))
    return out


def plan_defense(target, deadline_at, sources, speeds, now, bonus_pct=0, options=None,
                 skip_sources=None, threat_arrivals=None):
    """
    target:  {vid, x, y}
    sources: [{vid, name, x, y, troops: {unit: qtd}, under_attack}]
             `troops` é o teto (total do cache/managed); o envio confere.
    skip_sources: {vid: motivo} -- já tentado há pouco, etc.

    threat_arrivals: chegadas dos ataques da janela (ver `assess`); cada linha
    diz quantos deles vence (`beats`).

    Devolve {lines, skipped, total_troops, total_pop, options}. Cada linha:
    {source_vid, source_name, troops, distance, travel_sec, arrival_at,
    slack_sec, beats}, ordenadas pela folga (quem tem menos folga sai
    primeiro).
    """
    opts = dict(DEFAULT_OPTIONS)
    opts.update({k: v for k, v in (options or {}).items() if v is not None})
    margin = int(opts["arrival_margin_sec"] or 0)
    reserve = float(opts["reserve_pct"] or 0)
    skip_sources = skip_sources or {}
    lines, skipped = [], []
    for src in sources:
        vid = str(src.get("vid"))
        if vid == str(target.get("vid")):
            continue
        name = src.get("name") or vid
        if vid in skip_sources:
            skipped.append({"vid": vid, "name": name, "reason": skip_sources[vid]})
            continue
        if src.get("under_attack") and opts["exclude_attacked_sources"]:
            skipped.append({"vid": vid, "name": name, "reason": "ataque chegando na origem"})
            continue
        if src.get("x") is None or src.get("y") is None:
            continue
        distance = _dist(src["x"], src["y"], target["x"], target["y"])
        package = {}
        for unit in opts["units"]:
            have = int((src.get("troops") or {}).get(unit) or 0)
            give = have - int(math.ceil(have * reserve))
            if give <= 0:
                continue
            travel = WorldConfig.travel_seconds(speeds, distance, {unit: give}, bonus_pct)
            if travel is not None and now + travel <= deadline_at - margin:
                package[unit] = give
        if not package:
            continue
        if all(u in RIDE_ALONG_UNITS for u in package):
            skipped.append({"vid": vid, "name": name,
                            "reason": "só explorador chegaria a tempo"})
            continue
        if _pop(package) < int(opts["min_package_pop"] or 0):
            skipped.append({"vid": vid, "name": name, "reason": "pacote abaixo do piso"})
            continue
        travel = WorldConfig.travel_seconds(speeds, distance, package, bonus_pct)
        arrival = now + travel
        lines.append({
            "source_vid": vid, "source_name": name, "troops": package,
            "distance": round(distance, 1), "travel_sec": int(travel),
            "arrival_at": int(now + travel),
            "slack_sec": int(deadline_at - margin - (now + travel)),
            "beats": sum(1 for t in (threat_arrivals or [deadline_at]) if arrival <= t - margin),
        })
    # Teto por alvo: as mais próximas primeiro -- chegam antes e deixam a
    # defesa distante do império onde está.
    cap = int(opts["max_pop_per_target"] or 0)
    if cap > 0:
        kept, total = [], 0
        for line in sorted(lines, key=lambda l: l["distance"]):
            if total >= cap:
                skipped.append({"vid": line["source_vid"], "name": line["source_name"],
                                "reason": "teto de população por alvo atingido"})
                continue
            kept.append(line)
            total += _pop(line["troops"])
        lines = kept
    lines.sort(key=lambda l: l["slack_sec"])
    totals = {}
    for line in lines:
        for u, q in line["troops"].items():
            totals[u] = totals.get(u, 0) + q
    return {"lines": lines, "skipped": skipped, "total_troops": totals,
            "total_pop": _pop(totals), "options": opts}
