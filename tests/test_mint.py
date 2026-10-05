"""
Testes da cunhagem (§8.55): custo da moeda, escolha do hub, o que cada aldeia
manda ao hub, leitura da academia e da bandeira, e a ativação da campanha de
itens contra um wrapper de mentira (nenhuma requisição de verdade).

Fixtures:
  * ACADEMY -- recorte VERBATIM de `screen=snob` da BBM 003 (captura de
    04/10/2026, `cache/feature_map/premium_20261004_2305/pages/snob.html.gz`).
    Duas reduções: o token `h` virou REDACTED (repositório público) e os
    acentos de "Criação automática"/"será"/"Duração" foram escritos de novo,
    porque a captura os gravou corrompidos (U+FFFD). Os leitores não dependem
    dessas palavras.
  * CURRENT_FLAG -- recorte VERBATIM de `screen=flags` da mesma captura.
  * FLAG_BONUS_DESCRIPTIONS / DECREE_DESCRIPTIONS -- `descriptions` VERBATIM
    de `ajax=get_inventory` (itens 3021_0 e 3023_0), lido em 05/10/2026.
  * Estados das aldeias: números do `cache/managed` de 05/10/2026.

Rodar: python tests/test_mint.py
"""
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import mint_store
from game import mint_manager, mint_planner
from game.defence_manager import DefenceManager
from game.mint_manager import MintManager
from pages import academy

ACADEMY = '''nob.Modes.train.storage_item = {"wood":23520,"stone":25200,"iron":21000,"id":"coin"};
<span class="nowrap" id="coin_cost_wood"><span class="icon header wood"> </span><span class="value">23<span class="grey">.</span>520</span></span>
                        <span class="nowrap" id="coin_cost_stone"><span class="icon header stone"> </span><span class="value">25<span class="grey">.</span>200</span></span>
                        <span class="nowrap" id="coin_cost_iron"><span class="icon header iron" > </span><span class="value">21<span class="grey">.</span>000<span></span>
                    </div>
                </td>
                <td>
                                            <form action="/game.php?village=44683&amp;screen=snob&amp;action=coin&amp;h=REDACTED" method="post">
                            <input type="text" id="coin_mint_count" name="count" maxlength="5" style="width: 50px;" value="1">
                            <a href="#" id="coin_mint_fill_max">(1)</a>
                            <input type="submit" class="btn btn-default" value="Cunhar">
                        </form>
                                    </td>
            </tr>
        </table>

        <table class="vis auto-minting">
    <tr>
        <th>
                            <span class="avail auto-minting-status" title="Disponibilidade"></span>
                        Criação automática        </th>
    </tr>
    <tr class="h-100">
        <td class="auto-minting-cell">
            <p class="auto-minting-description">
                Quando ativada, a disponibilidade de recursos nesta aldeia será usada para cunhar moedas de ouro.
                Assim que houver recursos suficientes para uma moeda de ouro, ela será cunhada automaticamente.
                Você pode cancelar o processo a qualquer momento.            </p>

            <div class="auto-minting-controls">
                                    <span>Duração 8h</span>
                    <form action="/game.php?village=44683&amp;screen=snob&amp;action=start_auto_minting_session&amp;h=REDACTED" method="post">
                        <button class="btn btn-default">Ativar</button>
                    </form>
                            </div>
        </td>
    </tr>
</table>
'''

