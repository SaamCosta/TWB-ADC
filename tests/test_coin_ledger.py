"""
Moedas por aldeia para a bandeira de moeda (§8.85): o contador da conta e a
sessão automática na academia (`pages/academy`), o registro `TWB_MINT`
(`core/coin_ledger`), a taxa do tipo 7 no plano (`core/flag_planner`) e os
três pontos que cunham (`SnobManager.coin_item`, `MintManager._mint_max` e a
leitura do hub).

Fixture: `tests/fixtures/academy_coins_br143.json`, recortes VERBATIM de
`screen=snob` do hub (05/10 e 10/10, `cache/mint/samples/`). Os acentos vieram
corrompidos na gravação (U+FFFD); `_accented` os escreve de novo, porque a
tela que o bot recebe vem em UTF-8 certo, e os leitores têm que casar as duas.
A tela com o botão Ativar é o `ACADEMY` do `test_mint.py` (BBM 003, 04/10).
A resposta do POST `action=coin` nunca foi capturada: nos testes de cunhagem
ela é a mesma tela com o contador de outro dia (a de 10/10 depois da de
05/10), e o bot salva a primeira de verdade em `cache/mint/samples/coin_post`.

Rodar: python tests/test_coin_ledger.py
"""
import json
import os
import shutil
import sys
import tempfile
import time
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import coin_ledger, flag_planner, mint_store
from game import mint_manager
from game.mint_manager import MintManager
from game.snobber import SnobManager
from pages import academy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_mint import ACADEMY as ACADEMY_CAN_START  # noqa: E402 -- verbatim, 04/10, botão Ativar

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "academy_coins_br143.json")
with open(FIX, "r", encoding="utf-8") as _fh:
    FIXTURE = json.load(_fh)


def _page(key, accented=False):
    part = FIXTURE[key]
    html = "\n".join([part["storage_item"], part["server_date"], part["counter"], part["session"]])
    return _accented(html) if accented else html


def _accented(html):
    for broken, fixed in (("J� ", "Já "), ("at� ", "até "), ("amanh� ", "amanhã "),
                          ("�s ", "às ")):
        html = html.replace(broken, fixed)
    return html


# -- leitores da academia ---------------------------------------------------------

def test_contador_da_conta_nas_duas_amostras():
    # Limite 50 com 42 guardadas; limite 59 com 37: L(L+1)/2 + guardadas.
    assert academy.coin_total(_page("started_0510")) == 1317
    assert academy.coin_total(_page("running_1010")) == 1807
    assert academy.coin_total(_page("running_1010", accented=True)) == 1807


def test_contador_que_nao_fecha_nao_vale():
    html = _page("running_1010").replace("23 moedas de ouro", "22 moedas de ouro")
    assert academy.coin_total(html) is None
    assert academy.coin_total(FIXTURE["running_1010"]["session"]) is None
    assert academy.coin_total(None) is None


def test_sessao_automatica_e_o_fim():
    p = academy.auto_minting_progress(_page("running_1010", accented=True))
    assert p["coins"] == 24
    assert time.strftime("%d/%m/%Y %H:%M:%S", time.localtime(p["end"])) == "10/10/2026 20:03:20"
    p = academy.auto_minting_progress(_page("started_0510"))
    assert p["coins"] == 0
    # "amanhã às 02:35:04" lido às 18:35:05 de 05/10: 8 h de sessão.
    assert time.strftime("%d/%m/%Y %H:%M:%S", time.localtime(p["end"])) == "06/10/2026 02:35:04"
    assert academy.auto_minting_progress(FIXTURE["running_1010"]["counter"]) is None


# -- registro e taxa --------------------------------------------------------------

def test_evento_so_com_o_contador_subindo():
    assert json.loads(coin_ledger.mint_event("post", before=1807, after=1808))["coins"] == 1
    assert coin_ledger.mint_event("post", before=1807, after=1807) is None
    assert coin_ledger.mint_event("post", before=None, after=1808) is None
    assert coin_ledger.mint_event("total", total=None) is None


