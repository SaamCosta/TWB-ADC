"""
Testes do modo mint_coins -- cunhar moeda de ouro sem nunca recrutar nobre.

Por que existe: a moeda de ouro e' da conta inteira, mas o nobre custa
populacao da *aldeia*. A aldeia de torre de vigia (Feature 30) nao tem
populacao de sobra -- nivel 20 custa 11.607 -- entao ela deve cunhar para o
imperio e nunca nobrar. Antes desta mudanca isso nao era expressavel:
`SnobManager.run()` so' alcancava `coin_item()` atraves de `attempt_recruit()`,
dentro de `if self.wanted > 0`, e `Village.run_snob_recruit()` nem instanciava
o manager quando `snobs` era 0 (testava o valor por veracidade). Ou seja,
`snobs: 0` desligava a cunhagem junto.

O markup de `SNOB_SCREEN` e' recorte verbatim de
`game.php?village=41123&screen=snob` no br143, buscado em 2026-08-13 -- e'
dele que sai o custo real da moeda (28k/30k/25k) e o `"id":"coin"` que liga
`using_coin_system`. Nada aqui faz requisicao.

Rodar: python tests/test_snob_mint_only.py
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game.snobber import SnobManager
from game.village import Village

# Recorte verbatim da tela de academia do br143 (aldeia 41123, 2026-08-13).
SNOB_SCREEN = """<script type="text/javascript">
//<![CDATA[
	$(function(){
        BuildingSnob.Modes.train.storage_item = {"wood":28000,"stone":30000,"iron":25000,"id":"coin"};
        BuildingSnob.Modes.train.initGold();
	});
