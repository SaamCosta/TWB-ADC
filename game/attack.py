"""
Attack manager
Sounds dangerous but it just sends farms
"""

from core.extractors import Extractor
import logging
import math
import time
from datetime import datetime
from datetime import timedelta

from core.filemanager import FileManager


class AttackManager:
    """
    Attackmanager class
    """
    map = None
    village_id = None
    troopmanager = None
    wrapper = None
    targets = {}
    logger = logging.getLogger("Attacks")
    max_farms = 15
    template = {}
    extra_farm = []
    repman = None
    target_high_points = False
    farm_radius = 50
    farm_minpoints = 0
    farm_maxpoints = 1000
    ignored = []

    # Configures the amount of spies used to detect if villages are safe to farm
    scout_farm_amount = 5

    forced_peace_time = None
    # True enquanto a janela de paz forcada esta ativa agora (distinto de
    # forced_peace_time, que e o teto de *chegada* da proxima janela).
    in_forced_peace = False

    # blocks villages which cannot be attacked at the moment (too low points, beginners protection etc..)
    _unknown_ignored = []

    # Don't mess with these they are in the config file
    farm_high_prio_wait = 1200
    farm_default_wait = 3600
    farm_low_prio_wait = 7200

    def __init__(self, wrapper=None, village_id=None, troopmanager=None, map=None):
        """
        Create the attack manager
        """
        self.wrapper = wrapper
        self.village_id = village_id
        self.troopmanager = troopmanager
        self.map = map
        # P3: mutaveis por instancia (ver CLAUDE.md). `ignored` e
        # `_unknown_ignored` sao mutados in-place (.append/.remove) e nunca
        # reatribuidos, entao como atributos de classe eram compartilhados
        # por todas as aldeias -- um alvo fora do farm_radius de uma aldeia
        # ficava ignorado para todas, mesmo estando perto de outra.
        # `targets` e `extra_farm` sao reatribuidos, mas declarar aqui evita
        # a mesma armadilha se algum caminho falhar antes da atribuicao.
        self.ignored = []
        self._unknown_ignored = []
        self.targets = {}
        self.extra_farm = []

    def enough_in_village(self, units):
        """
        Checks if there are enough troops in a village,
        respecting the conquest_reserve set by ConquestManager /
        PvpConquestManager.
        """
        farmable = self._get_farmable_troops()
        for unit in units:
            available = int(farmable.get(unit, 0))
            if units[unit] > available:
                return f"{unit} ({available}/{units[unit]})"
        return False

    def _get_farmable_troops(self):
        """
        Feature 8 / Feature 13: Returns available troops minus every active
        conquest_reserve (summed across owners -- barbarian noble train
        escort, PvP conquest clear/escort, etc. -- see
        TroopManager.total_conquest_reserve()). Ensures troops earmarked for
        any pending conquest are never consumed by farm attacks while
        waiting for that attack to actually fire.
        """
        reserve = self.troopmanager.total_conquest_reserve() if hasattr(
            self.troopmanager, "total_conquest_reserve"
        ) else {}
        farmable = {}
        for unit, qty in self.troopmanager.troops.items():
            reserved = reserve.get(unit, 0)
            farmable[unit] = str(max(0, int(qty) - reserved))
        return farmable

    def run(self):
        """
        Run the farming logic
        """
        if not self.troopmanager.can_attack or self.troopmanager.troops == {}:
            # Disable farming is disabled in config or no troops available
            return False
        self.get_targets()
        ignored = []
        # Limits the amount of villages that are farmed from the current village
        for target in self.targets[0: self.max_farms]:
            if type(self.template) == list:
                f = False
                for template in self.template:
                    if template in ignored:
                        continue
                    out_res = self.send_farm(target, template)
                    if out_res == 1:
                        f = True
                        break
                    elif out_res == -1:
                        ignored.append(template)
                if not f:
                    continue
            else:
                out_res = self.send_farm(target, self.template)
                if out_res == -1:
                    break

    def send_farm(self, target, template):
        """
        Send a farming run
        """
        target, *_ = target  # unpack village dict; ignore distance and sort_key
        missing = self.enough_in_village(template)
        if not missing:
            cached = self.can_attack(vid=target["id"], clear=False)
            if cached:
                attack_result = self.attack(target["id"], troops=template)
                if attack_result == "forced_peace":
                    return 0
                self.logger.info(
                    "Attacking %s -> %s (%s)" ,self.village_id, target["id"], str(template)
                )
                self.wrapper.reporter.report(
                    self.village_id,
                    "TWB_FARM",
                    "Attacking %s -> %s (%s)"
                    % (self.village_id, target["id"], str(template)),
                )
                if attack_result:
                    for u in template:
                        self.troopmanager.troops[u] = str(
                            int(self.troopmanager.troops[u]) - template[u]
                        )
                    self.attacked(
                        target["id"],
                        scout=True,
                        safe=True,
                        high_profile=cached["high_profile"]
                        if type(cached) == dict
                        else False,
                        low_profile=cached["low_profile"]
                        if type(cached) == dict and "low_profile" in cached
                        else False,
                    )
                    return 1
                else:
                    self.logger.debug(
                        "Ignoring target %s because unable to attack (server refused, not blocking future attempts)", target["id"]
                    )
        else:
            self.logger.debug(
                "Not sending additional farm because not enough units: %s", missing
            )
            return -1
        return 0

    def get_targets(self):
        """
        Gets all possible farming targets based on distance and loot efficiency.
        Sorts by: distance / farm_score (lower = more efficient).
        Falls back to distance-only for farms with no report history.
        """
        output = []
        # Feature 5: load all cached farm scores for efficiency sorting
        farm_scores = AttackCache.cache_grab()
        # Unknown farms get high priority so they are visited first to build history.
        # Once farm_manager runs and scores them, they settle into their real position.
        default_score = 9999

        my_village = (
            self.map.villages[self.village_id]
            if self.village_id in self.map.villages
            else None
        )
        for vid in self.map.villages:
            village = self.map.villages[vid]
            if village["owner"] != "0" and vid not in self.extra_farm:
                if vid not in self.ignored:
                    self.logger.debug(
                        "Ignoring village %s because player owned, add to additional_farms to auto attack", vid
                    )
                    self.ignored.append(vid)
                continue
            if my_village and "points" in my_village and "points" in village:
                if village["points"] >= self.farm_maxpoints:
                    if vid not in self.ignored:
                        self.logger.debug(
                            "Ignoring village %s because points %d exceeds limit %d",
                            vid, village["points"], self.farm_maxpoints
                        )
                        self.ignored.append(vid)
                    continue
                if village["points"] <= self.farm_minpoints:
                    if vid not in self.ignored:
                        self.logger.debug(
                            "Ignoring village %s because points %d below limit %d",
                            vid, village["points"], self.farm_minpoints
                        )
                        self.ignored.append(vid)
                    continue
                if (
                        village["points"] >= my_village["points"]
                        and not self.target_high_points
                ):
                    if vid not in self.ignored:
                        self.logger.debug(
                            "Ignoring village %s because of higher points %d -> %d",
                            vid, my_village["points"], village["points"]
                        )
                        self.ignored.append(vid)
                    continue
                if vid in self._unknown_ignored:
                    continue
            if village["owner"] != "0":
                get_h = time.localtime().tm_hour
                if get_h in range(0, 8) or get_h == 23:
                    self.logger.debug(
                        "Village %s will be ignored because it is player owned and attack between 23h-8h", vid
                    )
                    continue
            distance = self.map.get_dist(village["location"])
            if distance > self.farm_radius:
                if vid not in self.ignored:
                    self.logger.debug(
                        "Village %s will be ignored because it is too far away: distance is %f, max is %d",
                        vid, distance, self.farm_radius
                    )
                    self.ignored.append(vid)
                continue
            if vid in self.ignored:
                self.logger.debug("Removed %s from farm ignore list", vid)
                self.ignored.remove(vid)

            # `or default_score` trataria um score 0 (farm que nao rende nada)
            # como "sem historico" e o colocaria no topo da fila. Enquanto o
            # farm_score nunca era gravado (P1-8) isso era inofensivo; agora
            # que o farm_manager grava de verdade, precisa distinguir
            # "ainda nao pontuado" (None) de "pontuado como ruim" (0).
            score = farm_scores.get(vid, {}).get("farm_score")
            if score is None:
                score = default_score
            output.append([village, distance, distance / max(score, 1)])
        self.logger.info(
            "Farm targets: %d Ignored targets: %d", len(output), len(self.ignored)
        )
        self.targets = sorted(output, key=lambda x: x[2])

    def attacked(self, vid, scout=False, high_profile=False, safe=True, low_profile=False):
        """
        The farm was sent and this is a callback on what happened.
        Merges with existing cache to preserve farm_score and attack_count.
        """
        existing = AttackCache.get_cache(vid) or {}
        cache_entry = {
            "scout": scout,
            "safe": safe,
            "high_profile": high_profile,
            "low_profile": low_profile,
            "last_attack": int(time.time()),
            # preserve score fields calculated by farm_manager
            "farm_score": existing.get("farm_score", None),
            "attack_count": existing.get("attack_count", 0),
        }
        AttackCache.set_cache(vid, cache_entry)

    def scout(self, vid):
        """
        Attempt to send scouts to a farm
        """
        if "spy" not in self.troopmanager.troops or int(self.troopmanager.troops["spy"]) < self.scout_farm_amount:
            self.logger.debug(
                "Cannot scout %s at the moment because insufficient unit: spy", vid
            )
            return False
        troops = {"spy": self.scout_farm_amount}
        # P2-37: nao retornava nada em caso de sucesso, entao o guard do
        # chamador (`if self.scout(vid): return False`) nunca era verdadeiro --
        # o bot mandava o espiao E o farm no mesmo ciclo, contra o proprio
        # objetivo de "espiar antes de atacar".
        if self.attack(vid, troops=troops):
            self.attacked(vid, scout=True, safe=False)
            return True
        return False

    def can_attack(self, vid, clear=False):
        """
        Checks if it is safe en engage
        If not an amount of 5 scouts will be sent
        """
        cache_entry = AttackCache.get_cache(vid)

        if cache_entry and cache_entry["last_attack"]:
            last_attack = datetime.fromtimestamp(cache_entry["last_attack"])
            now = datetime.now()
            if last_attack < now - timedelta(hours=12):
                self.logger.debug(f"Attacked long ago %s, trying scout attack", {last_attack})
                if self.scout(vid):
                    return False

        if not cache_entry:
            status = self.repman.safe_to_engage(vid)
            if status == 1:
                return True

            if self.troopmanager.can_scout:
                self.scout(vid)
                return False
            self.logger.warning(
                "%s will be attacked but scouting is not possible (yet), going in blind!", vid
            )
            return True

        if not cache_entry["safe"] or clear:
            if cache_entry["scout"] and self.repman:
                status = self.repman.safe_to_engage(vid)
                if status == -1:
                    self.logger.info(
                        "Checking %s: scout report not yet available", vid
                    )
                    return False
                if status == 0:
                    # Relatório velho = último contato há MAIS de
                    # farm_low_prio_wait*2. Estava invertido: re-espiava alvo
                    # recém-espiado e descartava para sempre o que precisava
                    # ser reavaliado (P1-10).
                    if int(time.time()) - cache_entry["last_attack"] > self.farm_low_prio_wait * 2:
                        self.logger.info(f"{vid}: Old scout report found ({cache_entry['last_attack']}), re-scouting")
                        self.scout(vid)
                        return False
                    else:
                        self.logger.info(
                            "%s: scout report noted enemy units, ignoring", vid
                        )
                        return False
                self.logger.info(
                    "%s: scout report noted no enemy units, attacking", vid
                )
                return True

            self.logger.debug(
                "%s will be ignored for attack because unsafe, set safe:true to override", vid
            )
            return False

        if not cache_entry["scout"] and self.troopmanager.can_scout:
            self.scout(vid)
            return False
        min_time = self.farm_default_wait
        if cache_entry["high_profile"]:
            min_time = self.farm_high_prio_wait
        if "low_profile" in cache_entry and cache_entry["low_profile"]:
            min_time = self.farm_low_prio_wait

        if cache_entry and self.repman:
            res_left, res = self.repman.has_resources_left(vid)
            total_loot = 0
            for x in res:
                total_loot += int(res[x])

            if res_left and total_loot > 100:
                self.logger.debug(f"Draining farm of resources! Sending attack to get {res}.")
                min_time = int(self.farm_high_prio_wait / 2)

        if cache_entry["last_attack"] + min_time > int(time.time()):
            self.logger.debug(
                "%s will be ignored because of previous attack (%d sec delay between attacks)",
                vid, min_time
            )
            return False
        return cache_entry

    def has_troops_available(self, troops):
        for t in troops:
            if (
                    t not in self.troopmanager.troops
                    or int(self.troopmanager.troops[t]) < troops[t]
            ):
                return False
        return True

    def attack(self, vid, troops=None):
        """
        Send a TW attack
        """
        # P1-17: o AttackManager passou a ser criado sempre (village.py::
        # ensure_attack_manager), inclusive durante paz forcada. Antes o
        # bloqueio vinha de o objeto simplesmente nao existir; agora precisa
        # ser explicito, senao Hunter/PvP atacariam dentro da janela de paz.
        if self.in_forced_peace:
            self.logger.info("[Attack] %s -> %s: forced peace active, not sending", self.village_id, vid)
            return "forced_peace"

        # P2-38: validar a posicao antes do GET da praca -- a requisicao
        # (com o sleep de delay_factor) era desperdicada quando o alvo nao
        # estava no mapa.
        if vid not in self.map.map_pos:
            return False

        url = f"game.php?village={self.village_id}&screen=place&target={vid}"
        pre_attack = self.wrapper.get_url(url)
        if pre_attack is None:
            self.logger.warning("[Attack] %s -> %s: request timed out, aborting", self.village_id, vid)
            return False
        pre_data = {}
        for u in Extractor.attack_form(pre_attack):
            k, v = u
            pre_data[k] = v
        if troops:
            pre_data.update(troops)
        else:
            pre_data.update(self.troopmanager.troops)

        x, y = self.map.map_pos[vid]
        post_data = {"x": x, "y": y, "target_type": "coord", "attack": "Aanvallen"}
        pre_data.update(post_data)

        confirm_url = f"game.php?village={self.village_id}&screen=place&try=confirm"
        conf = self.wrapper.post_url(url=confirm_url, data=pre_data)
        if conf is None:
            self.logger.warning("[Attack] %s -> %s: confirm request timed out, aborting", self.village_id, vid)
            return False
        if '<div class="error_box">' in conf.text:
            return False
        duration = Extractor.attack_duration(conf)
        if self.forced_peace_time:
            now = datetime.now()
            if now + timedelta(seconds=duration) > self.forced_peace_time:
                self.logger.info("Attack would arrive after the forced peace timer, not sending attack!")
                return "forced_peace"

        self.logger.info(
            "[Attack] %s -> %s duration %f.1 h", self.village_id, vid, duration / 3600
        )

        confirm_data = {}
        for u in Extractor.attack_form(conf):
            k, v = u
            if k == "support":
                continue
            confirm_data[k] = v
        new_data = {"building": "main", "h": self.wrapper.last_h}
        confirm_data.update(new_data)
        # The extractor doesn't like the empty cb value, and mistakes its value for x. So I add it here.
        if "x" not in confirm_data:
            confirm_data["x"] = x

        result = self.wrapper.get_api_action(
            village_id=self.village_id,
            action="popup_command",
            params={"screen": "place"},
            data=confirm_data,
        )

        return result


