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

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(self):
        cfg = self.config.get("pvp_conquest", {})
        if not cfg.get("enabled", False):
            return

        targets = PvpConquestCache.all()
        if not targets:
            return

        for target_id, data in targets.items():
            status = data.get("status", "pending_scout")
            try:
                if status == "pending_scout":
                    self._step_scout(target_id, data)
                elif status == "pending_sim":
                    self._step_simulate(target_id, data)
                elif status == "scheduled":
                    self._step_check_complete(target_id, data)
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

        # Build attacker dict using clear_ratio of available troops
        attacker_units = {
            unit: int(int(qty) * clear_ratio)
            for unit, qty in clear_village.units.troops.items()
            if int(qty) > 0
        }

        # Run simulator
        wall_level = scout_report.get("extra", {}).get("buildings", {}).get("wall", 0)
        try:
            sim_result = self.sim.simulate(
                attackerUnits=dict(attacker_units),
                defenderUnits=dict({u: int(q) for u, q in defender_units.items()}),
                wall=wall_level,
                nightbonus=False,
                moral=100,
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

        # Select noble villages (Feature 11b — auto-select all with snob > 0)
        noble_villages = data.get("noble_villages") or self._select_noble_villages(nobles_per_target)
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

        # Escort for nobles: reuse ConquestManager logic via config
        conquest_cfg = self.config.get("conquest", {})
        escort_ratio = conquest_cfg.get("escort_ratio", 0.5)
        escort_units = {
            unit: max(1, int(int(qty) * escort_ratio) // max(len(noble_villages), 1))
            for unit, qty in clear_village.units.troops.items()
            if int(qty) > 0 and unit not in ("spy", "snob")
        }

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
        noble_attacks = []
        for nvid in noble_villages:
            nv = self.villages.get(nvid)
            if not nv or not nv.units:
                continue
            troops = dict(escort_units)
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
        """
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

    def _select_noble_villages(self, max_count):
        """
        Feature 11b: auto-select all managed villages with snob > 0,
        up to max_count.
        """
        result = []
        for vid, village in self.villages.items():
            if not village.units:
                continue
            if int(village.units.troops.get("snob", 0)) > 0:
                result.append(vid)
            if len(result) >= max_count:
                break
        return result

    def _hunter_add_schedule(self, target_id, arrival_str, attacks, label=""):
        """
        Adds a schedule to cache/hunter/schedules.json via HunterReader.
        """
        try:
            from webmanager.utils import HunterReader
        except ImportError:
            try:
                from utils import HunterReader
            except ImportError:
                logger.error("PvpConquest: cannot import HunterReader")
                return

        # Unique key includes label so clear and nobles don't collide
        # HunterReader.add_schedule handles deduplication via sched_key
        # We create a slightly different arrival to distinguish schedules
        HunterReader.add_schedule(
            target_id=f"{target_id}_pvp_{label}",
            arrival_str=arrival_str,
            attacks=attacks,
        )