NOW = 1793800000


def _ev(h_ago, vid, **ev):
    return (NOW - int(h_ago * 3600), vid, ev)


def _scenario(extra_growth=0):
    """Hub (38409) com uma sessão lida duas vezes, uma doadora com 2 moedas."""
    return [
        _ev(30, "38409", src="total", total=1807),
        _ev(20, "38409", src="auto", coins=18, end=NOW - 12 * 3600, total=1825),
        _ev(12.2, "38409", src="auto", coins=40, end=NOW - 12 * 3600, total=1847),
        _ev(8, "41123", src="post", coins=1, before=1847, after=1848),
        _ev(2, "41123", src="post", coins=1, before=1848 + extra_growth, after=1849 + extra_growth),
    ]


def test_moedas_por_hora_por_aldeia():
    out = coin_ledger.mint_inputs(["38409", "41123", "44683"], _scenario(), NOW)
    # A sessão conta pelo maior número lido (40), não pela soma das leituras.
    assert abs(out["38409"]["coin_h"] - 40 / 30.0) < 1e-9, out["38409"]
    assert abs(out["41123"]["coin_h"] - 2 / 30.0) < 1e-9
    # Contador da conta: 1807 -> 1849 = 42 = 40 + 2. Nada fora do registro.
    assert out["44683"]["coin_h"] == 0.0, out["44683"]


def test_moeda_fora_do_registro_nao_vira_zero():
    out = coin_ledger.mint_inputs(["38409", "41123", "44683"], _scenario(extra_growth=6), NOW)
    assert out["44683"]["coin_h"] is None and "não registrou" in out["44683"]["coin_why"]
    # Quem cunhou com registro continua medido (é um piso).
    assert out["41123"]["coin_h"] > 0


def test_sem_contador_ou_com_pouco_registro_e_desconhecido():
    # 30 h de registro, mas nenhuma leitura do contador da conta: sem ele, a
    # aldeia que não aparece pode ter cunhado sem o bot ver.
    only_posts = [_ev(30, "41123", src="post", coins=1), _ev(2, "41123", src="post", coins=1)]
    out = coin_ledger.mint_inputs(["41123", "44683"], only_posts, NOW)
    assert abs(out["41123"]["coin_h"] - 2 / 30.0) < 1e-9
    assert out["44683"]["coin_h"] is None and "contador" in out["44683"]["coin_why"]
    short = coin_ledger.mint_inputs(["44683"], _scenario()[-2:], NOW)
    assert short["44683"]["coin_h"] is None and "piso" in short["44683"]["coin_why"]
    assert coin_ledger.mint_inputs(["44683"], [], NOW)["44683"]["coin_h"] is None


# As linhas TWB_MINT reais de 04/11 (twb_1793823892.log e twb_1793831869.log),
# na ordem. A sessão do hub começou às 13:18 (processo anterior ao registro) e
# rendeu 33; o contador só passou a ser lido às 17:55, e até o fim dela subiu 12
# (10 por POST, 2 da sessão). As 31 de antes não estão no crescimento (§8.86).
REAL_0411 = [
    (1793825715, "34597", {"after": 4888, "before": 4887, "coins": 1, "src": "post"}),
    (1793826522, "39472", {"after": 4889, "before": 4888, "coins": 1, "src": "post"}),
    (1793832691, "52755", {"after": 4891, "before": 4890, "coins": 1, "src": "post"}),
    (1793833761, "51540", {"after": 4892, "before": 4891, "coins": 1, "src": "post"}),
    (1793833793, "51540", {"after": 4893, "before": 4892, "coins": 1, "src": "post"}),
    (1793834541, "54895", {"after": 4894, "before": 4893, "coins": 1, "src": "post"}),
    (1793834574, "54895", {"after": 4895, "before": 4894, "coins": 1, "src": "post"}),
    (1793835386, "57689", {"after": 4897, "before": 4895, "coins": 2, "src": "post"}),
    (1793836169, "55553", {"after": 4899, "before": 4898, "coins": 1, "src": "post"}),
    (1793837342, "38409", {"coins": 33, "end": 1793837926, "src": "auto", "total": 4899}),
    (1793838049, "38409", {"src": "total", "total": 4899}),
]
REAL_NOW = 1793825715 + 25 * 3600


