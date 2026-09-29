"""
Identificação e orientação do /map do webmanager (docs/backend.md §8.38).

1. `Extractor.map_relations` lê paleta, diplomacia e amigos da tela
   `screen=map` -- fixture verbatim do br143 em 2026-09-29, com os ids dos`n   amigos trocados por 90000000N (o repositorio e publico)
   (tests/fixtures/map_relations_br143.txt).
2. `MapBuilder.classify` segue a precedência de `TWMap.getColorByPlayer`
   (merged/map.js do br143): amigo vem DEPOIS da relação da tribo.
3. `MapBuilder.build` indexa `grid[y][x]` (linha = y), com o intervalo
   inclusivo e a aldeia central no meio. A versão anterior era `grid[x][y]`
   e o /map saía transposto.
4. `Map.save_diplomacy` não sobrescreve a leitura boa com uma tela que não é
   o mapa.

Rodar: python tests/test_map_relations.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.extractors import Extractor  # noqa: E402
from game import map as game_map  # noqa: E402
from webmanager.utils import MapBuilder  # noqa: E402

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


with open(os.path.join(ROOT, "tests", "fixtures", "map_relations_br143.txt"),
          encoding="utf-8") as fh:
    FIXTURE = fh.read()

# -- 1. parser ---------------------------------------------------------------
rel = Extractor.map_relations(FIXTURE)
check(rel is not None, "fixture real nao casou")
rel = rel or {}
check(rel.get("colors", {}).get("partner") == [0, 160, 244],
      "cor de partner: %r" % rel.get("colors", {}).get("partner"))
check(rel.get("colors", {}).get("grey") == [150, 150, 150], "cor grey (barbara)")
check(rel.get("ally_relations") == {"2": "nap", "16": "partner", "19": "partner",
                                    "49": "enemy", "2349": "nap"},
      "relacoes: %r" % rel.get("ally_relations"))
check(rel.get("friends") == ["900000001", "900000002"], "amigos: %r" % rel.get("friends"))
check("111059" not in str(rel.get("ally_relations")),
      "TWMap.reservations (logo abaixo) vazou para as relacoes")

# Tela que nao e o mapa (sessao expirada, bot protection): None, nao vazio.
check(Extractor.map_relations("<html><body>login</body></html>") is None,
      "tela sem TWMap.colors devia ser None")
check(Extractor.map_relations(None) is None, "res None devia ser None")

# Tribo sem diplomacia e jogador sem amigos: vazio LEGITIMO, nao falha.
colors_only = FIXTURE.split("TWMap.allyRelations")[0]
empty = Extractor.map_relations(colors_only)
check(empty is not None and empty["ally_relations"] == {} and empty["friends"] == [],
      "so a paleta devia dar relacoes/amigos vazios, veio %r" % empty)

# -- 2. precedencia ----------------------------------------------------------
ME, MY_TRIBE = "5955651", "987"
REL = {"16": "partner", "2": "nap", "49": "enemy"}
FRIENDS = ["900000001"]


def cls(owner, tribe, vid="1", current=None):
    return MapBuilder.classify({"id": vid, "owner": owner, "tribe": tribe},
                               current, ME, MY_TRIBE, REL, FRIENDS)


check(cls(ME, MY_TRIBE, vid="7", current="7") == "this", "aldeia atual")
check(cls(ME, MY_TRIBE) == "player", "sua aldeia")
check(cls("0", None) == "barbarian", "barbara (tribe None no cache real)")
check(cls("123", MY_TRIBE) == "ally", "sua tribo")
check(cls("123", "16") == "partner", "aliado")
check(cls("123", "2") == "nap", "PNA")
check(cls("123", "49") == "enemy", "inimigo")
check(cls("123", "555") == "other", "tribo sem relacao")
check(cls("123", "0") == "other", "sem tribo")
# O caso que a ordem da legenda engana: amigo numa tribo aliada.
check(cls("900000001", "16") == "partner",
      "amigo em tribo aliada: o jogo pinta como Aliado (relacao antes de amigo)")
check(cls("900000001", "0") == "friend", "amigo sem tribo")
check(cls("900000001", "555") == "friend", "amigo em tribo sem relacao")

# -- 3. orientacao -----------------------------------------------------------
villages = {
    "c": {"id": "c", "location": [500, 400], "owner": ME, "tribe": MY_TRIBE},
    "e": {"id": "e", "location": [510, 400], "owner": "9", "tribe": "16"},   # leste
    "s": {"id": "s", "location": [500, 410], "owner": "0", "tribe": None},  # sul
}
out = MapBuilder.build(villages, current_village="c", size=15)
grid = out["grid"]
check(len(grid) == 31 and len(grid[0]) == 31,
      "raio 15 = 31x31 inclusivo, veio %dx%d" % (len(grid), len(grid[0])))
check(out["extra"]["origin"] == [485, 385], "origin: %r" % out["extra"]["origin"])
check((grid[15][15] or {}).get("id") == "c", "centro fora do meio")
check((grid[15][25] or {}).get("id") == "e",
      "aldeia a LESTE tem que estar na mesma LINHA (grid[y][x])")
check((grid[25][15] or {}).get("id") == "s",
      "aldeia ao SUL tem que estar na mesma COLUNA (grid[y][x])")
check((grid[15][15] or {}).get("relation") == "this", "classe do centro")
check((grid[15][25] or {}).get("relation") == "other",
      "sem diplomacy.json a tribo 16 nao tem relacao conhecida")
check("relation" not in villages["e"], "build nao pode mutar o dict do cache")
check(out["extra"]["diplomacy_loaded"] is False, "sem diplomacia carregada")

out = MapBuilder.build(villages, current_village="c", size=15,
                       diplomacy={"player_id": ME, "ally_id": MY_TRIBE,
                                  "ally_relations": {"16": "partner"}, "friends": [],
                                  "colors": {"partner": [1, 2, 3]}})
check(out["grid"][15][25]["relation"] == "partner", "com diplomacia, 16 = partner")
check(out["extra"]["colors"]["partner"] == [1, 2, 3], "paleta do arquivo vence o default")
check([i["key"] for i in out["extra"]["legend"]][:3] == ["this", "player", "friend"],
      "legenda na ordem do jogo")

# -- 4. gravacao -------------------------------------------------------------
saved = []
orig_save = game_map.FileManager.save_json_file
game_map.FileManager.save_json_file = staticmethod(lambda data, path, **k: saved.append((path, data)))
try:
    m = game_map.Map(wrapper=None, village_id="32056")
    gs = {"player": {"id": "5955651", "ally": "987"}}
    check(m.save_diplomacy("<html>login</html>", gs) is False, "tela errada devia recusar")
    check(saved == [], "tela errada NAO pode sobrescrever a leitura boa")
    check(m.save_diplomacy(FIXTURE, gs) is True, "fixture real devia gravar")
    path, data = saved[-1] if saved else (None, {})
    check(path == "cache/diplomacy.json", "caminho: %r" % path)
    check(data.get("player_id") == "5955651" and data.get("ally_id") == "987",
          "dono/tribo do game_data: %r" % data)
    check(m.save_diplomacy(FIXTURE, None) is True, "game_state None nao pode derrubar")
    check(saved[-1][1].get("player_id") is None and saved[-1][1].get("ally_id") == "0",
          "sem game_state: player_id None, ally 0")
finally:
    game_map.FileManager.save_json_file = orig_save

if failures:
    for f in failures:
        print("FAIL:", f)
    sys.exit(1)
print("OK test_map_relations")
