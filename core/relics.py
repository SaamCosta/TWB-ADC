"""
Relíquias, Fase 1 (§8.75): a conta das relíquias, sem rede.

O leitor (`game/relic_manager.py`) baixa as telas; os parsers ficam no
`Extractor` (`relic_inventory`, `relic_overview`, `village_bonus_board`,
`report_list_rows`). Aqui fica o que se calcula a partir delas, para poder ser
testado contra as fixtures:

- cobertura de cada relíquia equipada: distância euclidiana <= `range`,
  contando a anfitriã (§8.74: reproduz exatamente as listas do jogo de 08/10 e
  29/10), e a conferência contra "Outras aldeias afetadas";
- soma por atributo e aldeia, com o teto de 20% que vale SÓ para a parte das
  relíquias (itens e paladino não entram, §8.74);
- conferência contra o quadro `benefit`/`relic` que a visão geral de cada
  aldeia mostra;
- contador de "Relíquia encontrada" por dia do servidor, da lista
  `screen=report&mode=other`.

Nada aqui decide mexer em relíquia: isso é a Fase 2 (planejador) e a 3.
"""
import datetime
import math

# Teto por atributo sobre a soma das relíquias (§8.74, BBM 001 em 29/10:
# quartel 10+5+10 = 25 → "+5% aplicado, +5% descartado").
RELIC_ATTRIBUTE_CAP = 20.0

# Títulos padrão das linhas da lista de relatórios (§8.74). "encontrada" e
# "adquirida" têm a MESMA classe (`report_ReportRelicAcquired`), então só o
# título separa. O jogador pode renomear a linha: relíquia com outro título
# conta como `renamed`, nunca como achado.
REPORT_FOUND = "Relíquia encontrada"
REPORT_ACQUIRED = "Relíquia adquirida"
REPORT_UNLOCKED = "Relíquia transferida para o inventário"
RELIC_THUMB_PREFIX = "relic_system/"

# Achados por dia que o jogo permite (§8.74: 2 batidos todo dia de 27 a 29/10).
DAILY_FOUND_CAP = 2

# Linhas por página da lista de relatórios no br143 (medido em 04/10 e de novo
# em 29/10: `page_size` 50). Página com menos linhas é a categoria inteira.
REPORT_PAGE_SIZE = 50

