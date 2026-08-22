"""
Testes do bonus de velocidade do apoio -- item "Sinal da Aflicao"
(Extractor.incoming_support_speed_bonus + WorldConfig.travel_seconds).

O item acelera o apoio que CHEGA na aldeia que o ativou. Texto do jogo:

    "Apoio a caminho enviado enquanto este estiver ativo ira percorrer 30%
     mais rapido. Sem efeito em apoio ja enviado."

Duas propriedades que definem o desenho:
  - vale no momento do ENVIO, entao da para tratar como fator no calculo de
    viagem em vez de precisar acompanhar comandos em voo;
  - fica no DESTINO, nao na doadora -- por isso o valor viaja por
    cache/managed/<destino>.json ate quem vai enviar.

A FORMULA foi medida contra o servidor, nao deduzida do texto. br143,
2026-08-22, item ativo na BBM 008, envio real da BBM 009 (3,16228 campos,
espada a 22 min/campo, que e a unidade mais lenta do pacote):

    sem bonus    3,16228 x 22 x 60 = 4.174 s = 1:09:34
    o jogo mostrou                           = 0:53:31
    4.174 / 1,3                    = 3.211 s = 0:53:30   <-- bate (1 s)
    4.174 x 0,7                    = 2.922 s = 0:48:41   <-- NAO bate

Ou seja "30% mais rapido" e **duracao / 1,3**. A leitura ingenua (x 0,7) erra
5 minutos numa viagem de uma hora, sempre para menos, e o erro cresce com a
distancia -- faria o bot achar que ainda da tempo quando nao da.

O percentual e LIDO do markup, nunca assumido: o item existe em mais de uma
potencia na conta.

Rodar: python tests/test_support_speed_bonus.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.extractors import Extractor
from core.world_config import WorldConfig

# --------------------------------------------------------------------------
# Fixture. A metade final -- de "<i>" ate o fechamento -- e VERBATIM da
# resposta crua de game.php?village=41114&screen=overview em 2026-08-22.
# A abertura do <td> e o <h3> estao RECONSTRUIDOS: o cliente bloqueou o dump
# daquele trecho por conter a URL do CDN. As tres propriedades que o parser
# usa foram, ainda assim, verificadas contra o HTML cru na mesma sessao:
#   - class="effect_tooltip village_overview_effect"          (lido)
#   - title delimitado por aspas duplas, comecando com "\n    " (lido)
#   - <b>+30%</b> LITERAL, nao escapado -- o regex <b>\+(\d+)%</b> casou
#     direto contra a string crua e devolveu "30"                (lido)
#
# ⚠️ O title carrega HTML literal, entao contem ">" -- por isso o parser NAO
# pode usar <td[^>]*>. Este fixture reproduz essa armadilha de proposito.
# --------------------------------------------------------------------------
REAL_EFFECT_CELL = (
    '<td class="effect_tooltip village_overview_effect" title="\n'
    '                        <h3><img src=&quot;ICONE/benefit_incoming_support_speed.webp&quot;>'
    ' Sinal da Aflição</h3>\n'
    '                        <i>Apoio a caminho enviado enquanto este estiver ativo irá '
    'percorrer 30% mais rápido. Sem efeito em apoio já enviado.</i>\n\n'
    '                        <ul>\n'
    '                        <li><b>+30%</b> de itens expira em 24.08. às 08:25</li>\n'
    '                </ul>                    ">\n'
    '                        <img src="ICONE/benefit_incoming_support_speed.webp" alt=""/>\n'
    '                        Sinal da Aflição\n'
    '</td>'
)

# O outro efeito ativo na mesma aldeia, sem title -- serve para garantir que o
# parser nao confunde efeitos.
OUTRO_EFEITO = (
    '<td class="effect_tooltip village_overview_effect" title="">4% Recursos</td>'
)

BR143_SPEEDS = {"spear": 18.0, "sword": 22.0, "spy": 9.0, "light": 10.0}
DIST_009_008 = 3.1622776601683795  # sqrt(1^2 + 3^2), (583|312) -> (584|309)


def _check(label, got, expected):
    assert got == expected, f"{label}: esperado {expected!r}, veio {got!r}"
    print(f"  ok  {label}: {got!r}")


def test_le_o_percentual_do_markup_real():
    print("test_le_o_percentual_do_markup_real")
    pagina = "<table>" + OUTRO_EFEITO + REAL_EFFECT_CELL + "</table>"
    _check("percentual", Extractor.incoming_support_speed_bonus(pagina), 30)
    _check("so o outro efeito -> 0", Extractor.incoming_support_speed_bonus(
        "<table>" + OUTRO_EFEITO + "</table>"), 0)
    _check("pagina sem efeitos", Extractor.incoming_support_speed_bonus("<html></html>"), 0)
    _check("string vazia", Extractor.incoming_support_speed_bonus(""), 0)


def test_percentual_nao_e_chumbado():
    """
    O usuario tem outro item de potencia diferente. Trocar o numero no markup
    tem que mudar a leitura -- se este teste passar com 30 chumbado, o parser
    esta errado.
    """
    print("test_percentual_nao_e_chumbado")
    for pct in (10, 25, 30, 50, 100):
        markup = REAL_EFFECT_CELL.replace("+30%", f"+{pct}%")
        _check(f"le {pct}%", Extractor.incoming_support_speed_bonus(markup), pct)


def test_valor_absurdo_e_ignorado():
    """Fora de 0-100 e leitura errada, nao item milagroso."""
    print("test_valor_absurdo_e_ignorado")
    _check("500% ignorado", Extractor.incoming_support_speed_bonus(
        REAL_EFFECT_CELL.replace("+30%", "+500%")), 0)
    _check("0% ignorado", Extractor.incoming_support_speed_bonus(
        REAL_EFFECT_CELL.replace("+30%", "+0%")), 0)


def test_td_com_maior_que_dentro_do_title():
    """
    A armadilha real do markup, medida em vez de suposta.

    O title carrega HTML literal (<h3>, <i>, <b>, <ul>), entao contem '>'. Ao
    escrever este teste eu afirmei que por isso um regex com <td[^>]*> "nao
    casaria" a celula. Rodei e era falso -- ele casa. O que acontece de fato,
    e que vale fixar aqui, e mais especifico:

      1. <td[^>]*> TRUNCA a tag de abertura: para no '>' do <h3> que esta
         dentro do title, nao no '>' que fecha o <td>.
      2. Por causa disso, extrair title="..." de dentro da tag casada FALHA --
         essa e a armadilha de verdade.
      3. Mas a forma em bloco, <td ...>(.*?)</td>, se RECUPERA, porque o
         (.*?) atravessa o resto do title e chega ao <b>+30%</b>.

    Ou seja: o parser atual esta certo, e um parser ingenuo em bloco tambem
    funcionaria aqui. O que nao funciona e escopar no atributo. Fixado para
    ninguem "simplificar" na direcao (2) achando que e equivalente.
    """
    print("test_td_com_maior_que_dentro_do_title")
    import re

    abertura = re.search(r"<td[^>]*>", REAL_EFFECT_CELL).group(0)
    _check("(1) tag de abertura trunca no <h3>", abertura.endswith("<h3>"), True)
    _check(
        "(2) title nao sai da tag truncada",
        re.search(r'title="([^"]*)"', abertura),
        None,
    )
    bloco = re.compile(
        r'<td[^>]*class="[^"]*village_overview_effect[^"]*"[^>]*>(.*?)</td>', re.S
    )
    _check("(3) forma em bloco se recupera", len(bloco.findall(REAL_EFFECT_CELL)), 1)
    _check("parser atual casa", Extractor.incoming_support_speed_bonus(REAL_EFFECT_CELL), 30)


def test_formula_bate_com_a_medicao_real():
    """
    O numero que o jogo mostrou: 0:53:31 para 124 lanceiros + 90 espadas + 50
    exploradores da BBM 009 para a BBM 008, com o item ativo.
    """
    print("test_formula_bate_com_a_medicao_real")
    tropas = {"spear": 124, "sword": 90, "spy": 50}
    sem = WorldConfig.travel_seconds(BR143_SPEEDS, DIST_009_008, tropas)
    com = WorldConfig.travel_seconds(BR143_SPEEDS, DIST_009_008, tropas, speed_bonus_pct=30)
    _check("sem bonus (s)", sem, 4174)
    # 4174,2 / 1,3 = 3210,9 -> int() trunca para 3210. O jogo mostrou 3211.
    # O segundo de diferenca e o truncamento, nao a formula: irrelevante para
    # uma decisao cuja unidade e a hora, e errar para MENOS e o lado seguro
    # (o bot acha a viagem um tico mais curta do que ela e).
    _check("com +30% (s)", com, 3210)
    medido = 53 * 60 + 31  # 0:53:31 lido na tela de confirmacao
    assert abs(com - medido) <= 2, f"esperado ~{medido}s, veio {com}s"
    print(f"  ok  bate com o jogo: {com}s vs {medido}s medidos")
    # E explicitamente NAO a leitura ingenua.
    assert com != int(4174 * 0.7), "duracao * 0.7 seria 2921s -- formula errada"
    print("  ok  nao e duracao * 0,7 (que daria 2921s)")


def test_bonus_zero_ou_invalido_nao_altera():
    print("test_bonus_zero_ou_invalido_nao_altera")
    t = {"sword": 10}
    base = WorldConfig.travel_seconds(BR143_SPEEDS, 10, t)
    for bonus in (0, None, "", "abc", -20):
        _check(f"bonus {bonus!r}", WorldConfig.travel_seconds(
            BR143_SPEEDS, 10, t, speed_bonus_pct=bonus), base)


def test_gate_usa_o_bonus_do_destino():
    """
    Integracao: o bonus tem que vir do DESTINO, nao da doadora. Com +30% no
    destino a janela desliza, e um envio que o bot recusaria passa a ser
    aceito -- que e exatamente o caso da BBM 007 em 2026-08-22.
    """
    print("test_gate_usa_o_bonus_do_destino")
    from game.defence_manager import DefenceManager

    class _Units:
        troops = {"spear": "1000", "sword": "1000"}

    def _dm(bonus):
        dm = DefenceManager(village_id="doadora")
        dm.unit_speeds = BR143_SPEEDS
        dm.units = _Units()
        dm.support_lead_time_sec = 7200
        dm.my_other_villages_eta = {"alvo": int(3.9 * 3600)}
        dm.my_other_villages_support_bonus = {"alvo": bonus}

        class _Map:
            map_pos = {"alvo": [0, 0]}
            my_location = (0, 0)

            @staticmethod
            def get_dist(pos):
                return 13.04  # BBM 007 -> BBM 008

        dm.map = _Map()
        return dm

    sem = _dm(0)
    com = _dm(30)
    _check("viagem sem bonus (h)", round(sem.support_travel_seconds("alvo") / 3600, 2), 4.78)
    _check("viagem com +30% (h)", round(com.support_travel_seconds("alvo") / 3600, 2), 3.68)
    _check("bot sem o bonus recusa", sem.support_timing("alvo")[0], False)
    _check("com o bonus, envia", com.support_timing("alvo")[0], True)


if __name__ == "__main__":
    test_le_o_percentual_do_markup_real()
    test_percentual_nao_e_chumbado()
    test_valor_absurdo_e_ignorado()
    test_td_com_maior_que_dentro_do_title()
    test_formula_bate_com_a_medicao_real()
    test_bonus_zero_ou_invalido_nao_altera()
    test_gate_usa_o_bonus_do_destino()
    print("\nOK - todos os testes do bonus de velocidade passaram")
