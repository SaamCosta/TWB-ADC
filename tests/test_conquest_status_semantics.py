"""
Testes da separacao entre "conquista confirmada" e "o bot achou que acabou".

Ate 2026-08-13 um unico status "complete" cobria tres coisas com graus de
certeza muito diferentes:

  - cache/villages diz que o dono somos nos      -> prova
  - nosso relatorio de nobre marca lealdade <= 0 -> prova
  - a aritmetica de lealdade chegou a zero       -> palpite

e o dashboard pintava as tres de verde com o rotulo "Conquistada". No
incidente da Barbara #40314 o alvo apareceu verde as 20:19:37 com o nobre
ainda voando e a aldeia ainda barbara.

Rodar: python tests/test_conquest_status_semantics.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from webmanager.utils import ConquestReader

# Status que afirmam posse ao usuario. Verde e uma afirmacao de fato.
VERDES = {s for s, cor in ConquestReader.STATUS_COLORS.items() if cor == "success"}


def test_apenas_conquered_e_verde():
    """
    A propriedade central do item 3. Se alguem adicionar um status novo e
    pintar de verde sem ter prova de posse, este teste quebra.
    """
    assert VERDES == {"conquered"}


def test_estimativa_nao_e_verde_nem_se_chama_conquistada():
    assert ConquestReader.STATUS_COLORS["assumed_done"] != "success"
    rotulo = ConquestReader.STATUS_LABELS["assumed_done"].lower()
    assert "conquistada" not in rotulo
    assert "confirma" in rotulo  # tem que dizer o que falta


def test_registro_antigo_perde_o_verde():
    """
    Arquivos gravados antes da separacao: nao da para saber se foram prova ou
    palpite. Na duvida, nao afirmar posse.
    """
    assert ConquestReader.STATUS_COLORS["complete"] != "success"
    assert "antigo" in ConquestReader.STATUS_LABELS["complete"].lower()


def test_todo_status_tem_rotulo_e_cor():
    """Status sem rotulo apareceria como texto cru na tela."""
    assert set(ConquestReader.STATUS_LABELS) == set(ConquestReader.STATUS_COLORS)


def test_perdida_para_outro_jogador_e_vermelha():
    assert ConquestReader.STATUS_COLORS["lost"] == "danger"


def test_estimativa_nao_e_regenerada_a_partir_de_valor_negativo():
    """
    Lealdade <= 0 num relatorio significa troca de dono; o jogo reinicia em 25
    e sobe dai. O clamp existe para a tela nao mostrar regeneracao negativa
    enquanto o nobre ainda voa (last_hit_timestamp no futuro).
    """
    import datetime
    futuro = datetime.datetime.now().timestamp() + 3600
    valor = ConquestReader._estimate_loyalty({
        "loyalty_start": 100, "hits_done": 1, "loyalty_drop_per_noble": 25,
        "loyalty_regen_per_hour": 1, "last_hit_timestamp": futuro,
    })
    assert valor == 75.0  # 100 - 25, sem regen negativa


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
