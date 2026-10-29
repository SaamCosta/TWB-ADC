"""
Relíquias, Fase 2 (docs/backend.md §8.77): o planejador `core/relic_planner.py`.

Fixture `relic_planner_state_br143.json`: o estado real de 29/10/2026 (as 12
relíquias de `cache/relics.json`, vagas 5/8, `can_equip`), as coordenadas das
67 aldeias da conta, as entradas medidas (reporter de 7 dias, nobres do Hunter
de 14 dias, velocidade 1) e as aldeias com lealdade < 100. Sem dado de jogador.

Cobre: teto/saturação no aglomerado BBM 001-010, anfitriã inelegível (cooldown,
lealdade, já tem relíquia), vaga cheia, atributo de valor 0 que não decide
nada, e o primeiro resultado esperado (equipar as paradas). Mais os leitores de
disco (reporter, nobres, velocidade do mundo) contra recortes sintéticos.

Sem rede. Rodar: python tests/test_relic_planner.py
"""
import copy
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import relic_planner as P  # noqa: E402
from core.world_config import WorldConfig  # noqa: E402

FIX = os.path.join(ROOT, "tests", "fixtures", "relic_planner_state_br143.json")
failures = []

# O aglomerado BBM 001-010 (K35) e as anfitriãs de 29/10.
CLUSTER = ["38409", "38997", "39292", "41123", "41283", "44683", "74689"]
SELA, PICARETA, MOCHILA = "310487", "1126953", "297445"
BONECOS = ["863230", "573838"]
PARADAS_COM_VALOR = {"1199783": "Ferradura Resistente", "1105799": "Alabarba Resistente"}
PARADAS_SEM_VALOR = {"377483": "Estrela d'alva de má qualidade", "1193326": "Boneco de má qualidade"}


def check(cond, msg):
    if not cond:
        failures.append(msg)


def fixture():
    with open(FIX, encoding="utf-8") as fh:
        return json.load(fh)


def run(fx, **kw):
    return P.plan(fx["state"], fx["coords"], fx["inputs"], now=fx["now"],
                  low_loyalty=kw.pop("low_loyalty", fx["low_loyalty"]), labels=fx["labels"], **kw)


def relic(fx, rid):
    return next(r for r in fx["state"]["relics"] if r["id"] == rid)


# -- classificação e valor por atributo ------------------------------------------

def test_classifica_o_texto_do_jogo():
    cases = {
        "na produção de ferro": ("production", "iron"),
        "na produção de madeira": ("production", "wood"),
        "na produção de argila": ("production", "stone"),
        "Quartel nos custos de recrutamento": ("recruit_cost", "barracks"),
        "Oficina nos custos de recrutamento": ("recruit_cost", "garage"),
        "nos custos de recrutamento dos nobres": ("noble_cost", None),
        "Estábulo na velocidade de recrutamento": ("recruit_speed", "stable"),
        "na velocidade de construção": ("build_speed", None),
        "na velocidade de viagem do mercador": ("merchant_speed", None),
        "Lanceiro: poder de ataque e defesa": ("combat", None),
        "Explorador: escondido": ("combat", None),
        "Catapulta: dano contra edifícios": ("combat", None),
        "algo que o jogo ainda não mostrou": ("unknown", None),
    }
    for key, (kind, detail) in cases.items():
        spec = P.classify(key)
        check(spec["kind"] == kind, "%s -> %s (veio %s)" % (key, kind, spec))
        if detail:
            check(detail in spec.values(), "%s -> %s (veio %s)" % (key, detail, spec))


def test_zero_tem_motivo_e_nunca_peso():
    inputs = {"base_prod_h": {"wood": 2400.0, "stone": 2400.0, "iron": 2400.0},
              "cap_frac": {"iron": 1.0}, "recruit_h": {"barracks": 300.0},
              "recruit_busy": {"barracks": 0.22}, "build_busy": 0.95, "nobles_h": 0.0}
    for key in ("Lanceiro: poder de ataque", "na velocidade de viagem do mercador",
                "Quartel na velocidade de recrutamento", "na velocidade de construção",
                "nos custos de recrutamento dos nobres", "na produção de ferro",
                "Estábulo nos custos de recrutamento"):
        rate, why = P.attribute_rate(P.classify(key), inputs)
        check(rate == 0 and why, "%s vale 0 com motivo (%r, %r)" % (key, rate, why))
    rate, _ = P.attribute_rate(P.classify("na produção de madeira"), inputs)
    check(abs(rate - 24.0) < 1e-9, "madeira livre: 2400/h por 100 pontos = 24/h por ponto (%r)" % rate)
    rate, _ = P.attribute_rate(P.classify("Quartel nos custos de recrutamento"), inputs)
    check(abs(rate - 3.0) < 1e-9, "desconto de quartel = gasto/h / 100 (%r)" % rate)
    busy = dict(inputs, recruit_busy={"barracks": 0.95})
    rate, _ = P.attribute_rate(P.classify("Quartel na velocidade de recrutamento"), busy)
    check(rate > 0, "velocidade de quartel só vale com a fila como gargalo")


