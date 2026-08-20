"""
Testes do tratamento da recusa do jogo no farm.

  AttackManager._refused_for_lack_of_units()  -- classifica a ultima recusa
  AttackManager.send_farm()                   -- devolve -1 so nessa causa

O que corrige: o contador local de tropa (`troopmanager.troops`) so decrementa
quando o envio da certo. Numa recusa por falta de unidade ele continua
afirmando que ha tropa, `enough_in_village()` aprova de novo, e o bot tenta o
mesmo pacote no proximo alvo. Medido ao vivo em 2026-08-19: a BBM 001, com 17
cavalarias em casa, gerou 28 tentativas das quais 23 foram recusadas -- cada
uma custando um GET e um POST com o delay_factor no meio.

A distincao que importa: falta de unidade e problema do PACOTE (nao adianta
tentar o mesmo tamanho no proximo alvo), qualquer outra recusa e problema do
ALVO (o pacote segue valido). Blacklistar o pacote por causa de um alvo ruim
pararia o farm da aldeia inteira.

Mensagem verificada ao vivo no br143 postando 9999 lanceiros de uma aldeia que
tem zero, na etapa `try=confirm` -- que valida e nao envia:

    Não existem unidades suficientes

Rodar: python tests/test_farm_refusal.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game.attack import AttackManager, INSUFFICIENT_UNITS_MESSAGES

REAL = "Não existem unidades suficientes"


def _man(refusal=None):
    man = AttackManager.__new__(AttackManager)
    man.last_refusal = refusal
    return man


# --------------------------------------------------------------------------
# _refused_for_lack_of_units
# --------------------------------------------------------------------------

def test_mensagem_real_do_servidor_e_reconhecida():
    assert _man(REAL)._refused_for_lack_of_units() is True


def test_sem_recusa_registrada():
    assert _man(None)._refused_for_lack_of_units() is False


def test_recusa_por_outro_motivo_nao_conta():
    """
    Problema do alvo, nao do pacote. Se isto devolvesse True, um unico alvo
    invalido tiraria o pacote de circulacao e pararia o farm da aldeia.
    """
    assert _man("Esta aldeia não existe")._refused_for_lack_of_units() is False
    assert _man("Modo inválido")._refused_for_lack_of_units() is False


def test_mensagem_desconhecida_degrada_para_o_comportamento_antigo():
    """
    Idioma nao mapeado nao pode ser adivinhado. False mantem o caminho de
    antes (segue para o proximo alvo) e o texto vai ao log em WARNING, que e
    de onde sai a string para acrescentar a lista.
    """
    assert _man("Not enough units available")._refused_for_lack_of_units() is False


def test_comparacao_ignora_caixa():
    assert _man("NÃO EXISTEM UNIDADES SUFICIENTES")._refused_for_lack_of_units() is True


def test_casa_como_substring():
    """A mensagem pode vir com pontuacao ou texto em volta."""
    assert _man("Erro: não existem unidades suficientes.")._refused_for_lack_of_units() is True


def test_string_de_falha_do_extractor_nao_e_confundida():
    """
    Extractor.error_box_text devolve estes textos quando nao consegue ler --
    nenhum deles pode ser lido como falta de tropa.
    """
    for s in ("sem resposta", "sem error_box legivel", "vazio"):
        assert _man(s)._refused_for_lack_of_units() is False, s


def test_lista_de_mensagens_e_imutavel():
    """
    Mutavel no corpo do modulo e o primeiro padrao de bug do CLAUDE.md; aqui
    tambem evita que um chamador acrescente idioma em runtime sem querer.
    """
    assert isinstance(INSUFFICIENT_UNITS_MESSAGES, tuple)


# --------------------------------------------------------------------------
# send_farm -- o codigo de retorno que poe o pacote na lista de ignorados
# --------------------------------------------------------------------------

class _Fake(AttackManager):
    """AttackManager com a rede recortada, para exercitar send_farm."""

    def __init__(self, refusal):
        self.last_refusal = None
        self._refusal = refusal
        self.village_id = "1"
        self.logger = _Silent()
        self.wrapper = _Wrapper()
        self.troopmanager = _Troops()

    def enough_in_village(self, units):
        return False          # localmente parece haver tropa

    def can_attack(self, vid, clear=False):
        return {"high_profile": False, "low_profile": False}

    def attack(self, vid, troops=None):
        self.last_refusal = self._refusal
        return False          # o jogo recusou


class _Silent:
    def __getattr__(self, _):
        return lambda *a, **k: None


class _Wrapper:
    reporter = _Silent()


class _Troops:
    troops = {"light": 17}

    def total_conquest_reserve(self, exclude_owner=None):
        return {}


ALVO = ({"id": "9"}, 5.0, 0.1)


def test_falta_de_tropa_devolve_menos_um():
    """-1 e o que faz run() por o pacote na lista de ignorados do ciclo."""
    assert _Fake(REAL).send_farm(ALVO, {"light": 15}) == -1


def test_outra_recusa_devolve_zero():
    """0 segue para o proximo alvo com o mesmo pacote, que e o certo aqui."""
    assert _Fake("Esta aldeia não existe").send_farm(ALVO, {"light": 15}) == 0


def test_recusa_sem_mensagem_devolve_zero():
    assert _Fake(None).send_farm(ALVO, {"light": 15}) == 0


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
