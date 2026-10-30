"""
Relíquias, Fase 4 (docs/backend.md §8.79): fundir. `core/relic_fusion.py`
(tabela de qualidade, candidatas, valor, freios, reconferência, resultado) e
`RelicManager._act_fuse()`/`_post()` (GET de reconferência, POST
`upgrade_relic`, recusa AJAX, nunca PP, resposta crua salva).

Inventário verbatim do br143 de 29/10/2026 22:42 (`relic_system_br143_2242.html`,
anonimizado: só `discovered_by_*`), com as duas Fogueiras de má qualidade
inativas. "Paradas" = a mesma relíquia do JSON verbatim com `village_id` e
`inactive_until` zerados, e uma terceira Fogueira é a cópia de uma delas com
outro id (o jogo ainda não deu a terceira). O plano de valor usa a fixture do
planejador (`relic_planner_state_br143.json`, estado real de 29/10). Respostas
das ações: o JSON verbatim de relíquia no envelope `{"response", "game_data"}`
do `get_api_action` (7º padrão); a recusa é o `{"error": [...]}` do §8.63.
Sem rede, e sem tocar `cache/` real.

Rodar: python tests/test_relic_fusion.py
"""
import copy
import datetime
import json
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import relic_executor as E  # noqa: E402
from core import relic_fusion as F  # noqa: E402
from core import relic_planner as P  # noqa: E402
from core.extractors import Extractor  # noqa: E402
from game import relic_manager as RM  # noqa: E402

FIX = os.path.join(ROOT, "tests", "fixtures")
failures = []

FOG_A, FOG_B, FOG_C = "238187", "359750", "999001"   # C: cópia de A com outro id
ALABARDA = "157444"     # Alabarba Aprimorada, parada
MOCHILA_APR = "1105799"  # Mochila Aprimorada, equipada na BBM 013
CFG = E.settings({"relics": {"manage": True, "fuse": True}})
DAY = "2026-10-29"
NOW = 1793324563.0


def check(cond, msg):
    if not cond:
        failures.append(msg)


def raw_text():
    return open(os.path.join(FIX, "relic_system_br143_2242.html"), encoding="utf-8").read()


def raw_relics():
    text = raw_text()
    start = text.index("RelicSystem.Inventory.init(") + len("RelicSystem.Inventory.init(")
    return json.loads(Extractor.balanced_slice(text, text.index("[", start)), strict=False)


def parked_raw(extra_third=True):
    """O JSON verbatim, com as duas Fogueiras no inventário e (opcional) a terceira."""
    relics = copy.deepcopy(raw_relics())
    for r in relics:
        if str(r["id"]) in (FOG_A, FOG_B):
            r["village_id"] = None
            r["inactive_until"] = None
    if extra_third:
        third = copy.deepcopy(next(r for r in relics if str(r["id"]) == FOG_A))
        third["id"] = int(FOG_C)
        relics.append(third)
    return relics


def page(relics=None, host="44683"):
    text = raw_text()
    if relics is not None:
        start = text.index("RelicSystem.Inventory.init(") + len("RelicSystem.Inventory.init(")
        raw = Extractor.balanced_slice(text, text.index("[", start))
        text = text.replace(raw, json.dumps(relics), 1)
    return re.sub(r"(\}\]\s*,\s*)44683", lambda m: m.group(1) + host, text, count=1)


def inventory(relics=None):
    return Extractor.relic_inventory(page(relics))


def state_of(inv):
    """O estado como o `cache/relics.json` guarda (`state` por relíquia)."""
    out = {"relics": copy.deepcopy(inv["relics"]), "materials": inv.get("materials"),
           "slots": {"total": 8}, "can_equip": True}
    for r in out["relics"]:
        r["state"] = "inventory" if not r.get("village_id") else (
            "inactive" if r.get("inactive_sec") else "equipped")
    return out


