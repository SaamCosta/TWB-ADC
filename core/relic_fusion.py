"""
Relíquias, Fase 4 (§8.79): fundir. Lógica pura, sem rede e sem POST.

A mecânica, com a fonte de cada regra:

- `upgrade_relic` com `relic_ids[]` = [principal, material, material]. O JS do
  jogo (`RelicSystem.0ba79d.js`, o mesmo hash de 01:12 a 22:42 de 29/10) exige
  os 3 espaços cheios e a posição 0 sempre relíquia; espaço 1 e 2 aceitam
  relíquia ou componente (`material_qualities[]`), e componente só da MESMA
  qualidade da principal (`placeMaterialIntoSlot`). Depois do POST o JS
  seleciona a relíquia pelo id da posição 0: o id da principal fica (a fusão
  do usuário de 29/10 manteve o 1105799).
- A ajuda do jogo (`screen=relic_system&mode=help`, 29/10 22:42) define os dois
  métodos. **Método 1:** principal + 2 materiais da mesma qualidade E do mesmo
  tipo: a principal sobe uma qualidade, as propriedades ficam, os valores
  sobem e o raio "muitas vezes" aumenta. **Método 2:** 3 relíquias quaisquer da
  mesma qualidade: uma relíquia ALEATÓRIA, de tipo qualquer, da qualidade
  seguinte. A página não publica probabilidade nenhuma (nem de tipo, nem de
  secundário, nem da chance de "perfeito"). Sem fonte, a aleatória nunca sai
  (pedido do usuário): ela aparece no plano só para informar.
- Qualidade de saída, raio e valores: `QUALITY_TABLE`, medida nas relíquias
  da conta (§8.74; as 10 relíquias de 01:12 e as 9 de 22:42 de 29/10 batem). O "muitas
  vezes" do raio é a tabela: sobe em 2 dos 4 degraus. Uma fusão do método 1
  ainda não foi observada: depois de uma, `check_result` confere o previsto.
- `renowned` é o teto: o JS não oferece atualização para ela.
- Com 2 relíquias é o `premium_upgrade_relic` (100 PP), que o bot nunca usa.
  Também nunca `reroll_relic` nem `reduce_cooldown` (`PP_ACTIONS`).
- Componentes (`materials`, 9º argumento do `Inventory.init`, `[{quality,
  count, image}]` pelo JS): vieram vazios em todas as leituras; de onde saem a
  ajuda não diz. O bot não os usa: nenhuma resposta com eles foi medida.

Valor (a mesma conta do planejador): o plano é refeito sobre o estado
hipotético (principal na qualidade seguinte, materiais fora) e a fusão vale a
diferença do valor do plano otimizado, `gain_h`. Além disso, o valor da
resultante na melhor anfitriã elegível (`result_best_h`) tem que superar a
soma do que as três valiam, cada uma na sua melhor anfitriã
(`consumed_best_h`). Só entram relíquias paradas que o plano não vai equipar
nem mover.
"""
import itertools

from core import relic_executor as E

QUALITIES = ("shoddy", "polished", "refined", "superior", "renowned")
NEXT_QUALITY = {q: QUALITIES[i + 1] for i, q in enumerate(QUALITIES[:-1])}
QUALITY_LABELS = {"shoddy": "de má qualidade", "polished": "Resistente", "refined": "Aprimorada",
                  "superior": "Superior", "renowned": "Reconhecida"}
# (raio, principal, secundário) por qualidade, medidos (§8.74, §8.79).
QUALITY_TABLE = {"shoddy": (2, 5, 1), "polished": (2, 6, 2), "refined": (3, 7, 3),
                 "superior": (3, 8, 4), "renowned": (4, 10, 5)}
FUSION_SIZE = 3
ALLOWED_POSTS = ("equip_relic", "remove_relic", "upgrade_relic")
PP_ACTIONS = ("premium_upgrade_relic", "reroll_relic", "reduce_cooldown")
# Planos refeitos por leitura, no máximo (cada um é uma busca local inteira).
MAX_EVALS = 8

RANDOM_WHY = ("aprimoramento aleatório: a ajuda do jogo (mode=help) não publica as "
              "probabilidades de tipo e atributos, então não há valor esperado")


def signature(relic):
    """O que precisa ser igual entre o plano e a hora de agir (lista: vai para JSON)."""
    main = relic.get("main") or {}
    return [relic.get("type"), relic.get("quality"), main.get("key"), main.get("value"),
            [[s.get("key"), s.get("value"), bool(s.get("perfect"))] for s in relic.get("subs") or []]]


