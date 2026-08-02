"""
Feature 18 support module — fetches and caches the public Tribal Wars world
configuration (interface.php?func=get_config), used to detect world-specific
mechanics (currently: night bonus) instead of assuming fixed/neutral values.

This endpoint is unauthenticated and public on every TW server, e.g.:
  https://br143.tribalwars.com.br/interface.php?func=get_config

It is cached to disk (cache/world/config_{server}.json) and refreshed at most
once per CACHE_TTL, since world settings are static for the lifetime of a
world (they're set at world creation and don't change).
"""
import logging
import re
import time

import requests

from core.filemanager import FileManager

logger = logging.getLogger("WorldConfig")

CACHE_TTL = 6 * 3600  # world settings never change mid-world; refresh is just a safety net


class WorldConfig:
    """
    Reads/caches world-level settings not exposed anywhere in the normal
    game.php HTML the bot already scrapes.
    """

    @staticmethod
    def _cache_path(server):
        return f"cache/world/config_{server}.json"

    @staticmethod
    def _fetch(endpoint):
        """
        Fetches the raw world config XML. `endpoint` is the configured
        game.php URL (config["server"]["endpoint"]) -- the interface.php
        endpoint lives at the same host, one level up.
        """
        base = endpoint.split("/game.php")[0].rstrip("/")
        url = f"{base}/interface.php?func=get_config"
        try:
            res = requests.get(url, timeout=(10, 20))
            if res.status_code != 200:
                logger.warning("Unexpected status %d fetching %s", res.status_code, url)
                return None
            return res.text
        except Exception as e:
            logger.warning("Failed to fetch %s: %s", url, e)
            return None

    @staticmethod
    def _parse_night(xml_text):
        """
        Extracts the <night>...</night> block. Returns None if the world
        config doesn't have night bonus configured at all (older/simpler
        worlds may omit the block entirely).
        """
        match = re.search(r"<night>(.*?)</night>", xml_text, re.S)
        if not match:
            return None
        block = match.group(1)

        def _tag(name, default=0):
            m = re.search(fr"<{name}>(.*?)</{name}>", block)
            return int(m.group(1)) if m else default

        return {
            "active": _tag("active"),
            "start_hour": _tag("start_hour"),
            "end_hour": _tag("end_hour"),
            "def_factor": _tag("def_factor", 2),
        }

    @staticmethod
    def _parse_mood(xml_text):
        """
        Extracts the <mood>...</mood> block (morale settings). loss_max is
        the only field currently used -- see Simulator moral estimate in
        game/pvp_conquest.py for how it's applied.
        """
        match = re.search(r"<mood>(.*?)</mood>", xml_text, re.S)
        if not match:
            return None
        block = match.group(1)

        def _tag(name, default=0):
            m = re.search(fr"<{name}>(.*?)</{name}>", block)
            return int(m.group(1)) if m else default

        return {
            "loss_max": _tag("loss_max", 30),
            "loss_min": _tag("loss_min", 0),
        }

    @classmethod
    def get(cls, server, endpoint, force_refresh=False):
        """
        Returns the cached (or freshly fetched) world config dict:
        {"night": {...} or None, "mood": {...} or None, "_fetched_at": ts}

        Falls back to a stale cache (or an "unknown" placeholder) if the
        live fetch fails, so a transient network hiccup never blocks the
        caller -- it just means the bot uses last-known (or neutral)
        world settings for that cycle.
        """
        cache_path = cls._cache_path(server)
        if not force_refresh:
            cached = FileManager.load_json_file(cache_path)
            if cached and (time.time() - cached.get("_fetched_at", 0)) < CACHE_TTL:
                return cached

        xml_text = cls._fetch(endpoint)
        if xml_text is None:
            cached = FileManager.load_json_file(cache_path)
            return cached or {"night": None, "mood": None, "_fetched_at": 0}

        result = {
            "night": cls._parse_night(xml_text),
            "mood": cls._parse_mood(xml_text),
            "_fetched_at": int(time.time()),
        }
        FileManager.create_directory(FileManager.get_path("cache/world"))
        FileManager.save_json_file(result, cache_path)
        return result

    @staticmethod
    def is_night_bonus_active(world_config, server_hour=None):
        """
        Returns True if the world has night bonus enabled AND the current
        hour falls inside the configured night window.

        server_hour: 0-23. If not given, defaults to the bot machine's local
        hour -- this assumes the bot runs in the same timezone as the game
        server, which holds for single-country TW domains (e.g. br143 and
        Brazil) but is a known approximation, not a guarantee. The bot does
        not currently extract true server time from the game HTML.
        """
        night = (world_config or {}).get("night")
        if not night or not night.get("active"):
            return False

        if server_hour is None:
            server_hour = time.localtime().tm_hour

        start, end = night["start_hour"], night["end_hour"]
        if start == end:
            return False
        if start < end:
            return start <= server_hour < end
        return server_hour >= start or server_hour < end  # wraps past midnight

    @staticmethod
    def estimate_moral(world_config, attacker_points, defender_points):
        """
        Best-effort moral estimate from village points, scaled by the
        world's own `mood.loss_max` setting (confirmed live from the public
        world config, not guessed).

        IMPORTANT — this is NOT an officially documented formula. Innogames
        support confirms no exact public formula exists; the wiki only
        describes the behavior qualitatively (100% when defender has >=
        points than attacker, decreasing toward a floor as the point gap
        grows, plus a separate join-date-based floor increase over time that
        this function does NOT model since the bot doesn't track opponent
        join dates). Treat this as a conservative approximation, not ground
        truth -- cross-check against the in-game simulator's morale
        calculator before trusting it for high-value PvP conquest decisions.

        Returns an int percentage in [floor, 100].
        """
        mood = (world_config or {}).get("mood") or {}
        loss_max = mood.get("loss_max", 30)
        floor = max(0, 100 - loss_max)

        if not attacker_points or attacker_points <= 0:
            return 100
        if not defender_points or defender_points <= 0:
            defender_points = 0

        ratio = min(1.0, defender_points / attacker_points)
        moral = floor + ratio * (100 - floor)
        return int(round(moral))
