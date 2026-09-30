"""
Apoio a membros da tribo (docs/backend.md §8.39).

1. Leitura do tópico do fórum -- fixture do br143 (2026-09-29) com o markup
   verbatim e os jogadores anonimizados, porque o repositório é público e o
   fórum da tribo não é.
2. Saldo: tabela menos as respostas postadas DEPOIS da última edição dela.
3. Texto colado: BBCode, uma aldeia por linha, texto livre com rótulo.
4. Planejador: origem sob ataque fica fora, exposta só com pedido explícito,
   a mais segura é usada primeiro, reserva respeitada, teto de viagem tira a
   unidade lenta.
5. Ciclo de vida do plano: proposto -> aprovado -> dispatching -> enviado,
   adiamento sem gastar a aprovação, validade de 24 h, e `dispatching` nunca
   é reclamado de novo (sem reenvio às cegas).
6. Executor da aldeia: manda exatamente o aprovado ou nada.

Rodar: python tests/test_tribe_support.py
"""
import os
import shutil
import sys
import tempfile
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import support_store  # noqa: E402
from core.support_planner import plan_support  # noqa: E402
from core.support_request import (forum_link_ids, parse_forum_thread,  # noqa: E402
                                  parse_pasted_text, remaining, reply_text)

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


with open(os.path.join(ROOT, "tests", "fixtures", "forum_support_thread_br143.html"),
          encoding="utf-8") as fh:
    THREAD = fh.read()

# -- 1/2. tópico e saldo ------------------------------------------------------
p = parse_forum_thread(THREAD)
check(p is not None, "fixture do topico nao foi reconhecida")
p = p or {}
check(len(p.get("requests", [])) == 36, "36 aldeias na tabela, veio %d" % len(p.get("requests", [])))
check(p.get("unit_order") == ["spear", "sword", "spy", "heavy"],
      "colunas da tabela: %r" % p.get("unit_order"))
check(p.get("table_updated_at") == "2026-09-29T19:34:00",
      "edicao da tabela ('Editado ... hoje as 19:34'): %r" % p.get("table_updated_at"))
check(p.get("is_last_page") is True, "topico de pagina unica")
first = (p.get("requests") or [{}])[0]
check(first.get("num") == 1 and (first.get("x"), first.get("y")) == (776, 536)
      and first.get("village_id") == "89733", "primeira linha: %r" % first)
check(first.get("need") == {"spear": 0, "sword": 0, "spy": 50, "heavy": 3000},
      "pedido da primeira linha: %r" % first.get("need"))
after = [r for r in p.get("replies", []) if r["after_update"]]
check(len(after) == 2, "duas respostas depois da edicao (19:35 e 19:36), veio %d" % len(after))
rem = {r["num"]: r for r in remaining(p)}
check(rem[15]["missing"] == {"spear": 5000, "sword": 5500, "spy": 1000, "heavy": 3000},
      "#15: 6000/6000/1000/3000 menos 1000/500: %r" % rem[15]["missing"])
check(rem[10]["missing"] == {"spear": 0, "sword": 0, "spy": 600, "heavy": 800},
      "#10: resposta maior que o pedido nao fica negativa: %r" % rem[10]["missing"])
check(parse_forum_thread("<html>login</html>") is None, "tela que nao e topico devia ser None")

# Resposta ANTES da edicao ja esta na tabela: nao desconta de novo.
early = THREAD.replace("hoje às 19:35", "hoje às 19:20")
check(remaining(parse_forum_thread(early))[14]["missing"]["spear"] == 6000,
      "resposta anterior a edicao nao pode ser descontada de novo")
# Mesmo minuto: conta como nao descontada, marcada ambigua.
same = parse_forum_thread(THREAD.replace("hoje às 19:35", "hoje às 19:34"))
amb = [r for r in same["replies"] if r["ambiguous"]]
check(len(amb) == 1 and amb[0]["after_update"], "mesmo minuto da edicao: ambigua e descontada")

check(forum_link_ids("https://br143.tribalwars.com.br/game.php?village=41123&screen=forum"
                     "&screenmode=view_thread&forum_id=2513&thread_id=1639") == ("2513", "1639"),
      "ids do link do forum")
check(forum_link_ids("https://example.com/?forum_id=1&thread_id=2") is None,
      "link sem screen=forum nao e topico")

# -- 3. texto colado ----------------------------------------------------------
t = parse_pasted_text("Preciso de 3000 pesada e 1000 lança em 776|536")
check([r["need"] for r in t["requests"]] == [{"heavy": 3000, "spear": 1000}],
      "texto livre com rotulo: %r" % t["requests"])
