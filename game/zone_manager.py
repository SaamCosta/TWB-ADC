"""
Feature 11 — Organização de aldeias em zonas geográficas

Desde 2026-10-03 (docs/backend.md §8.45) as zonas são centradas nas aldeias de
torre de vigia (`"profile": "watchtower"` no config): cada aldeia gerenciada
entra na zona da torre mais próxima, e o campo `covered` diz se alguma torre
de fato a enxerga com o nível que tem hoje. Sem nenhuma torre designada, cai
no agrupamento antigo por raio (`zones.radius`).

Resultado persistido em cache/zones.json — disponível para todos os módulos.
"""
import logging
from core.filemanager import FileManager

logger = logging.getLogger("ZoneManager")


# Alcance da torre de vigia por nível, em campos. Copiado da tabela que o
# próprio jogo publica em `screen=watchtower` (br143, 2026-10-03, lida nas
# aldeias de nível 16 e 10 — as duas mostram a tabela inteira). A fórmula da
# §4.4 (1,1 × 1,1475^(n−1)) dá o mesmo arredondado, menos na borda: no nível 17
# ela dá 9,94 e o jogo diz 10, e é exatamente a borda que decide `covered`.
WATCHTOWER_RANGE = {
    1: 1.1, 2: 1.3, 3: 1.5, 4: 1.7, 5: 2.0,
    6: 2.3, 7: 2.6, 8: 3.0, 9: 3.4, 10: 3.9,
    11: 4.4, 12: 5.1, 13: 5.8, 14: 6.7, 15: 7.6,
    16: 8.7, 17: 10.0, 18: 11.5, 19: 13.1, 20: 15.0,
}


def watchtower_range(level):
    """Alcance em campos de uma torre no `level` dado; 0 sem torre."""
    try:
        level = int(level or 0)
    except (TypeError, ValueError):
        return 0.0
    if level <= 0:
        return 0.0
    return WATCHTOWER_RANGE.get(min(level, 20), 0.0)