class AttackCache:
    @staticmethod
    def get_cache(village_id):
        return FileManager.load_json_file(f"cache/attacks/{village_id}.json")

    @staticmethod
    def set_cache(village_id, entry):
        return FileManager.save_json_file(entry, f"cache/attacks/{village_id}.json")

    @staticmethod
    def cache_grab():
        output = {}

        for existing in FileManager.list_directory("cache/attacks", ends_with=".json"):
            output[existing.replace(".json", "")] = FileManager.load_json_file(f"cache/attacks/{existing}")
        return output


class ConquestCache:
    """
    Feature 8: Persists conquest state per target village.
    Cache path: cache/conquest/{target_id}.json
    """
    @staticmethod
    def get(target_id):
        return FileManager.load_json_file(f"cache/conquest/{target_id}.json")

    @staticmethod
    def set(target_id, entry):
        FileManager.save_json_file(entry, f"cache/conquest/{target_id}.json")

    @staticmethod
    def all_reserved():
        """Returns set of target_ids currently reserved by any village."""
        reserved = set()
        for fname in FileManager.list_directory("cache/conquest", ends_with=".json"):
            data = FileManager.load_json_file(f"cache/conquest/{fname}")
            if data and data.get("status") in ("train_sent", "extra_pending"):
                reserved.add(fname.replace(".json", ""))
        return reserved


