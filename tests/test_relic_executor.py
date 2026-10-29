"""
Relíquias, Fase 3 (docs/backend.md §8.78): quando o plano vira ação.
`core/relic_executor.py` (histerese, leituras seguidas, teto por dia do
servidor, nada se desfaz em 24 h, reconferência) e `RelicManager.act()`
(GET na anfitriã, POSTs `remove_relic`/`equip_relic`, recusa AJAX, resposta
sem inventário).

O inventário é o verbatim do br143 de 29/10/2026 (`relic_system_br143.html`,
anonimizado, o mesmo do `test_relics.py`). As respostas das ações são
montadas com o JSON verbatim de relíquia dessa fixture dentro do envelope
`{"response": ..., "game_data": ...}` que o `get_api_action` recebe com
`TribalWars-Ajax: 1` (7º padrão); a recusa é o formato `{"error": [...]}`
medido no §8.63. Sem rede, e sem tocar o `cache/relics.json` real.

Rodar: python tests/test_relic_executor.py
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
from core.extractors import Extractor  # noqa: E402
from game import relic_manager as RM  # noqa: E402

FIX = os.path.join(ROOT, "tests", "fixtures")
failures = []

ALABARDA = "1105799"   # Alabarba Resistente, parada no inventário
MOCHILA = "297445"     # Mochila Reconhecida, equipada na BBM 001 (41123)
SELA = "310487"        # Sela Superior, BBM 003 (44683), trava de 85.233 s
BBM001, BBM014, BBM018 = "41123", "44674", "39472"
CFG = E.settings({"relics": {"manage": True}})
DAY = "2026-10-29"
NOW = 1793300000.0


def check(cond, msg):
    if not cond:
        failures.append(msg)


def page(host="44683", can_equip=True, loyalty_locked=False, relics=None):
    """A tela verbatim, como se lida na aldeia `host`, opcionalmente com outro array."""
    text = open(os.path.join(FIX, "relic_system_br143.html"), encoding="utf-8").read()
    if relics is not None:
        start = text.index("RelicSystem.Inventory.init(") + len("RelicSystem.Inventory.init(")
        raw = Extractor.balanced_slice(text, text.index("[", start))
        text = text.replace(raw, json.dumps(relics), 1)
    return re.sub(r"(\}\]\s*,\s*)44683(\s*,\s*true\s*,\s*100\s*,\s*'[^']*'\s*,\s*)true(\s*,\s*)false",
                  lambda m: "%s%s%s%s%s%s" % (m.group(1), host, m.group(2),
                                              "true" if can_equip else "false", m.group(3),
                                              "true" if loyalty_locked else "false"),
                  text, count=1)


def raw_relics():
    text = open(os.path.join(FIX, "relic_system_br143.html"), encoding="utf-8").read()
    start = text.index("RelicSystem.Inventory.init(") + len("RelicSystem.Inventory.init(")
    return json.loads(Extractor.balanced_slice(text, text.index("[", start)), strict=False)


def moved(relics, rid, host):
    out = copy.deepcopy(relics)
    for r in out:
        if str(r["id"]) == rid:
            r["village_id"] = int(host) if host else None
    return out


def equip_move(rid=ALABARDA, host=BBM014, gain=180.0):
    return {"action": "equip", "relic_ids": [rid], "names": ["Alabarba Resistente"],
            "from": {rid: None}, "to": {rid: host}, "gain_h": gain, "gain_alone_h": gain,
            "value_before_h": 0.0, "text": "equipar Alabarba Resistente em BBM 014"}


def move_move(rid=MOCHILA, origin=BBM001, host=BBM018, gain=60.0, before=1.9):
    return {"action": "move", "relic_ids": [rid], "names": ["Mochila Reconhecida"],
            "from": {rid: origin}, "to": {rid: host}, "gain_h": gain, "gain_alone_h": gain,
            "value_before_h": before, "text": "mover Mochila Reconhecida de BBM 001 para BBM 018"}


def seen_twice(plan):
    ex = {}
    E.update_streaks(ex, plan, 1)
    E.update_streaks(ex, plan, 2)
    return ex


# -- freios puros --------------------------------------------------------------

def test_defaults_e_config():
    cfg = E.settings({})
    check(cfg["manage"] is False, "padrão: desligado")
    check(cfg["min_gain_h"] == 50 and cfg["stable_reads"] == 2 and cfg["max_moves_per_day"] == 2,
          "padrões da Fase 3 (%r)" % cfg)
    check(E.settings({"relics": {"min_gain_h": "x"}})["min_gain_h"] == 50, "ilegível cai no padrão")


def test_histerese():
    plan = {"moves": [equip_move(gain=49.0), move_move(gain=60.0, before=900.0),
                      move_move(rid=SELA, origin="44683", gain=120.0, before=900.0)]}
    ex = seen_twice(plan)
    why = {m["relic_ids"][0] + m["action"]: w for m, w in E.evaluate(plan, ex, CFG, NOW, DAY)}
    check("abaixo do piso" in (why[ALABARDA + "equip"] or ""), "equipar abaixo de 50/h não sai")
    check("abaixo de 10%" in (why[MOCHILA + "move"] or ""), "mover +60 sobre 900 (6,7%%) não sai")
    check(why[SELA + "move"] is None, "mover +120 sobre 900 (13%%) sai")
    plan = {"moves": [equip_move(gain=55.0)]}
    check(E.choose(plan, seen_twice(plan), CFG, NOW, DAY) is not None,
          "equipar parada parte de 0: só o piso absoluto conta")
    dep = dict(equip_move(), gain_alone_h=None)
    check("depende" in E.evaluate({"moves": [dep]}, {}, CFG, NOW, DAY)[0][1],
          "passo que depende de outro (anfitriã ocupada hoje) não sai")


def test_mesmo_plano_em_leituras_seguidas():
    plan = {"moves": [equip_move()]}
    ex = {}
    E.update_streaks(ex, plan, 100)
    check(E.choose(plan, ex, CFG, NOW, DAY) is None, "uma leitura não basta")
    check(E.awaiting_confirmation(plan, ex, CFG, NOW, DAY), "aguarda confirmação")
    E.update_streaks(ex, plan, 100)
    check(E.choose(plan, ex, CFG, NOW, DAY) is None, "a mesma leitura não conta duas vezes")
    E.update_streaks(ex, plan, 200)
    check(E.choose(plan, ex, CFG, NOW, DAY) is not None, "duas leituras seguidas: sai")
    other = {"moves": [equip_move(host=BBM018)]}
    E.update_streaks(ex, other, 300)
    check(E.choose(other, ex, CFG, NOW, DAY) is None, "outro destino: a conta recomeça")
    E.update_streaks(ex, plan, 400)
    check(ex["streak"][E.move_key(plan["moves"][0])]["count"] == 1,
          "passo que sumiu de uma leitura zera")


def test_teto_por_dia_do_servidor():
    plan = {"moves": [equip_move(), move_move(rid=SELA, origin="44683", gain=500.0, before=900.0)]}
    ex = seen_twice(plan)
    for i in range(3):
        E.record(ex, equip_move(rid="x%d" % i), True, "feito", NOW, DAY)
    rows = dict((m["action"], w) for m, w in E.evaluate(plan, ex, CFG, NOW, DAY))
    check("teto do dia: 3 de 3 equipar" in (rows["equip"] or ""), "4º equipar do dia não sai (%r)" % rows)
    check(rows["move"] is None, "o teto de equipar não trava mover")
    for i in range(2):
        E.record(ex, move_move(rid="y%d" % i), True, "feito", NOW, DAY)
    rows = dict((m["action"], w) for m, w in E.evaluate(plan, ex, CFG, NOW, DAY))
    check("teto do dia: 2 de 2 mover" in (rows["move"] or ""), "3º mover do dia não sai")
    check(E.choose(plan, ex, CFG, NOW, "2026-10-30") is not None, "dia novo do servidor: libera")
    E.record(ex, equip_move(rid="z"), False, "recusado", NOW, DAY)
    check(E.day_counts(ex, DAY) == (2, 3), "recusa não conta no dia")
    check(E.choose(plan, ex, CFG, NOW, None) is None, "sem relógio do servidor: não age")


def test_dia_do_servidor():
    server = datetime.datetime(2026, 10, 29, 23, 59, 50).timestamp()
    state = {"server_time": server, "fetched_at": 1000}
    check(E.server_day(state, 1005) == "2026-10-29", "23:59:55 ainda é 29")
    check(E.server_day(state, 1020) == "2026-10-30", "00:00:20 já é 30")
    check(E.server_day({}, 1) is None, "sem relógio: None")


def test_nada_se_desfaz_em_24h():
    plan = {"moves": [move_move(rid=ALABARDA, origin=BBM014, host=BBM018, gain=300.0, before=180.0)]}
    ex = seen_twice(plan)
    E.record(ex, equip_move(), True, "feito", NOW - 3600, DAY)
    why = E.evaluate(plan, ex, CFG, NOW, DAY)[0][1]
    check(why and "o bot mexeu nela há 1.0 h" in why, "equipada há 1 h não sai de lá (%r)" % why)
    check(E.evaluate(plan, ex, CFG, NOW + 22.5 * 3600, "2026-10-30")[0][1] is not None, "23,5 h depois da ação ainda trava")
    check(E.choose(plan, ex, CFG, NOW + 24 * 3600, "2026-10-30") is not None, "25 h depois da ação: libera")


def test_ordem_equipar_antes_de_mover():
    plan = {"moves": [move_move(rid=SELA, origin="44683", gain=900.0, before=900.0), equip_move(gain=100.0)]}
    ex = seen_twice(plan)
    check(E.choose(plan, ex, CFG, NOW, DAY)["action"] == "equip",
          "equipar parada sai antes de um mover de ganho maior")
    swap = {"moves": [dict(move_move(), action="swap")]}
    check("não sai nesta fase" in E.evaluate(swap, seen_twice(swap), CFG, NOW, DAY)[0][1],
          "swap/replace ficam para depois")


def test_reconferencia():
    inv = lambda **kw: Extractor.relic_inventory(page(**kw))  # noqa: E731
    check(E.precheck(equip_move(), inv(host=BBM014)) == (None, None), "estado igual ao plano: age")
    why, kind = E.precheck(equip_move(), inv(host="44683"))
    check(kind == "diverge" and "não na anfitriã" in why, "inventário lido em outra aldeia")
    why, kind = E.precheck(equip_move(), inv(host=BBM014, relics=moved(raw_relics(), ALABARDA, BBM018)))
    check(kind == "diverge" and "está em" in why, "o jogador equipou a relíquia em outro lugar")
    why, kind = E.precheck(equip_move(), inv(host=BBM014, relics=moved(raw_relics(), MOCHILA, BBM014)))
    check(kind == "diverge" and "já tem relíquia" in why, "anfitriã ocupada")
    why, kind = E.precheck(equip_move(), inv(host=BBM014, loyalty_locked=True))
    check(kind == "recusa" and "lealdade" in why, "lealdade da anfitriã (loyalty_locked do jogo)")
    why, kind = E.precheck(equip_move(), inv(host=BBM014), low_loyalty={BBM014: "estimada 57"})
    check(kind == "recusa" and "estimada" in why, "lealdade estimada da conquista")
    why, kind = E.precheck(equip_move(), inv(host=BBM014, can_equip=False))
    check(kind == "recusa" and "can_equip" in why, "sem vaga")
    sela = move_move(rid=SELA, origin="44683", host=BBM018)
    why, kind = E.precheck(sela, inv(host=BBM018))
    check(kind == "recusa" and "trava de remoção" in why, "Sela na trava de 24 h do jogo")
    fogueira = move_move(rid="238187", origin="88755", host=BBM018)
    why, kind = E.precheck(fogueira, inv(host=BBM018))
    check(kind == "recusa", "relíquia inativa/travada não sai (%r)" % why)
    check(E.precheck(move_move(), inv(host=BBM018, can_equip=False)) == (None, None),
          "mover não precisa de vaga livre: a remoção libera a dela")
    check(E.precheck(equip_move(), None)[1] == "diverge", "sem releitura: não age")


# -- RelicManager.act() ----------------------------------------------------------

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


def _manager(plan, tmp):
    RM.CACHE_PATH = os.path.join(tmp, "relics.json")
    man = RM.RelicManager(wrapper=FakeWrapper(), config={"relics": {"enabled": True, "manage": True}})
    now = datetime.datetime.now()
    state = {"fetched_at": int(now.timestamp()), "server_time": int(now.timestamp()),
             "plan": plan, "exec": {}}
    E.update_streaks(state["exec"], plan, 1)
    E.update_streaks(state["exec"], plan, 2)
    man.state = state
    man._coords = {}
    return man


def envelope(relics, host, can_equip):
    return {"response": {"relics": relics, "village_id": int(host), "can_equip": can_equip},
            "game_data": {"village": {"id": int(host)}}}


def test_act_equipar_parada():
    tmp = tempfile.mkdtemp()
    man = _manager({"moves": [equip_move()]}, tmp)
    w = man.wrapper
    w.pages[BBM014] = page(host=BBM014)
    w.posts = [envelope(moved(raw_relics(), ALABARDA, BBM014), BBM014, True)]
    check(man.act() is True, "equipou")
    check([c[0] for c in w.calls] == ["GET", "POST"], "1 GET na anfitriã + 1 POST (%r)" % w.calls)
    check(w.calls[0][1].endswith("village=%s&screen=relic_system" % BBM014), "GET na anfitriã")
    post = w.calls[1]
    check(post[1:3] == (BBM014, "equip_relic") and post[3]["screen"] == "relic_system"
          and post[4] == {"relic_id": ALABARDA}, "POST equip_relic na aldeia da URL (%r)" % (post,))
    check(E.day_counts(man.state["exec"], E.server_day(man.state, datetime.datetime.now().timestamp()))
          == (0, 1), "contou 1 equipar no dia do servidor")
    host = next(r["village_id"] for r in man.state["relics"] if r["id"] == ALABARDA)
    check(host == BBM014, "a resposta virou o estado novo, sem GET extra")
    check(man.state["exec"]["response_has_relics"] is True, "formato da resposta registrado")
    check(man.state["plan"].get("stale") and man.candidate() is None,
          "plano velho depois da ação: nada mais sai dele")
    check(os.path.exists(RM.CACHE_PATH), "gravado no caminho do teste")


def test_act_recusa_ajax():
    tmp = tempfile.mkdtemp()
    man = _manager({"moves": [equip_move()]}, tmp)
    w = man.wrapper
    w.pages[BBM014] = page(host=BBM014)
    w.posts = [{"error": ["Você não pode equipar esta relíquia."]}]
    check(man.act() is False, "recusa não é ação feita (A26-09)")
    entry = man.state["exec"]["history"][-1]
    check(entry["ok"] is False and "recusou equipar" in entry["detail"], "histórico com o motivo")
    check(E.day_counts(man.state["exec"], E.server_day(man.state, datetime.datetime.now().timestamp()))
          == (0, 0), "recusa não conta no dia")
    check(E.move_key(equip_move()) in man.state["exec"]["skip"], "o passo fica congelado")
    check(len(w.calls) == 2, "sem GET de confirmação depois de recusa")


def test_act_resposta_sem_inventario_confirma_com_get():
    tmp = tempfile.mkdtemp()
    man = _manager({"moves": [equip_move()]}, tmp)
    w = man.wrapper
    w.pages[BBM014] = page(host=BBM014)
    w.posts = [{"response": {}, "game_data": {}}]

    def after(url, _orig=w.get_url):
        out = _orig(url)
        w.pages[BBM014] = page(host=BBM014, relics=moved(raw_relics(), ALABARDA, BBM014))
        return out
    w.get_url = after
    check(man.act() is True, "confirmado pelo GET")
    check([c[0] for c in w.calls] == ["GET", "POST", "GET"], "GET de confirmação (%r)" % w.calls)
    check(man.state["exec"]["response_has_relics"] is False, "registra que a resposta não trouxe")


def test_act_equipar_sem_efeito_nao_conta():
    tmp = tempfile.mkdtemp()
    man = _manager({"moves": [equip_move()]}, tmp)
    w = man.wrapper
    w.pages[BBM014] = page(host=BBM014)
    w.posts = [envelope(raw_relics(), BBM014, True)]  # JSON sem erro, relíquia parada
    check(man.act() is False, "JSON sem erro com a relíquia parada não é sucesso")
    check("não se confirmou" in man.state["exec"]["history"][-1]["detail"], "motivo")


def test_act_mover():
    tmp = tempfile.mkdtemp()
    man = _manager({"moves": [move_move(gain=300.0, before=100.0)]}, tmp)
    w = man.wrapper
    w.pages[BBM018] = page(host=BBM018)
    parked = moved(raw_relics(), MOCHILA, None)
    w.posts = [envelope(parked, BBM001, True), envelope(moved(parked, MOCHILA, BBM018), BBM018, True)]
    check(man.act() is True, "moveu")
    kinds = [(c[0], c[1] if c[0] == "POST" else None, c[2] if c[0] == "POST" else None) for c in w.calls]
    check(kinds == [("GET", None, None), ("POST", BBM001, "remove_relic"), ("POST", BBM018, "equip_relic")],
          "GET na anfitriã, remove na origem, equip no destino (%r)" % kinds)
    check(w.calls[1][4] == {}, "remove_relic sem corpo")
    check(E.day_counts(man.state["exec"], E.server_day(man.state, datetime.datetime.now().timestamp()))
          == (1, 0), "contou 1 mover")


def test_act_mover_que_para_no_meio():
    tmp = tempfile.mkdtemp()
    man = _manager({"moves": [move_move(gain=300.0, before=100.0)]}, tmp)
    w = man.wrapper
    w.pages[BBM018] = page(host=BBM018)
    parked = moved(raw_relics(), MOCHILA, None)
    w.posts = [envelope(parked, BBM001, True), {"error": ["Erro."]}]
    check(man.act() is True, "a remoção mudou o mundo: conta como mexida")
    entry = man.state["exec"]["history"][-1]
    check(entry["ok"] is True and "ficou no inventário" in entry["detail"], "registra o meio do caminho")
    again = {"moves": [equip_move(rid=MOCHILA, host=BBM018, gain=300.0)]}
    man.state["plan"] = again
    E.update_streaks(man.state["exec"], again, 3)
    E.update_streaks(man.state["exec"], again, 4)
    check(man.candidate() is None, "a relíquia que o bot tirou fica parada por 24 h")


def test_act_estado_diverge_nao_age_e_rele():
    tmp = tempfile.mkdtemp()
    man = _manager({"moves": [equip_move()]}, tmp)
    w = man.wrapper
    w.pages[BBM014] = page(host=BBM014, relics=moved(raw_relics(), ALABARDA, BBM018))
    check(man.act() is False, "não agiu")
    check([c[0] for c in w.calls] == ["GET"], "nenhum POST")
    check(man.pending == "estado diverge do plano", "pede releitura")


def test_act_desligado_ou_plano_velho():
    tmp = tempfile.mkdtemp()
    man = _manager({"moves": [equip_move()]}, tmp)
    man.config = {"relics": {"enabled": True, "manage": False}}
    check(man.act() is False and not man.wrapper.calls, "manage desligado: 0 requisição")
    man.config = {"relics": {"enabled": True, "manage": True}}
    man.state["fetched_at"] -= RM.ACT_MAX_STATE_AGE + 1
    check(man.act() is False and not man.wrapper.calls, "plano de leitura velha: 0 requisição")


def test_confirm_due():
    tmp = tempfile.mkdtemp()
    man = _manager({"moves": [equip_move()]}, tmp)
    man.state["exec"] = {}
    E.update_streaks(man.state["exec"], man.state["plan"], 1)
    check(man.confirm_due() is False, "leitura recente: espera")
    man.state["fetched_at"] -= 31 * 60
    check(man.confirm_due() is True and "confirmar o plano" in man.pending, "30 min depois: relê")


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
    print("OK: relíquias, Fase 3 (histerese, leituras, teto por dia, 24 h, reconferência, ações)")