class ZoneManager:
    """
    Clusters managed villages into geographic zones.

    Watchtower mode (any village designated as a tower): every village joins
    the zone of the nearest tower village — ties broken by tower id, so the
    result is deterministic. A designated tower whose building is still at
    level 0 is a zone centre all the same (it was chosen for its position);
    it just covers nothing yet, which `covered` reports.

    Radius mode (no tower designated): greedy expansion — for each unassigned
    village (sorted by ID), open a new zone and pull in any other unassigned
    village within `radius` tiles of it.

    Rebuilt every cycle from cache/managed/*.json by twb.py.
    Result saved to cache/zones.json.
    """

    def __init__(self, radius=10):
        self.radius = radius
        self.mode = "radius"
        self.zones = {}         # zone_name -> [village_id, ...]
        self.village_zone = {}  # village_id -> zone_name
        self.towers = {}        # zone_name -> {village_id, x, y, level, range}
        self.villages = {}      # village_id -> {tower, distance, covered, covered_by}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _distance(x1, y1, x2, y2):
        return ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5

    # ------------------------------------------------------------------
    # Core build
    # ------------------------------------------------------------------

    def build(self, managed_villages, towers=None):
        """
        Cluster villages into zones.

        Parameters
        ----------
        managed_villages : dict
            {village_id: {x, y, ...}}  — typically loaded from cache/managed/*.json
        towers : dict, optional
            {village_id: watchtower_level} of the villages designated as
            watchtower villages. Ids without coordinates in `managed_villages`
            are ignored. Empty/None selects radius mode.

        Returns
        -------
        self (fluent)
        """
        self.zones = {}
        self.village_zone = {}
        self.towers = {}
        self.villages = {}

        if not managed_villages:
            return self

        sites = {
            vid: level for vid, level in (towers or {}).items()
            if vid in managed_villages
        }
        if sites:
            self._build_watchtower(managed_villages, sites)
        else:
            self._build_radius(managed_villages)

        logger.info(
            "ZoneManager (%s): %d village(s) → %d zone(s), %d covered: %s",
            self.mode,
            len(self.village_zone),
            len(self.zones),
            sum(1 for v in self.villages.values() if v["covered"]),
            {k: v for k, v in self.zones.items()},
        )
        return self

    def _build_watchtower(self, managed_villages, sites):
        self.mode = "watchtower"
        for tvid in sorted(sites):
            zone_name = f"zone_{tvid}"
            self.zones[zone_name] = []
            self.towers[zone_name] = {
                "village_id": tvid,
                "x": managed_villages[tvid].get("x", 0),
                "y": managed_villages[tvid].get("y", 0),
                "level": int(sites[tvid] or 0),
                "range": watchtower_range(sites[tvid]),
            }

        for vid in sorted(managed_villages):
            vx = managed_villages[vid].get("x", 0)
            vy = managed_villages[vid].get("y", 0)
            ranked = sorted(
                (self._distance(vx, vy, t["x"], t["y"]), t["village_id"], zone_name)
                for zone_name, t in self.towers.items()
            )
            distance, tower_vid, zone_name = ranked[0]
            # Coberta por QUALQUER torre que alcance, não só pela mais próxima:
            # a vizinha pode ser uma torre de nível 0 e a de longe, uma de 16.
            covered_by = next(
                (tv for d, tv, zn in ranked
                 if self.towers[zn]["range"] > 0 and d <= self.towers[zn]["range"]),
                None,
            )
            self.zones[zone_name].append(vid)
            self.village_zone[vid] = zone_name
            self.villages[vid] = {
                "tower": tower_vid,
                "distance": round(distance, 2),
                "covered": covered_by is not None,
                "covered_by": covered_by,
            }

    def _build_radius(self, managed_villages):
        self.mode = "radius"
        # Sort for deterministic assignment (same villages → same zones every run)
        vids = sorted(managed_villages.keys())
        zone_counter = 1

        for vid in vids:
            if vid in self.village_zone:
                continue  # already assigned to a zone

            zone_name = f"zone_{zone_counter}"
            zone_counter += 1
            self.zones[zone_name] = [vid]
            self.village_zone[vid] = zone_name

            vx = managed_villages[vid].get("x", 0)
            vy = managed_villages[vid].get("y", 0)

            # Pull in any unassigned village within radius
            for other_vid in vids:
                if other_vid in self.village_zone:
                    continue
                ox = managed_villages[other_vid].get("x", 0)
                oy = managed_villages[other_vid].get("y", 0)
                if self._distance(vx, vy, ox, oy) <= self.radius:
                    self.zones[zone_name].append(other_vid)
                    self.village_zone[other_vid] = zone_name

        # Sem torre nenhuma, nada é enxergado: covered=False é o fato, não um
        # valor neutro.
        for vid in vids:
            self.villages[vid] = {
                "tower": None, "distance": None,
                "covered": False, "covered_by": None,
            }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self):
        """Persist zone assignments to cache/zones.json."""
        payload = {
            "mode": self.mode,
            "radius": self.radius,
            "zones": self.zones,
            "village_zone": self.village_zone,
            "towers": self.towers,
            "villages": self.villages,
        }
        FileManager.save_json_file(payload, "cache/zones.json")

    @staticmethod
    def load():
        """Load last saved zone assignments. Returns dict or None."""
        return FileManager.load_json_file("cache/zones.json")

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_zone(self, village_id):
        """Returns the zone name for a village, or None."""
        return self.village_zone.get(village_id)

    def get_zone_members(self, zone_name):
        """Returns list of village IDs in the given zone."""
        return self.zones.get(zone_name, [])

    def get_neighbors(self, village_id):
        """Returns all other village IDs in the same zone."""
        zone = self.get_zone(village_id)
        if not zone:
            return []
        return [v for v in self.zones.get(zone, []) if v != village_id]

    def zone_under_attack(self, village_id, managed_cache):
        """
        Returns True if any neighbor in the same zone is under attack.
        managed_cache: dict of {village_id: cache_data} already loaded by caller.
        Used by Feature 12 (regional evacuation).
        """
        for neighbor_id in self.get_neighbors(village_id):
            neighbor_data = managed_cache.get(neighbor_id, {})
            if neighbor_data.get("under_attack", False):
                return True
        return False

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @staticmethod
    def tower_levels(config, managed):
        """
        {village_id: watchtower_level} for every village with
        `"profile": "watchtower"` that has managed cache. Level comes from the
        cached building levels (`buidling_levels` — the misspelling is the key
        Village.set_cache_vars() writes); missing/unreadable = 0.
        """
        towers = {}
        for vid, vcfg in (config.get("villages") or {}).items():
            if not isinstance(vcfg, dict) or vcfg.get("profile") != "watchtower":
                continue
            if vid not in managed:
                continue
            levels = managed[vid].get("buidling_levels") or {}
            try:
                towers[vid] = int(levels.get("watchtower") or 0)
            except (TypeError, ValueError):
                towers[vid] = 0
        return towers

    @classmethod
    def build_from_cache(cls, config):
        """
        Convenience: read all cache/managed/*.json, build zones, save.
        Called once per cycle from twb.py after the village loop.

        Returns the populated ZoneManager instance.
        """
        enabled = config.get("zones", {}).get("enabled", True)
        radius = config.get("zones", {}).get("radius", 10)

        manager = cls(radius=radius)

        if not enabled:
            logger.debug("ZoneManager: disabled in config, skipping")
            return manager

        managed = {}
        for cache_file in FileManager.list_directory("cache/managed", ends_with=".json"):
            vid = cache_file.replace(".json", "")
            data = FileManager.load_json_file(f"cache/managed/{cache_file}")
            if data and data.get("x") and data.get("y"):
                managed[vid] = data

        if not managed:
            logger.debug("ZoneManager: no managed village cache available yet")
            return manager

        manager.build(managed, towers=cls.tower_levels(config, managed))
        manager.save()
        return manager