def table_check(relics):
    """
    {qualidade: [divergência]} das relíquias que não batem com `QUALITY_TABLE`
    (raio, valor principal, secundário não perfeito). Qualidade divergente não
    entra em fusão: a previsão do resultado seria um palpite.
    """
    out = {}
    for r in relics or []:
        q = r.get("quality")
        if q not in QUALITY_TABLE:
            continue
        rng, main, sub = QUALITY_TABLE[q]
        got_main = (r.get("main") or {}).get("value")
        subs = [s.get("value") for s in r.get("subs") or [] if not s.get("perfect")]
        if r.get("range") != rng or (got_main is not None and float(got_main) != main) \
                or any(float(v) != sub for v in subs if v is not None):
            out.setdefault(q, []).append("%s (%s): raio %s, valores %s/%s; tabela %s, %s/%s" % (
                r.get("name"), r.get("id"), r.get("range"), got_main, subs, rng, main, sub))
    return out


def upgraded(relic):
    """A principal depois do método 1, pela tabela. None se não há qualidade seguinte."""
    to_q = NEXT_QUALITY.get(relic.get("quality"))
    if to_q is None:
        return None
    rng, main, sub = QUALITY_TABLE[to_q]
    out = dict(relic)
    out.update(quality=to_q, range=rng,
               name="%s %s" % (relic.get("type_name") or relic.get("name"), QUALITY_LABELS[to_q]))
    if relic.get("main"):
        out["main"] = dict(relic["main"], value=float(main))
    out["subs"] = [dict(s, value=float(sub)) for s in relic.get("subs") or []]
    return out


def _parked(state, base_plan):
    """(paradas que podem ser fundidas, {id: motivo} das paradas que não podem)."""
    targeted = {str(i) for i in (base_plan.get("target") or {})}
    for move in base_plan.get("moves") or []:
        targeted.update(str(i) for i in move.get("relic_ids") or [])
    ok, out = [], {}
    for r in (state or {}).get("relics") or []:
        if r.get("village_id"):
            continue  # equipada ou inativa: nunca
        rid = str(r["id"])
        if rid in targeted:
            out[rid] = "o plano vai equipá-la"
        elif r.get("trade_offer_id"):
            out[rid] = "em oferta de troca"
        elif r.get("inactive_sec"):
            out[rid] = "inativa"
        else:
            ok.append(r)
    return ok, out


def _entry(kind, relics, best_alone, to_q):
    ids = [str(r["id"]) for r in relics]
    names = [r.get("name") for r in relics]
    if kind == "same_type":
        text = "fundir %s (principal) com %s e %s: %s %s" % (
            names[0], names[1], names[2], relics[0].get("type_name") or names[0], QUALITY_LABELS[to_q])
    else:
        text = "fundir %s, %s e %s: relíquia aleatória %s" % (names[0], names[1], names[2],
                                                            QUALITY_LABELS[to_q])
    return {"action": "fuse", "kind": kind, "relic_ids": ids, "names": names,
            "from": {i: None for i in ids}, "to": {i: None for i in ids},
            "quality_from": relics[0].get("quality"), "quality_to": to_q,
            "type": relics[0].get("type") if kind == "same_type" else None,
            "signature": {str(r["id"]): signature(r) for r in relics},
            "consumed_best_h": round(sum(best_alone.get(i, 0.0) for i in ids), 1),
            "gain_h": None, "gain_alone_h": None, "result_best_h": None, "result": None,
            "blocked": None, "text": text}