CURRENT_FLAG = (
    'FlagsScreen.setFlagCounts({"7":{"1":"0"}});\n'
    '<div id="current_flag" style="margin-top: 10px; ">\n\t\t\t<table class="vis" style="width: 100%; margin: 0">'
    '\n\t\t\t\t<tr>\n\t\t\t\t\t<th>Atual bandeira</th>\n\t\t\t\t</tr>\n\t\t\t\t<tr>\n\t\t\t\t\t<td>\n\t\t\t\t\t\t'
    '<img src="https://dsbr.innogamescdn.com/asset/07afad24/graphic/flags/medium/7_4.webp" alt="" style="float: left;'
    ' margin-right: 4px; width: 60px; height: 60px" />\n\t\t\t\t\t\t<strong>Menores custos de moeda</strong>\n\t\t\t\t'
    '\t\t<p>\n\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t-16% nos custos de moedas\n\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t'
    '</p>\n\n\t\t\t\t\t\t<a href="#" onclick="FlagsScreen.unassignFlag(game_data.village.id); return false">Remover'
    ' bandeira</a>\n\t\t\t\t\t</td>\n\t\t\t\t</tr>\n\t\t\t</table>\n\t\t</div>'
)

FLAG_BONUS_DESCRIPTIONS = [
    {"text": "Duplica o efeito da bandeira atual. A troca da bandeira cancela o efeito do bônus. Não pode ser usado em bandeiras do tipo: Capacidade da população.", "color": None, "image": None},
    {"text": "Duração da recompensa: 48:00:00", "color": "green", "image": None},
    {"text": "Efeito: Em uma aldeia", "color": "green", "image": None},
]
DECREE_DESCRIPTIONS = [
    {"text": "-10% nos custos de moedas", "color": None, "image": None},
    {"text": "Duração: 24:00:00", "color": "green", "image": None},
    {"text": "Efeito: Em todas as aldeias", "color": "green", "image": None},
]


def village(name, x, y, flag, storage, res, snob=1):
    return {
        "name": name, "x": x, "y": y, "storage": storage,
        "resources": dict(zip(("wood", "stone", "iron"), res)),
        "buidling_levels": {"snob": snob},
        "flags": {"current_flag": flag},
    }


STATES = {
    "41123": village("BBM 001", 577, 306, [7, 2], 500000, (312456, 50660, 50616)),
    "38409": village("BBM 002", 578, 305, [7, 7], 500000, (454881, 94346, 51698)),
    "74689": village("BBM 010", 578, 306, [7, 7], 400000, (290547, 6281, 30849)),
    "34597": village("BBM 016", 576, 316, [1, 4], 142373, (105887, 27182, 21072)),
    "46676": village("BBM 027", 569, 299, [1, 1], 62305, (52875, 47033, 46422), snob=0),
}
CONFIG_VILLAGES = {
    "41123": {"managed": True, "snobs": 4},
    "38409": {"managed": True, "snobs": 0, "mint_coins": True},
    "74689": {"managed": True, "snobs": 4},
    "34597": {"managed": True, "snobs": 4},
    "46676": {"managed": True, "snobs": 4},
}


# ---------------------------------------------------------------- planner

def test_desconto_da_bandeira_bate_com_os_niveis_medidos():
    medidos = {1: 25200, 2: 24640, 3: 24080, 4: 23520, 5: 22960, 7: 21840}
    for level, wood in medidos.items():
        assert mint_planner.flag_coin_cost(level)["wood"] == wood, level
    assert mint_planner.flag_discount_pct(0) == 0


def test_hub_e_a_bbm_002():
    hub, ranking = mint_planner.choose_hub(STATES, CONFIG_VILLAGES, time.time())
    assert hub == "38409", ranking
    # Mesma bandeira que a BBM 010: desempata pelo armazém (500k x 400k).
    assert ranking[1]["vid"] == "74689"
    # Sem academia não entra.
    assert "46676" not in {c["vid"] for c in ranking}


def test_override_vale_so_para_aldeia_com_academia():
    now = time.time()
    assert mint_planner.choose_hub(STATES, CONFIG_VILLAGES, now, override="74689")[0] == "74689"
    assert mint_planner.choose_hub(STATES, CONFIG_VILLAGES, now, override="46676")[0] == "38409"