def test_sessao_iniciada_antes_do_contador_nao_esconde_moeda():
    vids = ["38409", "34597", "44683"]
    # Só o registro real: depois do fim da sessão há uma leitura do contador,
    # então a aldeia sem registro não é zero medido, é desconhecida.
    out = coin_ledger.mint_inputs(vids, REAL_0411, REAL_NOW)
    assert out["44683"]["coin_h"] is None and "contador" in out["44683"]["coin_why"], out["44683"]
    assert abs(out["38409"]["coin_h"] - 33 / 25.0) < 1e-9
    assert abs(out["34597"]["coin_h"] - 1 / 25.0) < 1e-9
    # Uma cunhagem registrada depois: o contador fecha, zero medido.
    later = REAL_0411 + [(1793845000, "34597", {"src": "post", "coins": 1, "before": 4899, "after": 4900})]
    assert coin_ledger.mint_inputs(vids, later, REAL_NOW)["44683"]["coin_h"] == 0.0
    # 6 moedas à mão no meio: a conta inteira (4887 -> 4906 = 19 contra 11 + 33)
    # daria -25 e "zero"; a partir do fim da sessão, são 6 fora do registro.
    hand = REAL_0411 + [(1793845000, "34597", {"src": "post", "coins": 1, "before": 4905, "after": 4906})]
    out = coin_ledger.mint_inputs(vids, hand, REAL_NOW)
    assert out["44683"]["coin_h"] is None and "6 moeda" in out["44683"]["coin_why"], out["44683"]


# As linhas TWB_MINT reais de 04/11 21:58 a 05/11 20:00 (twb_1793838294.log e
# twb_1793883288.log). O PC suspendeu às 02:21 e voltou às 09:49, então a
# sessão do hub das 21:21 não teve leitura final (+2 no contador, 22:09 ->
# 10:05). A sessão das 10:05 foi lida às 17:57 (29), e a das 18:11 estava em
# andamento: o 4946 -> 4947 entre 19:52 e 20:00 é dela (§8.88).
REAL_0511 = [
    (1793840295, "68082", {"after": 4900, "before": 4899, "coins": 1, "src": "post"}),
    (1793840942, "57033", {"after": 4901, "before": 4900, "coins": 1, "src": "post"}),
    (1793883938, "38409", {"after": 4904, "before": 4903, "coins": 1, "src": "post"}),
    (1793883938, "38409", {"src": "total", "total": 4904}),
    (1793886441, "56822", {"after": 4905, "before": 4904, "coins": 1, "src": "post"}),
    (1793896911, "39292", {"after": 4908, "before": 4907, "coins": 1, "src": "post"}),
    (1793903474, "34597", {"after": 4923, "before": 4922, "coins": 1, "src": "post"}),
    (1793904419, "39472", {"after": 4925, "before": 4924, "coins": 1, "src": "post"}),
    (1793911212, "52755", {"after": 4938, "before": 4937, "coins": 1, "src": "post"}),
    (1793912223, "38409", {"coins": 29, "end": 1793912743, "src": "auto", "total": 4938}),
    (1793912520, "51540", {"after": 4939, "before": 4938, "coins": 1, "src": "post"}),
    (1793913096, "38409", {"src": "total", "total": 4939}),
    (1793913435, "54895", {"after": 4940, "before": 4939, "coins": 1, "src": "post"}),
    (1793913467, "54895", {"after": 4941, "before": 4940, "coins": 1, "src": "post"}),
    (1793914774, "55647", {"after": 4942, "before": 4941, "coins": 1, "src": "post"}),
    (1793916611, "61947", {"after": 4943, "before": 4942, "coins": 1, "src": "post"}),
    (1793917036, "58039", {"after": 4944, "before": 4943, "coins": 1, "src": "post"}),
    (1793919094, "61990", {"after": 4945, "before": 4944, "coins": 1, "src": "post"}),
    (1793919125, "61990", {"after": 4946, "before": 4945, "coins": 1, "src": "post"}),
    (1793919654, "68082", {"after": 4948, "before": 4947, "coins": 1, "src": "post"}),
]
# O início da sessão das 18:11 como o `_report_start` o registraria: a tela que
# volta do início traz o "Fim" (aqui, 20 s depois de início + 8 h, como na §8.86).
END_C = 1793913074 + 8 * 3600 + 20
START_C = (1793913097, "38409", {"src": "auto", "coins": 0, "end": END_C, "total": 4939})
# E o da sessão das 21:21, se o registro já existisse.
START_A = (1793838063, "38409", {"src": "auto", "coins": 0, "end": 1793838062 + 8 * 3600 + 20,
                                 "total": 4899})