def stub_plan(value_after, best=None, target=None):
    """plan_fn falso: valor do plano refeito e o melhor valor de cada relíquia."""
    def fn(hyp):
        return {"value_after": value_after, "target": dict(target or {}),
                "relics": [{"id": str(r["id"]), "best_hosts": [{"value": (best or {}).get(str(r["id"]), 0.0)}]}
                           for r in hyp["relics"]]}
    return fn


def base_plan(st, value_after=1000.0, best=None, target=None, moves=None):
    return {"value_after": value_after, "target": dict(target or {}), "moves": list(moves or []),
            "relics": [{"id": str(r["id"]), "best_hosts": [{"value": (best or {}).get(str(r["id"]), 0.0)}]}
                       for r in st["relics"]]}


def same_type(fx):
    return [f for f in fx["fusions"] if f["kind"] == "same_type"]


# -- mecânica -------------------------------------------------------------------

def test_tabela_de_qualidade_bate_com_o_inventario():
    inv = inventory()
    check(len(inv["relics"]) == 9, "9 relíquias às 22:42 (veio %d)" % len(inv["relics"]))
    check(F.table_check(inv["relics"]) == {}, "raio e valores batem com a tabela: %r"
          % F.table_check(inv["relics"]))
    bad = copy.deepcopy(inv["relics"])
    bad[0]["range"] = 4
    check(list(F.table_check(bad)) == [bad[0]["quality"]], "raio fora da tabela é divergência")
    perfect = copy.deepcopy(inv["relics"])
    perfect[0]["subs"][0].update(value=6.0, perfect=True)
    check(F.table_check(perfect) == {}, "secundário perfeito (dobrado) não conta como divergência")
    check(F.NEXT_QUALITY["shoddy"] == "polished" and "renowned" not in F.NEXT_QUALITY,
          "renowned é o teto")


def test_resultado_do_metodo_1_pela_tabela():
    fog = next(r for r in inventory()["relics"] if r["id"] == FOG_A)
    up = F.upgraded(fog)
    check(up["id"] == FOG_A and up["type"] == "bonfire" and up["quality"] == "polished",
          "mesmo id e tipo, qualidade seguinte")
    check(up["range"] == 2 and up["main"]["value"] == 6.0 and [s["value"] for s in up["subs"]] == [2.0, 2.0],
          "raio 2 (não sobe neste degrau), 6/2/2: %r" % ((up["range"], up["main"], up["subs"]),))
    check(up["main"]["key"] == fog["main"]["key"] and [s["key"] for s in up["subs"]]
          == [s["key"] for s in fog["subs"]], "atributos mantidos")
    check(fog["quality"] == "shoddy" and fog["main"]["value"] == 5.0, "a original não muda")
    ren = next(r for r in inventory()["relics"] if r["quality"] == "renowned")
    check(F.upgraded(ren) is None, "reconhecida não sobe")


# -- elegibilidade e valor ----------------------------------------------------------

def test_elegibilidade():
    st = state_of(inventory(parked_raw()))
    fx = F.fusions(st, base_plan(st), stub_plan(1000.0))
    fus = same_type(fx)
    check(len(fus) == 1 and set(fus[0]["relic_ids"]) == {FOG_A, FOG_B, FOG_C},
          "3 Fogueiras paradas: uma fusão do método 1 (%r)" % [f["relic_ids"] for f in fus])
    used = {i for f in fx["fusions"] for i in f["relic_ids"]}
    equipped = {r["id"] for r in st["relics"] if r.get("village_id")}
    check(not used & equipped, "nunca funde relíquia equipada")
    # inativas (o estado real de 22:42): nenhuma fusão
    st2 = state_of(inventory())
    check(F.fusions(st2, base_plan(st2), stub_plan(0))["fusions"] == [], "inativas não entram")
    # só 2 do mesmo tipo: é o caso premium, nunca vira fusão
    st3 = state_of(inventory(parked_raw(extra_third=False)))
    check(same_type(F.fusions(st3, base_plan(st3), stub_plan(0))) == [], "com 2 não há fusão (premium)")
    # o plano vai equipar uma delas: fica fora
    fx = F.fusions(st, base_plan(st, target={FOG_C: "41123"}), stub_plan(1000.0))
    check(same_type(fx) == [] and fx["excluded"].get(FOG_C) == "o plano vai equipá-la",
          "relíquia que a Fase 3 vai equipar não é fundida")
    fx = F.fusions(st, base_plan(st, moves=[{"relic_ids": [FOG_B]}]), stub_plan(1000.0))
    check(same_type(fx) == [], "nem a que está num passo do plano")
    # em oferta de troca
    traded = copy.deepcopy(st)
    next(r for r in traded["relics"] if r["id"] == FOG_B)["trade_offer_id"] = 77
    check(same_type(F.fusions(traded, base_plan(traded), stub_plan(0))) == [], "em troca não entra")


