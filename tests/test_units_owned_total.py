"""
Testes de Extractor.units_owned_total -- o total de tropas que o recrutamento
compara com o template.

Em 2026-09-23 o usuario notou que o bot recrutava para cobrir uma lacuna de
fazenda que nao existia. Causa: `TroopManager.update_totals` somava a tela
`place&mode=units` com `units_in_total`, cujo `re.sub` apaga toda linha que
abre com `village_anchor` -- a intencao era esconder o apoio RECEBIDO em
`units_home`, mas as linhas de `units_away` (tropa DESTA aldeia apoiando
outra) abrem igual, e sumiam junto. A fazenda conta essas tropas; o
recrutamento nao contava.

Fixture VERBATIM do br143, BBM 006 (41283), capturado em 2026-09-23 com
`cache/_probe_place_units.py` (so GET, cliente do bot): recorte contiguo de
`<table id="units_home"` ate o fim da tabela de coleta. Estado naquele
momento: em casa 5 espadachins e 150 exploradores; na coleta 1657 lanceiros,
1675 espadachins, 200 leves, 413 pesadas; apoiando a SFC 002 1000 lanceiros,
1000 espadachins e 300 pesadas.

Rodar: python tests/test_units_owned_total.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.extractors import Extractor

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "fixtures", "place_units_support_away_br143.html"),
          encoding="utf-8") as fh:
    REAL = fh.read()


def _sum(pairs):
    total = {}
    for unit, qty in pairs:
        total[unit] = total.get(unit, 0) + int(qty)
    return total


def test_support_away_is_counted():
    total = _sum(Extractor.units_owned_total(REAL))
    assert total["spear"] == 1657 + 1000, total
    assert total["sword"] == 5 + 1675 + 1000, total
    assert total["heavy"] == 413 + 300, total
    assert total["light"] == 200, total
    assert total["spy"] == 150, total


def test_old_parser_drops_support_away():
    # O parser antigo, sobre o mesmo markup, perde exatamente a linha de
    # apoio. Se um dia ele passar a contar, este teste avisa que a premissa
    # do units_owned_total mudou.
    old = _sum(Extractor.units_in_total(REAL))
    new = _sum(Extractor.units_owned_total(REAL))
    diff = {u: new.get(u, 0) - old.get(u, 0) for u in new if new.get(u, 0) != old.get(u, 0)}
    assert diff == {"spear": 1000, "sword": 1000, "heavy": 300}, diff


def test_without_away_table_matches_old_parser():
    i = REAL.find('<table id="units_away"')
    j = REAL.find('</table>', i) + len('</table>')
    no_away = REAL[:i] + REAL[j:]
    assert _sum(Extractor.units_owned_total(no_away)) == _sum(Extractor.units_in_total(no_away))


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