def test_producao_censurada_pelo_armazem():
    inputs = {"base_prod_h": {"wood": 2400.0, "stone": 2400.0, "iron": 2400.0},
              "cap_frac": {"iron": 0.75}}
    rate, _ = P.attribute_rate(P.classify("na produção de ferro"), inputs)
    check(abs(rate - 6.0) < 1e-9, "ferro no teto em 75%% das leituras: vale 1/4 (%r)" % rate)


def test_formula_da_mina():
    check(abs(P.mine_production(30, 1.0) - 2400.0) < 1.0, "nível 30, velocidade 1: ~2400/h")
    check(abs(P.mine_production(30, 2.0) - 2 * P.mine_production(30, 1.0)) < 1e-6,
          "a velocidade do mundo multiplica")


# -- teto e saturação --------------------------------------------------------------

def test_teto_satura_no_aglomerado():
    fx = fixture()
    # Taxa sintética de velocidade de quartel em toda aldeia (fila como gargalo):
    # o aglomerado já soma 25% com os dois Bonecos e a Picareta, então uma
    # relíquia de quartel a mais ali vale 0; fora dele, vale.
    key = "Quartel na velocidade de recrutamento"
    rates = {vid: {key: 10.0} for vid in fx["coords"]}
    model = P.Model(fx["coords"], rates)
    relics = P._relic_table(fx["state"], fx["now"])
    alloc = {rid: r["host"] for rid, r in relics.items()}
    sums = model.sums(alloc, relics)
    for vid in ("38409", "41123", "44683", "74689"):
        check(sums[vid][key] >= 20, "%s já tem %g%% de quartel" % (vid, sums[vid][key]))
    base = model.value(alloc, relics)
    trial = dict(alloc)
    trial["1193326"] = "38409"           # Boneco de má qualidade (+5% quartel), alcance 2
    gain_cluster = model.value(trial, relics) - base
    check(abs(gain_cluster) < 1e-9, "quartel a mais no aglomerado vale 0 (%r)" % gain_cluster)
    trial["1193326"] = "44620"           # BBM 013, fora do aglomerado
    check(model.value(trial, relics) - base > 0, "fora do aglomerado vale")
    # E o teto vale só para a parte das relíquias: 25% somado conta como 20%.
    check(abs(base - sum(min(20.0, s.get(key, 0.0)) * 10.0 for s in sums.values())) < 1e-6,
          "valor = taxa x min(20, soma)")


def test_valor_marginal_respeita_o_que_ja_esta_la():
    fx = fixture()
    rates = {vid: {"na produção de ferro": 24.0} for vid in fx["coords"]}
    model = P.Model(fx["coords"], rates)
    relics = P._relic_table(fx["state"], fx["now"])
    alloc = {rid: r["host"] for rid, r in relics.items()}
    base = model.value(alloc, relics)
    trial = dict(alloc, **{PICARETA: None})
    lost = base - model.value(trial, relics)
    covered = len(model.cover(relic(fx, PICARETA)["village_id"], 4))
    check(abs(lost - 24.0 * 10 * covered) < 1e-6,
          "Picareta (+10%% ferro) vale 24 x 10 x %d aldeias (%r)" % (covered, lost))


# -- elegibilidade ----------------------------------------------------------------

def test_relicas_presas_nao_saem():
    fx = fixture()
    out = run(fx)
    by_id = {r["id"]: r for r in out["relics"]}
    check(by_id[SELA]["fixed"] and "removível" in by_id[SELA]["fixed"], "Sela em cooldown fica")
    check(by_id[SELA]["target_host"] == relic(fx, SELA)["village_id"], "Sela não se mexe")
    for rid in ("157444", "238187"):
        check(by_id[rid]["fixed"] and "inativa" in by_id[rid]["fixed"], "%s inativa fica" % rid)
        check(rid not in out["target"], "inativa não conta como disponível nem ocupa vaga")
    moved = {i for m in out["moves"] for i in m["relic_ids"]}
    check(not moved & {SELA, "157444", "238187"}, "nenhum passo mexe em relíquia presa")