def test_valor_esperado_e_superar_as_que_somem():
    st = state_of(inventory(parked_raw()))
    # natural: as três valem 0 em toda aldeia, e a resultante também (combate)
    fus = same_type(F.fusions(st, base_plan(st), stub_plan(1000.0)))[0]
    check(fus["gain_h"] == 0.0 and fus["consumed_best_h"] == 0.0, "valor 0 dos dois lados")
    why = F.evaluate({"fusions": [fus]}, {}, CFG, NOW, DAY)[0][1]
    check("abaixo do piso" in why, "ganho 0 não sai (%r)" % why)
    # ganho no plano, e a resultante vale mais que as três: sai (depois de 2 leituras)
    fus = same_type(F.fusions(st, base_plan(st), stub_plan(1120.0, best={FOG_A: 120.0, FOG_B: 120.0,
                                                                       FOG_C: 120.0})))[0]
    check(fus["gain_h"] == 120.0 and fus["result_best_h"] == 120.0, "ganho +120/h (%r)" % fus)
    plan = {"fusions": [fus]}
    ex = {}
    E.update_streaks(ex, plan, 1)
    check("visto em 1 de 2" in F.evaluate(plan, ex, CFG, NOW, DAY)[0][1], "uma leitura não basta")
    E.update_streaks(ex, plan, 2)
    check(F.choose(plan, ex, CFG, NOW, DAY) is fus, "duas leituras seguidas: sai")
    # as três valiam, cada uma, 60/h paradas: a resultante (120) não supera 180
    worth = base_plan(st, best={FOG_A: 60.0, FOG_B: 60.0, FOG_C: 60.0})
    fus = same_type(F.fusions(st, worth, stub_plan(1120.0, best={FOG_A: 120.0})))[0]
    check(fus["consumed_best_h"] == 180.0, "soma das três (%r)" % fus["consumed_best_h"])
    why = F.evaluate({"fusions": [fus]}, {}, CFG, NOW, DAY)[0][1]
    check("não supera" in why, "resultante abaixo das que somem não sai (%r)" % why)


def test_valor_pelo_planejador_de_verdade():
    """O caso natural com o planejador real (fixture de 29/10): Fogueira vale 0 em toda aldeia."""
    fx = json.load(open(os.path.join(FIX, "relic_planner_state_br143.json"), encoding="utf-8"))
    st = copy.deepcopy(fx["state"])
    fogs = [r for r in state_of(inventory(parked_raw()))["relics"] if r["type"] == "bonfire"]
    st["relics"] += fogs
    plan_fn = lambda s: P.plan(s, fx["coords"], fx["inputs"], now=fx["now"],  # noqa: E731
                               low_loyalty=fx["low_loyalty"], labels=fx["labels"])
    base = plan_fn(st)
    out = F.fusions(st, base, plan_fn)
    fus = same_type(out)
    check(len(fus) == 1 and fus[0]["gain_h"] == 0.0 and fus[0]["result_best_h"] == 0.0,
          "Fogueira Resistente vale 0 no plano real (%r)" % [(f["gain_h"], f["result_best_h"]) for f in fus])
    check(fus and fus[0]["result"] == {"name": "Fogueira Resistente", "range": 2, "main": 6.0,
                                       "subs": [2.0, 2.0]}, "resultado previsto (%r)" % (fus and fus[0]["result"]))


