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
    # Sessão ainda não aberta: só o contador da conta.
    assert [json.loads(d)["src"] for _, _, d in mgr.wrapper.reporter.lines] == ["total"]


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
