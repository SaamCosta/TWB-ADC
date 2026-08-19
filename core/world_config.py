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
# Mapped in 2026-08-12 by reading <moral> from 39 live worlds across 4 markets
# and matching each value against that world's public /page/settings wording:
#   0 -> "Inactive"                          (enc1, enc2, nlc1, nlc2, dec5)
#   1 -> "Baseado em pontos"                 (br143, br137, enp17-19, dep20-21)
#   2 -> "Points and time based"             (br132, br138-142, en153-156, nl114)
#   3 -> "Punkte und unbegrenzte Zeit"       (de250-257, dec4)
# There is NO "time only" value: every enabled mode includes points morale.
MORAL_OFF = 0
MORAL_POINTS = 1
MORAL_POINTS_TIME = 2
MORAL_POINTS_TIME_UNLIMITED = 3

# Floor of the points-based morale formula: moral = 30 + 70 * (def / att).
MORAL_POINTS_FLOOR = 30

# Values of <night><active>, mapped the same way against /page/settings:
#   0 -> "Inactive"                                        (en153, enc1, ens1)
#   1 -> "Ativo de 23:00 até 7:00" / "Aktiv von 23:00 bis 8:00"
#        -> one fixed window for the whole world (br142, de250, nl109)
#   2 -> "Ativo, os jogadores podem selecionar o período de 8 horas"
#        -> every player picks their OWN 8h window (br143, br139, en154, nlp17)
NIGHT_OFF = 0
NIGHT_FIXED = 1
NIGHT_PER_PLAYER = 2


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

        `active` is the NIGHT_* mode, and it matters: on NIGHT_PER_PLAYER
        worlds (br143) `start_hour`/`end_hour` are only the *default* window,
        not the one this particular defender picked. See
        `is_night_bonus_active`.

        <duration> is deliberately not parsed: it reads 14 on all 39 worlds
        sampled in 2026-08-12, including worlds with the night bonus switched
        off entirely, so it is a global constant carrying no per-world
        information. It is almost certainly the documented 14-day delay before
        a player's chosen window takes effect (announced with the dynamic
        night bonus), which is a per-player fact the world config can't tell
        us anyway.
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
        uses. See the MORAL_* constants for the value mapping (br143 = 1,
        points based, read live from the endpoint).

        Returns None when the tag is absent, so the caller can tell "world
        says no morale" (0) apart from "we don't know" (None).
        """
        m = re.search(r"<moral>\s*(\d+)\s*</moral>", xml_text)
        return int(m.group(1)) if m else None

    @staticmethod
    def _parse_features(xml_text):
        """
        Mecanicas ligadas/desligadas por mundo, que o bot vinha lendo de flags
        digitadas a mao em config.json["world"].

        Isto existe porque em 2026-08-17 o br143 (sem arqueiro, <archer>0</archer>)
        rodava com archers_enabled=true, e o bot tentava recrutar e pesquisar
        arqueiro em toda aldeia defensiva, todo ciclo. Nao foi erro de leitura:
        este mesmo modulo ja baixava o XML que traz a resposta e descartava a
        tag no parse, e entao o valor era perguntado a um humano que nunca
        atualizou o campo ao entrar no mundo. O default `true` vinha do
        config.example.json de um fork cujo autor jogava em mundo com arqueiro.

        Todas sao inteiros no XML e "ligado" e > 0:
          <game><archer>    0/1
          <game><knight>    0 = sem paladino; 1/2/3 = variantes (br143 = 3,
                            "Ativo, habilidades podem ser aprendidas")
          <game><church>    0/1
          <game><watchtower> 0/1
          <build><destroy>  0/1 -- demolicao, que e o que habilita ariete e
                            catapulta terem para que servir
          <game><tech>      sistema de pesquisa (br143 = 2, "simplificada")

        Chave ausente vira None, para o consumidor distinguir "o mundo diz que
        nao tem" (0) de "nao sabemos" (None) e so ai cair no config.json.
        """

        def _tag(name, block=None):
            source = xml_text
            if block:
                m = re.search(fr"<{block}>(.*?)</{block}>", xml_text, re.S)
                if not m:
                    return None
                source = m.group(1)
            m = re.search(fr"<{name}>\s*(\d+)\s*</{name}>", source)
            return int(m.group(1)) if m else None

        return {
            "archer": _tag("archer", block="game"),
            "knight": _tag("knight", block="game"),
            "church": _tag("church", block="game"),
            "watchtower": _tag("watchtower", block="game"),
            "destroy": _tag("destroy", block="build"),
            "tech": _tag("tech", block="game"),
        }

    @staticmethod
    def feature_enabled(world_config, name, fallback):
        """
        True/False para uma mecanica do mundo, com `fallback` (o valor do
        config.json) usado apenas quando o mundo nao publicou o dado -- rede
        fora no primeiro ciclo, ou tag que este mundo nao expoe.

        O mundo vence quando responde. Foi a inversao disso que deixou o bot
        recrutando arqueiro num mundo sem arqueiro: o campo manual estava
        errado e nada o confrontava com a fonte.
        """
        value = ((world_config or {}).get("features") or {}).get(name)
        if value is None:
            return bool(fallback)
        return value > 0

    @staticmethod
    def _parse_mood(xml_text):
        """
        Extracts the <mood>...</mood> block.

        ⚠️ Despite the name, this is *not* the morale configuration -- the
        morale system is the top-level <moral> flag (see `_parse_moral`).
        `estimate_moral` used to build its floor out of `loss_max`
        (`100 - 35` = 65%) and that was simply the wrong setting. Never wire
        this back into morale.

        What it IS was confirmed on 2026-08-13 against /page/settings, which
        spells the same numbers out in the player's language: br143 shows
        "Redução de lealdade por ataque do nobre: 20-35" and reports
        <mood><loss_min>20</loss_min><loss_max>35</loss_max></mood>. So
        loss_min/loss_max are the **loyalty drop range per noble hit** -- each
        noble removes a uniform random amount in [loss_min, loss_max].

        Live confirmation from six noble reports the same day: drops of 22,
        21, 25, 21, 25 and 33, all inside 20-35.

        Read by ConquestManager via `loyalty_drop_range()` below. The old note
        here said "nothing reads them"; that is no longer true.
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

        server/endpoint ausentes devolvem o mesmo placeholder em vez de
        estourar. `_fetch` faz `endpoint.split("/game.php")` e `_cache_path`
        interpola o server no nome do arquivo, entao um None ali virava
        AttributeError no *construtor* de quem chama (ConquestManager,
        PvpConquestManager) -- derrubando a aldeia inteira por causa de uma
        chave de config faltando, num caminho que existe justamente para
        degradar em silencio.
        """
        if not server or not endpoint:
            logger.warning(
                "WorldConfig: server/endpoint ausentes na config "
                "(server=%r, endpoint=%r) -- seguindo sem dados do mundo",
                server, endpoint
            )
            return {"night": None, "moral": None, "mood": None, "_fetched_at": 0}

        cache_path = cls._cache_path(server)
        if not force_refresh:
            cached = FileManager.load_json_file(cache_path)
            if (
                    cached
                    and (time.time() - cached.get("_fetched_at", 0)) < CACHE_TTL
                    # Cache gravado antes de "features" existir conta como
                    # velho. Sem isto o bot rodaria ate CACHE_TTL inteiro com as
                    # flags do mundo ausentes, caindo no config.json -- que e
                    # exatamente a fonte que esta feature existe para nao usar.
                    and "features" in cached
            ):
                return cached

        xml_text = cls._fetch(endpoint)
        if xml_text is None:
            cached = FileManager.load_json_file(cache_path)
            return cached or {
                "night": None, "moral": None, "mood": None,
                "features": None, "_fetched_at": 0,
            }

        result = {
            "night": cls._parse_night(xml_text),
            "moral": cls._parse_moral(xml_text),
            "mood": cls._parse_mood(xml_text),
            "features": cls._parse_features(xml_text),
            "_fetched_at": int(time.time()),
        }
        FileManager.create_directory(FileManager.get_path("cache/world"))
        FileManager.save_json_file(result, cache_path)
        return result

    @staticmethod
    def loyalty_drop_range(world_config, fallback=25):
        """
        Faixa (min, max) de queda de lealdade por nobre, do <mood> do mundo.

        Cada nobre remove um valor sorteado uniformemente nesse intervalo --
        no br143, 20 a 35. Um trem de 4 nobres portanto remove de 80 a 140, e
        NAO os 100 garantidos que um valor fixo de 25 sugere: em ~1 de cada 8
        trens a soma fica abaixo de 100 e a aldeia nao cai. Foi o que
        aconteceu em 2026-08-12 com a Barbara #40314 (as quatro quedas somaram
        89, deixando a lealdade em 11), e o bot, que assumia 25 fixo, deu a
        conquista como certa e seguiu adiante.

        `fallback` e usado para os dois extremos quando o mundo nao publicou o
        bloco (rede fora no primeiro ciclo, mundo sem a tag). Devolver
        (fallback, fallback) reproduz exatamente o comportamento antigo, que e
        a degradacao certa: sem dado, nao inventamos incerteza.
        """
        mood = (world_config or {}).get("mood") or {}
        lo = mood.get("loss_min")
        hi = mood.get("loss_max")
        if not lo or not hi or lo > hi:
            return (fallback, fallback)
        return (lo, hi)

    @staticmethod
    def is_night_bonus_active(world_config, server_hour=None):
        """
        Tri-state:

        - False -- the world has no night bonus, or the current hour is
          outside its fixed window.
        - True  -- inside the world's fixed window (NIGHT_FIXED).
        - None  -- **unknowable**: the world gives every player their own 8h
          window (NIGHT_PER_PLAYER, e.g. br143), so whether the bonus applies
          depends on the *defender's* choice, which is not in the world config
          at all. Callers must decide what to assume; see the note below.

        ⚠️ The None case is why this isn't a plain bool. Before 2026-08-12 the
        function answered True/False on per-player worlds by comparing the
        clock against `start_hour`/`end_hour`, which on those worlds is merely
        the default window -- a confident answer to a question the world
        config cannot answer. The defender's real window IS visible in game,
        on the map village hover, but only for premium accounts and only via
        scraping the bot doesn't do yet.

        server_hour: 0-23. If not given, defaults to the bot machine's local
        hour -- this assumes the bot runs in the same timezone as the game
        server, which holds for single-country TW domains (e.g. br143 and
        Brazil) but is a known approximation, not a guarantee. The bot does
        not currently extract true server time from the game HTML. Note this
        is also "is it night *now*", not "will it be night when the attack
        lands" -- for slow noble trains those differ by hours.
        """
        night = (world_config or {}).get("night")
        if not night or not night.get("active"):
            return False

        if night.get("active") == NIGHT_PER_PLAYER:
            return None

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

        Which system is active comes from the world's top-level <moral> flag
        (see the MORAL_* constants for how each value was mapped):

        - 0 (off): morale never applies -> 100.
        - 1 (points), 2 (points + time), 3 (points + unlimited time): the
          formula above. **Every enabled mode includes the points component**,
          so the formula always applies. On 2 and 3 the game additionally
          raises morale with the defender's account age, and (per the wiki)
          the higher of the two wins -- the bot doesn't track opponent join
          dates, so the points value is a lower bound. That errs toward
          under-estimating the attack, the safe direction here.
        - missing (failed fetch, or a cache written before <moral> was
          parsed) or unrecognized: same formula. Conservative on purpose --
          under-estimating morale skips a viable conquest, while
          over-estimating it throws a noble train away.

        ⚠️ Do NOT reintroduce the <mood> block here (see `_parse_mood`): the
        previous version built the floor from `mood.loss_max`, which on br143
        is 35 and yielded a 65% floor -- more than double the real one, in the
        dangerous direction (overestimated moral -> conquests that fail).

        Returns an int percentage in [30, 100].
        """
        moral_mode = (world_config or {}).get("moral")
        if moral_mode == MORAL_OFF:
            return 100
        known = (MORAL_POINTS, MORAL_POINTS_TIME, MORAL_POINTS_TIME_UNLIMITED)
        if moral_mode is not None and moral_mode not in known:
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