def test_aleatoria_nunca_sai():
    relics = parked_raw(extra_third=False)
    star = copy.deepcopy(next(r for r in relics if str(r["id"]) == FOG_A))
    star.update(id=999002, type="morningstar", name="Estrela d'alva de má qualidade", type_name="Estrela d'alva")
    relics.append(star)
    st = state_of(inventory(relics))
    out = F.fusions(st, base_plan(st), stub_plan(99999.0, best={FOG_A: 9999.0}))
    rnd = [f for f in out["fusions"] if f["kind"] == "random"]
    check(len(rnd) == 1 and len(rnd[0]["relic_ids"]) == 3, "a aleatória aparece só para informar")
    plan = {"fusions": rnd}
    ex = {}
    E.update_streaks(ex, plan, 1)
    E.update_streaks(ex, plan, 2)
    why = F.evaluate(plan, ex, CFG, NOW, DAY)[0][1]
    check(why == F.RANDOM_WHY and F.choose(plan, ex, CFG, NOW, DAY) is None,
          "sem fonte das probabilidades, não sai nem com ganho enorme")
    # Duas travas independentes: mesmo sem o `blocked` gravado (plano de outra
    # versão, cache editado), o tipo da fusão sozinho a segura.
    bare = dict(rnd[0], blocked=None, gain_h=9999.0, gain_alone_h=9999.0, result_best_h=9999.0)
    plan = {"fusions": [bare]}
    E.update_streaks(ex, plan, 3)
    E.update_streaks(ex, plan, 4)
    check(F.choose(plan, ex, CFG, NOW, DAY) is None, "aleatória sem `blocked` também não sai")


def test_teto_por_dia_e_24h():
    st = state_of(inventory(parked_raw()))
    fus = same_type(F.fusions(st, base_plan(st), stub_plan(1120.0, best={FOG_A: 120.0})))[0]
    plan = {"fusions": [fus]}
    ex = {}
    E.update_streaks(ex, plan, 1)
    E.update_streaks(ex, plan, 2)
    E.record(ex, dict(fus, relic_ids=["1", "2", "3"]), True, "feito", NOW - 7200, DAY)
    check(F.fusions_today(ex, DAY) == 1 and E.day_counts(ex, DAY) == (0, 0),
          "fusão conta à parte de mover/equipar")
    check("teto do dia: 1 de 1" in F.evaluate(plan, ex, CFG, NOW, DAY)[0][1], "2ª fusão do dia não sai")
    check(F.choose(plan, ex, CFG, NOW, "2026-10-30") is fus, "dia novo libera")
    E.record(ex, {"action": "equip", "relic_ids": [FOG_B], "from": {}, "to": {}}, True, "feito",
             NOW - 3600, "2026-10-30")
    why = F.evaluate(plan, ex, CFG, NOW, "2026-10-30")[0][1]
    check(why and "o bot mexeu numa delas há 1.0 h" in why, "relíquia que o bot tocou há 1 h (%r)" % why)
    # a fusão não trava o equipar da resultante (é o objetivo dela)
    ex2 = {}
    E.record(ex2, fus, True, "feito", NOW - 60, DAY)
    equip = {"action": "equip", "relic_ids": [FOG_A], "from": {FOG_A: None}, "to": {FOG_A: "41123"},
             "gain_alone_h": 300.0, "value_before_h": 0.0, "text": "equipar"}
    eplan = {"moves": [equip]}
    E.update_streaks(ex2, eplan, 1)
    E.update_streaks(ex2, eplan, 2)
    check(E.choose(eplan, ex2, CFG, NOW, DAY) is equip, "equipar a fundida não espera 24 h")
    check(E.touched_recently(ex2, {FOG_A}, NOW, 24, actions=None), "mas uma nova fusão dela espera")
    check(E.choose(eplan, ex2, CFG, NOW, None) is None and
          "sem relógio" in F.evaluate(plan, {}, dict(CFG, stable_reads=0), NOW, None)[0][1],
          "sem relógio do servidor: não age")