def test_lealdade_baixa_nao_recebe():
    fx = fixture()
    out = run(fx)
    low = set(fx["low_loyalty"])
    check({"69630", "88755"} <= low, "as duas anfitriãs das inativas têm lealdade < 100")
    check(not set(out["target"].values()) & (low - {relic(fx, r)["village_id"] for r in ("157444", "238187")}),
          "nenhuma relíquia vai para aldeia com lealdade < 100")
    # Forçando: a melhor anfitriã da Ferradura com lealdade baixa sai da lista.
    best = next(r for r in out["relics"] if r["id"] == "1199783")["best_hosts"][0]["vid"]
    out2 = run(fx, low_loyalty=dict(fx["low_loyalty"], **{best: "teste"}))
    check(best not in out2["target"].values(), "anfitriã com lealdade baixa deixa de ser escolhida")


def test_anfitria_com_reliquia_nao_recebe_outra():
    fx = fixture()
    out = run(fx)
    hosts = [h for h in out["target"].values()]
    check(len(hosts) == len(set(hosts)), "uma relíquia por anfitriã (%r)" % hosts)
    check(relic(fx, SELA)["village_id"] not in
          [h for rid, h in out["target"].items() if rid != SELA], "a anfitriã da Sela fica com ela")


def test_vaga_cheia():
    fx = fixture()
    fx["state"]["slots"] = dict(fx["state"]["slots"], total=5)
    out = run(fx)
    check(out["slots"]["used_after"] <= 5, "não passa de 5 vagas (%r)" % out["slots"])
    check(all(m["action"] != "equip" for m in out["moves"]), "sem vaga, nada de equipar direto")
    fx2 = fixture()
    fx2["state"]["can_equip"] = False
    out2 = run(fx2)
    check(out2["slots"]["used_after"] == 5, "can_equip falso: as 5 ativas e nenhuma a mais")


# -- o plano ----------------------------------------------------------------------

def test_valor_zero_nao_decide():
    fx = fixture()
    out = run(fx)
    by_id = {r["id"]: r for r in out["relics"]}
    for rid, name in PARADAS_SEM_VALOR.items():
        check(by_id[rid]["target_host"] is None, "%s (só combate/velocidade sem gargalo) fica parada" % name)
        check(all(b["value"] == 0 for b in by_id[rid]["best_hosts"]), "%s vale 0 em toda parte" % name)
    for rid in BONECOS:
        check(rid not in {i for m in out["moves"] for i in m["relic_ids"]},
              "Boneco Reconhecido (valor 0) não é mexido")
    # Acrescentar atributo de combate não muda o valor de ninguém.
    fx2 = fixture()
    for r in fx2["state"]["relics"]:
        r["subs"] = list(r["subs"] or []) + [{"key": "Arqueiro: poder de defesa", "value": 9.0,
                                              "text": "Arqueiro: +9% poder de defesa"}]
    out2 = run(fx2)
    check(abs(out2["value_after"] - out["value_after"]) < 1e-6 and
          [m["text"] for m in out2["moves"]] == [m["text"] for m in out["moves"]],
          "atributo de combate não muda nem o valor nem o plano")


def test_equipar_as_paradas():
    fx = fixture()
    out = run(fx)
    check(out["slots"] == {"total": 8, "used_now": 5, "used_after": 8}, "3 vagas livres preenchidas (%r)" % out["slots"])
    equipped = {m["relic_ids"][0] for m in out["moves"] if m["action"] == "equip"}
    for rid, name in PARADAS_COM_VALOR.items():
        check(rid in equipped, "%s é equipada" % name)
    check(out["gain"] > 0 and out["value_after"] > out["value_now"], "o plano ganha")
    check(out["summary"].startswith("faria: "), out["summary"])
    total = sum(m["gain_h"] for m in out["moves"])
    check(abs(total - out["gain"]) < 1.0, "ganhos dos passos somam o ganho total")
    check(all(m["gain_h"] >= P.MIN_GAIN for m in out["moves"]), "nenhum passo abaixo do mínimo")
    ids = [i for m in out["moves"] for i in m["relic_ids"]]
    check(len(ids) == len(set(ids)), "cada relíquia mexe no máximo uma vez no plano")


def test_sem_nada_a_ganhar():
    fx = fixture()
    for vid in fx["inputs"]:
        fx["inputs"][vid] = {}
    out = run(fx)
    check(out["moves"] == [] and out["summary"] == "nada a fazer", out["summary"])


def test_aldeia_sem_managed_entra_com_o_que_se_sabe():
    inputs = P.village_inputs(["1", "2"], {"1": {"buidling_levels": {"wood": 30}, "storage": 1000}},
                              {"pre": [], "recruit": [], "build": []}, {}, now=1e9, speed=1.0)
    check(inputs["2"]["base_prod_h"] is None and inputs["2"]["missing"], "sem managed: diz o que falta")
    check(inputs["1"]["base_prod_h"]["wood"] > 2000, "com managed: produção pelo nível")
    no_speed = P.village_inputs(["1"], {"1": {"buidling_levels": {"wood": 30}}},
                                {}, {}, now=1e9, speed=None)
    check(no_speed["1"]["base_prod_h"] is None and any("velocidade" in m for m in no_speed["1"]["missing"]),
          "sem velocidade do mundo: não inventa produção")


