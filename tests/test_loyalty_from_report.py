"""
Testes de Extractor.loyalty_from_report().

Os HTMLs abaixo sao recortes VERBATIM de relatorios reais do br143, buscados
com a sessao do bot em 2026-08-13 (relatorios 67947364, 67948390, 67949583,
67950495, 68619784 e 68665911 -- o trem de nobres da Barbara #40314 e as duas
conquistas). Nao sao markup inventado: a versao anterior da funcao falhava
justamente por ter sido escrita contra um markup suposto.

Rodar: python tests/test_loyalty_from_report.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.extractors import Extractor


def _linha(de, para):
    """Reproduz a linha exata do relatorio, com a tabulacao que o jogo manda."""
    return (
        '<td>77/5<span class="grey">.</span>245</td> </tr>'
        '    \t<tr><th>Lealdade:</th> \t<td colspan="2">'
        'Descida <b>%s</b> para <b>%s</b></td></tr>   </table>' % (de, para)
    )


def test_trem_de_quatro_nobres():
    """A sequencia real: 100 -> 78 -> 57 -> 32 -> 11."""
    for de, para in [(100, 78), (78, 57), (57, 32), (32, 11)]:
        assert Extractor.loyalty_from_report(_linha(de, para)) == float(para)


def test_pega_o_segundo_numero_nao_o_primeiro():
    """
    A celula tem o antes e o depois. Interessa o depois -- confundir os dois
    faria o bot achar que a lealdade e maior do que e, e mandar nobre a mais.
    """
    assert Extractor.loyalty_from_report(_linha(32, 11)) == 11.0


def test_lealdade_negativa_em_conquista():
    """
    Os dois relatorios de conquista trazem valores negativos. Um \\d+ sem sinal
    capturaria 7 e 8 -- positivos -- invertendo o significado do relatorio.
    """
    assert Extractor.loyalty_from_report(_linha(18, -7)) == -7.0
    assert Extractor.loyalty_from_report(_linha(25, -8)) == -8.0


def test_span_dedicado_tem_prioridade():
    html = '<span id="loyalty_new_value">42</span>' + _linha(32, 11)
    assert Extractor.loyalty_from_report(html) == 42.0


def test_span_dedicado_negativo():
    assert Extractor.loyalty_from_report('<span id="loyalty_new_value">-3</span>') == -3.0


def test_relatorio_sem_lealdade_devolve_none():
    """Relatorio de espionagem/farm: nao ha linha de lealdade."""
    html = '<tr><th>Saque:</th><td colspan="2">2179 1874 1192</td></tr>'
    assert Extractor.loyalty_from_report(html) is None


def test_html_vazio_ou_lixo_devolve_none():
    assert Extractor.loyalty_from_report("") is None
    assert Extractor.loyalty_from_report("<html><body>bot protection</body></html>") is None


def test_aceita_objeto_com_atributo_text():
    class FakeResponse:
        text = None
    r = FakeResponse()
    r.text = _linha(57, 32)
    assert Extractor.loyalty_from_report(r) == 32.0


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