def fusions(state, base_plan, plan_fn, max_evals=MAX_EVALS):
    """
    As fusões possíveis agora, com o valor de cada uma. `plan_fn(estado)` é o
    planejador com as mesmas taxas, coordenadas e elegibilidade do plano base
    (`relic_planner.plan_from_disk`). Devolve {"fusions": [...], "excluded":
    {id: motivo}, "table": {qualidade: [divergência]}}.
    """
    relics = list((state or {}).get("relics") or [])
    table = table_check(relics)
    best_alone = {str(r["id"]): float(((r.get("best_hosts") or [{}])[0]).get("value") or 0.0)
                  for r in base_plan.get("relics") or []}
    parked, excluded = _parked(state, base_plan)
    by_quality = {}
    for r in parked:
        if r.get("quality") in NEXT_QUALITY:
            by_quality.setdefault(r["quality"], []).append(r)
    base_value = float(base_plan.get("value_after") or 0.0)
    out, evals = [], 0
    for q, group in sorted(by_quality.items(), key=lambda kv: QUALITIES.index(kv[0])):
        to_q = NEXT_QUALITY[q]
        by_type = {}
        for r in group:
            by_type.setdefault(r.get("type"), []).append(r)
        cheap = lambda r: (best_alone.get(str(r["id"]), 0.0), str(r["id"]))  # noqa: E731
        # Método 1: cada uma do tipo como principal, as duas que menos valem como material.
        for rtype, same in sorted(by_type.items(), key=lambda kv: str(kv[0])):
            if len(same) < FUSION_SIZE:
                continue
            best = None
            for main in sorted(same, key=lambda r: str(r["id"])):
                mats = sorted((r for r in same if r is not main), key=cheap)[:FUSION_SIZE - 1]
                entry = _entry("same_type", [main] + mats, best_alone, to_q)
                result = upgraded(main)
                entry["result"] = {"name": result["name"], "range": result["range"],
                                   "main": (result.get("main") or {}).get("value"),
                                   "subs": [s.get("value") for s in result.get("subs") or []]}
                if any(s.get("perfect") for s in main.get("subs") or []):
                    entry["blocked"] = ("a principal tem secundário perfeito, e o que a fusão faz "
                                        "com ele não foi medido")
                elif table.get(q) or table.get(to_q):
                    entry["blocked"] = "a tabela de qualidade não bate com as relíquias da conta: %s" % (
                        "; ".join(table.get(q, []) + table.get(to_q, [])))
                elif evals >= max_evals:
                    entry["blocked"] = "não avaliada: teto de %d planos por leitura" % max_evals
                else:
                    evals += 1
                    hyp = dict(state)
                    gone = {str(m["id"]) for m in mats}
                    hyp["relics"] = [result if r is main else r for r in relics
                                     if str(r["id"]) not in gone]
                    after = plan_fn(hyp)
                    entry["gain_h"] = entry["gain_alone_h"] = round(
                        float(after.get("value_after") or 0.0) - base_value, 1)
                    row = next((x for x in after.get("relics") or [] if str(x["id"]) == str(main["id"])), {})
                    entry["result_best_h"] = float(((row.get("best_hosts") or [{}])[0]).get("value") or 0.0)
                    entry["result_target"] = (after.get("target") or {}).get(str(main["id"]))
                if best is None or (entry["gain_h"] or -1e18) > (best["gain_h"] or -1e18):
                    best = entry
            out.append(best)
        # Método 2: só para informar (nunca sai). As 3 que menos valem, de tipos não todos iguais.
        if len(group) >= FUSION_SIZE and len(by_type) >= 2:
            combos = [c for c in itertools.combinations(sorted(group, key=cheap), FUSION_SIZE)
                      if len({r.get("type") for r in c}) > 1]
            if combos:
                trio = min(combos, key=lambda c: sum(cheap(r)[0] for r in c))
                entry = _entry("random", list(trio), best_alone, to_q)
                entry["blocked"] = RANDOM_WHY
                out.append(entry)
    return {"fusions": out, "excluded": excluded, "table": table,
            "materials": (state or {}).get("materials") or []}


# -- freios (o mesmo idioma do relic_executor) ---------------------------------

def fusions_today(exec_state, day):
    return int(((exec_state.get("days") or {}).get(day) or {}).get("fusions", 0)) if day else 0


def evaluate(plan, exec_state, cfg, now, day):
    """[(fusão, motivo ou None)]: None = pode sair agora."""
    streak = exec_state.get("streak") or {}
    skip = exec_state.get("skip") or {}
    today = fusions_today(exec_state, day)
    rows = []
    for f in (plan or {}).get("fusions") or []:
        key = E.move_key(f)
        ids = [str(i) for i in f.get("relic_ids") or []]
        gain = f.get("gain_h")
        touched = E.touched_recently(exec_state, set(ids), now, cfg["undo_block_h"], actions=None)
        seen = int((streak.get(key) or {}).get("count", 0))
        until = float((skip.get(key) or {}).get("until") or 0)
        if f.get("kind") != "same_type":
            why = f.get("blocked") or RANDOM_WHY
        elif len(ids) != FUSION_SIZE or len(set(ids)) != FUSION_SIZE:
            why = "a fusão gratuita pede 3 relíquias (com 2 é a premium, que o bot nunca usa)"
        elif f.get("blocked"):
            why = f["blocked"]
        elif gain is None:
            why = "sem valor calculado"
        elif gain < cfg["min_gain_h"]:
            why = "ganho %.0f/h abaixo do piso de %.0f/h" % (gain, cfg["min_gain_h"])
        elif (f.get("result_best_h") or 0.0) <= (f.get("consumed_best_h") or 0.0):
            why = "a resultante vale %.0f/h na melhor anfitriã, não supera os %.0f/h das três" % (
                f.get("result_best_h") or 0.0, f.get("consumed_best_h") or 0.0)
        elif touched:
            why = "o bot mexeu numa delas há %.1f h (nada antes de %d h)" % (
                min(touched.values()), cfg["undo_block_h"])
        elif until > now:
            why = "recusado antes: %s" % (skip.get(key) or {}).get("why")
        elif day is None:
            why = "sem relógio do servidor: o teto do dia não pode ser contado"
        elif today >= cfg["max_fusions_per_day"]:
            why = "teto do dia: %d de %d fusões" % (today, cfg["max_fusions_per_day"])
        elif seen < cfg["stable_reads"]:
            why = "visto em %d de %d leituras seguidas" % (seen, cfg["stable_reads"])
        else:
            why = None
        rows.append((f, why))
    return rows