def _shift(events, since, n):
    """O contador da conta `n` acima a partir de `since`: moeda que ninguém registrou."""
    out = []
    for ts, vid, ev in events:
        ev = dict(ev)
        if ts >= since:
            for key in ("before", "after", "total"):
                if ev.get(key) is not None:
                    ev[key] += n
        out.append((ts, vid, ev))
    return out


def test_sessao_do_hub_em_andamento_nao_e_moeda_fora_do_registro():
    vids = ["38409", "44683"]
    now = 1793919654 + 1800
    real = REAL_0411 + REAL_0511
    # O campo de 05/11 às 21:00: 3 fora do registro (2 da sessão sem leitura
    # final, 1 da em andamento), no limite da folga: zero medido.
    out = coin_ledger.mint_inputs(vids, real, now)
    assert out["44683"]["coin_h"] == 0.0, out["44683"]
    # A sessão em andamento cunha mais 3 até o próximo POST: sem o início no
    # registro, as aldeias sem registro viram "desconhecido" (o furo).
    more = real + [(now, "57033", {"src": "post", "coins": 1, "before": 4951, "after": 4952})]
    out = coin_ledger.mint_inputs(vids, more, now)
    assert out["44683"]["coin_h"] is None and "6 moeda" in out["44683"]["coin_why"], out["44683"]
    # Com o início no registro, a janela da sessão aberta sai da conferência.
    out = coin_ledger.mint_inputs(vids, more + [START_C], now)
    assert out["44683"]["coin_h"] == 0.0, out["44683"]
    # O hub fica com o que foi lido: 33 + 29 + 1 POST + 0 da sessão aberta.
    assert out["38409"]["coins"] == 63, out["38409"]
    # Moeda à mão FORA da janela continua aparecendo: 6 entre 17:57 e 18:02
    # (sessão das 10:05 já fechada) somam aos 2 da sessão sem leitura final.
    hand = _shift(more, 1793912520, 6) + [START_C]
    out = coin_ledger.mint_inputs(vids, hand, now)
    assert out["44683"]["coin_h"] is None and "8 moeda" in out["44683"]["coin_why"], out["44683"]
    # Uma leitura no meio da sessão (4 até agora) é do hub, mas a sessão
    # segue aberta: não entra no registrado, ou esconderia os mesmos 8.
    mid = (now - 60, "38409", {"src": "auto", "coins": 4, "end": END_C, "total": 4957})
    out = coin_ledger.mint_inputs(vids, hand + [mid], now)
    assert out["44683"]["coin_h"] is None and "8 moeda" in out["44683"]["coin_why"], out["44683"]
    assert out["38409"]["coins"] == 33 + 29 + 1 + 4


def test_sessao_sem_leitura_final_fica_fora_da_conferencia():
    vids = ["44683"]
    now = 1793919654 + 1800
    # 2 à mão às 13:41 + os 2 da sessão das 21:21 = 4, acima da folga.
    base = _shift(REAL_0411 + REAL_0511, 1793896911, 2) + [START_C]
    out = coin_ledger.mint_inputs(vids, base, now)
    assert out["44683"]["coin_h"] is None and "4 moeda" in out["44683"]["coin_why"], out["44683"]
    # Com o início da sessão das 21:21 no registro e sem leitura final, ela
    # fica aberta e o 22:09 -> 10:05 sai da conta: sobram os 2 à mão.
    [a] = [s for s in coin_ledger.hub_sessions([START_A]) if s["end"] == START_A[2]["end"]]
    assert not a["closed"]
    out = coin_ledger.mint_inputs(vids, base + [START_A], now)
    assert out["44683"]["coin_h"] == 0.0, out["44683"]