//]]>
</script>"""

COIN_COST = {"wood": 28000, "stone": 30000, "iron": 25000}


class FakeResponse:
    def __init__(self, text):
        self.text = text


class FakeWrapper:
    """Registra tudo que sairia para o jogo, sem sair."""

    last_h = "1fa2e891"

    def __init__(self, screen=SNOB_SCREEN):
        self.screen = screen
        self.gets = []
        self.posts = []

    def get_action(self, action, village_id):
        self.gets.append(("action", action, village_id))
        return None if self.screen is None else FakeResponse(self.screen)

    def get_url(self, url):
        self.gets.append(("url", url, None))
        return FakeResponse("")

    def post_url(self, url, data):
        self.posts.append((url, data))
        return FakeResponse("")


class FakeResman:
    def __init__(self, actual=None, building_needs=None):
        self.actual = dict(actual or COIN_COST)
        self.requested = {}
        if building_needs:
            self.requested["building"] = dict(building_needs)
        self.requests = []

    def update(self, game_state):
        pass

    def request(self, source="building", resource="wood", amount=1):
        self.requests.append((source, resource, amount))


def _manager(actual=None, building_needs=None, screen=SNOB_SCREEN):
    man = SnobManager(wrapper=FakeWrapper(screen=screen), village_id="38409")
    man.resman = FakeResman(actual=actual, building_needs=building_needs)
    man.troop_manager = types.SimpleNamespace(total_troops={})
    man.building_level = 1
    man.wanted = 0
    man.mint_only = True
    return man


def _mintou(man):
    return any("action=coin" in url for url, _ in man.wrapper.posts)


def _recrutou(man):
    """Qualquer coisa que forme nobre: action=train no GET, reserve no POST."""
    return (
        any("action=train" in str(a) for _, a, _ in man.wrapper.gets)
        or any("action=reserve" in url for url, _ in man.wrapper.posts)
    )


# --------------------------------------------------------------------------
# o caminho novo
# --------------------------------------------------------------------------

def test_cunha_com_recurso_suficiente():
    man = _manager()
    assert man.run() is True
    assert _mintou(man)
    assert man.wrapper.posts[0][1]["coin_mint_count"] == "1"


def test_nunca_recruta_nobre():
    """O coracao do modo: cunhar sem jamais formar nobre."""
    man = _manager()
    man.run()
    assert not _recrutou(man)


def test_sem_recurso_nao_cunha_e_nao_pede_ao_mercado():
    """
    Em mint_only a aldeia cunha do que sobra. Pedir recurso ao
    ResourceManager faria o mercado comprar madeira para virar moeda --
    o oposto de "excedente".
    """
    man = _manager(actual={"wood": 1000, "stone": 30000, "iron": 25000})
    assert man.run() is False
    assert not _mintou(man)
    assert man.resman.requests == []


def test_falta_de_recurso_nao_trava_o_recrutamento_da_aldeia():
    """
    is_incomplete significa "a aldeia esta' poupando para um nobre" e, com
    prioritize_snob ligado, barra todo o recrutamento dela (village.py). Em
    mint_only nao ha' nobre a caminho -- travar as tropas seria um efeito
    colateral sem causa.
    """
    man = _manager(actual={"wood": 0, "stone": 0, "iron": 0})
    man.run()
    assert man.is_incomplete is False


# --------------------------------------------------------------------------
# a guarda do construtor
# --------------------------------------------------------------------------

def test_nao_cunha_enquanto_a_fila_de_construcao_tem_fome():
    """
    A torre de vigia custa 4,85M de recursos; enquanto ela sobe, a aldeia nao
    tem excedente nenhum. A guarda corta antes da requisicao HTTP.
    """
    man = _manager(building_needs={"wood": 5000})
    assert man.run() is False
    assert man.wrapper.gets == [], "nem deveria abrir a tela da academia"


def test_pop_pendente_nao_bloqueia():
    """
    BuildingManager tambem registra `pop` em requested["building"], mas
    populacao nao e' recurso que a moeda dispute nem que o mercado compre.
    """
    man = _manager(building_needs={"pop": 200, "wood": 0})
    assert man.run() is True
    assert _mintou(man)


# --------------------------------------------------------------------------
# degradado seguro (segundo padrao do CLAUDE.md: None vindo da rede)
# --------------------------------------------------------------------------

def test_tela_indisponivel_nao_derruba():
    man = _manager(screen=None)  # get_action devolvendo None (timeout / 4xx)
    assert man.run() is False
    assert not _mintou(man)


def test_mundo_sem_sistema_de_moeda_nao_faz_nada():
    """Sem `"id":"coin"` o mundo usa recurso guardado, que so' serve a quem vai
    recrutar -- exatamente o que este modo existe para nao fazer."""
    man = _manager(screen='<script>train.storage_item = {"wood":1,"stone":1,"iron":1};</script>')
    assert man.run() is False
    assert not _mintou(man)
    assert not _recrutou(man)


# --------------------------------------------------------------------------
# o caminho antigo continua igual
# --------------------------------------------------------------------------

def test_sem_mint_e_sem_snobs_nao_faz_nada():
    man = _manager()
    man.mint_only = False
    man.wanted = 0
    assert not man.run()
    assert man.wrapper.gets == []
    assert man.wrapper.posts == []


def test_has_enough_ainda_pede_recurso_no_caminho_de_recrutamento():
    """
    Regressao do loop que substituiu os tres blocos repetidos: o caminho de
    nobre (request=True) tem que continuar registrando o que falta.
    """
    man = _manager(actual={"wood": 28000, "stone": 10000, "iron": 5000})
    assert man.has_enough(COIN_COST) is False
    assert sorted(man.resman.requests) == [
        ("snob", "iron", 20000),
        ("snob", "stone", 20000),
    ]


def test_academia_nivel_zero_nao_cunha():
    man = _manager()
    man.building_level = 0
    assert man.run() is False
    assert man.wrapper.gets == []


# --------------------------------------------------------------------------
# ligacao em village.py -- a decisao de quando o modo vale
# --------------------------------------------------------------------------

class FakeBuilder:
    def __init__(self, snob_level=1):
        self.snob_level = snob_level

    def get_level(self, building):
        return self.snob_level if building == "snob" else 0


def _village(snobs=0, mint_coins=False, snob_level=1):
    """Fake com os metodos reais de Village presos nele, sem __init__ nem rede."""
    import logging

    vil = types.SimpleNamespace(
        village_id="38409",
        config={"villages": {"38409": {"snobs": snobs, "mint_coins": mint_coins}}},
        logger=logging.getLogger("test"),
        wrapper=FakeWrapper(),
        builder=FakeBuilder(snob_level=snob_level),
        snobman=None,
        units=types.SimpleNamespace(total_troops={}),
        resman=FakeResman(),
    )
    vil.get_village_config = types.MethodType(Village.get_village_config, vil)
    vil.run_snob_recruit = types.MethodType(Village.run_snob_recruit, vil)
    return vil


def test_village_liga_mint_only_quando_snobs_e_zero():
    vil = _village(snobs=0, mint_coins=True)
    vil.run_snob_recruit()
    assert vil.snobman is not None, "snobs: 0 nao pode mais impedir a cunhagem"
    assert vil.snobman.mint_only is True
    assert any("action=coin" in url for url, _ in vil.wrapper.posts)


def test_village_com_snobs_pedidos_nao_entra_em_mint_only():
    """Quem recruta ja' cunha pelo caminho normal; mint_only e' so' para quem nao recruta."""
    vil = _village(snobs=4, mint_coins=True)
    vil.run_snob_recruit()
    assert vil.snobman.mint_only is False
    assert vil.snobman.wanted == 4


def test_village_sem_academia_nao_instancia_manager():
    vil = _village(snobs=0, mint_coins=True, snob_level=0)
    vil.run_snob_recruit()
    assert vil.snobman is None


def test_village_snobs_nulo_nao_derruba():
    """`snobs: null` chegava em `None > 0` e levantava TypeError."""
    vil = _village(snobs=None, mint_coins=True)
    vil.run_snob_recruit()
    assert vil.snobman.wanted == 0
    assert vil.snobman.mint_only is True


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
