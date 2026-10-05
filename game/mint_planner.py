"""
Cunhagem (§8.55) -- lógica pura: custo da moeda por aldeia, escolha da aldeia
central de cunhagem ("hub") e o que cada aldeia manda para ela.

Sem rede e sem disco: tudo entra como argumento (o `cache/managed` já lido),
para os testes rodarem sem estado de jogo e o painel calcular a mesma
recomendação que o bot executa.

⚠️ De onde vêm os números.

  * Custo base da moeda no br143: 28.000 / 30.000 / 25.000. Lido na tela
    `snob&mode=coin` (captura de 04/10/2026), na linha das aldeias sem bandeira
    de cunhagem.
  * Bandeira tipo 7 ("custo de cunhagem"), nível n: −(8 + 2n) %. Medido na
    mesma tela, pela coluna de custo de seis aldeias: nível 1 = 25.200 (−10 %),
    2 = 24.640 (−12 %), 3 = 24.080 (−14 %), 4 = 23.520 (−16 %),
    5 = 22.960 (−18 %), 7 = 21.840 (−22 %). Nível 6, 8 e 9 seguem a mesma
    reta por extrapolação -- não medidos.
  * O número que vale mesmo é o `train.storage_item` da academia de cada
    aldeia (`{"wood":23520,"stone":25200,"iron":21000,"id":"coin"}` na
    BBM 003): é o custo com TODOS os bônus ativos aplicados. Quando o bot já o
    leu (`coin_cost` no `cache/managed`), ele vence a conta pela bandeira --
    é a única fonte que enxerga o Bônus de bandeira e o Decreto Real.
"""
import math

RESOURCES = ("wood", "stone", "iron")

BASE_COIN_COST = {"wood": 28000, "stone": 30000, "iron": 25000}

COIN_FLAG_TYPE = 7

# Custo medido mais velho que isto não representa mais a aldeia: o Decreto
# Real dura 24 h e o Bônus de bandeira 48 h, então um custo lido durante uma
# campanha passaria por permanente depois que ela acaba.
MEASURED_COST_MAX_AGE = 6 * 3600


def flag_discount_pct(level):
    """Desconto da bandeira tipo 7 no nível dado (0 = sem bandeira)."""
    try:
        level = int(level or 0)
    except (TypeError, ValueError):
        return 0
    return 8 + 2 * level if level > 0 else 0


def coin_flag_level(state):
    """Nível da bandeira de cunhagem equipada, ou 0 se a aldeia usa outra."""
    current = ((state or {}).get("flags") or {}).get("current_flag")
    if isinstance(current, (list, tuple)) and len(current) == 2:
        try:
            if int(current[0]) == COIN_FLAG_TYPE:
                return int(current[1])
        except (TypeError, ValueError):
            return 0
    return 0


def has_academy(state):
    try:
        return int(((state or {}).get("buidling_levels") or {}).get("snob") or 0) > 0
    except (TypeError, ValueError):
        return False


def measured_coin_cost(state, now):
    """
    `coin_cost` gravado pelo bot a partir da academia, se for recente e
    completo; senão None. A idade entra porque o custo medido inclui bônus
    temporários (ver MEASURED_COST_MAX_AGE).
    """
    entry = (state or {}).get("coin_cost")
    if not isinstance(entry, dict):
        return None
    try:
        age = now - int(entry.get("read_at") or 0)
        cost = {r: int(entry[r]) for r in RESOURCES}
    except (KeyError, TypeError, ValueError):
        return None
    if age > MEASURED_COST_MAX_AGE or any(v <= 0 for v in cost.values()):
        return None
    return cost


def with_measured(states, measured):
    """
    Cópias rasas de `states` com o custo medido na academia em `coin_cost`.

    O custo medido mora em `cache/mint/state.json`, não no `cache/managed`:
    o `Village.set_cache_vars()` reescreve o arquivo da aldeia inteiro a cada
    rodada, e um campo gravado lá por outro módulo sumiria na rodada seguinte.
    """
    out = {}
    for vid, state in (states or {}).items():
        entry = (measured or {}).get(str(vid))
        if entry:
            state = dict(state or {})
            state["coin_cost"] = entry
        out[vid] = state
    return out


def flag_coin_cost(level, base=None):
    """Custo previsto só pela bandeira equipada (sem bônus temporário)."""
    base = base or BASE_COIN_COST
    factor = 1 - flag_discount_pct(level) / 100.0
    return {r: int(round(base[r] * factor)) for r in RESOURCES}


def village_coin_cost(state, now):
    """(custo, origem) -- origem é 'medido' ou 'bandeira'."""
    measured = measured_coin_cost(state, now)
    if measured:
        return measured, "medido"
    return flag_coin_cost(coin_flag_level(state)), "bandeira"


def distance(a, b):
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def _coords(state):
    try:
        return int(state["x"]), int(state["y"])
    except (KeyError, TypeError, ValueError):
        return None


def _total_resources(state):
    res = (state or {}).get("resources") or {}
    total = 0
    for r in RESOURCES:
        try:
            total += int(res.get(r) or 0)
        except (TypeError, ValueError):
            pass
    return total


