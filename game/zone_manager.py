"""
Feature 11 — Organização de aldeias em zonas geográficas

Agrupa aldeias gerenciadas em zonas por proximidade usando clustering por raio.
O raio padrão é 10 tiles e pode ser ajustado em config.json -> zones.radius.

Resultado persistido em cache/zones.json — disponível para todos os módulos.
"""
import logging
from core.filemanager import FileManager

logger = logging.getLogger("ZoneManager")


class ZoneManager:
    """
    Clusters managed villages into geographic zones based on a configurable radius.

    Algorithm: greedy expansion — for each unassigned village (sorted by ID),
    open a new zone and pull in any other unassigned village within `radius` tiles.
    Simple, deterministic, zero dependencies.

    Rebuilt every cycle from cache/managed/*.json by twb.py.
    Result saved to cache/zones.json.
    """

    def __init__(self, radius=10):
        self.radius = radius
        self.zones = {}         # zone_name -> [village_id, ...]
        self.village_zone = {}  # village_id -> zone_name

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _distance(x1, y1, x2, y2):
        return ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5

    # ------------------------------------------------------------------
    # Core build
    # ------------------------------------------------------------------

    def build(self, managed_villages):
        """
        Cluster villages into zones.

        Parameters
        ----------
        managed_villages : dict
            {village_id: {x, y, ...}}  — typically loaded from cache/managed/*.json

        Returns
        -------
        self (fluent)
        """
        self.zones = {}
        self.village_zone = {}

        if not managed_villages:
            return self

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

        logger.info(
            "ZoneManager: %d village(s) → %d zone(s) (radius=%.1f): %s",
            len(self.village_zone),
            len(self.zones),
            self.radius,
            {k: v for k, v in self.zones.items()},
        )
        return self

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self):
        """Persist zone assignments to cache/zones.json."""
        payload = {
            "radius": self.radius,
            "zones": self.zones,
            "village_zone": self.village_zone,
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

        manager.build(managed)
        manager.save()
        return manager