def test_custo_medido_vence_a_bandeira_e_expira():
    now = time.time()
    measured = {"34597": {"wood": 10000, "stone": 10000, "iron": 10000, "read_at": int(now)}}
    hub, _ = mint_planner.choose_hub(
        mint_planner.with_measured(STATES, measured), CONFIG_VILLAGES, now)
    assert hub == "34597"
    measured["34597"]["read_at"] = int(now - mint_planner.MEASURED_COST_MAX_AGE - 1)
    hub, _ = mint_planner.choose_hub(
        mint_planner.with_measured(STATES, measured), CONFIG_VILLAGES, now)
    assert hub == "38409"


def test_rota_manda_primeiro_o_que_falta_no_hub():
    hub = STATES["38409"]
    plan = mint_planner.plan_route(
        donor_res=STATES["41123"]["resources"], floor=20000,
        hub_res=hub["resources"], hub_storage=hub["storage"], hub_inflight={},
        carry=60000, per_merchant=1000, cost=mint_planner.flag_coin_cost(7),
    )
    # O hub tem 454 mil de madeira: madeira só gasta comerciante.
    assert "wood" not in plan, plan
    assert plan["iron"] == 30616 and plan["stone"] > 0, plan
    assert sum(plan.values()) <= 60000


def test_rota_respeita_piso_espaco_e_minimo():
    cost = mint_planner.flag_coin_cost(7)
    assert mint_planner.plan_route({"wood": 15000, "stone": 15000, "iron": 15000}, 20000,
                                   {}, 500000, {}, 100000, 1000, cost) == {}
    plan = mint_planner.plan_route({"wood": 0, "stone": 0, "iron": 200000}, 0,
                                   {"iron": 470000}, 500000, {"iron": 3000}, 100000, 1000, cost)
    assert plan == {"iron": 2000}, plan  # 95% de 500k = 475k, menos estoque e a caminho
    assert mint_planner.plan_route({"iron": 900}, 0, {}, 500000, {}, 100000, 1000, cost) == {}


def test_moedas_pelo_recurso_mais_escasso():
    assert mint_planner.coins_for({"wood": 10**6, "stone": 10**6, "iron": 19500}, mint_planner.flag_coin_cost(7)) == 1


# ---------------------------------------------------------------- telas

def test_academia_custo_maximo_e_cunhagem_automatica():
    assert academy.coin_cost(ACADEMY) == {"wood": 23520, "stone": 25200, "iron": 21000}
    assert academy.max_mintable(ACADEMY) == 1
    assert academy.auto_minting_state(ACADEMY) == "can_start"
    sem_botao = ACADEMY.split('<form action="/game.php?village=44683&amp;screen=snob&amp;action=start')[0] + "</table>"
    assert academy.auto_minting_state(sem_botao) == "no_start_button"
    assert academy.auto_minting_state("<html>login</html>") is None
    assert academy.coin_cost("<html>login</html>") is None


def test_bandeira_atual():
    assert academy.current_flag(CURRENT_FLAG) == (7, 4)
    hidden = 'FlagsScreen.setFlagCounts({});<div id="current_flag" style="margin-top: 10px; display: none">'
    assert academy.current_flag(hidden) == ()
    assert academy.current_flag("<html>sessão expirada</html>") is None


def test_duracao_lida_da_descricao_do_item():
    payload = {"data": {"3021_0": {"descriptions": FLAG_BONUS_DESCRIPTIONS},
                        "3023_0": {"descriptions": DECREE_DESCRIPTIONS}}}
    assert mint_manager.item_duration_seconds(payload, "3021_0", 0) == 48 * 3600
    assert mint_manager.item_duration_seconds(payload, "3023_0", 0) == 24 * 3600
    assert mint_manager.item_duration_seconds(payload, "nada", 7) == 7


def test_horario_diario():
    base = time.mktime((2026, 10, 5, 22, 0, 0, 0, 0, -1))
    assert mint_manager.daily_due(base, "22:30", None)[0] is False
    due, today = mint_manager.daily_due(base + 1800, "22:30", None)
    assert due and today == "2026-10-05"
    assert mint_manager.daily_due(base + 1800, "22:30", "2026-10-05")[0] is False
    assert mint_manager.daily_due(base + 1800 + mint_manager.DAILY_MAX_LATE + 60, "22:30", None)[0] is False
    assert mint_manager.daily_next(base, "22:30") == base + 1800


