"""Zonas centradas nas torres de vigia (docs/backend.md §8.45).

Ate 2026-10-03 a "semente" de cada zona era a aldeia de MENOR ID ainda sem
zona, e a zona era um disco de `zones.radius` em volta dela. Com isso a zona
dependia de qual aldeia era mais antiga, nao da geografia: a BBM 018 (588|309)
ficava a 2 campos da BBM 013 e mesmo assim abria zona propria, porque estava a
16,1 da semente da zona vizinha.

Agora cada aldeia entra na zona da torre (`profile: watchtower`) mais proxima,
e `covered` diz se ALGUMA torre a alcanca com o nivel que tem hoje. Cobre:

- a tabela de alcance contra o recorte verbatim de `screen=watchtower`
  (br143, BBM 002 nivel 16) -- inclusive o nivel 17, onde a formula da §4.4
  daria 9,94 e o jogo diz 10;
- torre mais proxima, desempate por id da torre;
- coberta por uma torre que NAO e a mais proxima (a vizinha tem nivel 0);
- torre designada com nivel 0 e centro de zona, mas nao cobre nada, nem a si;
- sem torre designada: cai no agrupamento antigo, com covered=False;
- `tower_levels()` le so quem tem profile watchtower e o nivel de
  `buidling_levels` (com o erro de grafia que o cache grava);
- as 40 aldeias reais de 2026-10-03: 3 zonas (24/3/13) e 14 cobertas.

Roda sem pytest:
    python tests/test_zone_watchtower.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from game.zone_manager import WATCHTOWER_RANGE, ZoneManager, watchtower_range


checks = 0


def check(condition, message):
    global checks
    checks += 1
    if not condition:
        raise AssertionError(message)


# Recorte verbatim de game.php?village=38409&screen=watchtower (br143,
# 2026-10-03), capturado com WebWrapper.get_url. A linha "selected" e o nivel
# atual da aldeia (16).
WATCHTOWER_TABLE = '<tr >\n\n            <td>Nível 1</td>\n\n            <td>1.1 campos</td>\n\n        </tr>\n\n            <tr >\n\n            <td>Nível 2</td>\n\n            <td>1.3 campos</td>\n\n        </tr>\n\n            <tr >\n\n            <td>Nível 3</td>\n\n            <td>1.5 campos</td>\n\n        </tr>\n\n            <tr >\n\n            <td>Nível 4</td>\n\n            <td>1.7 campos</td>\n\n        </tr>\n\n            <tr >\n\n            <td>Nível 5</td>\n\n            <td>2 campos</td>\n\n        </tr>\n\n            <tr >\n\n            <td>Nível 6</td>\n\n            <td>2.3 campos</td>\n\n        </tr>\n\n            <tr >\n\n            <td>Nível 7</td>\n\n            <td>2.6 campos</td>\n\n        </tr>\n\n            <tr >\n\n            <td>Nível 8</td>\n\n            <td>3 campos</td>\n\n        </tr>\n\n            <tr >\n\n            <td>Nível 9</td>\n\n            <td>3.4 campos</td>\n\n        </tr>\n\n            <tr >\n\n            <td>Nível 10</td>\n\n            <td>3.9 campos</td>\n\n        </tr>\n\n            <tr >\n\n            <td>Nível 11</td>\n\n            <td>4.4 campos</td>\n\n        </tr>\n\n            <tr >\n\n            <td>Nível 12</td>\n\n            <td>5.1 campos</td>\n\n        </tr>\n\n            <tr >\n\n            <td>Nível 13</td>\n\n            <td>5.8 campos</td>\n\n        </tr>\n\n            <tr >\n\n            <td>Nível 14</td>\n\n            <td>6.7 campos</td>\n\n        </tr>\n\n            <tr >\n\n            <td>Nível 15</td>\n\n            <td>7.6 campos</td>\n\n        </tr>\n\n            <tr style="font-weight: bold" class="selected">\n\n            <td>Nível 16</td>\n\n            <td>8.7 campos</td>\n\n        </tr>\n\n            <tr >\n\n            <td>Nível 17</td>\n\n            <td>10 campos</td>\n\n        </tr>\n\n            <tr >\n\n            <td>Nível 18</td>\n\n            <td>11.5 campos</td>\n\n        </tr>\n\n            <tr >\n\n            <td>Nível 19</td>\n\n            <td>13.1 campos</td>\n\n        </tr>\n\n            <tr >\n\n            <td>Nível 20</td>\n\n            <td>15 campos</td>\n\n        </tr>\n\n    </table>'

rows = re.findall(r"<td>N\S+vel (\d+)</td>\s*<td>([\d.]+) campos</td>", WATCHTOWER_TABLE)
check(len(rows) == 20, "a tabela do jogo tem 20 niveis, o regex leu %d" % len(rows))
served = {int(lvl): float(rng) for lvl, rng in rows}
check(served == WATCHTOWER_RANGE, "WATCHTOWER_RANGE divergiu da tabela do jogo: %s" % {
    k: (WATCHTOWER_RANGE.get(k), v) for k, v in served.items() if WATCHTOWER_RANGE.get(k) != v})

# A borda que motivou usar a tabela em vez da formula.
formula_17 = 1.1 * 1.1475 ** 16
check(round(formula_17, 2) == 9.94, "formula no nivel 17 = %.2f" % formula_17)
check(watchtower_range(17) == 10.0, "o jogo diz 10 campos no nivel 17")
check(watchtower_range(0) == 0.0 and watchtower_range(None) == 0.0, "sem torre = 0")
check(watchtower_range("x") == 0.0, "nivel ilegivel = 0, nao excecao")
check(watchtower_range(25) == 15.0, "nivel acima de 20 satura no 20")


def vil(x, y, wt=0):
    return {"x": x, "y": y, "buidling_levels": {"watchtower": wt}}


# --- torre mais proxima e covered por outra torre ---------------------------
managed = {
    "100": vil(500, 500, 16),   # torre A, alcance 8,7
    "200": vil(510, 500, 0),    # torre B, designada mas nivel 0
    "301": vil(503, 500),       # 3 de A -> zona A, coberta por A
    "302": vil(508, 500),       # 2 de B, 8 de A -> zona B, coberta por A
    "303": vil(515, 500),       # 5 de B, 15 de A -> zona B, sem cobertura
    "304": vil(505, 500),       # 5 de A e 5 de B: empate -> menor id de torre (A)
}
zm = ZoneManager().build(managed, towers={"100": 16, "200": 0})
check(zm.mode == "watchtower", "com torre designada o modo e watchtower")
check(set(zm.zones) == {"zone_100", "zone_200"}, "uma zona por torre: %s" % list(zm.zones))
check(zm.get_zone("301") == "zone_100", "301 vai para a torre mais proxima")
check(zm.get_zone("302") == "zone_200", "302 vai para B, que e a mais proxima")
check(zm.villages["302"]["covered"] and zm.villages["302"]["covered_by"] == "100",
      "302 esta na zona de B mas e A (nivel 16) quem a enxerga")
check(not zm.villages["303"]["covered"], "303 esta fora do alcance de todas as torres")
check(zm.get_zone("304") == "zone_100", "empate desempata pelo id da torre")
check(zm.get_zone("200") == "zone_200", "a torre B e centro da propria zona")
check(zm.villages["200"]["covered_by"] is None,
      "B (510|500) tem nivel 0 e fica a 10 de A (alcance 8,7): ninguem a cobre")
check(zm.villages["100"]["covered"], "torre de nivel > 0 cobre a si mesma")
check(zm.towers["zone_100"]["range"] == 8.7 and zm.towers["zone_200"]["range"] == 0.0,
      "alcance gravado por torre")
check(sorted(zm.get_neighbors("303")) == ["200", "302"], "vizinhos = mesma zona da torre")

# Torre designada sem cache (sem coordenadas) e ignorada, nao derruba.
zm = ZoneManager().build(managed, towers={"100": 16, "999": 20})
check(set(zm.zones) == {"zone_100"}, "torre sem cache gerenciado nao vira zona")

# --- sem torre: agrupamento antigo -----------------------------------------
zm = ZoneManager(radius=10).build(managed, towers={})
check(zm.mode == "radius", "sem torre cai no modo raio")
check(zm.zones["zone_1"][0] == "100", "modo raio continua semeando pelo menor id")
check(not any(v["covered"] for v in zm.villages.values()),
      "sem torre nenhuma, nada e coberto")
check(set(zm.villages) == set(managed), "modo raio tambem grava todas as aldeias")

# --- tower_levels ------------------------------------------------------------
config = {"villages": {
    "100": {"profile": "watchtower"},
    "200": {"profile": "watchtower"},
    "301": {"profile": "offensive"},
    "888": {"profile": "watchtower"},   # sem cache gerenciado
}}
managed_tl = dict(managed)
managed_tl["200"] = {"x": 510, "y": 500, "buidling_levels": None}
check(ZoneManager.tower_levels(config, managed_tl) == {"100": 16, "200": 0},
      "so profile watchtower com cache; buidling_levels None = nivel 0")

# --- as 40 aldeias reais (cache/managed de 2026-10-03) -----------------------
REAL = {
    "32056": (574, 317), "34597": (576, 316), "35059": (579, 318), "36294": (569, 312),
    "37318": (577, 315), "38363": (586, 313), "38409": (578, 305), "38412": (553, 300),
    "38997": (580, 309), "39292": (579, 308), "39449": (565, 302), "39472": (588, 309),
    "39975": (583, 312), "40314": (571, 308), "40374": (588, 314), "40618": (569, 304),
    "41114": (584, 309), "41123": (577, 306), "41140": (585, 304), "41283": (576, 309),
    "42134": (571, 299), "44167": (557, 293), "44620": (586, 308), "44674": (587, 307),
    "44683": (579, 304), "46584": (571, 296), "46676": (569, 299), "49709": (572, 295),
    "50833": (575, 291), "51540": (582, 289), "52755": (572, 289), "52876": (568, 291),
    "54895": (583, 290), "55553": (572, 287), "55647": (583, 288), "57689": (575, 287),
    "58039": (569, 278), "61947": (583, 285), "74689": (578, 306), "74690": (582, 304),
}
real = {vid: {"x": x, "y": y} for vid, (x, y) in REAL.items()}
zm = ZoneManager().build(real, towers={"38409": 16, "38412": 10, "52755": 0})
sizes = {k: len(v) for k, v in zm.zones.items()}
check(sizes == {"zone_38409": 24, "zone_38412": 3, "zone_52755": 13},
      "3 zonas 24/3/13, veio %s" % sizes)
check(sum(1 for v in zm.villages.values() if v["covered"]) == 14,
      "14 das 40 enxergadas hoje (13 pela BBM 002 + a BBM 023)")
# BBM 018 e BBM 013: a 2 campos uma da outra, separadas pelo modo antigo.
check(zm.get_zone("39472") == zm.get_zone("44620"),
      "BBM 018 e BBM 013 agora na mesma zona")
check(max(v["distance"] for v in zm.villages.values()) <= 15.0,
      "toda aldeia real esta a ate 15 campos da sua torre (cobertura total no nivel 20)")

print("test_zone_watchtower: %d checks OK" % checks)
