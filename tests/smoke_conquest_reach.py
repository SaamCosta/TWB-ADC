"""
SMOKE SO-LEITURA do caminho real de selecao de alvo barbaro.

Fora do glob `test_*.py` de proposito (mesma convencao de
`tests/smoke_bot_manager.py`): isto vai a REDE com a sessao do bot. Rodar na
mao ao mexer em `find_target` / `_candidate_pool`:

    python tests/smoke_conquest_reach.py

Roda o `ConquestManager.find_target()` de verdade -- com o `Map` vivo da BBM
001 buscado pelo proprio WebWrapper do bot, o `config.json` real, o
`cache/villages` real e o `cache/conquest` real -- variando so o `reach_from`.

Nao envia nada e nao escreve: `Map.build_cache_entry` e trocado por uma versao
em memoria, entao nem o snapshot compartilhado e tocado.

Por que existe (setimo padrao do CLAUDE.md): a suite cobre a logica com dubles,
e dubles nao reproduzem a forma da resposta do servidor. Em 2026-08-16 um
parser com fixture verbatim e testes verdes teria falhado no primeiro ciclo
real porque o wrapper manda um cabecalho a mais que a sondagem manual.
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

from core.filemanager import FileManager
from core.request import WebWrapper
from game.attack import ConquestManager
from game.map import Map

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
print("\nscan vivo da BBM 001: %d aldeias, my_location=%s"
      % (len(area.villages), area.my_location))

man = ConquestManager(wrapper=wrapper, village_id=ANCHOR, troopmanager=None,
                      map_obj=area, config=config)

cfg = config["conquest"]
cenarios = [
    ("so a ancora (caminho historico)", None),
    ("origens com nobre hoje (BBM 001 + BBM 011)", [coord["41123"], coord["74690"]]),
    ("as %d gerenciadas" % len(coord), list(coord.values())),
]
for label, reach in cenarios:
    pool = man._candidate_pool(reach)
    alvo = man.find_target(cfg, reach_from=reach)
    meta = man._get_village_meta(alvo) if alvo else {}
    print("\n== %s\n   pool: %d aldeias\n   alvo: %s %s %s pts"
          % (label, len(pool), alvo, meta.get("location"), meta.get("points")))
