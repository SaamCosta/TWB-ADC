"""
Testes de WorldConfig.loyalty_drop_range().

Cada nobre remove um sorteio uniforme dentro da faixa que o mundo publica
(<mood><loss_min>20</loss_min><loss_max>35</loss_max></mood> no br143, os
mesmos numeros que /page/settings mostra como "Redução de lealdade por ataque
do nobre"). Um trem de 4 nobres remove portanto de 80 a 140, e nao os 100
garantidos que um valor fixo de 25 sugeria.

Rodar: python tests/test_loyalty_drop_range.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.world_config import WorldConfig

BR143 = {"mood": {"loss_min": 20, "loss_max": 35, "load": 1}}


def test_le_a_faixa_do_mundo():
    assert WorldConfig.loyalty_drop_range(BR143) == (20, 35)


def test_quatro_nobres_no_pior_caso_nao_zeram_lealdade():
    """
    O fato que motivou o item 4. Com 25 fixo a conta previa exatamente 100 e
    dava a conquista como certa; no pior caso real sobra 20 de lealdade.
    """
    lo, _ = WorldConfig.loyalty_drop_range(BR143)
    assert 100 - (4 * lo) == 20


def test_quatro_nobres_no_melhor_caso_zeram_com_folga():
    _, hi = WorldConfig.loyalty_drop_range(BR143)
    assert 100 - (4 * hi) <= 0


def test_soma_real_do_incidente_cabe_na_faixa():
    """
    As quatro quedas medidas nos relatorios de 2026-08-12: 22, 21, 25, 21.
    Somam 89 -- dentro do possivel (80..140) e abaixo de 100, que e como a
    Barbara #40314 sobreviveu ao trem com lealdade 11.
    """
    quedas = [22, 21, 25, 21]
    lo, hi = WorldConfig.loyalty_drop_range(BR143)
    assert all(lo <= q <= hi for q in quedas)
    assert sum(quedas) == 89
    assert 100 - sum(quedas) == 11


def test_mundo_sem_mood_degrada_para_o_fallback():
    """Sem dado, reproduz exatamente o comportamento antigo (valor fixo)."""
    assert WorldConfig.loyalty_drop_range({}, fallback=25) == (25, 25)
    assert WorldConfig.loyalty_drop_range(None, fallback=25) == (25, 25)
    assert WorldConfig.loyalty_drop_range({"mood": None}, fallback=30) == (30, 30)


def test_faixa_incoerente_degrada_para_o_fallback():
    """min > max, ou zeros: nao confiar, cair no fallback."""
    assert WorldConfig.loyalty_drop_range({"mood": {"loss_min": 40, "loss_max": 10}}) == (25, 25)
    assert WorldConfig.loyalty_drop_range({"mood": {"loss_min": 0, "loss_max": 0}}) == (25, 25)


def test_parse_mood_extrai_a_faixa_do_xml_real():
    """Recorte verbatim do interface.php?func=get_config do br143."""
    xml = "<config><mood><loss_max>35</loss_max><loss_min>20</loss_min>" \
          "<load>1</load></mood></config>"
    mood = WorldConfig._parse_mood(xml)
    assert (mood["loss_min"], mood["loss_max"]) == (20, 35)
    assert WorldConfig.loyalty_drop_range({"mood": mood}) == (20, 35)


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
