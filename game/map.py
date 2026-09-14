"""
Map management, pls don't read this code.
"""
import logging
import math
import time

from core.extractors import Extractor
from core.filemanager import FileManager


# Lado do setor de mapa em campos. Vem do proprio jogo: `getSectorIdByTile`
# em merged/map.js faz `e - e % 20`, ou seja setores sao blocos de 20x20
# alinhados em multiplos de 20.
SECTOR_SIZE = 20


class Map:
    """
    Class to manage the world around you
    """
    wrapper = None
    village_id = None
    my_location = None
    last_fetch = 0
    fetch_delay = 8

    def __init__(self, wrapper=None, village_id=None, sector_radius=0):
        """
        Creates the map files
        """
        self.wrapper = wrapper
        self.village_id = village_id
        # Raio, em setores, da regiao extra buscada via map.php. 0 = so o
        # prefetch da tela de mapa (comportamento historico).
        self.sector_radius = int(sector_radius or 0)
        # Por instância, não por classe: cada Village cria seu próprio Map,
        # mas como atributos de classe todos escreviam no mesmo dict global,
        # acumulando o mapa de todas as regiões já visitadas por qualquer
        # aldeia. Ver P1-15 em docs/backend.md
        self.map_data = []
        self.villages = {}
        self.map_pos = {}

    def get_map(self):
        """
        Fetch the map every 24ish hours and update the cache entries
        """
        if self.last_fetch + (self.fetch_delay * 3600) > time.time():
            return
        self.last_fetch = time.time()
        res = self.wrapper.get_action(village_id=self.village_id, action="map")
        game_state = Extractor.game_state(res)
        self.map_data = Extractor.map_data(res)
        # `TWMap.sectorPrefech` traz so o que a tela de mapa desenha de cara --
        # medido em 2026-08-31: 2 setores, e nao centrados na aldeia. A BBM 007
        # (571|308) recebia 1 setor util e enxergava 36 aldeias enquanto a
        # BBM 003, a 8 campos de distancia, enxergava 220. Buscar a vizinhanca
        # explicitamente elimina esse sorteio. Os setores extras tem a mesma
        # estrutura do prefetch, entao entram na mesma lista e sao consumidos
        # pelo mesmo parser abaixo.
        extra = self.fetch_sectors(game_state)
        if extra:
            self.map_data = self.merge_sectors(self.map_data or [], extra)
        if self.map_data:
            for tile in self.map_data:
                data = tile["data"]
                x = int(data["x"])
                y = int(data["y"])
                vdata = data["villages"]
                # Fix broken parsing                 
                if type(vdata) is dict:
                    cdata = [{}] * 20
                    for k, v in vdata.items():
                        if type(v) is not dict:
                            cdata[int(k)] = {0: item[0:] for item in v}
                        else:
                            cdata[int(k)] = v
                    vdata = cdata
                for lon, val in enumerate(vdata):
                    if not val:
                        continue
                    # Force dict type to iterate properly
                    if type(val) != dict:
                        val = {i: val[i] for i in range(0, len(val))}
                    for lat, entry in val.items():
                        if not lat:
                            continue
                        coords = [x + int(lon), y + int(lat)]
                        if entry[0] == str(self.village_id):
                            self.my_location = coords

                        self.build_cache_entry(location=coords, entry=entry)
                if not self.my_location:
                    self.my_location = [
                        game_state["village"]["x"],
                        game_state["village"]["y"],
                    ]
        if not self.map_data or not self.villages:
            return self.get_map_old(game_state=game_state)
        return True

    def get_map_old(self, game_state):
        """
        Old method of parsing the map, might work, might not, who knows
        """
        if self.map_data:
            for tile in self.map_data:
                data = tile["data"]
                x = int(data["x"])
                y = int(data["y"])
                vdata = data["villages"]
                for lon, lon_val in enumerate(vdata):
                    try:
                        for lat in vdata[lon]:
                            coords = [x + int(lon), y + int(lat)]
                            entry = vdata[lon][lat]
                            if entry[0] == str(self.village_id):
                                self.my_location = coords

                            self.build_cache_entry(location=coords, entry=entry)
                    except:
                        raise
            if not self.my_location:
                self.my_location = [
                    game_state["village"]["x"],
                    game_state["village"]["y"],
                ]
        if not self.map_data or not self.villages:
            logging.warning(
                "Error reading map state for village %s, farming might not work properly",
                self.village_id
            )
            return False
        return True

    @staticmethod
    def sector_grid(center_x, center_y, radius):
        """
        Ids dos setores que cobrem o quadrado de `radius` setores em volta do
        ponto, no formato (x, y) alinhado em multiplos de SECTOR_SIZE.

        Coordenada negativa e descartada porque nao existe no mapa; o limite
        superior nao e filtrado de proposito -- o tamanho do mundo varia por
        servidor e pedir um setor inexistente devolve setor vazio, o que e
        inofensivo, enquanto chutar o limite errado esconderia mapa real.
        """
        base_x = center_x - center_x % SECTOR_SIZE
        base_y = center_y - center_y % SECTOR_SIZE
        out = []
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                sx = base_x + dx * SECTOR_SIZE
                sy = base_y + dy * SECTOR_SIZE
                if sx < 0 or sy < 0:
                    continue
                out.append((sx, sy))
        return out

    @staticmethod
    def merge_sectors(base, extra):
        """
        Junta setores extras aos do prefetch, sem repetir os que ja vieram.
        A chave e a coordenada do setor, nao a identidade do dict.
        """
        seen = set()
        merged = []
        for sector in list(base) + list(extra):
            if not isinstance(sector, dict):
                continue
            key = (sector.get("x"), sector.get("y"))
            if key in seen:
                continue
            seen.add(key)
            merged.append(sector)
        return merged

    def fetch_sectors(self, game_state):
        """
        Busca a vizinhanca da aldeia em `map.php?v=2`, o endpoint que o proprio
        jogo usa quando o jogador arrasta o mapa (`loadSectors` em
        merged/map.js). Devolve a lista de setores, ou [] em qualquer falha --
        nunca levanta, porque o farm precisa seguir com o prefetch se isto nao
        responder.

        Formato do pedido, lido do JS: um parametro por setor, nomeado
        `<x>_<y>`, cujo valor e 1 quando os tiles de terreno tambem sao
        necessarios e 0 quando so os dados de aldeia bastam. O bot nunca usa
        os tiles, entao manda 0 (medido: 83 KB contra 91 KB para 9 setores,
        com as mesmas 471 aldeias).
        """
        if self.sector_radius < 1:
            return []
        if not game_state or not isinstance(game_state, dict):
            return []
        try:
            center_x = int(game_state["village"]["x"])
            center_y = int(game_state["village"]["y"])
        except (KeyError, TypeError, ValueError):
            # game_state ausente ou em formato inesperado (sessao expirada,
            # bot protection): degrada para o prefetch em vez de derrubar.
            logging.debug(
                "Map: sem coordenada utilizavel no game_state da aldeia %s, "
                "mantendo apenas o prefetch", self.village_id
            )
            return []

        sectors = self.sector_grid(center_x, center_y, self.sector_radius)
        if not sectors:
            return []

        locale = game_state.get("locale") or ""
        query = "&".join(f"{sx}_{sy}=0" for sx, sy in sectors)
        url = f"map.php?v=2&locale={locale}&e={int(time.time() * 1000)}&{query}"

        # Cabecalhos de XHR, como o $.ajax do jogo manda. Partem dos headers do
        # proprio wrapper (setimo padrao do CLAUDE.md: sondar com o cliente que
        # o bot usa de fato) para nao perder cookies/CSRF/referer.
        headers = dict(self.wrapper.headers)
        headers["accept"] = "application/json, text/javascript, */*; q=0.01"
        headers["x-requested-with"] = "XMLHttpRequest"

        res = self.wrapper.get_url(url, headers=headers)
        if res is None:
            logging.warning(
                "Map: map.php nao respondeu para a aldeia %s, "
                "farm limitado ao prefetch neste ciclo", self.village_id
            )
            return []
        try:
            data = res.json()
        except ValueError:
            # 200 que nao e JSON: tela de login, bot protection ou markup novo.
            logging.warning(
                "Map: map.php devolveu resposta nao-JSON para a aldeia %s "
                "(%d bytes), farm limitado ao prefetch neste ciclo",
                self.village_id, len(res.text)
            )
            return []
        if not isinstance(data, list):
            logging.warning(
                "Map: map.php devolveu %s em vez de lista de setores para a "
                "aldeia %s", type(data).__name__, self.village_id
            )
            return []

        found = [s for s in data if isinstance(s, dict) and "data" in s]
        logging.debug(
            "Map: %d setores pedidos, %d recebidos para a aldeia %s",
            len(sectors), len(found), self.village_id
        )
        return found

    def build_cache_entry(self, location, entry):
        """
        Builds a cache entry based on their weird data structure
        """
        vid = entry[0]
        name = entry[2]
        try:
            points = int(entry[3].replace(".", ""))
        except ValueError:
            # Breaks farming logic on event villages
            return
        player = entry[4]
        bonus = entry[6]
        clan = entry[11]
        structure = {
            "id": vid,
            "name": name,
            "location": location,
            "bonus": bonus,
            "points": points,
            "safe": False,
            "scout": False,
            "tribe": clan,
            "owner": player,
            "buildings": {},
            "resources": {},
        }
        self.map_pos[vid] = location
        cached = self.in_cache(vid)
        if not cached:
            MapCache.set_cache(village_id=vid, entry=structure)
        if cached and cached != structure:
            MapCache.set_cache(village_id=vid, entry=structure)
        self.villages[vid] = structure

    def in_cache(self, vid):
        """
        Checks if a village is already in the village cache
        """
        entry = MapCache.get_cache(village_id=vid)
        return entry

    def get_dist(self, ext_loc):
        """
        Calculates distance from current village to coords
        """
        distance = math.sqrt(
            ((self.my_location[0] - ext_loc[0]) ** 2)
            + ((self.my_location[1] - ext_loc[1]) ** 2)
        )
        return distance


class MapCache:
    """
    Holds a cache of all found villages within a certain distance
    """
    @staticmethod
    def get_cache(village_id):
        """
        Get data from the cache
        """
        return FileManager.load_json_file(f"cache/villages/{village_id}.json")

    @staticmethod
    def set_cache(village_id, entry):
        """
        Creates or updates a cache entry
        """
        FileManager.save_json_file(entry, f"cache/villages/{village_id}.json")
