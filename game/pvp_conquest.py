"""
Feature 13 — Conquista PvP semi-manual

Fluxo por alvo:
  pending_scout   → bot envia scout de qualquer aldeia com espiões
  pending_sim     → relatório chegou; Simulator avalia se a limpeza é viável
  scheduled       → Hunter agendou clear + noble train com chegada simultânea
  complete        → conquista concluída (loyalty ≤ 0 ou aldeia ownership confirmada)
  failed          → clear inviável ou noble train não disparou

Cache: cache/pvp_conquest/{target_id}.json
"""

import datetime
import logging
import time

from core.extractors import Extractor
from core.filemanager import FileManager
from core.world_config import WorldConfig
from game.simulator import Simulator

logger = logging.getLogger("PvpConquest")

DATETIME_FMT = "%Y-%m-%d %H:%M:%S"


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

class PvpConquestCache:
    DIR = "cache/pvp_conquest"

    @staticmethod
    def get(target_id):
        return FileManager.load_json_file(f"{PvpConquestCache.DIR}/{target_id}.json")

    @staticmethod
    def set(target_id, data):
        FileManager.save_json_file(data, f"{PvpConquestCache.DIR}/{target_id}.json")

    @staticmethod
    def delete(target_id):
        FileManager.remove_file(f"{PvpConquestCache.DIR}/{target_id}.json")

    @staticmethod
    def all():
        out = {}
        for fname in FileManager.list_directory(PvpConquestCache.DIR, ends_with=".json"):
            tid = fname.replace(".json", "")
            data = FileManager.load_json_file(f"{PvpConquestCache.DIR}/{fname}")
            if data:
                out[tid] = data
        return out


# ---------------------------------------------------------------------------
# Main manager — called once per cycle from twb.py
# ---------------------------------------------------------------------------