# -- leitores de disco -----------------------------------------------------------

def test_leitor_do_reporter():
    tmp = tempfile.mkdtemp()
    now = 1793250000
    lines = [
        "%d - 111 - TWB_RECRUIT - Recruitment of 25 axe started (barracks idle till %d)" % (now - 7200, now - 3600),
        "%d - 111 - TWB_RECRUIT - Recruitment of 25 axe started (barracks idle till %d)" % (now - 5400, now - 1800),
        "%d - 111 - TWB_PRE_RESOURCE - {'wood': 1000, 'stone': 5, 'iron': 1000, 'pop': 9}" % (now - 100),
        "%d - 111 - TWB_PRE_RESOURCE - {'wood': 10, 'stone': 5, 'iron': 1000, 'pop': 9}" % (now - 50),
        "%d - 111 - TWB_RECRUIT - Recruitment of 99 axe started (barracks idle till %d)" % (now - 30 * 86400, now),
        "lixo sem formato",
    ]
    with open(os.path.join(tmp, "twb_1.log"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    ev = P.read_reporter(tmp, now)
    check(len(ev["recruit"]) == 2, "fora da janela não entra (%r)" % ev["recruit"])
    check(len(ev["pre"]) == 2, "duas leituras de recurso")
    inputs = P.village_inputs(["111"], {"111": {"buidling_levels": {}, "storage": 1000}}, ev, {},
                              now=now, speed=1.0)
    e = inputs["111"]
    check(e["recruit_units"]["barracks"]["axe"] == 50, "50 machados")
    check(abs(e["recruit_h"]["barracks"] - 50 * 130 / (7 * 24.0)) < 1e-6,
          "gasto/h = 50 x 130 / 168 h (%r)" % e["recruit_h"])
    check(abs(e["recruit_busy"]["barracks"] - 5400 / (7 * 86400.0)) < 1e-9,
          "intervalos sobrepostos contam uma vez (%r)" % e["recruit_busy"])
    check(e["cap_frac"] == {"wood": 0.5, "stone": 0.0, "iron": 1.0}, "teto por recurso (%r)" % e["cap_frac"])


def test_custo_medido_vence_a_tabela():
    cost, src = P.unit_cost("spear", {})
    check(cost == (50, 30, 10) and "não medida" in src, "sem leitura: tabela, marcada")
    cost, src = P.unit_cost("spear", {"spear": {"wood": 50, "stone": 30, "iron": 20, "vid": "1"}})
    check(cost == (50, 30, 20) and "tela" in src, "com leitura: o número lido")


def test_nobres_do_hunter():
    now = 1793250000
    schedules = {
        "a": {"attacks": [
            {"source_village_id": "1", "status": "sent", "sent_at": now - 3600, "troops": {"snob": 1}},
            {"source_village_id": "1", "status": "failed", "sent_at": now - 3600, "troops": {"snob": 1}},
            {"source_village_id": "2", "status": "sent", "sent_at": now - 20 * 86400, "troops": {"snob": 1}},
            {"source_village_id": "3", "status": "sent", "sent_at": now - 60, "troops": {"axe": 9}},
        ]},
    }
    check(P.noble_departures(schedules, now) == {"1": 1}, "só nobre que saiu, na janela")


def test_lealdade_estimada():
    now = 1793250000
    conquests = {"5": {"status": "conquered", "last_hit_timestamp": now - 10 * 3600},
                 "6": {"status": "conquered", "last_hit_timestamp": now - 100 * 3600},
                 "7": {"status": "train_sent", "last_hit_timestamp": now}}
    low = P.low_loyalty_hosts({"relics": []}, conquests, now, regen=1.0)
    check(set(low) == {"5"}, "25 + 10 h = 35 < 100; 100 h depois já é 100 (%r)" % low)


def test_velocidade_do_mundo():
    xml = "<config>\n<speed>1.4</speed>\n<unit_speed>0.75</unit_speed>\n</config>"
    check(WorldConfig._parse_speed(xml) == 1.4, "lê <speed>, não <unit_speed>")
    check(WorldConfig._parse_speed("<config><unit_speed>1</unit_speed></config>") is None, "sem tag: None")
    check(P.world_speed({"speed": 1.0}) == 1.0 and P.world_speed({}) is None, "world_speed do cache")


def test_plano_serializavel():
    fx = fixture()
    out = run(fx)
    json.dumps(out)
    check(copy.deepcopy(out) == out, "dict puro")


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
    print("OK")