# "out. 29, 01:14". Só `out.` foi visto na tela (29/10); os outros são as
# abreviações do pt-BR que o jogo usa no resto da interface. Mês que não casa
# deixa a linha sem data, e o dia dela vira incompleto, em vez de chutar.
MONTHS_PT = {"jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
             "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12}

FOUND_HISTORY_DAYS = 14


def distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def active_relics(inventory):
    """Relíquias que dão bônus agora: numa aldeia e fora do período inativo."""
    return [r for r in (inventory or {}).get("relics") or []
            if r.get("village_id") and not r.get("inactive_sec")]


def relic_state(relic):
    if not relic.get("village_id"):
        return "inventory"
    return "inactive" if relic.get("inactive_sec") else "equipped"


def coverage(relics, coords):
    """
    {relic_id: [vid, ...]} das aldeias em `coords` a até `range` da anfitriã,
    ela inclusa. Anfitriã sem coordenada dá lista vazia (e quem confere com o
    jogo a separa como "sem coordenada", não como divergência).
    """
    out = {}
    for relic in relics:
        host = coords.get(relic["village_id"])
        if host is None or relic.get("range") is None:
            out[relic["id"]] = []
            continue
        rng = float(relic["range"]) + 1e-9
        out[relic["id"]] = sorted(vid for vid, xy in coords.items() if distance(host, xy) <= rng)
    return out


def compare_coverage(inventory, overview, computed, coords):
    """
    Confere a cobertura calculada com a da tela `mode=overview`. Devolve
    {"divergences": [...], "unplaced": [...]}: divergência é aldeia que um lado
    tem e o outro não, com as duas coordenadas conhecidas; `unplaced` é aldeia
    que o jogo lista e que não tem coordenada aqui (não dá para conferir).
    Também confere vagas e inativas entre as duas telas.
    """
    divergences, unplaced = [], []
    if not overview:
        return {"divergences": divergences, "unplaced": unplaced}
    by_host = {e["host_id"]: e for e in overview.get("equipped") or [] if e.get("host_id")}
    active = active_relics(inventory)
    for relic in active:
        entry = by_host.get(relic["village_id"])
        if entry is None:
            divergences.append({"relic_id": relic["id"], "host_id": relic["village_id"],
                                "kind": "missing_in_game",
                                "text": "equipada no inventário e ausente da visão geral"})
            continue
        game = set(entry.get("affected") or []) | {relic["village_id"]}
        mine = set(computed.get(relic["id"]) or [])
        for vid in sorted(game - mine):
            if vid not in coords:
                unplaced.append(vid)
            else:
                divergences.append({"relic_id": relic["id"], "host_id": relic["village_id"],
                                    "vid": vid, "kind": "only_game",
                                    "text": "o jogo cobre e o cálculo não"})
        for vid in sorted(mine - game):
            divergences.append({"relic_id": relic["id"], "host_id": relic["village_id"],
                                "vid": vid, "kind": "only_computed",
                                "text": "o cálculo cobre e o jogo não"})
    hosts = {r["village_id"] for r in active}
    for host in sorted(set(by_host) - hosts):
        divergences.append({"relic_id": by_host[host].get("relic_id"), "host_id": host,
                            "kind": "missing_in_inventory",
                            "text": "na visão geral e não equipada no inventário"})
    if overview.get("slots_used") != len(active):
        divergences.append({"kind": "slots",
                            "text": "vagas ocupadas %s na visão geral, %d relíquias ativas"
                                    % (overview.get("slots_used"), len(active))})
    inactive = [r for r in (inventory or {}).get("relics") or [] if relic_state(r) == "inactive"]
    if len(overview.get("inactive") or []) != len(inactive):
        divergences.append({"kind": "inactive",
                            "text": "%d inativas na visão geral, %d no inventário"
                                    % (len(overview.get("inactive") or []), len(inactive))})
    return {"divergences": divergences, "unplaced": sorted(set(unplaced))}


def _stats(relic):
    return [s for s in [relic.get("main")] + list(relic.get("subs") or []) if s]


def village_attributes(relics, computed):
    """
    {vid: {key: {"sum", "applied", "discarded", "relics": [id, ...]}}}: a
    soma das relíquias por atributo em cada aldeia coberta, com o teto.
    O valor é o do texto do jogo; secundário `perfect` não é dobrado aqui
    porque o texto já é o que a aldeia recebe (nenhum perfeito visto ainda).
    """
    out = {}
    for relic in relics:
        for vid in computed.get(relic["id"]) or []:
            attrs = out.setdefault(vid, {})
            for stat in _stats(relic):
                entry = attrs.setdefault(stat["key"], {"sum": 0.0, "relics": []})
                entry["sum"] += stat["value"]
                entry["relics"].append(relic["id"])
    for attrs in out.values():
        for entry in attrs.values():
            entry["applied"] = min(entry["sum"], RELIC_ATTRIBUTE_CAP)
            entry["discarded"] = max(0.0, entry["sum"] - RELIC_ATTRIBUTE_CAP)
    return out


def totals(attributes):
    relic_pct = sum(e["sum"] for a in attributes.values() for e in a.values())
    discarded = sum(e["discarded"] for a in attributes.values() for e in a.values())
    return {"covered_villages": len(attributes), "relic_pct": relic_pct,
            "discarded_pct": discarded,
            "discarded_share": (discarded / relic_pct) if relic_pct else 0.0}


def board_check(vid, board, relics, computed, attributes, inactive=()):
    """
    Diferenças entre o quadro da visão geral da aldeia `vid` e o cálculo:
    relíquias que a alcançam (nome + anfitriã) e, por atributo, a soma das
    contribuições de relíquia e o descartado. Lista vazia = bate.

    `inactive`: relíquias inativas (conquista, 24 h). O quadro da ANFITRIÃ as
    lista na linha `<!-- relic -->`, mas nenhum atributo delas entra nos
    totais `benefit` (§8.79: BBM 067 e a 87765 em 29/10, a da 87765 com um
    "+1% Quartel na velocidade" que não aparece no quadro). Entram só na lista
    esperada da anfitriã; nas vizinhas, não visto.
    """
    vid = str(vid)
    msgs = []
    expected = sorted([(r.get("name") or "", r["village_id"]) for r in relics
                       if vid in (computed.get(r["id"]) or [])]
                      + [(r.get("name") or "", r["village_id"]) for r in inactive or ()
                         if str(r.get("village_id")) == vid])
    seen = sorted((r.get("name") or "", r.get("host_id")) for r in board.get("relics") or [])
    if expected != seen:
        msgs.append("relíquias que alcançam: jogo %s, cálculo %s" % (seen, expected))
    mine = attributes.get(vid) or {}
    shown = {}
    for benefit in board.get("benefits") or []:
        relic_sum = sum(s["value"] for s in benefit.get("sources") or [] if s.get("relic"))
        if relic_sum:
            shown[benefit["key"]] = (relic_sum, benefit.get("discarded") or 0.0)
    for key in sorted(set(shown) | set(mine)):
        game_sum, game_disc = shown.get(key, (0.0, 0.0))
        calc = mine.get(key) or {"sum": 0.0, "discarded": 0.0}
        if abs(game_sum - calc["sum"]) > 1e-6 or abs(game_disc - calc["discarded"]) > 1e-6:
            msgs.append("%s: jogo %g%% (descartado %g), cálculo %g%% (descartado %g)"
                        % (key, game_sum, game_disc, calc["sum"], calc["discarded"]))
    return msgs


def received_date(text, server_now):
    """
    Data (`datetime.date`) da coluna "Recebido em" ("out. 29, 01:14"), no ano
    do servidor; mês à frente do servidor é do ano anterior. None se não casa.
    """
    if not text or server_now is None:
        return None
    parts = text.replace(",", " ").split()
    if len(parts) < 2:
        return None
    month = MONTHS_PT.get(parts[0].rstrip(".").lower()[:3])
    try:
        day = int(parts[1])
    except ValueError:
        return None
    if month is None:
        return None
    year = server_now.year - (1 if month > server_now.month else 0)
    try:
        return datetime.date(year, month, day)
    except ValueError:
        return None


def found_by_day(rows, server_now, page_size=REPORT_PAGE_SIZE):
    """
    {"AAAA-MM-DD": {"found", "acquired", "unlocked", "renamed", "complete"}}
    para cada dia do servidor da página de relatórios lida, do dia da linha
    mais antiga até hoje.

    Um dia só é `complete` se a página o contém inteiro: ou a página tem
    menos linhas que `page_size` (é a categoria toda), ou existe linha de um
    dia anterior. O dia da linha mais antiga de uma página cheia pode
    continuar na página seguinte. Linha de relíquia sem data legível deixa
    todos os dias incompletos: não dá para saber de qual ela é.
    """
    if server_now is None:
        return {}
    today = server_now.date()
    dated = [(row, received_date(row.get("received"), server_now)) for row in rows]
    dates = [d for _, d in dated if d is not None]
    if not dates:
        return {}
    oldest = min(dates)
    whole_category = len(rows) < page_size
    relic_undated = any(d is None and (row.get("thumb") or "").startswith(RELIC_THUMB_PREFIX)
                        for row, d in dated)
    out = {}
    day = oldest
    while day <= today:
        out[day.isoformat()] = {"found": 0, "acquired": 0, "unlocked": 0, "renamed": 0,
                                "complete": (whole_category or day > oldest) and not relic_undated}
        day += datetime.timedelta(days=1)
    for row, date in dated:
        if date is None or not (row.get("thumb") or "").startswith(RELIC_THUMB_PREFIX):
            continue
        entry = out.get(date.isoformat())
        if entry is None:
            continue
        kind = {REPORT_FOUND: "found", REPORT_ACQUIRED: "acquired",
                REPORT_UNLOCKED: "unlocked"}.get(row.get("title"), "renamed")
        entry[kind] += 1
    return out


def merge_found(history, fresh, today=None, keep_days=FOUND_HISTORY_DAYS):
    """
    Junta a leitura nova ao histórico. Dia completo novo substitui; dia
    incompleto novo só entra se o histórico não tinha o dia completo. Guarda
    os últimos `keep_days` dias.
    """
    out = dict(history or {})
    for day, entry in (fresh or {}).items():
        old = out.get(day)
        if entry.get("complete") or not (old or {}).get("complete"):
            out[day] = dict(entry)
    if today is not None:
        cutoff = (today - datetime.timedelta(days=keep_days - 1)).isoformat()
        out = {d: e for d, e in out.items() if d >= cutoff}
    return dict(sorted(out.items()))


def build_state(inventory, overview, coords, fetched_at, server_time=None):
    """
    O estado que vai para `cache/relics.json`, sem o contador de achados
    (quem lê a lista de relatórios o acrescenta). `coords` já deve estar
    restrita às aldeias da conta.
    """
    relics = list((inventory or {}).get("relics") or [])
    active = active_relics(inventory)
    computed = coverage(active, coords)
    attributes = village_attributes(active, computed)
    check = compare_coverage(inventory, overview, computed, coords)
    for relic in relics:
        relic["state"] = relic_state(relic)
        relic["covers"] = computed.get(relic["id"], [])
        if relic.get("removal_cooldown_sec"):
            relic["removable_at"] = int(fetched_at + relic["removal_cooldown_sec"])
        if relic.get("inactive_sec"):
            relic["inactive_until_at"] = int(fetched_at + relic["inactive_sec"])
    slots = None
    if overview:
        used, free = overview.get("slots_used", 0), overview.get("slots_free", 0)
        slots = {"used": used, "free": free, "total": used + free,
                 "next_thresholds": list(overview.get("next_thresholds") or [])}
    return {
        "fetched_at": int(fetched_at),
        "server_time": server_time,
        "can_equip": (inventory or {}).get("can_equip"),
        "loyalty_locked": (inventory or {}).get("loyalty_locked"),
        "is_new_system": (inventory or {}).get("is_new_system"),
        "materials": (inventory or {}).get("materials"),
        "slots": slots,
        "relics": relics,
        "counts": {s: sum(1 for r in relics if r["state"] == s)
                   for s in ("equipped", "inactive", "inventory")},
        "coverage_check": check,
        "villages": attributes,
        "totals": totals(attributes),
    }