class PvpConquestManager:
    """
    Processes all pending PvP conquest targets each bot cycle.

    Requires:
      - villages: dict {village_id: Village} (managed villages, already run this cycle)
      - wrapper: WebWrapper instance
      - config: full bot config dict
    """

    def __init__(self, wrapper, villages, config):
        self.wrapper = wrapper
        self.villages = villages      # {village_id: Village}
        self.config = config
        self.sim = Simulator()
        # Feature 18: cached world settings (night bonus, moral) -- refreshed
        # at most every WorldConfig.CACHE_TTL, cheap to call every cycle.
        self.world_config = WorldConfig.get(
            server=config.get("server", {}).get("server"),
            endpoint=config.get("server", {}).get("endpoint"),
        )

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    # Real transitions are pending_scout -> pending_sim -> scheduled, plus
    # the completion check once scheduled. 4 gives headroom without risking
    # a runaway loop if a future step is added carelessly.
    MAX_STEPS_PER_CALL = 4

    def run(self):
        cfg = self.config.get("pvp_conquest", {})
        if not cfg.get("enabled", False):
            return

        targets = PvpConquestCache.all()
        if not targets:
            return

        for target_id, data in targets.items():
            try:
                # Bugfix (2026-08-07): this used to do at most one step per
                # target per call (e.g. pending_scout -> pending_sim), so a
                # target that became ready to advance further *within this
                # same call* -- e.g. a scout report was already sitting in
                # cache the moment _step_scout ran, and _step_simulate could
                # have run immediately after -- had to wait an entire extra
                # bot cycle before anything happened. Conquest is supposed
                # to preempt routine play once it's underway, not crawl one
                # state per cycle, so now each target is chained through as
                # many ready steps as fit in one call. Stops as soon as a
                # step makes no progress (still genuinely waiting on
                # something external, like a report that hasn't arrived) or
                # lands on a status this loop doesn't recognise (terminal:
                # "complete"/"failed").
                for _ in range(self.MAX_STEPS_PER_CALL):
                    status = data.get("status", "pending_scout")
                    if status == "pending_scout":
                        self._step_scout(target_id, data)
                    elif status == "pending_sim":
                        self._step_simulate(target_id, data)
                    elif status == "scheduled":
                        self._step_check_complete(target_id, data)
                        break
                    else:
                        break

                    if data.get("status", status) == status:
                        break  # no progress this step -- wait for next call
            except Exception as e:
                logger.error("PvpConquest: error processing target %s: %s", target_id, e)

    # ------------------------------------------------------------------
    # Step 1 — Scout
    # ------------------------------------------------------------------

    def _step_scout(self, target_id, data):
        """
        Find any managed village with spies and send a scout to the target.
        Marks status → pending_sim once the scout is sent.
        If a recent scout report already exists, skip straight to simulation.
        """
        # Check if there's already a usable scout report
        if self._find_scout_report(target_id):
            logger.info("PvpConquest: scout report already available for %s, skipping to sim", target_id)
            data["status"] = "pending_sim"
            PvpConquestCache.set(target_id, data)
            return

        scout_amount = self.config.get("pvp_conquest", {}).get("scout_amount", 5)

        for vid, village in self.villages.items():
            if not village.units:
                continue
            spies = int(village.units.troops.get("spy", 0))
            if spies < scout_amount:
                continue
            if not village.area or target_id not in village.area.map_pos:
                continue

            result = village.attack.attack(target_id, troops={"spy": scout_amount})
            if result and result != "forced_peace":
                logger.info(
                    "PvpConquest: scout sent from %s → %s (%d spies)",
                    vid, target_id, scout_amount
                )
                data["status"] = "pending_sim"
                data["scout_village_id"] = vid
                data["scout_sent_at"] = int(time.time())
                PvpConquestCache.set(target_id, data)
                return

        logger.warning("PvpConquest: no village with spies available to scout %s", target_id)

    # ------------------------------------------------------------------
    # Step 2 — Simulate & Schedule
    # ------------------------------------------------------------------

    def _step_simulate(self, target_id, data):
        """
        Reads the scout report, runs the simulator with the designated
        clear village's troops, and — if the attack is viable — creates
        a Hunter schedule (clear + nobles).
        """
        scout_report = self._find_scout_report(target_id)
        if not scout_report:
            # Scout report not yet available — wait next cycle
            age = time.time() - data.get("scout_sent_at", time.time())
            if age > 7200:
                logger.warning(
                    "PvpConquest: no scout report for %s after 2h — resetting to pending_scout",
                    target_id
                )
                data["status"] = "pending_scout"
                PvpConquestCache.set(target_id, data)
            return

        defender_units = scout_report.get("extra", {}).get("defence_units", {})

        cfg = self.config.get("pvp_conquest", {})
        clear_ratio = cfg.get("clear_ratio", 0.8)
        min_attack_power = cfg.get("min_attack_power", 50000)
        nobles_per_target = cfg.get("nobles_per_target", 4)
        arrival_buffer = cfg.get("arrival_buffer_seconds", 2)

        # Determine clear village
        clear_vid = data.get("clear_village_id")
        if not clear_vid or clear_vid not in self.villages:
            clear_vid = self._select_clear_village()
            if not clear_vid:
                logger.warning("PvpConquest: no offensive village available to clear %s", target_id)
                data["status"] = "failed"
                data["fail_reason"] = "no_clear_village"
                PvpConquestCache.set(target_id, data)
                return
            data["clear_village_id"] = clear_vid

        clear_village = self.villages[clear_vid]
        if not clear_village.units:
            logger.warning("PvpConquest: clear village %s has no troop data", clear_vid)
            return

        # Build attacker dict using clear_ratio of available troops.
        #
        # Bugfix (2026-08-07): "spy" was never excluded here. Simulator.
        # attack_sum() (called just below) indexes every unit through
        # attack_pool, which has no "spy" entry -- so this crashed with
        # KeyError("spy") for any clear village that simply has spies
        # parked at home (i.e. virtually always, since TroopManager always
        # reports the full in-village troop count). Also excluding "snob"
        # for the same reason escort_units does: any noble sitting idle in
        # the clear village shouldn't be thrown into the clear wave by
        # accident -- it's needed for the noble train itself.
        #
        # Bugfix (2026-08-07): "knight" (Paladino) excluded too, per user:
        # the Paladin should never leave the village automatically -- only
        # in specific, deliberately chosen clearing situations, which this
        # automatic troop-selection has no way to judge. Leave it out of
        # every auto-built attack here; sending it is a manual decision,
        # not something PvpConquestManager should do on its own.
        attacker_units = {
            unit: int(int(qty) * clear_ratio)
            for unit, qty in clear_village.units.troops.items()
            if int(qty) > 0 and unit not in ("spy", "snob", "knight")
        }

        # Run simulator
        wall_level = scout_report.get("extra", {}).get("buildings", {}).get("wall", 0)

        # Feature 18: moral/night bonus were previously hardcoded to neutral
        # values (moral=100, nightbonus=False), which could make the bot
        # recommend conquests that fail in practice against much smaller
        # targets or during the world's night bonus window. Opt-in via
        # config (pvp_conquest.dynamic_moral_night_bonus) since the moral
        # estimate is a best-effort approximation (see
        # core/world_config.py::estimate_moral docstring) -- validate
        # against the in-game simulator before relying on it.
        nightbonus = False
        moral = 100
        if cfg.get("dynamic_moral_night_bonus", False):
            nightbonus = WorldConfig.is_night_bonus_active(self.world_config)
            target_points = self._target_points(target_id)
            attacker_points = getattr(clear_village, "points", 0)
            if target_points is not None and attacker_points:
                moral = WorldConfig.estimate_moral(self.world_config, attacker_points, target_points)
            else:
                logger.warning(
                    "PvpConquest: missing points data for %s (attacker=%s, defender=%s) "
                    "-- falling back to moral=100 for this simulation",
                    target_id, attacker_points, target_points
                )
            logger.info(
                "PvpConquest: dynamic sim inputs for %s -- moral=%d%%, nightbonus=%s",
                target_id, moral, nightbonus
            )

        try:
            sim_result = self.sim.simulate(
                attackerUnits=dict(attacker_units),
                defenderUnits=dict({u: int(q) for u, q in defender_units.items()}),
                wall=wall_level,
                nightbonus=nightbonus,
                moral=moral,
                luck=0,
            )
        except Exception as e:
            logger.error("PvpConquest: simulator error for %s: %s", target_id, e)
            return

        # Evaluate result
        att_losses = sum(sim_result["attacker"]["losses"].values())
        att_total = sum(sim_result["attacker"]["quantity"].values())
        def_losses = sum(sim_result["defender"]["losses"].values())
        def_total = sum(sim_result["defender"]["quantity"].values())

        attack_power = self.sim.get_sum(self.sim.attack_sum(attacker_units))
        defender_wiped = def_losses >= def_total * 0.9
        acceptable_losses = att_losses <= att_total * 0.5

        logger.info(
            "PvpConquest: sim result for %s — att_power=%d, def_wiped=%s, att_losses=%d/%d",
            target_id, attack_power, defender_wiped, att_losses, att_total
        )

        data["last_simulation"] = {
            "att_power": attack_power,
            "att_losses": att_losses,
            "att_total": att_total,
            "def_losses": def_losses,
            "def_total": def_total,
            "wall_before": sim_result["wall_before"],
            "wall_after": sim_result["wall_after"],
            "viable": defender_wiped and acceptable_losses and attack_power >= min_attack_power,
        }

        if not data["last_simulation"]["viable"]:
            logger.warning(
                "PvpConquest: attack on %s deemed not viable (def_wiped=%s, acceptable_losses=%s, power=%d)",
                target_id, defender_wiped, acceptable_losses, attack_power
            )
            data["status"] = "failed"
            data["fail_reason"] = "simulation_failed"
            PvpConquestCache.set(target_id, data)
            return

        # Select the noble attack plan (Feature 11b — bugfix 2026-08-07: one
        # entry per available noble, up to nobles_per_target, not one entry
        # per village -- see _select_noble_attack_plan() docstring for why
        # a village can now contribute more than one separate attack).
        # data["noble_villages"] keeps its old key name for backward
        # compatibility (used by _release_reserve()); may now contain the
        # same village_id more than once.
        noble_villages = data.get("noble_villages") or self._select_noble_attack_plan(nobles_per_target)
        if not noble_villages:
            logger.warning("PvpConquest: no villages with nobles available for %s", target_id)
            data["status"] = "failed"
            data["fail_reason"] = "no_nobles"
            PvpConquestCache.set(target_id, data)
            return
        data["noble_villages"] = noble_villages

        # Build Hunter schedule
        arrival_ts = data.get("arrival_time")
        if not arrival_ts:
            logger.error("PvpConquest: target %s has no arrival_time set", target_id)
            return

        arrival_str = datetime.datetime.fromtimestamp(arrival_ts).strftime(DATETIME_FMT)

        attacks = []

        # Clear attack — arrives `arrival_buffer` seconds before nobles
        clear_arrival_ts = arrival_ts - arrival_buffer
        clear_arrival_str = datetime.datetime.fromtimestamp(clear_arrival_ts).strftime(DATETIME_FMT)

        # Escort for nobles: reuse ConquestManager's ratio via config.
        conquest_cfg = self.config.get("conquest", {})
        escort_ratio = conquest_cfg.get("escort_ratio", 0.5)
        noble_count = max(len(noble_villages), 1)

        # Register clear in Hunter
        self._hunter_add_schedule(
            target_id=target_id,
            arrival_str=clear_arrival_str,
            attacks=[{
                "source_village_id": clear_vid,
                "troops": attacker_units,
                "is_fake": False,
            }],
            label="clear",
        )

        # Register noble train in Hunter
        #
        # Bugfix (2026-08-07): escort per noble attack must be built from
        # THAT noble village's own troops, not the clear village's. The
        # previous code computed one shared escort_units dict from
        # clear_village.units.troops and reused it verbatim for every noble
        # attack -- if a noble village had a different troop mix (missing a
        # unit type entirely, or far fewer of it), Hunter would later try to
        # send more of that unit than the village actually had, and the
        # whole escort attack would fail once fired (server rejects it).
        noble_attacks = []
        for nvid in noble_villages:
            nv = self.villages.get(nvid)
            if not nv or not nv.units:
                continue
            # "knight" (Paladino) excluded -- see attacker_units above, same
            # rule applies to escort: never sent automatically.
            escort_units = {
                unit: max(1, int(int(qty) * escort_ratio) // noble_count)
                for unit, qty in nv.units.troops.items()
                if int(qty) > 0 and unit not in ("spy", "snob", "knight")
            }
            troops = dict(escort_units)
            # Always exactly 1 -- never stack multiple nobles into the same
            # attack, loyalty only drops once per battle regardless of how
            # many ride along, so extras would just be wasted. Additional
            # nobles from the same village show up here as additional
            # separate entries in noble_villages instead (see
            # _select_noble_attack_plan()).
            troops["snob"] = 1
            noble_attacks.append({
                "source_village_id": nvid,
                "troops": troops,
                "is_fake": False,
            })

        if noble_attacks:
            self._hunter_add_schedule(
                target_id=target_id,
                arrival_str=arrival_str,
                attacks=noble_attacks,
                label="nobles",
            )

        # Bugfix (2026-08-07): reserve the exact troops just committed to
        # Hunter (clear + each noble escort) so the regular farm loop and
        # the barbarian ConquestManager don't spend them before Hunter
        # actually fires -- which can be minutes to hours from now, since
        # send times are back-computed to synchronize arrival. Without this,
        # the scheduled attack can silently fail later (server rejects the
        # attack once the troops it expects are no longer in the village).
        # Released in _step_check_complete() once these Hunter schedules
        # resolve (see _maybe_release_reserve).
        self._reserve_troops(target_id, clear_vid, attacker_units, noble_attacks)

        data["status"] = "scheduled"
        data["scheduled_at"] = int(time.time())
        PvpConquestCache.set(target_id, data)
        logger.info(
            "PvpConquest: scheduled clear + %d noble(s) for target %s, arriving %s",
            len(noble_attacks), target_id, arrival_str
        )

    # ------------------------------------------------------------------
    # Step 3 — Check completion
    # ------------------------------------------------------------------

    def _step_check_complete(self, target_id, data):
        """
        Checks if the target village is now owned by us.
        Mirrors ConquestManager._target_is_mine().

        Also releases the troop reservation created by _reserve_troops()
        once it's safe to do so -- see _maybe_release_reserve().
        """
        self._maybe_release_reserve(target_id, data)

        village_data = FileManager.load_json_file(f"cache/villages/{target_id}.json")
        if not village_data:
            return

        player_id = None
        if self.wrapper and hasattr(self.wrapper, "player_id"):
            player_id = str(self.wrapper.player_id)
        if not player_id:
            try:
                player_id = str(self.wrapper.game_state["player"]["id"])
            except (AttributeError, KeyError, TypeError):
                return

        if str(village_data.get("owner", "0")) == player_id:
            data["status"] = "complete"
            data["completed_at"] = int(time.time())
            PvpConquestCache.set(target_id, data)
            logger.info("PvpConquest: target %s confirmed conquered!", target_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _target_points(self, target_id):
        """
        Feature 18: reads the target's points from cache/villages/{id}.json,
        populated by game/map.py scans. Returns None if the target hasn't
        been seen by any managed village's map scan yet.
        """
        village_data = FileManager.load_json_file(f"cache/villages/{target_id}.json")
        if not village_data:
            return None
        return village_data.get("points")

    def _find_scout_report(self, target_id):
        """Returns the most recent scout report against target_id, or None."""
        best_ts = 0
        best = None
        for fname in FileManager.list_directory("cache/reports", ends_with=".json"):
            rep = FileManager.load_json_file(f"cache/reports/{fname}")
            if not rep:
                continue
            if str(rep.get("dest")) != str(target_id):
                continue
            if rep.get("type") != "scout":
                continue
            when = rep.get("extra", {}).get("when", 0)
            if when > best_ts:
                best_ts = when
                best = rep
        return best

    def _select_clear_village(self):
        """
        Returns the village_id with the highest offensive attack power
        (profile == 'offensive' preferred, otherwise highest axe count).
        """
        best_vid = None
        best_power = 0
        for vid, village in self.villages.items():
            if not village.units or not village.units.troops:
                continue
            profile = self.config.get("villages", {}).get(vid, {}).get("profile", "")
            troops = village.units.troops

            # Attack power proxy: axes × 40 + light × 130
            power = int(troops.get("axe", 0)) * 40 + int(troops.get("light", 0)) * 130
            if profile == "offensive":
                power *= 2  # boost offensive villages

            if power > best_power:
                best_power = power
                best_vid = vid
        return best_vid

    def _select_noble_attack_plan(self, max_count):
        """
        Feature 11b (bugfix 2026-08-07): builds a plan of up to `max_count`
        *separate noble attacks*, one entry per available noble -- NOT one
        entry per village.

        Loyalty only drops once per battle no matter how many nobles ride
        along in the same attack (extras in that attack are wasted); to get
        N loyalty-reducing hits you need N separate attacks converging on
        the target, each carrying exactly one noble. Those N attacks can
        come from N different villages, or the same village firing several
        of its nobles as several distinct attack commands -- both are
        legitimate, and a village should never be capped at contributing
        "at most one" just because it's one village.

        The previous version (_select_noble_villages) picked one *village*
        per slot and always sent exactly 1 noble from it, so a single
        managed village sitting on 6 idle nobles would only ever commit 1
        of them to a conquest, regardless of nobles_per_target.

        Returns a list of village_ids, length <= max_count, where each
        occurrence of a village_id represents one separate attack (1 noble)
        to be built from that village -- the same village_id may repeat if
        it has more than one noble to spare. Order follows self.villages
        iteration order (dict insertion order), draining each village's
        available nobles before moving to the next.
        """
        plan = []
        for vid, village in self.villages.items():
            if not village.units:
                continue
            available = int(village.units.troops.get("snob", 0))
            for _ in range(available):
                if len(plan) >= max_count:
                    return plan
                plan.append(vid)
        return plan

    def _hunter_add_schedule(self, target_id, arrival_str, attacks, label=""):
        """
        Adds a schedule to cache/hunter/schedules.json via HunterReader.

        Critical bugfix (2026-08-07): this used to pass
        target_id=f"{target_id}_pvp_{label}" (e.g. "38409_pvp_clear") to
        HunterReader.add_schedule(), which stores that string verbatim as
        the schedule's "target_id" field. Hunter.run() (game/hunter.py)
        uses that exact field to look up village.area.map_pos and to call
        village.attack.attack(target_id, ...) -- neither works with
        anything other than a real village id, so every PvP-conquest
        schedule failed at send time with "target ... not in map_pos" and
        could never actually fire, from the very first version of this
        integration. Fixed by passing the real target_id and moving the
        clear/nobles distinction to HunterReader.add_schedule's `label`
        param instead, which only affects the cache dict key (still
        guarantees clear and nobles never collide, even if
        arrival_buffer_seconds were ever set to 0) and is stored as its own
        "label" field, never as "target_id".
        """
        try:
            from webmanager.utils import HunterReader
        except ImportError:
            try:
                from utils import HunterReader
            except ImportError:
                logger.error("PvpConquest: cannot import HunterReader")
                return

        HunterReader.add_schedule(
            target_id=target_id,
            arrival_str=arrival_str,
            attacks=attacks,
            label=label,
        )

    # ------------------------------------------------------------------
    # Troop reservation (bugfix, 2026-08-07)
    # ------------------------------------------------------------------
    #
    # Farm and the barbarian ConquestManager both run synchronously -- they
    # decide to spend troops and send the attack in the same breath, so
    # there's no window for another system to steal those troops first.
    # PvpConquestManager is different: _step_simulate() commits to a set of
    # troops *now*, but Hunter may not actually send the resulting attacks
    # until much later (send_time is back-computed from arrival_time to
    # synchronize clear + nobles). During that whole window the committed
    # troops must be visibly reserved, or farm/gather/barbarian-conquest can
    # spend them first and the scheduled attack fails when Hunter fires it.

    def _add_reserve(self, village, key, troops):
        """
        Adds `troops` ({unit: qty}) to `village`'s conquest_reserve under
        `key`, merging additively with whatever's already reserved under
        that same key (relevant if the same village is both the clear
        village and a noble village for this target).
        """
        if not village or not village.units:
            return
        current = village.units.conquest_reserve.get(key, {})
        merged = dict(current)
        for unit, qty in troops.items():
            merged[unit] = merged.get(unit, 0) + int(qty)
        village.units.conquest_reserve[key] = merged

    def _reserve_troops(self, target_id, clear_vid, attacker_units, noble_attacks):
        """
        Reserves the clear troops (from clear_vid) and every noble attack's
        escort+snob (from noble_attacks, as actually registered with
        Hunter) under the shared key "pvp:{target_id}".
        """
        key = f"pvp:{target_id}"
        self._add_reserve(self.villages.get(str(clear_vid)), key, attacker_units)
        for atk in noble_attacks:
            self._add_reserve(
                self.villages.get(str(atk["source_village_id"])), key, atk["troops"]
            )

    def _release_reserve(self, target_id, data):
        """
        Removes the "pvp:{target_id}" reservation from every village that
        had troops committed to it (clear_village_id + noble_villages, as
        recorded in the target's cache). Idempotent -- safe to call even if
        nothing is reserved (e.g. target failed before scheduling).
        """
        key = f"pvp:{target_id}"
        village_ids = set()
        if data.get("clear_village_id"):
            village_ids.add(str(data["clear_village_id"]))
        for vid in data.get("noble_villages") or []:
            village_ids.add(str(vid))
        for vid in village_ids:
            village = self.villages.get(vid)
            if village and village.units and village.units.conquest_reserve.pop(key, None):
                logger.info(
                    "PvpConquest: released troop reservation for target %s from village %s",
                    target_id, vid
                )

    def _hunter_schedules_resolved(self, target_id):
        """
        Returns True once neither the clear nor the nobles Hunter schedule
        for this target still has a status of "pending" -- i.e. every
        attack in both has been sent or has failed. A schedule that was
        never created (e.g. no noble villages ended up available) counts
        as already resolved.

        Bugfix (2026-08-07, first pass): the dict key under which
        HunterReader.add_schedule actually stores a schedule is
        "{target_id}_{arrival_str}", NOT the bare "{target_id}_pvp_{label}"
        that used to be passed in as its `target_id` argument -- that value
        only ended up in the schedule's own "target_id" field, not as the
        cache dict key. A direct `schedules.get(...)` lookup by that bare
        string therefore never matched anything, which made this always
        return True (missing == "already resolved" by design) and release
        the PvP conquest troop reservation on the very next cycle, defeating
        its whole purpose. Fixed (at the time) to search by the "target_id"
        field on each stored schedule instead of the dict key.

        Bugfix (2026-08-07, second pass): that fix matched against
        "{target_id}_pvp_{label}", which was only ever a valid value to
        match against because _hunter_add_schedule() was, at the time,
        *storing* that same bogus string as the schedule's real
        "target_id" field -- which is also the field Hunter.run() uses to
        actually fire the attack (village.area.map_pos lookup,
        village.attack.attack() call). That meant every PvP-conquest
        schedule could never fire for real. Now that _hunter_add_schedule()
        stores the correct real target_id and puts "clear"/"nobles" in a
        separate "label" field instead (see its docstring), this needs to
        match on both fields together.
        """
        schedules = FileManager.load_json_file("cache/hunter/schedules.json") or {}
        for sched in schedules.values():
            if (
                str(sched.get("target_id")) == str(target_id)
                and sched.get("label") in ("clear", "nobles")
                and sched.get("status") == "pending"
            ):
                return False
        return True

    def _maybe_release_reserve(self, target_id, data):
        """
        Releases the troop reservation once it's safe: either the Hunter
        schedules built for this target have all resolved (sent/failed), or
        -- as a robustness fallback in case that check ever misses something
        -- the arrival window is long past. Only acts once per target
        (tracked via data["reserve_released"]) to avoid pointless repeated
        cache writes every cycle.
        """
        if data.get("reserve_released"):
            return
        arrival_ts = data.get("arrival_time")
        overdue = bool(arrival_ts) and (time.time() > arrival_ts + 3600)
        if not (self._hunter_schedules_resolved(target_id) or overdue):
            return
        self._release_reserve(target_id, data)
        data["reserve_released"] = True
        PvpConquestCache.set(target_id, data)
