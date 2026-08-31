"""
Detects certain building levels from TWStats
"""

import json
import logging
import sys
from collections import defaultdict

import requests
from pyquery import PyQuery as pq

from core.filemanager import FileManager


class TwStats:
    """
    Baixa de twstats.com a tabela `predio -> nivel -> populacao consumida`.

    ATENCAO ao consumir `self.output`: o tipo da chave de nivel depende da
    PROCEDENCIA do dado. `get_building_data()` monta o dict com chave `int`
    (`int(tds[0])`); depois de passar pelo JSON do cache
    (`cache/world/buildings_<mundo>.json`) a mesma chave volta como `str`.
    Ou seja, `output["main"][2]` funciona no primeiro ciclo apos um sync e
    levanta `KeyError` em todos os ciclos seguintes -- normalizar antes de
    indexar. Foi metade do que quebrava o `buildings_to_farm_pop()` removido
    em 2026-08-31 (ver o commit e o CLAUDE.md).

    A tabela cobre so os predios de `max_levels`, e `farm` NAO esta entre
    eles: nao da para derivar capacidade de fazenda daqui. Quem precisa de
    populacao usa o dado ao vivo `game_state["village"]["pop"]` / `pop_max`,
    que o bot ja le todo ciclo.
    """
    max_levels = {
        'main': 30,
        'barracks': 25,
        'stable': 20,
        'garage': 15,
        'smith': 20,
        'snob': 3,
        'market': 25,
        'wood': 30,
        'stone': 30,
        'iron': 30,
        'wall': 20
    }

    output = {}
    logger = logging.getLogger("TwStats")

    def get_building_data(self, world):
        """
        Detects building data from TWStats
        """
        output = defaultdict(dict)
        for upgrade_building in self.max_levels:
            geturl = f"http://twstats.com/{world}/index.php?page=buildings&detail={upgrade_building}"
            res = requests.get(geturl)
            table = pq(res.content).find("table.vis")

            for tr in table("tr")[1:]:
                tds = pq(tr).text().splitlines()
                building_level, village_population = int(tds[0]), int(tds[-1])
                output[upgrade_building][building_level] = village_population

        try:
            with open('cache/world/buildings_%s.json' % world, 'w') as f:
                f.write(json.dumps(output))
        except:
            with open(f"../cache/world/buildings_{world}.json", "w", encoding="utf-8") as f:
                f.write(json.dumps(output))
        self.output = output
        return output

    def run(self, world):
        """
        Runs the update function
        """
        if self.output == {}:
            template = TwsCache.get_cache(world=world)
            if not template:
                self.logger.info("Syncing building -> pop levels with twstats.com")
                return self.get_building_data(world=world)
            self.output = template
            self.logger.debug("Using existing building -> pop levels")
            return template


class TwsCache:
    """
    Cache data for TWStats
    """
    @staticmethod
    def get_cache(world):
        """
        Gets the current cache
        """
        cache_path = f"cache/world/buildings_{world}.json"
        alt_cache_path = f"../cache/world/buildings_{world}.json"

        if FileManager.path_exists(cache_path):
            return FileManager.load_json_file(cache_path)
        elif FileManager.path_exists(alt_cache_path):
            return FileManager.load_json_file(alt_cache_path)
        return None


if __name__ == '__main__':
    TwStats().run(world=sys.argv[1])
