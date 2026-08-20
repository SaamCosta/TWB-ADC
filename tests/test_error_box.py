"""
Testes de Extractor.error_box_text -- o motivo pelo qual o jogo recusou algo.

Quatro pontos do bot faziam `if '<div class="error_box">' in resposta` e
jogavam o motivo fora: game/attack.py (farm), game/defence_manager.py
(suporte, sem log nenhum), game/hunter.py (logava que houve, nao o que dizia)
e game/resources.py -- este ultimo era o unico que lia o texto, com uma copia
local da funcao. Em 2026-08-19 ela subiu para core/extractors.py e passou a
servir os quatro.

Por que o motivo importa: as causas pedem reacoes opostas. "Nao existem
unidades suficientes" quer dizer "pare de tentar este pacote neste ciclo";
"aldeia nao existe" quer dizer "tire este alvo da lista". Ate aqui as duas
viravam o mesmo False silencioso, e o bot repetia o mesmo pacote no proximo
alvo -- 23 tentativas recusadas num unico ciclo da BBM 001 em 2026-08-19.

O fixture principal e VERBATIM do br143, capturado em 2026-08-19 postando
9999 lanceiros de uma aldeia que tem zero para a etapa `try=confirm` (que
valida e nao envia -- o envio exige uma terceira requisicao, popup_command,
que nao foi feita).

Rodar: python tests/test_error_box.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.extractors import Extractor

# --- verbatim: br143, place&try=confirm com tropa insuficiente -------------
REAL = (
    '<div class="error_box">\n\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t<div class="content">\n'
    '                                                            \tNão existem '
    'unidades suficientes\n\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t</div>\n'
    '                                           </div>\n'
)


class _Resp:
    """Imita o objeto de resposta do requests, que e o que os chamadores tem."""

    def __init__(self, text):
        self.text = text


def test_mensagem_real_do_servidor():
    assert Extractor.error_box_text(REAL) == "Não existem unidades suficientes"


def test_aceita_objeto_de_resposta():
    assert Extractor.error_box_text(_Resp(REAL)) == "Não existem unidades suficientes"


def test_acentuacao_preservada():
    """
    O jogo responde em pt-BR com charset=utf-8; a mensagem tem que chegar
    legivel ao log, que twb.py abre com encoding="utf-8".
    """
    msg = Extractor.error_box_text(REAL)
    assert "ã" in msg, "o 'a' com til se perdeu no caminho"
    assert msg.encode("utf-8").startswith(b"N\xc3\xa3o")


def test_box_de_uma_linha_so():
    """Fallback para o error_box sem <div class=content> dentro."""
    html = '<div class="error_box">Modo inválido</div>'
    assert Extractor.error_box_text(html) == "Modo inválido"


def test_sem_error_box():
    assert Extractor.error_box_text("<html><body>tudo certo</body></html>") == (
        "sem error_box legivel"
    )


def test_resposta_nula():
    """get_url devolve None em qualquer excecao (ver CLAUDE.md, 2o padrao)."""
    assert Extractor.error_box_text(None) == "sem resposta"


def test_objeto_sem_atributo_text():
    assert Extractor.error_box_text(object()) == "sem error_box legivel"


def test_box_vazio_nao_devolve_string_vazia():
    """
    O retorno vai direto num log; string vazia produziria uma linha que nao
    diz nada, indistinguivel de nao ter logado.
    """
    assert Extractor.error_box_text('<div class="error_box">   </div>') == "vazio"


def test_sempre_devolve_algo_truthy():
    for entrada in (None, "", "<html></html>", object(), REAL,
                    '<div class="error_box"></div>'):
        assert Extractor.error_box_text(entrada), f"caiu em falsy para {entrada!r}"


def test_texto_longo_e_truncado():
    html = '<div class="error_box">' + ("x" * 900) + "</div>"
    assert len(Extractor.error_box_text(html)) == 300


def test_tags_internas_viram_espaco():
    html = '<div class="error_box"><b>Aldeia</b> <i>inexistente</i></div>'
    assert Extractor.error_box_text(html) == "Aldeia inexistente"


def test_primeiro_box_vence_quando_ha_mais_de_um():
    html = ('<div class="error_box">primeiro</div>'
            '<div class="error_box">segundo</div>')
    assert Extractor.error_box_text(html) == "primeiro"


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