t = parse_pasted_text("01 JvzzYx #06 (776|536) K57 0 0 50 3000\n02 SFC 003 (730|522) K57 2480 3555 210 1425")
check([(r["num"], r["need"]) for r in t["requests"]] ==
      [(1, {"spy": 50, "heavy": 3000}),
       (2, {"spear": 2480, "sword": 3555, "spy": 210, "heavy": 1425})],
      "uma aldeia por linha (o '#06' do nome e o 'K57' nao sao numeros do pedido): %r"
      % [(r["num"], r["need"]) for r in t["requests"]])
t = parse_pasted_text("[table][**]Número[||]ALDEIA DESTINO[||]Espada[||]Cav. Pesada[/**]"
                      "[*]01[|][coord]776|536[/coord][|]100[|]3000[/table]")
check(t["unit_order"] == ["sword", "heavy"] and t["requests"][0]["need"] == {"sword": 100, "heavy": 3000},
      "BBCode respeita a ordem do cabecalho: %r" % t)
check(parse_pasted_text("sem coordenada nenhuma")["error"], "texto sem x|y e erro")
check(reply_text([(15, {"spear": 1000, "sword": 500}), (15, {"heavy": 10}), (3, {"spy": 5})],
                 ["spear", "sword", "spy", "heavy"]) == "03/0/0/5/0\n15/1000/500/0/10",
      "resposta no formato do organizador, somada por aldeia")

# -- 4. planejador ------------------------------------------------------------
SPEEDS = {"spear": 18.0, "sword": 22.0, "spy": 9.0, "heavy": 11.0}
sources = [
    {"vid": "exp", "name": "Exposta", "x": 100, "y": 100, "home": {"spear": 5000}},
    {"vid": "safe", "name": "Segura", "x": 500, "y": 500, "home": {"spear": 1000, "heavy": 100}},
    {"vid": "atk", "name": "Atacada", "x": 510, "y": 500, "home": {"spear": 9000},
     "under_attack": True, "incoming_eta": 3600},
    {"vid": "cau", "name": "Atencao", "x": 300, "y": 300, "home": {"spear": 1000}},
]
hostiles = [
    {"x": 102, "y": 100, "points": 9000, "relation": "enemy"},   # colado na Exposta
    {"x": 310, "y": 300, "points": 5000, "relation": "other"},   # a 10 da Atencao
    {"x": 505, "y": 500, "points": 9000, "relation": "partner"},  # aliado nao pesa
]
reqs = [{"num": 1, "name": "A", "x": 520, "y": 500, "missing": {"spear": 1500, "heavy": 80}}]
res = plan_support(reqs, sources, hostiles, SPEEDS, {"reserve_pct": 0.2})
tiers = {s["vid"]: s["tier"] for s in res["sources"]}
check(tiers == {"exp": "exposed", "safe": "safe", "atk": "excluded", "cau": "caution"},
      "classificacao: %r" % tiers)
check([s["vid"] for s in res["sources"]] == ["safe", "cau", "exp", "atk"], "ordem de seguranca")
by_src = {l["source_vid"]: l["troops"] for l in res["lines"]}
check(by_src.get("safe") == {"spear": 800, "heavy": 80},
      "a segura doa primeiro, deixando 20%% (1000 -> 800): %r" % by_src.get("safe"))
check(by_src.get("cau") == {"spear": 700}, "o resto sai da 'atencao': %r" % by_src.get("cau"))
check("atk" not in by_src and "exp" not in by_src, "atacada e exposta fora do plano")
check(res["uncovered"] == [], "pedido coberto")
res = plan_support([dict(reqs[0], missing={"spear": 9000})], sources, hostiles, SPEEDS,
                   {"reserve_pct": 0.2, "include_exposed": True})
check("exp" in {l["source_vid"] for l in res["lines"]}, "exposta entra quando pedido")
check("atk" not in {l["source_vid"] for l in res["lines"]}, "atacada NUNCA entra")
check(res["uncovered"] and res["uncovered"][0]["missing"]["spear"] == 9000 - 800 - 800 - 4000,
      "falta que sobra: %r" % res["uncovered"])
# Teto de viagem: a 20 campos, lanca leva 6 h e pesada 3,7 h. Teto de 5 h tira a lanca.
far = [{"num": 1, "name": "B", "x": 500, "y": 520, "missing": {"spear": 100, "heavy": 10}}]
res = plan_support(far, sources[1:2], [], SPEEDS, {"max_travel_hours": 5})
check(res["lines"] and res["lines"][0]["troops"] == {"heavy": 10},
      "teto de 5 h tira a lanca e mantem a pesada: %r" % res["lines"])