def test_sessao_lida_no_fim_volta_a_conferencia():
    vids = ["38409", "44683"]
    # A leitura final da sessão das 18:11 (10 min antes do fim; o fim lido
    # nela vem 20 s depois do registrado no início, a mesma sessão): 10 moedas,
    # contador 4957. Com ela, a janela volta a ser conferida.
    final = (END_C - 600, "38409", {"src": "auto", "coins": 10, "end": END_C + 20, "total": 4957})
    now = END_C + 60
    events = REAL_0411 + REAL_0511 + [START_C, final]
    sessions = [s for s in coin_ledger.hub_sessions(events) if s["end"] and s["end"] >= END_C - 300]
    assert len(sessions) == 1 and sessions[0]["closed"] and sessions[0]["coins"] == 10, sessions
    out = coin_ledger.mint_inputs(vids, events, now)
    assert out["44683"]["coin_h"] == 0.0, out["44683"]
    assert out["38409"]["coins"] == 33 + 29 + 1 + 10
    # 6 à mão dentro da janela dela aparecem depois da leitura final.
    hand = events[:-1] + [(final[0], "38409", dict(final[2], total=4963))]
    out = coin_ledger.mint_inputs(vids, hand, now)
    assert out["44683"]["coin_h"] is None and "8 moeda" in out["44683"]["coin_why"], out["44683"]


def test_post_da_primeira_leitura_conta_dentro():
    # O "antes" do primeiro POST é a primeira leitura do contador: a moeda dele
    # está no crescimento e tem que estar no registrado (senão, +1 fora sempre).
    # 5 moedas, acima da folga de 3.
    events = [(NOW - 30 * 3600, "41123", {"src": "post", "coins": 5, "before": 100, "after": 105}),
              (NOW - 3600, "38409", {"src": "total", "total": 105})]
    out = coin_ledger.mint_inputs(["44683"], events, NOW)
    assert out["44683"]["coin_h"] == 0.0, out


def test_valor_da_bandeira_de_moeda():
    inputs = {"coin_h": 2.0, "coin_why": None}
    rate, _ = flag_planner.flag_rate(7, inputs)
    assert rate == 2.0 * 83000 / 100.0
    value, _ = flag_planner.flag_value([7, 7], inputs)
    assert abs(value - 2.0 * 83000 * 0.22) < 1e-6
    assert flag_planner.flag_value([7, 7], {"coin_h": 0.0})[0] == 0.0
    assert flag_planner.flag_value([7, 7], {})[0] is None


def test_leitura_do_reporter():
    tmp = tempfile.mkdtemp(prefix="twb-coin-")
    try:
        with open(os.path.join(tmp, "twb_1.log"), "w", encoding="utf-8") as fh:
            for ts, vid, ev in _scenario():
                fh.write("%d - %s - TWB_MINT - %s\n" % (ts, vid, json.dumps(ev, sort_keys=True)))
            fh.write("%d - 41123 - TWB_MINT - nao e json\n" % (NOW - 60))
        events = flag_planner.read_events(tmp, NOW)
        assert len(events["mint"]) == 5, events["mint"]
        out = coin_ledger.mint_inputs(["38409"], events["mint"], NOW)
        assert abs(out["38409"]["coin_h"] - 40 / 30.0) < 1e-9
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# -- quem cunha -------------------------------------------------------------------

class Resp:
    def __init__(self, text):
        self.text = text


class Reporter:
    def __init__(self):
        self.lines = []

    def report(self, vid, action, data):
        self.lines.append((vid, action, data))


