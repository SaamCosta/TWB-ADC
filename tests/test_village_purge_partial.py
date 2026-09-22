"""
Teste da confirmacao de perda antes da limpeza de aldeias
(TWB.confirm_lost_villages) -- o B9 da auditoria do fork, docs/backend.md 7.10.

`tests/test_village_purge_guard.py` cobre a leitura VAZIA (incidente de
2026-08-22) e a de outra conta. Este cobre a leitura PARCIAL: `twb.py` pede
`screen=overview_villages` sem `group`/`page`, e o jogo serve o grupo e a
pagina que o jogador deixou selecionados no navegador. Com a visao geral
filtrada num grupo de 10 aldeias, a interseccao com o config nao fica vazia,
nenhuma recusa antiga dispara, e a limpeza apagava as outras 20 do config.

Fixture: linhas VERBATIM de `cache/world/villages_br143.txt` (map/village.txt
do br143 baixado em 2026-09-20). Quatro aldeias nossas (dono 5955651), a
44167 -- que esta no config hoje, foi conquistada depois de 20/09 e por isso
ainda aparece com o dono anterior no arquivo --, e uma de outro jogador.

Rodar: python tests/test_village_purge_partial.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game.world_villages import parse
from twb import TWB

VILLAGE_TXT = """\
32056,BBM+020,574,317,5955651,2411,0
34597,BBM+016,576,316,5955651,4231,0
35059,BBM+019,579,318,5955651,2378,0
36294,BBM+021,569,312,5955651,2285,0
44167,JULIET,557,293,919832469,1043,0
1,011,631,531,7363091,10106,0
"""
ROWS = parse(VILLAGE_TXT)


def _check(label, got, expected):
    assert got == expected, f"{label}: esperado {expected!r}, veio {got!r}"
    print(f"  ok  {label}: {got!r}")


def test_visao_geral_filtrada_por_grupo_nao_apaga_nada():
    # Navegador filtrado num grupo com 2 das 4 aldeias.
    lost, kept = TWB.confirm_lost_villages(
        ["35059", "36294"], ["32056", "34597"], ROWS
    )
    _check("perdidas", lost, [])
    _check("mantidas", sorted(kept), ["35059", "36294"])
    assert "grupo" in kept["35059"], kept["35059"]


def test_perda_real_confirmada_pelo_dono_na_lista():
    # A aldeia "1" e de outro jogador na lista do mundo.
    lost, kept = TWB.confirm_lost_villages(
        ["1"], ["32056", "34597", "35059"], ROWS
    )
    _check("perdidas", lost, ["1"])
    _check("mantidas", kept, {})


def test_lista_do_mundo_indisponivel_nao_apaga_nada():
    lost, kept = TWB.confirm_lost_villages(["35059"], ["32056"], {})
    _check("perdidas", lost, [])
    assert "indisponivel" in kept["35059"], kept


def test_ausente_da_lista_fica():
    lost, kept = TWB.confirm_lost_villages(["99999999"], ["32056"], ROWS)
    _check("perdidas", lost, [])
    _check("motivo", kept["99999999"], "ausente da lista do mundo")


def test_conquista_recente_nao_rouba_a_identidade():
    # A 44167 veio na visao geral (e nossa hoje) mas o arquivo ainda da o
    # dono anterior. Por maioria, "nos" continua sendo 5955651, e a 35059 --
    # nossa, fora da leitura -- nao vira perda por causa disso.
    lost, kept = TWB.confirm_lost_villages(
        ["35059"], ["44167", "32056", "34597"], ROWS
    )
    _check("perdidas", lost, [])
    _check("mantidas", sorted(kept), ["35059"])


def test_sem_como_saber_quem_somos_nao_apaga_nada():
    # Nenhuma aldeia lida aparece na lista: nao ha dono de referencia.
    lost, kept = TWB.confirm_lost_villages(["1"], ["88888888"], ROWS)
    _check("perdidas", lost, [])
    assert "quem somos" in kept["1"], kept


def test_twb_py_nao_apaga_mais_por_ausencia_na_visao_geral():
    # Guarda de regressao contra a forma antiga, que comparava direto com
    # found_villages: a lista de remocao tem que sair de `confirmed_lost`.
    src = open(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "twb.py"),
        encoding="utf-8",
    ).read()
    assert 'if vid not in self.found_villages]\n        if stale_config_ids' not in src
    assert "if vid in confirmed_lost]" in src
    assert "if cached_vid in confirmed_lost:" in src
    print("  ok  twb.py so remove o que confirm_lost_villages confirmou")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            print(name)
            fn()
    print("OK")
