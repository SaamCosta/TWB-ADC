"""Pontos da propria aldeia lidos do `game_data` (docs/backend.md §8.23).

Em 2026-09-22 todas as 31 aldeias estavam com `points: 0` no `cache/managed`:
a unica fonte era `OverviewPage.villages_data`, que so le o modo Producao da
visao geral, e esta conta abre no modo Combinado. O zero desligava em silencio
o piso de ataque falso -- a BBM 004 mandou 48 de populacao contra um minimo de
56 e o jogo recusou.

Cobre as duas metades:

- `Village.points_from_game_data()`: le o `int` do `game_data`, e leitura ruim
  preserva o valor anterior em vez de zerar (zerar reabriria o buraco);
- a cadeia inteira ate o envio: com os pontos certos, `min_attack_population`
  deixa de ser 0 e `AttackManager._legalize()` cresce o pacote de 48 para 56,
  que e o caso exato recusado em campo. E o teste inverso, com points=0,
  exige que o pacote NAO cresca -- e a assinatura do bug, para ele nao voltar
  calado.

Roda sem pytest:
    python tests/test_village_points.py
"""
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from core.world_config import WorldConfig
from game.attack import AttackManager
from game.village import Village


checks = 0


def check(condition, message):
    global checks
    checks += 1
    if not condition:
        raise AssertionError(message)


# --------------------------------------------------------------------------
# points_from_game_data
# --------------------------------------------------------------------------
# Formato de `game_data["village"]` como `Extractor.game_state()` devolve da
# visao geral do br143 em 2026-09-22 (BBM 001): `points` e int.
GAME_DATA = {"village": {"id": 41123, "name": "BBM 001", "points": 9898, "coord": "577|306"}}

check(Village.points_from_game_data(GAME_DATA) == 9898, "le o int do game_data")
check(
    Village.points_from_game_data({"village": {"points": "5612"}}) == 5612,
    "aceita string numerica",
)
for bad in (None, {}, {"village": None}, {"village": {}},
            {"village": {"points": None}}, {"village": {"points": "abc"}},
            {"village": {"points": 0}}, {"village": {"points": -3}}):
    check(
        Village.points_from_game_data(bad, current=7000) == 7000,
        "leitura ruim %r tem que preservar o valor anterior, nao zerar" % (bad,),
    )
check(Village.points_from_game_data(None) == 0, "sem valor anterior, continua 0")


# --------------------------------------------------------------------------
# A cadeia ate o envio: pontos -> piso -> pacote legal
# --------------------------------------------------------------------------
WORLD = {"features": {"fake_limit": 1}}  # br143: fake_limit 1 (%)
PACK = {"light": 12}  # o pacote recusado em campo: 12 x 4 = 48 de populacao


def legalize_with(points):
    am = AttackManager.__new__(AttackManager)
    am.logger = logging.getLogger("test_village_points")
    am.village_points = points
    am.min_attack_pop = WorldConfig.min_attack_population(WORLD, points)
    return am.min_attack_pop, am._legalize(PACK)


# O caso de campo: minimo de 56 = 5.600 a 5.699 pontos.
minimo, legal = legalize_with(5650)
check(minimo == 56, "5.650 pontos com fake_limit 1 da minimo 56, veio %s" % minimo)
check(legal == {"light": 14}, "o pacote de 48 tem que crescer para 56 (14 cavalarias), veio %s" % legal)

# A assinatura do bug: com points=0 o piso some e o pacote ilegal passa intacto.
minimo, legal = legalize_with(0)
check(minimo == 0, "sem pontos o piso e 0 -- e por isso que o bug era mudo")
check(legal == PACK, "sem pontos o pacote nao cresce (reproduz o envio recusado)")

# E o valor lido do game_data alimenta a cadeia sem conversao no meio.
minimo, legal = legalize_with(Village.points_from_game_data(GAME_DATA))
check(minimo == 98, "BBM 001 com 9.898 pontos: minimo 98, veio %s" % minimo)
check(sum(4 * q for q in legal.values()) >= 98, "pacote legalizado cobre o minimo da BBM 001")

print("test_village_points: %d checks OK" % checks)