# Conta abandonada de 26 pontos colada na origem nao e ameaca (o caso real
# que punha todas as aldeias do usuario em "atencao", hostil a 1 campo).
ghost = [{"x": 501, "y": 500, "points": 26, "relation": "other"}]
res = plan_support(reqs, sources[1:2], ghost, SPEEDS, {})
check(res["sources"][0]["tier"] == "safe" and res["sources"][0]["nearest_hostile"] is None,
      "26 pontos abaixo do piso de 500: %r" % res["sources"][0])
# Menos comandos: dentro da mesma faixa, a origem que cobre mais vem antes.
two = [{"vid": "peq", "name": "Pequena", "x": 500, "y": 500, "home": {"spear": 200}},
       {"vid": "gra", "name": "Grande", "x": 500, "y": 501, "home": {"spear": 5000}}]
res = plan_support([dict(reqs[0], missing={"spear": 1000})], two, [], SPEEDS, {})
check([l["source_vid"] for l in res["lines"]] == ["gra"],
      "uma origem grande em vez de varias pequenas: %r" % res["lines"])
# Separar rapidas: pesada nao anda na velocidade da espada.
res = plan_support([dict(reqs[0], missing={"sword": 100, "heavy": 50})],
                   [{"vid": "s", "name": "S", "x": 500, "y": 500, "home": {"sword": 500, "heavy": 500}}],
                   [], SPEEDS, {"split_fast": True})
parts = sorted((sorted(l["troops"]), l["travel_sec"]) for l in res["lines"])
check([p[0] for p in parts] == [["heavy"], ["sword"]] and parts[0][1] < parts[1][1],
      "split_fast: dois comandos, a pesada chega antes: %r" % parts)
# Pedido inteiro menor que o pacote minimo ainda e atendido.
res = plan_support([dict(reqs[0], missing={"heavy": 10})], sources[1:2], [], SPEEDS,
                   {"min_package_pop": 100})
check(res["lines"] and res["lines"][0]["troops"] == {"heavy": 10},
      "10 pesadas (60 pop) passam pelo piso de 100: %r" % res["lines"])

# Coleta e prioridade, com fatia: aldeia que coleta cede ate `gather_share`
# do TOTAL das unidades da coleta (a tropa passa 6-7 h fora, em casa ha ~0);
# explorador, que a coleta nao usa, segue a regra de casa + reserva.
res = plan_support([dict(reqs[0], missing={"spear": 500, "spy": 50})],
                   [dict(sources[1], home={"spear": 25, "spy": 100}, total={"spear": 1000, "spy": 100},
                         gather_enabled=True)],
                   [], SPEEDS, {"min_package_pop": 0, "gather_share": 0.2})
src0 = res["sources"][0]
check(src0["donatable"] == {"spear": 200, "spy": 80},
      "coleta ligada: 20%% do total de lanca (nao do que esta em casa) + explorador: %r"
      % src0["donatable"])
check(any("coleta" in r and "20%" in r for r in src0["reasons"]), "o ranking diz por que: %r" % src0["reasons"])
check([l["troops"] for l in res["lines"]] == [{"spear": 200, "spy": 50}], "plano: %r" % res["lines"])
res = plan_support([dict(reqs[0], missing={"spear": 500})],
                   [dict(sources[1], home={}, total={"spear": 1000}, gather_enabled=True)],
                   [], SPEEDS, {"min_package_pop": 0, "gather_share": 0})
check(res["lines"] == [], "fatia 0: a coleta fica com tudo")

# A fatia e um teto ACUMULADO: apoio enviado continua no total da aldeia, e
# o aprovado ainda vai sair. Sem descontar, cada recalculo daria mais 20%.
res = plan_support([dict(reqs[0], missing={"spear": 500, "spy": 50})],
                   [dict(sources[1], home={"spear": 25, "spy": 100}, total={"spear": 1000, "spy": 100},
                         gather_enabled=True, sent={"spear": 150}, pending={"spear": 30, "spy": 20})],
                   [], SPEEDS, {"min_package_pop": 0, "gather_share": 0.2})
check(res["sources"][0]["donatable"] == {"spear": 20, "spy": 60},
      "200 de fatia - 150 enviados - 30 pendentes = 20; explorador: 80 - 20 pendentes: %r"
      % res["sources"][0]["donatable"])