class ConquestManager:
    """
    Feature 8: Noble train manager for barbarian conquest.
    Handles target selection, escort calculation and attack sequencing.
    One ConquestManager instance per offensive village per cycle.
    """
    TRAIN_SIZE = 4
    MAX_RADIUS = 100
    # Units never used as escort filler.
    # knight (Paladino): there is only ever one per village and it must never
    # leave on its own -- same rule already enforced for the PvP conquest in
    # 2026-08-07 (see docs/features_log.md). Without it here, the barbarian
    # train could ship the Paladino out as escort filler.
    # snob: it is the train's payload, not escort -- _send_train sets
    # troops["snob"] = 1 explicitly per attack, overwriting whatever the
    # escort calculation produced. Leaving snob in the escort pool only
    # inflated total_per_attack against min_escort_total, so a train could be
    # judged "escorted enough" on the back of nobles that were never actually
    # sent as escort. Noble availability is gated separately, by
    # _available_nobles().
    EXCLUDED_UNITS = {"spy", "knight", "snob"}

    def __init__(self, wrapper, village_id, troopmanager, map_obj, config, repman=None):
        self.wrapper = wrapper
        self.village_id = village_id
        self.troopmanager = troopmanager
        self.map = map_obj
        self.config = config
        self.repman = repman  # ReportManager — used for real loyalty extraction
        self.logger = logging.getLogger(f"Conquest:{self.village_id}")
        self._attack_manager = AttackManager(
            wrapper=wrapper,
            village_id=village_id,
            troopmanager=troopmanager,
            map=map_obj,
        )

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self):
        """
        Main entry point called from village.run_conquest().
        Returns True if a train was dispatched, False otherwise.
        """
        cfg = self.config.get("conquest", {})
        if not cfg.get("enabled", False):
            return False

        # P1-9: a conquista em andamento e checada ANTES do guard de trem
        # completo. _handle_existing() trata o estado extra_pending, que
        # precisa de 1 noble, nao de TRAIN_SIZE. Com a ordem antiga, logo apos
        # disparar um trem a aldeia ficava com 0 nobles e todo run() saia no
        # primeiro return False -- a regen de lealdade, a leitura de lealdade
        # real e o envio do noble extra so voltavam a ser avaliados quando a
        # aldeia acumulasse 4 nobles novos, o que pode levar dias. Nesse meio
        # tempo a lealdade do alvo regenerava e o progresso se perdia.
        existing = self._get_my_conquest()
        if existing:
            return self._handle_existing(existing, cfg)

        # Need exactly TRAIN_SIZE nobles available, not counting nobles another
        # conquest system already has scheduled (Feature 27)
        available_nobles = self._available_nobles()
        if available_nobles < self.TRAIN_SIZE:
            self.logger.info(
                "Conquest: %d/%d nobles available, waiting for full train",
                available_nobles, self.TRAIN_SIZE
            )
            # Clear any stale reserve (nobles were lost or used elsewhere).
            # Only touches this manager's own owner_key -- other pending
            # reservations (e.g. a PvP conquest escort) must not be wiped.
            self.troopmanager.conquest_reserve.pop("barbarian_conquest", None)
            return False

        # Find and reserve a new target
        target_id = self.find_target(cfg)
        if not target_id:
            self.logger.info("Conquest: no suitable barbarian target found")
            return False

        # Pre-check escort: if insufficient, set reserve so farm/gather
        # leave these troops at home until escort threshold is met.
        escort = self._build_escort(cfg)
        if escort is None:
            needed = self._calculate_needed_escort(cfg)
            if needed:
                self.troopmanager.conquest_reserve["barbarian_conquest"] = needed
                self.logger.info(
                    "Conquest: escort insufficient — reserving %s for next cycle "
                    "(farm and gather will respect this reserve)",
                    needed
                )
            # P2-22: an empty result used to mean "no troops at all", which
            # essentially never happened, so a missing else was harmless.
            # Now _calculate_needed_escort() also returns {} when its own
            # gates decide reserving is counterproductive -- and troop counts
            # shrink (losses in farm/defence), so a village CAN cross back
            # under the gate after a reserve was already set. Without this
            # pop, that stale reserve would linger forever and starve
            # farm/gather exactly the way P2-22 describes, just by a
            # different route.
            elif self.troopmanager.conquest_reserve.pop("barbarian_conquest", None):
                self.logger.info(
                    "Conquest: released stale escort reserve — farm and gather "
                    "are free again while troops rebuild"
                )
            return False

        # Escort is sufficient: clear any previous reserve and fire the train
        self.troopmanager.conquest_reserve.pop("barbarian_conquest", None)
        return self._send_train(target_id, cfg)

    # ------------------------------------------------------------------
    # Target selection
    # ------------------------------------------------------------------

    def find_target(self, cfg):
        """
        Scans the map for barbarian villages within radius, scores them
        and returns the best unreserved target_id.

        Feature 15: a manually queued target (set via webmanager /conquest)
        always takes priority over automatic scoring, bypassing the
        radius/points filters below (deliberate user choice).
        """
        manual_target = self._get_manual_target()
        if manual_target:
            self.logger.info(
                "Conquest: using manually queued target %s (overrides automatic selection)",
                manual_target
            )
            return manual_target

        max_radius = min(cfg.get("max_radius", 20), self.MAX_RADIUS)
        min_pts = cfg.get("min_points", 100)
        max_pts = cfg.get("max_points", 3000)
        reserved = ConquestCache.all_reserved()

        # Collect managed village locations for gap-filling score
        my_locations = self._get_managed_locations()

        candidates = []
        for vid, village in self.map.villages.items():
            if village.get("owner", "0") != "0":
                continue  # not barbarian
            if vid in reserved:
                continue  # already targeted
            if vid == self.village_id:
                continue

            pts = village.get("points", 0)
            if pts < min_pts or pts > max_pts:
                continue

            dist = self.map.get_dist(village["location"])
            if dist > max_radius:
                continue

            score = self._score_target(village, dist, my_locations, cfg)
            candidates.append((vid, score))

        if not candidates:
            return None

        # Lower score = better target
        candidates.sort(key=lambda x: x[1])
        return candidates[0][0]

    def _score_target(self, village, dist, my_locations, cfg):
        """
        Scoring for fill_gaps priority (default):
        Combines distance from attacker and centrality to empire.
        Lower = more desirable.

        Bugfix (2026-08-07): the 60/30/10 weights below used to apply
        directly to raw values -- distance in tiles (0..max_radius, so 0..20
        by default) and points (0..max_points, so 0..1100 by default).
        Those two ranges differ by ~2 orders of magnitude, so the "10%
        points" term (pts * 0.1, up to 110) completely swamped the "60%
        centrality" + "30% distance" terms (up to ~18 combined) -- in
        practice this always picked the highest-points barbarian in range,
        basically ignoring distance/gap-filling entirely (confirmed live:
        picked a target 11.2 tiles away over one 1.4 tiles away purely
        because it had ~3x the points). Fixed by normalizing distance and
        points to comparable 0..1 scales (relative to max_radius/max_points)
        before applying the weights, so the stated 60/30/10 split actually
        holds regardless of the configured radius/points range.
        """
        priority = cfg.get("priority", "fill_gaps")
        pts = village.get("points", 1)
        loc = village["location"]

        max_radius = max(1, min(cfg.get("max_radius", 20), self.MAX_RADIUS))
        max_pts = max(1, cfg.get("max_points", 3000))
        # Higher points = more desirable, so this is subtracted below;
        # capped at 1.0 in case a village exceeds max_points somehow.
        pts_factor = min(1.0, pts / max_pts)
        dist_norm = min(1.0, dist / max_radius)

        if priority == "fill_gaps" and my_locations:
            # Average distance from ALL managed villages → lower means more central
            avg_dist_to_empire = sum(
                ((loc[0] - lx) ** 2 + (loc[1] - ly) ** 2) ** 0.5
                for lx, ly in my_locations
            ) / len(my_locations)
            avg_dist_norm = min(1.0, avg_dist_to_empire / max_radius)
            # Blend: centrality 60%, attacker distance 30%, inverse points 10%
            score = (avg_dist_norm * 0.6) + (dist_norm * 0.3) - (pts_factor * 0.1)
        else:
            # Simple: closer and higher points wins
            score = dist_norm - (pts_factor * 0.1)

        return score

    def _get_managed_locations(self):
        """Returns list of (x, y) for all managed villages with cached coords."""
        locations = []
        for fname in FileManager.list_directory("cache/managed", ends_with=".json"):
            data = FileManager.load_json_file(f"cache/managed/{fname}")
            if data and data.get("x") and data.get("y"):
                locations.append((data["x"], data["y"]))
        return locations

    def _get_manual_target(self):
        """
        Feature 15: checks cache/conquest/*.json for a target queued manually
        via the webmanager (/conquest), status == "manual". Processed
        oldest-first (FIFO, by "queued_at"). Any village whose noble train
        becomes ready will pick up the oldest pending manual target here,
        before find_target() ever runs its automatic scoring loop.

        Re-validates barbarian ownership against the shared cache/villages/
        snapshot (populated by any managed village's map fetch) before
        handing the target out -- if it's no longer a barbarian (someone
        else conquered it, or it was never barbarian to begin with, e.g. a
        bad manual entry), the queue entry is marked "invalid" instead of
        being retried forever.

        Returns target_id or None.
        """
        pending = []
        for fname in FileManager.list_directory("cache/conquest", ends_with=".json"):
            data = FileManager.load_json_file(f"cache/conquest/{fname}")
            if data and data.get("status") == "manual":
                target_id = fname.replace(".json", "")
                pending.append((data.get("queued_at", 0), target_id, data))

        pending.sort(key=lambda item: item[0])

        for _, target_id, data in pending:
            village_data = FileManager.load_json_file(f"cache/villages/{target_id}.json")
            if village_data and str(village_data.get("owner", "0")) != "0":
                self.logger.warning(
                    "Conquest: manual target %s is no longer a barbarian village "
                    "(owner=%s) -- cancelling manual queue entry",
                    target_id, village_data.get("owner")
                )
                ConquestCache.set(target_id, {
                    **data,
                    "status": "invalid",
                    "invalid_reason": "Não é mais uma aldeia bárbara",
                })
                continue
            return target_id
        return None

    def _get_village_meta(self, target_id):
        """
        Returns village metadata dict (name/points/location/owner) for
        target_id, preferring this village's own live map scan
        (self.map.villages) and falling back to the shared cache/villages/
        snapshot. The fallback matters for Feature 15: a manually queued
        target may lie outside the map region this particular village
        fetched this cycle, but another managed village may have already
        cached it.
        """
        village = self.map.villages.get(target_id)
        if village:
            return village
        return FileManager.load_json_file(f"cache/villages/{target_id}.json") or {}

    # ------------------------------------------------------------------
    # Train dispatch
    # ------------------------------------------------------------------

    def _send_train(self, target_id, cfg):
        """
        Builds and sends a 4-noble train to target_id.
        Divides available escort troops evenly across 4 attacks.
        """
        escort_per_attack = self._build_escort(cfg)
        if escort_per_attack is None:
            self.logger.warning(
                "Conquest: not enough troops for minimum escort, skipping"
            )
            return False

        self.logger.info(
            "Conquest: sending noble train (%d nobles) to %s | escort/attack: %s",
            self.TRAIN_SIZE, target_id, escort_per_attack
        )
        self.wrapper.reporter.report(
            self.village_id,
            "TWB_CONQUEST",
            f"Noble train → {target_id} | escort: {escort_per_attack}"
        )

        loyalty_drop = cfg.get("loyalty_drop_per_noble", 25)
        hits_sent = 0

        for i in range(self.TRAIN_SIZE):
            troops = dict(escort_per_attack)
            troops["snob"] = 1
            result = self._attack_manager.attack(target_id, troops=troops)
            if result and result != "forced_peace":
                hits_sent += 1
                # Deduct from troopmanager so next iteration sees updated counts
                for unit, qty in escort_per_attack.items():
                    current = int(self.troopmanager.troops.get(unit, 0))
                    self.troopmanager.troops[unit] = str(max(0, current - qty))
                snob_current = int(self.troopmanager.troops.get("snob", 0))
                self.troopmanager.troops["snob"] = str(max(0, snob_current - 1))
            else:
                self.logger.warning(
                    "Conquest: attack %d/%d failed for target %s",
                    i + 1, self.TRAIN_SIZE, target_id
                )
                break

        if hits_sent == 0:
            return False

        # Train fired: release this manager's reserve so farm/gather can use
        # that portion of the pool again (other owners' reservations, if any,
        # are left untouched).
        self.troopmanager.conquest_reserve.pop("barbarian_conquest", None)

        # Bugfix (auditoria Feature 15): faltavam os campos target_name/
        # target_points/target_location/hits_needed, e a chave gravada era
        # "hits" enquanto o webmanager (ConquestReader.load(), lê "hits_done").
        # Resultado: a página /conquest sempre mostrava 0/4 nobles e nome/
        # pontos/coordenada genéricos, independente do progresso real.
        target_meta = self._get_village_meta(target_id)

        loyalty_after = max(0, 100 - (hits_sent * loyalty_drop))
        ConquestCache.set(target_id, {
            "reserved_by": self.village_id,
            "hits_done": hits_sent,
            "hits_needed": self.TRAIN_SIZE,
            "loyalty_after_train": loyalty_after,
            "loyalty_source": "estimate",
            "last_hit_timestamp": int(time.time()),
            "status": "train_sent" if hits_sent == self.TRAIN_SIZE else "extra_pending",
            "target_name": target_meta.get("name") or ("Bárbara #%s" % target_id),
            "target_points": target_meta.get("points"),
            "target_location": target_meta.get("location"),
        })

        if loyalty_after > 0:
            self.logger.warning(
                "Conquest: train incomplete or loyalty not zeroed — "
                "estimated loyalty remaining: %.1f. Extra noble(s) may be needed.",
                loyalty_after
            )
        else:
            self.logger.info(
                "Conquest: full train sent to %s, loyalty should be at 0", target_id
            )

        return hits_sent > 0

    def _available_troops(self):
        """
        Feature 27: troops in this village genuinely free for the barbarian
        conquest -- total, minus EXCLUDED_UNITS, minus every reservation owned
        by *another* system (today: the PvP conquest's "pvp:{target_id}" keys,
        set by PvpConquestManager._reserve_troops).

        Before this, _build_escort/_calculate_needed_escort read
        troopmanager.troops raw, so the barbarian train could commit troops the
        PvP conquest had already earmarked for a scheduled clear or noble
        escort -- the same double-booking class of bug as the 38409 incident
        (docs/features_log.md, 2026-08-07), but across two systems instead of
        within one.

        Our own "barbarian_conquest" key is deliberately NOT subtracted. run()
        sets it while the escort is still too small, precisely to stop
        farm/gather from spending the troops being accumulated. Subtracting it
        here would make this manager block itself: reserve set -> next cycle
        sees less available -> escort still looks insufficient -> reserve never
        released, even once the real troop count would suffice.
        """
        reserve = self.troopmanager.total_conquest_reserve(
            exclude_owner="barbarian_conquest"
        ) if hasattr(self.troopmanager, "total_conquest_reserve") else {}

        available = {}
        for unit, qty in self.troopmanager.troops.items():
            if unit in self.EXCLUDED_UNITS:
                continue
            free = int(qty) - reserve.get(unit, 0)
            if free > 0:
                available[unit] = free
        return available

    def _available_nobles(self):
        """
        Feature 27: nobles in this village not already committed to another
        conquest system. PvpConquestManager reserves one snob per scheduled
        noble attack (game/pvp_conquest.py, troops["snob"] = 1 -> reserved
        under "pvp:{target_id}"), and those nobles may sit at home for hours
        while Hunter waits to synchronise arrival times.

        Reading troops["snob"] raw counted them as available, so the barbarian
        conquest could decide it had a full train and fire, consuming nobles a
        scheduled PvP train was relying on. Nobles are the most expensive unit
        in the game, which makes this the costliest instance of the
        double-booking bug this feature exists to fix.
        """
        reserve = self.troopmanager.total_conquest_reserve(
            exclude_owner="barbarian_conquest"
        ) if hasattr(self.troopmanager, "total_conquest_reserve") else {}
        total = int(self.troopmanager.troops.get("snob", 0))
        return max(0, total - reserve.get("snob", 0))

    def _calculate_needed_escort(self, cfg):
        """
        Feature 8: Calculates how many troops need to be kept home (reserved)
        so that when they accumulate, _build_escort() will pass.

        Target: min_escort_total troops per noble × TRAIN_SIZE nobles,
        divided by escort_ratio (since _build_escort commits ratio% of available).

        Example: min_escort_total=50, TRAIN_SIZE=4, escort_ratio=0.25
          → need 50 × 4 = 200 committed → need 200 / 0.25 = 800 total at home
          → spread evenly across available unit types

        Returns {unit: qty_to_reserve} or {} if no troops present at all, or
        if reserving would do more harm than good (see P2-22 below).

        P2-22: this used to reserve `min(per_unit, free)` per type, and the
        min() meant any type with fewer troops than the even split got 100%
        of it reserved. Since _get_farmable_troops() and do_gather() both
        subtract the reserve, that stopped farm and gather outright -- with
        no time limit, and the reserve lives in TroopManager, which persists
        across cycles, so it stayed stuck until the escort finally closed.
        Worse, it is self-defeating: farming is what funds the recruitment
        that would close the escort gap, so freezing the army to reach an
        escort target actively delays reaching it.

        Two gates now bound that:

        1. Only reserve once the goal is realistically in reach
           (escort_reserve_min_progress, default 0.5 = half of needed_total
           already home). Far from the target, the reserve buys nothing --
           it can't conjure troops, it only stops the farm income that pays
           for them -- so it's skipped entirely.
        2. Never reserve more than escort_reserve_max_pct (default 0.8) of
           any single type, so farm/gather always keep a working residual
           instead of being starved to zero on some unit the template needs.

        Together: small army -> no reserve at all (gate 1); large army ->
        the 20% left over is big enough in absolute terms to keep farming
        (gate 2). Both are opt-out-able via config for anyone who prefers
        the old all-in behaviour (max_pct 1.0, min_progress 0.0).
        """
        ratio = cfg.get("escort_ratio", 0.5)
        min_total = cfg.get("min_escort_total", 50)
        max_pct = cfg.get("escort_reserve_max_pct", 0.8)
        min_progress = cfg.get("escort_reserve_min_progress", 0.5)

        # Total troops needed at home to satisfy escort after ratio+split
        # per_attack = (available × ratio) // TRAIN_SIZE ≥ min_total
        # → available × ratio ≥ min_total × TRAIN_SIZE
        # → available ≥ (min_total × TRAIN_SIZE) / ratio
        needed_total = math.ceil((min_total * self.TRAIN_SIZE) / ratio) if ratio > 0 else 0

        # Net of other systems' reservations (Feature 27): reserving troops the
        # PvP conquest already claimed would make the two reservations sum to
        # more than the village actually has, starving farm/gather of troops
        # that only exist on paper.
        available = self._available_troops()

        if not available:
            return {}

        # P2-22, gate 1: is the escort target even in reach?
        have_total = sum(available.values())
        if needed_total > 0 and have_total < needed_total * min_progress:
            self.logger.info(
                "Conquest: %d/%d troops toward escort target — too far off to "
                "reserve (below %.0f%%), leaving farm and gather free",
                have_total, needed_total, min_progress * 100
            )
            return {}

        # Distribute the needed total evenly across available unit types
        per_unit = math.ceil(needed_total / len(available))
        reserve = {}
        for unit, free in available.items():
            # P2-22, gate 2: cap per type so a residual always stays farmable.
            # Only reserve up to what's actually free (no phantom reserve).
            qty = min(per_unit, int(free * max_pct))
            if qty > 0:
                reserve[unit] = qty

        return reserve

    def _build_escort(self, cfg):
        """
        Calculates per-attack escort by dividing available troops across
        TRAIN_SIZE attacks using escort_ratio.
        Returns dict of {unit: qty_per_attack} or None if below minimum.

        Accepts any combat troop type (spear, sword, archer, axe, light, heavy, ram).
        spy, knight and snob are excluded (see EXCLUDED_UNITS), as are troops
        reserved by another conquest system (see _available_troops).
        Works for both offensive and defensive village profiles.

        Minimum escort is validated two ways:
        - min_escort: per-unit minimums (optional, e.g. {"heavy": 20})
        - min_escort_total: minimum combined troops per noble attack (default: 50)
        """
        ratio = cfg.get("escort_ratio", 0.5)
        min_escort = cfg.get("min_escort", {})
        min_escort_total = cfg.get("min_escort_total", 50)

        # Feature 27: net of troops another system already reserved, so the
        # barbarian train never commits troops a scheduled PvP clear/escort is
        # counting on.
        available = self._available_troops()

        # Total troops to commit across all 4 attacks
        committed = {
            unit: int(qty * ratio)
            for unit, qty in available.items()
        }

        # Per-attack share (floor division, remainder stays home)
        per_attack = {
            unit: qty // self.TRAIN_SIZE
            for unit, qty in committed.items()
            if qty // self.TRAIN_SIZE > 0
        }

        if not per_attack:
            self.logger.warning("Conquest: no troops available for escort after ratio split")
            return None

        # Validate per-unit minimums if configured
        for unit, min_qty in min_escort.items():
            if per_attack.get(unit, 0) < min_qty:
                self.logger.warning(
                    "Conquest: escort below minimum for %s (%d < %d)",
                    unit, per_attack.get(unit, 0), min_qty
                )
                return None

        # Validate total escort per noble attack regardless of troop type
        total_per_attack = sum(per_attack.values())
        if total_per_attack < min_escort_total:
            self.logger.warning(
                "Conquest: escort total %d below min_escort_total %d per noble — "
                "waiting for more troops before sending train",
                total_per_attack, min_escort_total
            )
            return None

        self.logger.info(
            "Conquest: escort per noble = %s (total: %d)",
            per_attack, total_per_attack
        )
        return per_attack

    # ------------------------------------------------------------------
    # Extra noble logic (loyalty regeneration)
    # ------------------------------------------------------------------

    def _target_is_mine(self, target_id):
        """
        Proof-of-conquest: checks if target_id now appears in cache/villages/
        with owner matching our player_id.
        Returns True if confirmed ours, False otherwise.

        Bugfix (2026-08-07): used to read self.wrapper.player_id /
        self.wrapper.game_state, but WebWrapper never actually sets either --
        those attributes only exist on per-village objects (Village.game_data,
        BuildingManager.game_state), never on the shared session wrapper. The
        hasattr() check was always False and the game_state fallback always
        raised AttributeError, so this always returned False, silently. Fixed
        by reading the owner id from cache/villages/{self.village_id}.json --
        self.village_id is always one of our own managed villages, so its
        cached "owner" field IS our player_id, no wrapper plumbing needed.
        Mirrors the equivalent fix in
        PvpConquestManager._own_player_id() (game/pvp_conquest.py).
        """
        data = FileManager.load_json_file(f"cache/villages/{target_id}.json")
        if not data:
            return False
        own_data = FileManager.load_json_file(f"cache/villages/{self.village_id}.json")
        if not own_data:
            return False
        player_id = str(own_data.get("owner", "0"))
        if player_id == "0":
            return False
        owner = str(data.get("owner", "0"))
        return owner == player_id and owner != "0"

    def _get_real_loyalty(self, target_id):
        """
        Tries to extract real loyalty from the most recent noble attack report
        against target_id. Returns float loyalty value or None if not available.

        Reports with extra["loyalty_after"] are populated by reports.py
        when it processes noble (snob) attack reports.
        """
        if not self.repman:
            return None
        best_ts = 0
        best_loyalty = None
        for rep_id, entry in self.repman.last_reports.items():
            if str(entry.get("dest")) != str(target_id):
                continue
            extra = entry.get("extra", {})
            # Only consider reports that contain snob and have loyalty data
            if "loyalty_after" not in extra:
                continue
            units_sent = extra.get("units_sent", {})
            if "snob" not in units_sent:
                continue
            when = extra.get("when", 0)
            if when > best_ts:
                best_ts = when
                best_loyalty = float(extra["loyalty_after"])
        return best_loyalty

    def _handle_existing(self, conquest_data, cfg):
        """
        Called when this village already has a conquest in progress.

        Priority order for loyalty source:
        1. Village ownership check (cache/villages/) — definitive proof
        2. Real loyalty from noble attack report (reports.py extracts it)
        3. Mathematical estimate (fallback)
        """
        target_id = conquest_data["target_id"]
        regen = cfg.get("loyalty_regen_per_hour", 1.5)
        loyalty_drop = cfg.get("loyalty_drop_per_noble", 25)

        # --- Priority 1: ownership check (prova dos 9) ---
        if self._target_is_mine(target_id):
            self.logger.info(
                "Conquest: target %s confirmed as ours via village cache — marking complete",
                target_id
            )
            ConquestCache.set(target_id, {**conquest_data, "status": "complete"})
            self.wrapper.reporter.report(
                self.village_id, "TWB_CONQUEST",
                f"Conquest CONFIRMED: {target_id} is now ours."
            )
            return False

        # --- Priority 2: real loyalty from report ---
        real_loyalty = self._get_real_loyalty(target_id)
        last_hit = conquest_data.get("last_hit_timestamp", 0)

        if real_loyalty is not None:
            # Apply regen since that report's timestamp
            hours_since_report = (time.time() - last_hit) / 3600
            current_loyalty = min(100.0, real_loyalty + (hours_since_report * regen))
            loyalty_source = "report"
            self.logger.info(
                "Conquest: target %s — real loyalty from report: %.1f, "
                "estimated now: %.1f (%.1fh regen)",
                target_id, real_loyalty, current_loyalty, hours_since_report
            )
        else:
            # --- Priority 3: mathematical estimate ---
            loyalty_after = conquest_data.get("loyalty_after_train", 0)
            hours_elapsed = (time.time() - last_hit) / 3600
            current_loyalty = min(100.0, loyalty_after + (hours_elapsed * regen))
            loyalty_source = "estimate"
            self.logger.info(
                "Conquest: target %s — no report data, using estimate: %.1f "
                "(%.1fh elapsed)",
                target_id, current_loyalty, hours_elapsed
            )

        if current_loyalty <= 0:
            self.logger.info(
                "Conquest: target %s loyalty at 0 — marking complete", target_id
            )
            ConquestCache.set(target_id, {**conquest_data, "status": "complete"})
            return False

        self.logger.info(
            "Conquest: target %s loyalty = %.1f — sending extra noble(s)",
            target_id, current_loyalty
        )

        available_nobles = self._available_nobles()
        if available_nobles < 1:
            self.logger.info("Conquest: no noble available for extra hit, waiting")
            return False

        escort_per_attack = self._build_escort(cfg)
        if escort_per_attack is None:
            return False

        troops = dict(escort_per_attack)
        troops["snob"] = 1
        result = self._attack_manager.attack(target_id, troops=troops)

        if result and result != "forced_peace":
            new_loyalty = max(0.0, current_loyalty - loyalty_drop)
            ConquestCache.set(target_id, {
                **conquest_data,
                # .get("hits", ...) e fallback p/ arquivos antigos gravados
                # antes da correção do mismatch de chave (ver _send_train).
                "hits_done": conquest_data.get("hits_done", conquest_data.get("hits", 0)) + 1,
                "hits_needed": conquest_data.get("hits_needed", self.TRAIN_SIZE),
                "loyalty_after_train": new_loyalty,
                "loyalty_source": loyalty_source,
                "last_hit_timestamp": int(time.time()),
                "status": "extra_pending" if new_loyalty > 0 else "complete",
            })
            self.logger.info(
                "Conquest: extra noble sent to %s, estimated loyalty now %.1f",
                target_id, new_loyalty
            )
            return True

        return False

    def _get_my_conquest(self):
        """
        Returns active conquest data reserved by this village, or None.
        """
        for fname in FileManager.list_directory("cache/conquest", ends_with=".json"):
            target_id = fname.replace(".json", "")
            data = FileManager.load_json_file(f"cache/conquest/{fname}")
            if (
                data
                and data.get("reserved_by") == self.village_id
                and data.get("status") in ("train_sent", "extra_pending")
            ):
                data["target_id"] = target_id
                return data
        return None