class SnobWrapper:
    last_h = "h"

    def __init__(self, after):
        self.after = after
        self.reporter = Reporter()
        self.posts = []

    def post_url(self, url, data):
        self.posts.append(url)
        return None if self.after is None else Resp(self.after)


def _snob(after):
    man = SnobManager(wrapper=SnobWrapper(after), village_id="41123")
    man.resman = types.SimpleNamespace(actual={"wood": 99999, "stone": 99999, "iron": 99999},
                                       request=lambda **k: None)
    return man


def test_coin_item_registra_o_que_o_contador_contou():
    man = _snob(_page("running_1010", accented=True))
    assert man.coin_item(_page("started_0510"), request=False) is True
    assert len(man.wrapper.posts) == 1
    [(vid, action, data)] = man.wrapper.reporter.lines
    assert (vid, action) == ("41123", "TWB_MINT")
    assert json.loads(data) == {"src": "post", "coins": 490, "before": 1317, "after": 1807}


def test_coin_item_sem_subir_ou_sem_resposta_nao_registra():
    for after in (_page("started_0510"), None, "<html>login</html>"):
        man = _snob(after)
        assert man.coin_item(_page("started_0510"), request=False) is True
        assert man.wrapper.reporter.lines == [], after


class HubWrapper:
    last_h = "h"

    def __init__(self, page, after=None, started=None):
        self.page = page
        self.after = after          # resposta do action=coin
        self.started = started      # resposta do start_auto_minting_session
        self.reporter = Reporter()
        self.last_response = None
        self.posts = []

    def get_url(self, url, headers=None):
        return Resp(self.page)

    def post_url(self, url, data, headers=None):
        self.posts.append(url)
        text = self.started if "start_auto_minting_session" in url else self.after
        self.last_response = Resp(text or self.page)
        return self.last_response


def _with_tmp_store(fn):
    def run():
        tmp = tempfile.mkdtemp(prefix="twb-coin-hub-")
        orig = (mint_store.CAMPAIGN_PATH, mint_store.STATE_PATH, mint_manager.FileManager.get_path)
        mint_store.CAMPAIGN_PATH = os.path.join(tmp, "campaign.json")
        mint_store.STATE_PATH = os.path.join(tmp, "state.json")
        mint_manager.FileManager.get_path = staticmethod(lambda p: os.path.join(tmp, p))
        try:
            fn()
        finally:
            (mint_store.CAMPAIGN_PATH, mint_store.STATE_PATH,
             mint_manager.FileManager.get_path) = orig
            shutil.rmtree(tmp, ignore_errors=True)
    run.__name__ = fn.__name__
    return run


def _hub(wrapper):
    mgr = MintManager(wrapper)
    mgr.config = {"villages": {"38409": {}}, "minting": {"hub_auto_mint": True}}
    mgr.found_villages = ["38409"]
    mgr.route = {"hub": "38409"}
    return mgr


@_with_tmp_store
def test_hub_le_a_sessao_e_volta_logo_depois_do_fim():
    page = _page("running_1010", accented=True)
    end = academy.auto_minting_progress(page)["end"]
    mgr = _hub(HubWrapper(page))
    now = end - 600  # a leitura de 10 min antes do fim
    mgr._tick_hub(now)
    [(vid, action, data)] = mgr.wrapper.reporter.lines
    assert json.loads(data) == {"src": "auto", "coins": 24, "end": end, "total": 1807}
    assert mgr.state["hub"]["next_at"] == end + 60
    # Longe do fim, segue de 30 em 30 min.
    mgr = _hub(HubWrapper(page))
    mgr.state = {}
    mgr._tick_hub(end - 3 * 3600)
    assert mgr.state["hub"]["next_at"] == end - 3 * 3600 + 1800