def test_reconferencia():
    st = state_of(inventory(parked_raw()))
    fus = same_type(F.fusions(st, base_plan(st), stub_plan(0)))[0]
    check(F.precheck(fus, inventory(parked_raw())) == (None, None), "igual ao plano: age")
    gone = [r for r in parked_raw() if str(r["id"]) != FOG_B]
    why, kind = F.precheck(fus, inventory(gone))
    check(kind == "diverge" and "não está mais" in why, "o usuário fundiu uma delas")
    equipped = parked_raw()
    next(r for r in equipped if str(r["id"]) == FOG_C)["village_id"] = 41123
    why, kind = F.precheck(fus, inventory(equipped))
    check(kind == "diverge" and "equipada" in why, "o usuário equipou uma delas")
    changed = parked_raw()
    r = next(r for r in changed if str(r["id"]) == FOG_A)
    r["quality"] = "polished"
    why, kind = F.precheck(fus, inventory(changed))
    check(kind == "diverge" and "não é a do plano" in why, "a principal mudou (fundida pelo usuário)")
    traded = parked_raw()
    next(r for r in traded if str(r["id"]) == FOG_B)["trade_offer_id"] = 5
    check(F.precheck(fus, inventory(traded))[1] == "recusa", "em troca: recusa")
    check(F.precheck(fus, None)[1] == "diverge", "sem releitura: não age")


def test_resultado_conferido():
    st = state_of(inventory(parked_raw()))
    fus = same_type(F.fusions(st, base_plan(st), stub_plan(0)))[0]
    main = fus["relic_ids"][0]
    after = [r for r in parked_raw() if str(r["id"]) not in fus["relic_ids"][1:]]
    r = next(r for r in after if str(r["id"]) == main)
    r.update(quality="polished", range=2)
    r["main_stat"] = dict(r["main_stat"], name=r["main_stat"]["name"].replace("+5%", "+6%"))
    for s in r["sub_stats"]:
        s["name"] = s["name"].replace("+1%", "+2%")
    verdict, detail = F.check_result(fus, inventory(after))
    check(verdict == "ok" and detail == "como previsto", "fundida como previsto (%r, %r)" % (verdict, detail))
    r["main_stat"] = dict(r["main_stat"], name=r["main_stat"]["name"].replace("+6%", "+7%"))
    verdict, detail = F.check_result(fus, inventory(after))
    check(verdict == "ok" and "diferente da tabela" in detail, "valor fora da tabela fica registrado")
    check(F.check_result(fus, inventory(parked_raw()))[0] == "none", "nada mudou")
    check(F.check_result(fus, inventory([x for x in parked_raw() if str(x["id"]) != fus["relic_ids"][1]]))[0]
          == "changed", "material sumiu e a principal não subiu: mudou, mas não como previsto")


# -- RelicManager -------------------------------------------------------------------

class FakeWrapper:
    def __init__(self):
        self.calls = []
        self.last_h = "h0"
        self.pages = {}
        self.posts = []

    def get_url(self, url):
        self.calls.append(("GET", url))
        vid = re.search(r"village=(\d+)", url).group(1)
        text = self.pages.get(vid)
        return type("Res", (), {"text": text})() if text is not None else None

    def get_api_action(self, village_id, action, params=None, data=None):
        self.calls.append(("POST", village_id, action, dict(params or {}), dict(data or {})))
        return self.posts.pop(0) if self.posts else None