# A coleta desconta o que mandou da tropa em casa (o cache/managed deixa de
# mostrar como "em casa" o que esta coletando).
from game.troopmanager import TroopManager  # noqa: E402
tm = object.__new__(TroopManager)
tm.troops = {"spear": "1925", "heavy": "750", "spy": "200"}
tm._deduct_gathered({"squad_requests[0][candidate_squad][unit_counts][spear]": "1900",
                     "squad_requests[0][candidate_squad][unit_counts][heavy]": "750",
                     "squad_requests[0][candidate_squad][unit_counts][light]": "0",
                     "squad_requests[0][option_id]": "4"})
check(tm.troops == {"spear": "25", "heavy": "0", "spy": "200"},
      "desconto da coleta: %r" % tm.troops)

# -- 5. ciclo de vida do plano ------------------------------------------------
tmp = tempfile.mkdtemp(prefix="twb-support-")
orig_plan = support_store.PLAN_PATH
support_store.PLAN_PATH = os.path.join(tmp, "plan.json")
try:
    line = {"num": 1, "target_name": "A", "target_x": 520, "target_y": 500, "target_vid": None,
            "source_vid": "safe", "source_name": "Segura", "troops": {"spear": 800},
            "reserve_pct": 0.2}
    support_store.replace_proposed([line, dict(line, source_vid="cau")], "forum:1:2", now=1000)
    ids = [l["id"] for l in support_store.load_plan()["lines"]]
    check(support_store.approve(ids[:1], now=1000) == 1, "aprovar uma linha")
    support_store.replace_proposed([dict(line, source_vid="novo")], "forum:1:2", now=1100)
    st = {l["source_vid"]: l["status"] for l in support_store.load_plan()["lines"]}
    check(st == {"safe": "approved", "novo": "proposed"},
          "recalcular troca so as propostas, aprovada fica: %r" % st)
    check(support_store.claim_lines("safe", now=1200, blocked_reason="ataque chegando") == [],
          "origem sob ataque nao reclama nada")
    l0 = support_store.load_plan()["lines"][0]
    check(l0["status"] == "approved" and l0.get("note", "").startswith("adiado"),
          "adiada continua aprovada, com nota: %r" % l0)
    claimed = support_store.claim_lines("safe", now=1300)
    check(len(claimed) == 1 and support_store.load_plan()["lines"][0]["status"] == "dispatching",
          "reclamada vira dispatching ANTES do envio")
    check(support_store.claim_lines("safe", now=1400) == [],
          "dispatching nunca e reclamada de novo (sem reenvio as cegas)")
    check(support_store.finish_line(claimed[0]["id"], True, now=1500, duration_sec=100),
          "finish_line")
    check(support_store.load_plan()["lines"][0]["status"] == "sent", "enviada")
    new_id = [l["id"] for l in support_store.load_plan()["lines"] if l["status"] == "proposed"]
    support_store.approve(new_id, now=2000)
    check(support_store.claim_lines("novo", now=2000 + support_store.APPROVAL_TTL + 1) == [],
          "aprovacao vencida nao e enviada")
    check([l for l in support_store.load_plan()["lines"] if l["source_vid"] == "novo"][0]["status"]
          == "failed", "aprovacao vencida vira falha")
    check(support_store.home_check({"spear": 1000}, {"spear": 800}, 0.2) is None,
          "1000 em casa, 800 saem, 200 ficam: ok")
    check(support_store.home_check({"spear": 900}, {"spear": 800}, 0.2) is not None,
          "900 em casa nao sustenta 800 + reserva de 180")

    # -- 6. executor ----------------------------------------------------------
    from game.village import Village

    def make_village(under_attack=False, spear="1000", raise_exc=False, gathering=False):
        v = object.__new__(Village)
        v.village_id = "safe"
        v.logger = SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None,
                                   error=lambda *a, **k: None)
        sent = []

        def support(vid, troops=None, position=None):
            if raise_exc:
                raise RuntimeError("queda no meio")
            sent.append((vid, troops, position))
            return {"ok": True}

        v.def_man = SimpleNamespace(under_attack=under_attack, support=support,
                                    last_support_duration=3600, last_support_error=None)
        v.units = SimpleNamespace(troops={"spear": spear, "axe": "5", "spy": "300"},
                                  total_troops={"spear": 1000, "axe": 5, "spy": 300},
                                  conquest_reserve={})
        v.get_village_config = lambda vid, parameter=None, default=None: (
            gathering if parameter == "gather_enabled" else default)
        return v, sent

    def approve_one(**extra):
        support_store.replace_proposed([dict(line, **extra)], "forum:1:2", now=int(__import__("time").time()))
        pid = [l["id"] for l in support_store.load_plan()["lines"] if l["status"] == "proposed"]
        support_store.approve(pid)
        return pid[0]

    lid = approve_one()
    v, sent = make_village()
    v.run_tribe_support()
    check(sent == [(None, {"spear": 800}, (520, 500))], "envia exatamente o aprovado: %r" % sent)
    check(v.units.troops["spear"] == "200", "desconta da tropa em casa: %r" % v.units.troops)
    got = [l for l in support_store.load_plan()["lines"] if l["id"] == lid][0]
    check(got["status"] == "sent" and got.get("arrival_at"), "enviada com chegada: %r" % got)

    lid = approve_one()
    v, sent = make_village(spear="900")
    v.run_tribe_support()
    got = [l for l in support_store.load_plan()["lines"] if l["id"] == lid][0]
    check(sent == [] and got["status"] == "failed" and "reserva" in got["error"],
          "tropa abaixo do plano + reserva: falha sem enviar menos: %r" % got)

    lid = approve_one()
    v, sent = make_village(under_attack=True)
    v.run_tribe_support()
    got = [l for l in support_store.load_plan()["lines"] if l["id"] == lid][0]
    check(sent == [] and got["status"] == "approved", "ataque chegando adia: %r" % got)
    support_store.cancel([lid])

    # Coleta com fatia de 20% (total 1000 lancas = 200). Linha antiga acima
    # da fatia falha sem ir a praca; dentro da fatia mas coletando, ESPERA e
    # vira reserva que a coleta respeita; explorador sai.
    big = approve_one(gather_share=0.2)                                   # 800 > 200
    v, sent = make_village(gathering=True, spear="25")
    v.run_tribe_support()
    got = [l for l in support_store.load_plan()["lines"] if l["id"] == big][0]
    check(sent == [] and got["status"] == "failed" and "fatia da coleta" in got["error"],
          "acima da fatia: falha: %r" % got)

    wait_id = approve_one(troops={"spear": 150}, gather_share=0.2)
    v, sent = make_village(gathering=True, spear="25")
    v.run_tribe_support()
    got = [l for l in support_store.load_plan()["lines"] if l["id"] == wait_id][0]
    check(sent == [] and got["status"] == "approved" and "coleta voltar" in got.get("note", ""),
          "dentro da fatia mas coletando: espera, aprovada: %r" % got)
    check(v.units.conquest_reserve.get("tribe_support") == {"spear": 150},
          "a espera reserva a fatia para a coleta nao levar: %r" % v.units.conquest_reserve)
    v, sent = make_village(gathering=True, spear="1000")                  # a tropa voltou
    v.run_tribe_support()
    got = [l for l in support_store.load_plan()["lines"] if l["id"] == wait_id][0]
    check(sent == [(None, {"spear": 150}, (520, 500))] and got["status"] == "sent",
          "com a tropa em casa, a linha que esperava sai: %r" % got)
    check("tribe_support" not in v.units.conquest_reserve, "reserva liberada depois do envio")

    # Linha aprovada antes de a fatia ser gravada nela: vale o padrao (20%),
    # nao 0% -- 150 lancas cabem em 20% de 1000 e esperam a coleta voltar.
    legacy = approve_one(troops={"spear": 150})
    v, sent = make_village(gathering=True, spear="25")
    v.run_tribe_support()
    got = [l for l in support_store.load_plan()["lines"] if l["id"] == legacy][0]
    check(got["status"] == "approved" and "coleta voltar" in got.get("note", ""),
          "linha sem gather_share usa o padrao de 20%%: %r" % got)
    support_store.cancel([legacy])

    spy_id = approve_one(troops={"spy": 100}, gather_share=0.2)
    v, sent = make_village(gathering=True, spear="25")
    v.run_tribe_support()
    check(sent == [(None, {"spy": 100}, (520, 500))], "explorador sai com a coleta ligada: %r" % sent)

    lid = approve_one()
    v, sent = make_village(raise_exc=True)
    v.run_tribe_support()
    got = [l for l in support_store.load_plan()["lines"] if l["id"] == lid][0]
    check(got["status"] == "dispatching", "excecao no envio: resultado desconhecido, sem retentar")
finally:
    support_store.PLAN_PATH = orig_plan
    shutil.rmtree(tmp, ignore_errors=True)

if failures:
    for f in failures:
        print("FAIL:", f)
    sys.exit(1)
print("OK test_tribe_support")