def candidates(states, config_villages, now):
    """
    Aldeias que podem cunhar (academia construída e gerenciadas), com o que a
    escolha do hub precisa. `states` é {vid: cache/managed}, `config_villages`
    é `config["villages"]`.
    """
    out = []
    for vid, state in (states or {}).items():
        vcfg = (config_villages or {}).get(str(vid)) or {}
        if not vcfg.get("managed", False) or not has_academy(state):
            continue
        coords = _coords(state)
        if coords is None:
            continue
        cost, source = village_coin_cost(state, now)
        try:
            storage = int(state.get("storage") or 0)
        except (TypeError, ValueError):
            storage = 0
        out.append({
            "vid": str(vid),
            "name": state.get("name") or str(vid),
            "x": coords[0],
            "y": coords[1],
            "flag_level": coin_flag_level(state),
            "discount_pct": flag_discount_pct(coin_flag_level(state)),
            "cost": cost,
            "cost_source": source,
            "cost_total": sum(cost.values()),
            "storage": storage,
            "resources": {r: int(((state.get("resources") or {}).get(r)) or 0) for r in RESOURCES},
            # `snobs: 0` = não recruta nobre, então não disputa recurso com a
            # moeda. A escolha prefere essas, em empate.
            "mint_only": not (vcfg.get("snobs") or 0),
        })
    return out


def rank_hubs(cands, states):
    """
    Ordena os candidatos a hub, melhor primeiro. Critérios, nesta ordem:

      1. menor custo de moeda (é o que multiplica tudo que chega lá);
      2. maior armazém (é o que limita quanto se cunha de uma vez);
      3. aldeia que não recruta nobre;
      4. mais perto do recurso das outras aldeias (soma de distância × estoque,
         menor é melhor) -- comerciante perto volta mais rápido.

    Devolve a lista de candidatos, cada um com `centrality` e `reasons`.
    """
    stock_points = []
    for state in (states or {}).values():
        coords = _coords(state)
        if coords is not None:
            stock_points.append((coords, _total_resources(state)))

    for c in cands:
        here = (c["x"], c["y"])
        c["centrality"] = int(sum(distance(here, p) * amount for p, amount in stock_points) / 1000)

    ranked = sorted(
        cands,
        key=lambda c: (c["cost_total"], -c["storage"], not c["mint_only"], c["centrality"]),
    )
    for i, c in enumerate(ranked):
        reasons = []
        if c["flag_level"]:
            reasons.append("bandeira de cunhagem nível %d (−%d%%)" % (c["flag_level"], c["discount_pct"]))
        else:
            reasons.append("sem bandeira de cunhagem")
        reasons.append("armazém %s" % "{:,}".format(c["storage"]).replace(",", "."))
        reasons.append("só cunha" if c["mint_only"] else "recruta nobre")
        c["reasons"] = reasons
        c["rank"] = i + 1
    return ranked


def choose_hub(states, config_villages, now, override=None):
    """
    (vid do hub ou None, ranking). `override` é `minting.hub_village`: vale se
    for um candidato (academia + gerenciada); senão é ignorado e vence o
    primeiro do ranking -- quem chama compara com o override para avisar.
    """
    ranked = rank_hubs(candidates(states, config_villages, now), states)
    if override is not None and str(override) in {c["vid"] for c in ranked}:
        return str(override), ranked
    return (ranked[0]["vid"] if ranked else None), ranked


def plan_route(donor_res, floor, hub_res, hub_storage, hub_inflight, carry,
               per_merchant, cost, fill_max_pct=0.95, min_send=1000):
    """
    Quanto a aldeia doadora manda para o hub neste ciclo.

    Manda o que passa do `floor` (por recurso; 0 = tudo), em blocos de um
    comerciante, sempre do recurso que o hub tem MENOS em relação ao custo da
    moeda -- o hub cunha pelo recurso mais escasso, então mandar madeira para
    um hub que já tem madeira sobrando só gasta comerciante. Para quando acaba
    a carga (`carry`), a sobra da doadora ou o espaço do hub
    (`hub_storage × fill_max_pct` menos estoque e o que já está a caminho).

    Devolve {recurso: quantidade}, ou {} se o total ficar abaixo de `min_send`.
    """
    per_merchant = max(1, int(per_merchant or 1000))
    floor = max(0, int(floor or 0))
    cap = int((hub_storage or 0) * fill_max_pct)
    surplus, headroom, level = {}, {}, {}
    for r in RESOURCES:
        have = int((donor_res or {}).get(r) or 0)
        hub_have = int((hub_res or {}).get(r) or 0)
        coming = int((hub_inflight or {}).get(r) or 0)
        surplus[r] = max(0, have - floor)
        headroom[r] = max(0, cap - hub_have - coming)
        level[r] = hub_have + coming

    sent = {r: 0 for r in RESOURCES}
    merchants = int(carry or 0) // per_merchant
    while merchants > 0:
        options = [
            r for r in RESOURCES
            if surplus[r] - sent[r] > 0 and headroom[r] - sent[r] > 0 and cost.get(r)
        ]
        if not options:
            break
        r = min(options, key=lambda k: (level[k] + sent[k]) / float(cost[k]))
        chunk = min(per_merchant, surplus[r] - sent[r], headroom[r] - sent[r])
        sent[r] += chunk
        merchants -= 1

    plan = {r: v for r, v in sent.items() if v > 0}
    if sum(plan.values()) < min_send:
        return {}
    return plan


def coins_for(resources, cost):
    """Quantas moedas um estoque paga a um custo dado (recurso mais escasso)."""
    try:
        return int(min(int(resources.get(r) or 0) // int(cost[r]) for r in RESOURCES))
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return 0