def _manager(fus, tmp, fuse=True):
    RM.CACHE_PATH = os.path.join(tmp, "relics.json")
    RM.DEBUG_DIR = os.path.join(tmp, "debug")
    man = RM.RelicManager(wrapper=FakeWrapper(), config={"relics": {"enabled": True, "manage": True,
                                                                    "fuse": fuse}})
    now = datetime.datetime.now()
    plan = {"moves": [], "fusions": [fus]}
    state = {"fetched_at": int(now.timestamp()), "server_time": int(now.timestamp()),
             "plan": plan, "exec": {}}
    E.update_streaks(state["exec"], plan, 1)
    E.update_streaks(state["exec"], plan, 2)
    man.state = state
    man._coords = {}
    man._read_village = "44683"
    return man


def _good_fusion():
    st = state_of(inventory(parked_raw()))
    return same_type(F.fusions(st, base_plan(st), stub_plan(1120.0, best={FOG_A: 120.0})))[0]


def envelope(relics, host="44683", can_equip=True):
    return {"response": {"relics": relics, "village_id": int(host), "can_equip": can_equip},
            "game_data": {"village": {"id": int(host)}}}


def _fused(fus):
    after = [r for r in parked_raw() if str(r["id"]) not in fus["relic_ids"][1:]]
    r = next(r for r in after if str(r["id"]) == fus["relic_ids"][0])
    r.update(quality="polished", range=2, name="Fogueira Resistente")
    r["main_stat"] = dict(r["main_stat"], name=r["main_stat"]["name"].replace("+5%", "+6%"))
    for s in r["sub_stats"]:
        s["name"] = s["name"].replace("+1%", "+2%")
    return after


def test_act_funde():
    tmp = tempfile.mkdtemp()
    fus = _good_fusion()
    man = _manager(fus, tmp)
    w = man.wrapper
    w.pages["44683"] = page(parked_raw())
    check(man.candidate() is None and man.fusion_candidate() is fus, "sem mover/equipar: a fusão é a candidata")
    w.posts = [envelope(_fused(fus))]
    check(man.act() is True, "fundiu")
    check([c[0] for c in w.calls] == ["GET", "POST"], "1 GET de reconferência + 1 POST (%r)" % w.calls)
    post = w.calls[1]
    check(post[2] == "upgrade_relic" and post[3]["screen"] == "relic_system"
          and post[4] == {"relic_ids[]": fus["relic_ids"]}, "POST upgrade_relic com relic_ids[] (%r)" % (post,))
    check(not any(k.startswith("material") for k in post[4]), "nunca manda componente")
    day = E.server_day(man.state, datetime.datetime.now().timestamp())
    check(F.fusions_today(man.state["exec"], day) == 1, "contou 1 fusão no dia do servidor")
    entry = man.state["exec"]["history"][-1]
    check(entry["action"] == "fuse" and entry["ok"] and entry["detail"] == "feito", "histórico (%r)" % entry)
    main = next(r for r in man.state["relics"] if r["id"] == fus["relic_ids"][0])
    check(main["quality"] == "polished" and not any(r["id"] in fus["relic_ids"][1:] for r in man.state["relics"]),
          "a resposta virou o estado novo")
    raw = os.path.join(tmp, "debug", "action_upgrade_relic.json")
    check(os.path.exists(raw) and json.load(open(raw, encoding="utf-8"))["response"]["relics"],
          "primeira resposta crua salva")
    check(man.state["plan"].get("stale") and man.fusion_candidate() is None, "nada mais sai do plano velho")


def test_resposta_crua_so_a_primeira():
    tmp = tempfile.mkdtemp()
    man = _manager(_good_fusion(), tmp)
    man.wrapper.posts = [{"primeira": 1}, {"segunda": 2}]
    man._post("equip_relic", "44683", {"relic_id": "1"})
    man._post("equip_relic", "44683", {"relic_id": "1"})
    saved = json.load(open(os.path.join(tmp, "debug", "action_equip_relic.json"), encoding="utf-8"))
    check(saved == {"primeira": 1}, "a segunda não sobrescreve (%r)" % saved)