@_with_tmp_store
def test_hub_que_inicia_a_sessao_marca_a_leitura_final():
    # A tela com o botão Ativar (verbatim, sem o contador) e o contador de 05/10.
    # O "(1)" do ACADEMY cunha antes; a resposta é a mesma tela, então o
    # contador não sobe e a cunhagem NÃO entra no registro.
    start_page = ACADEMY_CAN_START + FIXTURE["started_0510"]["counter"]
    mgr = _hub(HubWrapper(start_page, started=_page("started_0510", accented=True)))
    mgr._tick_hub(NOW)
    assert any("start_auto_minting_session" in u for u in mgr.wrapper.posts), mgr.wrapper.posts
    assert mgr.state["hub"]["next_at"] == NOW + 8 * 3600 - mint_manager.AUTO_MINT_FINAL_READ
    # Antes de abrir, só o contador; aberta, a sessão entra com 0 moedas e o
    # fim da tela que voltou (§8.88), para o registro saber que ela corre.
    lines = [json.loads(d) for _, _, d in mgr.wrapper.reporter.lines]
    assert [ev["src"] for ev in lines] == ["total", "auto"], lines
    end = academy.auto_minting_progress(_page("started_0510", accented=True))["end"]
    assert lines[1] == {"src": "auto", "coins": 0, "end": end, "total": 1317}, lines[1]

    # Resposta do início sem a tabela da sessão (ou nenhuma): o fim vira
    # início + 8 h, e a linha sai do mesmo jeito.
    for last in (Resp("<html>sem a tabela</html>"), None):
        mgr = _hub(HubWrapper(start_page))
        mgr.wrapper.last_response = last
        mgr._report_start("38409", NOW)
        lines = [json.loads(d) for _, _, d in mgr.wrapper.reporter.lines]
        assert lines == [{"src": "auto", "coins": 0, "end": NOW + 8 * 3600, "total": None}], lines


@_with_tmp_store
def test_hub_herdado_sem_leitura_final_rele_antes_do_fim():
    # §8.86: o estado do disco de 04/11, deixado por um processo anterior à
    # leitura final (sessão iniciada às 13:18:31, volta às 21:19:31 = fim + 60,
    # sem `read_at`). Os números são os do `cache/mint/state.json`, deslocados
    # para o fim da sessão da fixture.
    page = _page("running_1010", accented=True)
    end = academy.auto_minting_progress(page)["end"]
    started = end - 8 * 3600
    final = end - mint_manager.AUTO_MINT_FINAL_READ
    inherited = {"vid": "38409", "started_at": started, "next_at": end + 60}

    mgr = _hub(HubWrapper(page))
    mgr.state = {"hub": dict(inherited)}
    mgr.route = {"hub": "38409"}
    assert mgr.next_due() == final
    mgr._tick_hub(final - 1)
    assert mgr.wrapper.reporter.lines == []
    mgr._tick_hub(final)
    [(_, _, data)] = mgr.wrapper.reporter.lines
    assert json.loads(data) == {"src": "auto", "coins": 24, "end": end, "total": 1807}
    # Feita a leitura final, não relê a cada tick até o fim.
    mgr._tick_hub(final + 300)
    assert len(mgr.wrapper.reporter.lines) == 1
    assert mgr.next_due() == end + 60

    # Controle: leitura final já feita (read_at depois dela) vale o next_at.
    mgr = _hub(HubWrapper(page))
    mgr.state = {"hub": dict(inherited, read_at=final + 1)}
    mgr._tick_hub(final + 300)
    assert mgr.wrapper.reporter.lines == []


@_with_tmp_store
def test_mint_max_do_hub_registra_pelo_contador():
    # O "(N)" ao lado do campo, no markup do ACADEMY verbatim (lá é "(1)").
    before = _page("started_0510", accented=True) + '<a href="#" id="coin_mint_fill_max">(3)</a>'
    mgr = _hub(HubWrapper(before, after=_page("running_1010", accented=True)))
    assert mgr._mint_max("38409", before) == 3
    [(_, _, data)] = mgr.wrapper.reporter.lines
    assert json.loads(data)["coins"] == 490


if __name__ == "__main__":
    falhas = 0
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok   %s" % nome)
            except Exception as exc:
                falhas += 1
                print("FALHA %s: %r" % (nome, exc))
    sys.exit(1 if falhas else 0)