# ---------------------------------------------------------------- campanha

class Resp:
    def __init__(self, text):
        self.text = text


class FakeWrapper:
    """Inventário que só cai quando o jogo 'aceita' o consumo daquela chave."""

    def __init__(self, amounts, flag_html=CURRENT_FLAG.replace("7_4", "7_7"), accept=None):
        self.amounts = dict(amounts)
        self.flag_html = flag_html
        self.accept = accept if accept is not None else set(amounts)
        self.consumed = []
        self.last_h = "h"
        self.last_response = None

    def get_api_data(self, village_id, action, params=None):
        return {"response": {
            "inventory": {k: {"amount": str(v)} for k, v in self.amounts.items() if v > 0},
            "data": {"3021_0": {"descriptions": FLAG_BONUS_DESCRIPTIONS},
                     "3023_0": {"descriptions": DECREE_DESCRIPTIONS}},
            "expire": [],
        }}

    def get_api_action(self, village_id, action, params=None, data=None):
        assert action == "consume" and params["screen"] == "inventory"
        self.consumed.append((village_id, data["item_key"]))
        if data["item_key"] in self.accept:
            self.amounts[data["item_key"]] -= 1
        return {"response": {}}

    def get_url(self, url, headers=None):
        if "screen=flags" in url:
            return Resp(self.flag_html)
        return Resp(ACADEMY)

    def post_url(self, url, data, headers=None):
        return Resp(ACADEMY)


def make_manager(wrapper):
    mgr = MintManager(wrapper)
    mgr.config = {"villages": CONFIG_VILLAGES, "minting": {}}
    mgr.found_villages = list(CONFIG_VILLAGES)
    return mgr


def with_tmp_store(fn):
    def run():
        tmp = tempfile.mkdtemp(prefix="twb-mint-")
        orig = (mint_store.CAMPAIGN_PATH, mint_store.STATE_PATH, mint_manager.time.sleep)
        mint_store.CAMPAIGN_PATH = os.path.join(tmp, "campaign.json")
        mint_store.STATE_PATH = os.path.join(tmp, "state.json")
        mint_manager.time.sleep = lambda s: None
        try:
            fn()
        finally:
            mint_store.CAMPAIGN_PATH, mint_store.STATE_PATH, mint_manager.time.sleep = orig
            shutil.rmtree(tmp, ignore_errors=True)
    run.__name__ = fn.__name__
    return run


@with_tmp_store
def test_campanha_ativa_bonus_e_dois_decretos_na_aldeia_certa():
    w = FakeWrapper({"3021_0": 2, "3023_0": 2, "3077_0": 1})
    mint_store.approve(hub="38409", hub_name="BBM 002", decrees=2, war_chest=False, floor=20000)
    mgr = make_manager(w)
    mgr._activate(mint_store.load_campaign(), None)
    c = mint_store.load_campaign()
    assert c["status"] == "active", c.get("events")
    assert w.consumed == [("38409", "3021_0"), ("38409", "3023_0"), ("38409", "3023_0")], w.consumed
    assert w.amounts["3077_0"] == 1  # Cofre não marcado: intocado
    assert c["ends_at"] - c["started_at"] == 48 * 3600
    route = mgr.route_for("38409")
    assert route["role"] == "hub" and route["flag_lock"] and route["pause_spending"]
    assert mgr.route_for("41123")["role"] == "donor"


@with_tmp_store
def test_bandeira_errada_falha_sem_gastar_nada():
    w = FakeWrapper({"3021_0": 2, "3023_0": 2}, flag_html=CURRENT_FLAG.replace("7_4", "1_7"))
    mint_store.approve(hub="38409", hub_name="BBM 002", decrees=2, war_chest=False, floor=0)
    make_manager(w)._activate(mint_store.load_campaign(), None)
    assert mint_store.load_campaign()["status"] == "failed"
    assert w.consumed == []


