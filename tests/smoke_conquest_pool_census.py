"""
SMOKE SO-LEITURA: censo do pool de candidatos do `find_target()`.

Fora do glob `test_*.py` de proposito (mesma convencao de
`smoke_conquest_reach.py`): vai a REDE com a sessao do bot.

    python tests/smoke_conquest_pool_census.py

POR QUE ELE EXISTE, E POR QUE NAO CONTA PELO `cache/villages`
-------------------------------------------------------------
Vigesimo quarto padrao do CLAUDE.md: em 2026-09-19 o diagnostico do
`P-CONQ-RAIO` mediu o efeito do raio sobre o snapshot compartilhado, que na
epoca NAO era a fonte que o `find_target()` lia -- a medicao estava certa e
descrevia um programa diferente do que rodava. Entao este censo nao recalcula
os filtros: ele roda o `find_target()` DE VERDADE e intercepta a lista de
candidatos que o laco real produziu, em `_prefer_area_of_interest()`, que e o
ultimo ponto onde ela existe inteira.

Nao envia nada e nao escreve: `Map.build_cache_entry` vira uma versao em
memoria, entao nem o snapshot compartilhado e tocado.
"""
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.WARNING, format="%(name)s: %(message)s")

from core.filemanager import FileManager
from core.request import WebWrapper
from game.attack import ConquestManager
from game.map import Map
from game.world_villages import WorldVillages

config = FileManager.load_json_file("config.json")
session = FileManager.load_json_file("cache/session.json")
if not config or not session:
    print("sem config.json ou cache/session.json -- nada a fazer")
    raise SystemExit(1)

wrapper = WebWrapper(config["server"]["endpoint"], server=config["server"]["server"],
                     endpoint=config["server"]["endpoint"])
wrapper.headers["user-agent"] = config["bot"]["user_agent"]
wrapper.web.cookies.update(session["cookies"])
wrapper.priority_mode = True


def _no_write(self, location, entry):
    """Mesma leitura do build_cache_entry, sem tocar em cache/villages."""
    try:
        points = int(entry[3].replace(".", ""))
    except ValueError:
        return
    self.map_pos[entry[0]] = location
    self.villages[entry[0]] = {"id": entry[0], "name": entry[2], "location": location,
                               "points": points, "owner": entry[4]}


Map.build_cache_entry = _no_write

ANCHOR = "41123"          # BBM 001, 577|306
managed = {fn[:-5]: FileManager.load_json_file("cache/managed/" + fn)
           for fn in os.listdir("cache/managed")}
coord = {v: (d["x"], d["y"]) for v, d in managed.items() if d and d.get("x")}

area = Map(wrapper=wrapper, village_id=ANCHOR)
area.get_map()
print("scan vivo da BBM 001: %d aldeias, my_location=%s"
      % (len(area.villages), area.my_location))

# Feature 36: a terceira fonte. `TWB_NO_WORLD=1` roda o censo sem ela, que e
# como se mede o "antes" depois da feature existir.
world = None if os.environ.get("TWB_NO_WORLD") else WorldVillages(config=config)
if world:
    t0 = time.time()
    print("village.txt: %d aldeias do mundo (%.2f s)"
          % (len(world.rows()), time.time() - t0))

man = ConquestManager(wrapper=wrapper, village_id=ANCHOR, troopmanager=None,
                      map_obj=area, config=config, world_villages=world)

# Intercepta a lista real do laco de find_target(). Nao recalcula filtro
# nenhum -- so guarda o que o codigo produziu.
capturado = {}
_original = ConquestManager._prefer_area_of_interest
_original_pool = ConquestManager._candidate_pool


def _spy(self, candidates, cfg):
    dentro = _original(self, candidates, cfg)
    capturado["todos"] = list(candidates)
    capturado["na_area"] = list(dentro)
    return dentro


def _spy_pool(self, reach_from=None, max_radius=None):
    # Chamar `_candidate_pool` por fora daqui mediria OUTRA coisa: sem o
    # `max_radius` que o find_target passa, o recorte do mundo nem acontece e
    # o pool volta com as 851 de antes. Vigesimo quarto padrao do CLAUDE.md --
    # medir a partir da mesma chamada que o codigo faz.
    t0 = time.time()
    pool = _original_pool(self, reach_from, max_radius=max_radius)
    capturado["pool"] = len(pool)
    capturado["pool_s"] = time.time() - t0
    capturado["raio"] = max_radius
    return pool


ConquestManager._prefer_area_of_interest = _spy
ConquestManager._candidate_pool = _spy_pool

cfg = config["conquest"]
cenarios = [
    ("so a ancora (caminho historico)", None),
    ("origens com nobre hoje (BBM 001 + BBM 011)", [coord["41123"], coord["74690"]]),
    ("as %d gerenciadas" % len(coord), list(coord.values())),
]
for label, reach in cenarios:
    capturado.clear()
    t0 = time.time()
    alvo = man.find_target(cfg, reach_from=reach)
    t_find = time.time() - t0
    meta = man._get_village_meta(alvo) if alvo else {}
    print("\n== %s  (raio efetivo %s)" % (label, capturado.get("raio")))
    print("   pool ................ %6d aldeias   (%.3f s)"
          % (capturado.get("pool", 0), capturado.get("pool_s", 0)))
    print("   candidatos elegiveis  %6d" % len(capturado.get("todos", [])))
    print("   ... na area de interesse %3d" % len(capturado.get("na_area", [])))
    print("   find_target() inteiro  %.3f s" % t_find)
    print("   alvo: %s %s %s pts" % (alvo, meta.get("location"), meta.get("points")))
