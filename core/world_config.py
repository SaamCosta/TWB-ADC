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

# Values of the world's top-level <moral> flag (the morale *system* in use).
MORAL_OFF = 0
MORAL_POINTS = 1
MORAL_TIME = 2
MORAL_BOTH = 3

# Floor of the points-based morale formula: moral = 30 + 70 * (def / att).
MORAL_POINTS_FLOOR = 30


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

        br143 reports active=2, start_hour=23, end_hour=7, def_factor=2 plus a
        <duration>14</duration> that is not parsed -- 23->7 is 8 hours, so
        whatever `duration` counts it isn't the window length. `active` is only
        ever read as a boolean, so the 1-vs-2 distinction is also unmodeled.
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
    def _parse_moral(xml_text):
        """
        Extracts the top-level <moral> flag -- which morale *system* the world
        uses: 0 = none, 1 = points based, 2 = time based (defender account
        age), 3 = both. br143 is 1, read live from the endpoint.

        Returns None when the tag is absent, so the caller can tell "world
        says no morale" (0) apart from "we don't know" (None).
        """
        m = re.search(r"<moral>\s*(\d+)\s*</moral>", xml_text)
        return int(m.group(1)) if m else None

    @staticmethod
    def _parse_mood(xml_text):
        """
        Extracts the <mood>...</mood> block, recorded for reference only.

        ⚠️ Despite the name, this is *not* the morale configuration -- the
        morale system is the top-level <moral> flag (see `_parse_moral`).
        br143 reports <mood><loss_max>35</loss_max><loss_min>20</loss_min>
        <load>1</load></mood> and the meaning of those fields is unconfirmed;
        nothing reads them. `estimate_moral` used to build its floor out of
        `loss_max` (`100 - 35` = 65%) and that was simply the wrong setting.
        Don't wire this back into morale without confirming what it is.
        """
        match = re.search(r"<mood>(.*?)</mood>", xml_text, re.S)
        if not match:
            return None
        block = match.group(1)

        def _tag(name, default=0):
            m = re.search(fr"<{name}>(.*?)</{name}>", block)
            return int(m.group(1)) if m else default

        return {
            "loss_max": _tag("loss_max"),
            "loss_min": _tag("loss_min"),
            "load": _tag("load"),
        }

    @classmethod
    def get(cls, server, endpoint, force_refresh=False):
        """
        Returns the cached (or freshly fetched) world config dict:
        {"night": {...} or None, "moral": int or None,
         "mood": {...} or None, "_fetched_at": ts}

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
            return cached or {"night": None, "moral": None, "mood": None, "_fetched_at": 0}

        result = {
            "night": cls._parse_night(xml_text),
            "moral": cls._parse_moral(xml_text),
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
        Best-effort moral estimate for the points-based morale system:

            moral = 30 + 70 * min(1, defender_points / attacker_points)

        100% when the defender is at least as big as the attacker, decaying
        toward a 30% floor as the point gap grows. The 30/70 split is the
        long-standing community formula (TW wiki); Innogames publishes no
        exact one, so this is still an approximation -- cross-check against
        the in-game simulator before betting a noble train on it.

        Which system is active comes from the world's top-level <moral> flag,
        read live from interface.php?func=get_config (br143 = 1):

        - 0 (off): morale never applies -> 100.
        - 1 (points) / 3 (both): the formula above. On 3 the game also applies
          time-based morale and (per the wiki) the higher of the two wins, so
          the points value is a lower bound -- it errs toward under-estimating
          the attack, which is the safe direction here.
        - 2 (time only): driven by the defender's account age, which the bot
          never sees -> 100. Mid/late-game PvP targets are old accounts, where
          time morale sits at or near 100% anyway.
        - missing (failed fetch, or a cache written before <moral> was
          parsed) or unrecognized: assumed points-based. Conservative on
          purpose -- under-estimating morale skips a viable conquest, while
          over-estimating it throws a noble train away.

        ⚠️ Do NOT reintroduce the <mood> block here (see `_parse_mood`): the
        previous version built the floor from `mood.loss_max`, which on br143
        is 35 and yielded a 65% floor -- more than double the real one, in the
        dangerous direction (overestimated moral -> conquests that fail).

        Returns an int percentage in [30, 100].
        """
        moral_mode = (world_config or {}).get("moral")
        if moral_mode in (MORAL_OFF, MORAL_TIME):
            return 100
        if moral_mode is not None and moral_mode not in (MORAL_POINTS, MORAL_BOTH):
            logger.warning(
                "Unrecognized world <moral> value %r -- using the points-based "
                "estimate, which is the conservative option", moral_mode
            )

        if not attacker_points or attacker_points <= 0:
            return 100
        if not defender_points or defender_points <= 0:
            defender_points = 0

        ratio = min(1.0, defender_points / attacker_points)
        moral = MORAL_POINTS_FLOOR + ratio * (100 - MORAL_POINTS_FLOOR)
        return int(round(moral))