@with_tmp_store
def test_resposta_sem_queda_no_inventario_nao_conta_como_ativado():
    w = FakeWrapper({"3021_0": 2, "3023_0": 2}, accept=set())
    mint_store.approve(hub="38409", hub_name="BBM 002", decrees=2, war_chest=False, floor=0)
    make_manager(w)._activate(mint_store.load_campaign(), None)
    c = mint_store.load_campaign()
    assert c["status"] == "failed" and "não caiu" in c["failed_reason"], c
    # Falhou o Bônus: os Decretos não chegam a ser tentados.
    assert w.consumed == [("38409", "3021_0")]


@with_tmp_store
def test_retomada_nao_gasta_de_novo_o_que_ja_saiu():
    w = FakeWrapper({"3021_0": 1, "3023_0": 2})  # o Bônus já foi gasto antes da queda
    mint_store.approve(hub="38409", hub_name="BBM 002", decrees=2, war_chest=False, floor=0)

    def crash_after_flag(data):
        data["status"] = "activating"
        data["plan"] = [{"key": "3021_0", "item_id": "3021", "count": 1},
                        {"key": "3023_0", "item_id": "3023", "count": 2}]
        data["inventory_before"] = {"3021_0": 2, "3023_0": 2}
    mint_store.update_campaign(crash_after_flag)
    make_manager(w)._activate(mint_store.load_campaign(), None)
    assert w.consumed == [("38409", "3023_0"), ("38409", "3023_0")], w.consumed
    assert mint_store.load_campaign()["status"] == "active"


@with_tmp_store
def test_releitura_sem_inventario_nao_vira_item_gasto():
    w = FakeWrapper({"3021_0": 2, "3023_0": 2})
    mint_store.approve(hub="38409", hub_name="BBM 002", decrees=2, war_chest=False, floor=0)
    real = w.get_api_data
    calls = {"n": 0}

    def broken_after_consume(village_id, action, params=None):
        calls["n"] += 1
        data = real(village_id, action, params)
        if calls["n"] > 1:  # a releitura depois do primeiro consumo vem sem `inventory`
            del data["response"]["inventory"]
        return data
    w.get_api_data = broken_after_consume
    make_manager(w)._activate(mint_store.load_campaign(), None)
    c = mint_store.load_campaign()
    assert c["status"] == "activating", c  # nada concluído sem prova
    assert w.consumed == [("38409", "3021_0")], w.consumed


@with_tmp_store
def test_segunda_campanha_e_recusada_enquanto_a_primeira_esta_aberta():
    mint_store.approve(hub="38409", hub_name="BBM 002", decrees=2, war_chest=False, floor=0)
    try:
        mint_store.approve(hub="74689", hub_name="BBM 010", decrees=0, war_chest=False, floor=0)
    except ValueError:
        return
    raise AssertionError("aprovou duas campanhas abertas")


def test_bandeira_travada_nao_troca_nem_sob_ataque():
    dm = DefenceManager(village_id="38409")
    dm.manage_flags_enabled = True
    dm._flag_state_confirmed = True
    dm._flags_fresh = True
    dm._can_change_flag = True
    dm.flags = {4: 7, 7: 7}
    dm.current_flag = [7, 7]
    calls = []
    dm.flag_set = lambda flag, level: calls.append((flag, level))
    dm.flag_lock_reason = "campanha de cunhagem ativa"
    dm.flag_logic(dm.set_flag_under_attack)
    assert calls == [], calls
    dm.flag_lock_reason = None
    dm.flag_logic(dm.set_flag_under_attack)
    assert calls and calls[0][0] == 4, calls  # sem trava, a defesa troca (prova que o teste alcança o flag_set)


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