def test_act_recusa_ajax():
    tmp = tempfile.mkdtemp()
    fus = _good_fusion()
    man = _manager(fus, tmp)
    w = man.wrapper
    w.pages["44683"] = page(parked_raw())
    w.posts = [{"error": ["Não é possível aprimorar estas relíquias."]}]
    check(man.act() is False, "recusa não é fusão feita (A26-09)")
    entry = man.state["exec"]["history"][-1]
    check(entry["ok"] is False and "recusou fundir" in entry["detail"], "motivo no histórico")
    check(F.fusions_today(man.state["exec"], E.server_day(man.state, datetime.datetime.now().timestamp())) == 0,
          "recusa não conta no dia")
    check(E.move_key(fus) in man.state["exec"]["skip"], "fica congelada")
    check(len(w.calls) == 2, "sem GET de confirmação depois de recusa")


def test_act_inventario_mudou_nao_age():
    tmp = tempfile.mkdtemp()
    fus = _good_fusion()
    man = _manager(fus, tmp)
    w = man.wrapper
    w.pages["44683"] = page([r for r in parked_raw() if str(r["id"]) != FOG_B])  # o usuário fundiu
    check(man.act() is False, "não age")
    check([c[0] for c in w.calls] == ["GET"], "nenhum POST")
    check(man.pending == "inventário diverge do plano de fusão", "pede releitura")


def test_act_desligada():
    tmp = tempfile.mkdtemp()
    man = _manager(_good_fusion(), tmp, fuse=False)
    man.wrapper.pages["44683"] = page(parked_raw())
    check(man.fusion_candidate() is None and man.act() is False and not man.wrapper.calls,
          "relics.fuse desligado: 0 requisição")
    man = _manager(_good_fusion(), tempfile.mkdtemp())
    man.config = {"relics": {"enabled": True, "manage": False, "fuse": True}}
    check(man.fuse is False and man.act() is False and not man.wrapper.calls,
          "fuse sem manage não age (a resultante não seria equipada)")
    check(E.settings({})["fuse"] is False and E.settings({})["max_fusions_per_day"] == 1, "padrões")


def test_nunca_pp():
    tmp = tempfile.mkdtemp()
    man = _manager(_good_fusion(), tmp)
    w = man.wrapper
    for action in F.PP_ACTIONS:
        check(action not in F.ALLOWED_POSTS, "%s fora da lista branca" % action)
        res = man._post(action, "44683", {"relic_ids[]": [FOG_A, FOG_B]})
        check(Extractor.ajax_error(res), "%s vira recusa local" % action)
    check(Extractor.ajax_error(man._post("upgrade_relic", "44683", {"relic_ids[]": [FOG_A, FOG_B]})),
          "fusão com 2 relíquias (o formato da premium) recusada")
    check(Extractor.ajax_error(man._post("upgrade_relic", "44683",
                                         {"relic_ids[]": [FOG_A], "material_qualities[]": ["shoddy"] * 2})),
          "componente recusado")
    check(Extractor.ajax_error(man._post("upgrade_relic", "44683", {"relic_ids[]": [FOG_A, FOG_A, FOG_B]})),
          "id repetido recusado")
    check(not w.calls, "nada disso tocou a rede (%r)" % w.calls)
    src = open(os.path.join(ROOT, "game", "relic_manager.py"), encoding="utf-8").read()
    for action in F.PP_ACTIONS:
        check('"%s"' % action not in src, "relic_manager não chama %s" % action)


if __name__ == "__main__":
    import logging
    logging.disable(logging.CRITICAL)
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except Exception as exc:
                import traceback
                traceback.print_exc()
                failures.append("%s levantou %r" % (name, exc))
    if failures:
        print("FALHAS (%d):" % len(failures))
        for f in failures:
            print(" -", f)
        sys.exit(1)
    print("OK: relíquias, Fase 4 (tabela, elegibilidade, valor, aleatória, teto, reconferência, nunca PP)")
