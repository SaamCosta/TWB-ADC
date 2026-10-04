"""
Testes do portao de recurso antes de formar nobre (docs/backend.md 8.52).

O defeito: `SnobManager.attempt_recruit` lia so' "Ainda podem ser produzidos"
(limite da CONTA: moedas e aldeias) e, sendo > 0, mandava
`screen=snob&action=train` sem conferir se a aldeia pagava o nobre. O jogo
recusava calado, o bot devolvia True, e a aldeia nunca registrava o pedido de
recurso do nobre -- em toda aldeia recrutadora, todo ciclo.

`tests/fixtures/snob_train_short_br143.html` e' recorte verbatim de
`game.php?village=40314&screen=snob` (BBM 007, br143, 2026-10-04, pelo
`get_action` do wrapper do bot): "Ainda podem ser produzidos: 1", nobre a
40.000/50.000/50.000 e a celula "Formar" inativa com "Recursos disponiveis
amanha as 03:04". A aldeia tinha 125.501 / 58.805 / 11.546.

O caso "recurso basta" usa a mesma fixture: a celula inativa e' trocada pela
forma ativa SUPOSTA, porque a ativa nunca foi capturada. O codigo trata
qualquer coisa diferente da forma inativa como liberada (falha aberta, igual
ao comportamento antigo), entao o teste nao depende de acertar o markup.

Rodar: python tests/test_snob_train_gate.py
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game.snobber import SnobManager

FIXTURE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fixtures", "snob_train_short_br143.html"
)
with open(FIXTURE, encoding="utf-8") as fh:
    SHORT_SCREEN = fh.read()

INACTIVE_CELL = '<td id="train_snob_cell" class="inactive">'
assert INACTIVE_CELL in SHORT_SCREEN, "fixture mudou: a celula inativa sumiu"
# Forma ativa suposta (nao capturada) -- so' precisa NAO ser a inativa.
ACTIVE_SCREEN = SHORT_SCREEN.replace(
    INACTIVE_CELL + "Recursos dispon", '<td id="train_snob_cell"><a class="btn">Formar</a><!--'
).replace("amanh", "-->", 1)

NOBLE_COST = {"wood": 40000, "stone": 50000, "iron": 50000}
FIELD_RESOURCES = {"wood": 125501, "stone": 58805, "iron": 11546, "pop": 1618}


class FakeResponse:
    def __init__(self, text):
        self.text = text


class FakeWrapper:
    last_h = "redacted"

    def __init__(self, screen):
        self.screen = screen
        self.gets = []
        self.posts = []

    def get_action(self, action, village_id):
        self.gets.append(("action", action))
        return FakeResponse(self.screen)

    def get_url(self, url):
        self.gets.append(("url", url))
        return FakeResponse("")

    def post_url(self, url, data):
        self.posts.append((url, data))
        return FakeResponse("")


class FakeResman:
    def __init__(self, actual):
        self.actual = dict(actual)
        self.requested = {}

    def update(self, game_state):
        pass

    def request(self, source="building", resource="wood", amount=1):
        self.requested.setdefault(source, {})[resource] = amount


def _manager(screen=SHORT_SCREEN, actual=None):
    man = SnobManager(wrapper=FakeWrapper(screen), village_id="40314")
    man.resman = FakeResman(actual or FIELD_RESOURCES)
    man.troop_manager = types.SimpleNamespace(wanted={}, total_troops={"snob": 0})
    man.building_level = 1
    man.wanted = 4
    return man


def _tentou_formar(man):
    return any("action=train" in str(x) for _, x in man.wrapper.gets)


# --------------------------------------------------------------------------
# parsers, contra o markup real
# --------------------------------------------------------------------------

def test_custo_do_nobre_lido_do_script():
    assert SnobManager.next_snob_cost(SHORT_SCREEN) == NOBLE_COST


def test_motivo_da_celula_inativa():
    reason = SnobManager.train_blocked_reason(SHORT_SCREEN)
    assert reason and reason.startswith("Recursos dispon"), reason
    assert "03:04" in reason


def test_parsers_sem_dado_devolvem_none():
    assert SnobManager.next_snob_cost("") is None
    assert SnobManager.next_snob_cost(None) is None
    assert SnobManager.next_snob_cost(
        "BuildingSnob.Modes.train.next_snob = {quebrado};"
    ) is None
    assert SnobManager.train_blocked_reason(ACTIVE_SCREEN) is None


# --------------------------------------------------------------------------
# o caso de campo
# --------------------------------------------------------------------------

def test_sem_recurso_nao_manda_action_train():
    """BBM 007 em 04/10: vaga na conta, recurso curto -> nenhum GET de formar."""
    man = _manager()
    assert man.run() is False
    assert not _tentou_formar(man)
    assert man.wrapper.posts == []


def test_sem_recurso_registra_o_que_falta_do_nobre():
    """
    O pedido e' o que FALTA (fonte "snob" esta' em SHORTFALL_SOURCES do
    compartilhamento), nao o custo total. Madeira sobra e nao entra.
    """
    man = _manager()
    man.run()
    # 58.805 de argila cobre os 50.000; so' o ferro falta.
    assert man.resman.requested["snob"] == {"iron": 50000 - 11546}
    assert man.is_incomplete is True


def test_pedido_antigo_de_moeda_nao_sobra_no_pedido_do_nobre():
    """
    Moeda e nobre gravam na mesma chave "snob" e `request()` so' sobrescreve
    recurso a recurso: um pedido de madeira da moeda ficaria pendurado.
    """
    man = _manager()
    man.resman.requested["snob"] = {"wood": 9999}
    man.run()
    assert "wood" not in man.resman.requested["snob"]


def test_com_recurso_e_celula_ativa_forma():
    man = _manager(screen=ACTIVE_SCREEN, actual={**NOBLE_COST, "pop": 500})
    man.resman.requested["snob"] = {"iron": 1}
    assert man.run() is True
    assert _tentou_formar(man)
    assert "snob" not in man.resman.requested
    assert man.is_incomplete is False


def test_com_recurso_mas_celula_inativa_nao_forma_e_nao_trava():
    """Populacao, por exemplo: nao e' falta de recurso, nao vira is_incomplete."""
    man = _manager(actual={**NOBLE_COST, "pop": 0})
    assert man.run() is False
    assert not _tentou_formar(man)
    assert man.is_incomplete is False
    assert "snob" not in man.resman.requested


def test_sem_script_de_custo_e_celula_ativa_segue_o_caminho_antigo():
    """Markup diferente: falha aberta, como antes da mudanca."""
    screen = ACTIVE_SCREEN.replace("BuildingSnob.Modes.train.next_snob", "x")
    man = _manager(screen=screen, actual={"wood": 0, "stone": 0, "iron": 0})
    assert man.run() is True
    assert _tentou_formar(man)


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