def choose(plan, exec_state, cfg, now, day):
    for f, why in evaluate(plan, exec_state, cfg, now, day):
        if why is None:
            return f
    return None


def awaiting_confirmation(plan, exec_state, cfg, now, day):
    return [f for f, why in evaluate(plan, exec_state, cfg, now, day)
            if why and why.startswith("visto em ")]


def precheck(fusion, fresh):
    """
    Reconfere a fusão contra o inventário relido na hora de agir. (motivo,
    tipo) ou (None, None). O usuário também funde (9º padrão): relíquia que
    sumiu, foi equipada ou mudou de atributos = "diverge", não age e relê.
    """
    if not fresh:
        return "inventário não relido", "diverge"
    by_id = {str(r.get("id")): r for r in fresh.get("relics") or []}
    for rid in fusion.get("relic_ids") or []:
        rid = str(rid)
        relic = by_id.get(rid)
        if relic is None:
            return "a relíquia %s não está mais no inventário" % rid, "diverge"
        if relic.get("village_id"):
            return "%s está equipada em %s" % (relic.get("name"), relic["village_id"]), "diverge"
        if signature(relic) != (fusion.get("signature") or {}).get(rid):
            return "%s não é a do plano (fundida ou rolada desde a leitura?)" % relic.get("name"), "diverge"
        if relic.get("trade_offer_id"):
            return "%s está em oferta de troca" % relic.get("name"), "recusa"
        if relic.get("inactive_sec"):
            return "%s está inativa" % relic.get("name"), "recusa"
    return None, None


def check_result(fusion, after):
    """
    ("ok" | "changed" | "none", detalhe) do inventário depois do POST.
    ok: a principal ficou com o mesmo id, tipo e atributos, na qualidade
    seguinte, e os materiais sumiram. changed: algo foi consumido, mas não como
    previsto (o bot mexeu: conta). none: nada mudou.
    """
    ids = [str(i) for i in fusion.get("relic_ids") or []]
    by_id = {str(r.get("id")): r for r in (after or {}).get("relics") or []}
    main = by_id.get(ids[0])
    gone = all(m not in by_id for m in ids[1:])
    before = (fusion.get("signature") or {}).get(ids[0]) or [None] * 5
    if main is not None and gone and main.get("quality") == fusion.get("quality_to") \
            and main.get("type") == before[0] and (main.get("main") or {}).get("key") == before[2]:
        expected = fusion.get("result") or {}
        got = {"range": main.get("range"), "main": (main.get("main") or {}).get("value"),
               "subs": [s.get("value") for s in main.get("subs") or []]}
        same = (got["range"] == expected.get("range") and got["main"] == expected.get("main")
                and got["subs"] == expected.get("subs"))
        return "ok", ("como previsto" if same else
                      "fundida, mas diferente da tabela: raio %s, valores %s/%s; previsto %s, %s/%s" % (
                          got["range"], got["main"], got["subs"], expected.get("range"),
                          expected.get("main"), expected.get("subs")))
    some_gone = any(m not in by_id for m in ids[1:])
    if some_gone or main is None or main.get("quality") != fusion.get("quality_from"):
        return "changed", "o inventário mudou, mas não como previsto: principal %s, materiais %s" % (
            "%s %s" % (main.get("name"), main.get("quality")) if main else "sumiu",
            "consumidos" if gone else ("parte consumida" if some_gone else "ainda lá"))
    return "none", "nada mudou no inventário"
