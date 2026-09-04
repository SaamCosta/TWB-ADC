"""
Feature 10: Coordinated attack scheduler (Hunter).

Manages noble trains and fake attacks from multiple source villages
with simultaneous arrival at the target.

Schedule format in config.json under the "hunter" key:

  "hunter": {
    "enabled": true,
    "schedules": [
      {
        "target_id": "12345",
        "arrival_time": "2026-06-21 15:00:00",
        "attacks": [
          {"source_village_id": "111", "troops": {"axe": 5000, "snob": 1}, "is_fake": false},
          {"source_village_id": "222", "troops": {"axe": 5000, "snob": 1}, "is_fake": false},
          {"source_village_id": "333", "troops": {"axe": 3000},            "is_fake": true}
        ]
      }
    ]
  }

Runtime state is persisted in cache/hunter/schedules.json.
Each attack's send_time is computed by probing the confirm page so the
server's own travel-time calculation is used — no local formula needed.
"""

import datetime
import logging
import time

from core.extractors import Extractor
from core.filemanager import FileManager


class Hunter:
    SCHEDULE_CACHE = "cache/hunter/schedules.json"
    DATETIME_FMT = "%Y-%m-%d %H:%M:%S"

    # Seconds before send_time to enter priority mode and start monitoring
    window = 120
    PROBE_RETRY_SECONDS = 60

    def __init__(self, wrapper=None):
        self.wrapper = wrapper
        # Populated by twb.py each cycle: {village_id: Village}
        self.villages = {}
        self.logger = logging.getLogger("Hunter")

    # ------------------------------------------------------------------
    # Schedule persistence
    # ------------------------------------------------------------------

    def _load_schedules(self):
        return FileManager.load_json_file(self.SCHEDULE_CACHE) or {}

    def _save_schedules(self, schedules):
        FileManager.save_json_file(schedules, self.SCHEDULE_CACHE)

    # ------------------------------------------------------------------
    # Config → cache bootstrap
    # ------------------------------------------------------------------

    def build_schedules_from_config(self, config):
        """
        Reads hunter.schedules from config and writes to cache, probing
        travel durations to calculate exact per-attack send_times.

        - Deduplicates by (target_id, arrival_time) — safe to call every cycle.
        - Schedules whose arrival_time has already passed are skipped silently.
        - If a travel-duration probe fails, the attack is stored without a
          send_time and retried next cycle inside run().
        """
        cfg_schedules = config.get("hunter", {}).get("schedules", [])
        if not cfg_schedules:
            return

        cached = self._load_schedules()
        changed = False

        for entry in cfg_schedules:
            target_id = str(entry.get("target_id", ""))
            arrival_str = entry.get("arrival_time", "")
            if not target_id or not arrival_str:
                self.logger.warning("Hunter: schedule entry missing target_id or arrival_time, skipping")
                continue

            try:
                arrival_ts = datetime.datetime.strptime(
                    arrival_str, self.DATETIME_FMT
                ).timestamp()
            except ValueError:
                self.logger.error(
                    "Hunter: invalid arrival_time '%s' (expected %s), skipping",
                    arrival_str, self.DATETIME_FMT
                )
                continue

            if arrival_ts < time.time():
                self.logger.debug(
                    "Hunter: schedule for target %s at %s is in the past, skipping",
                    target_id, arrival_str
                )
                continue

            # Stable key: survives config reloads, avoids duplicates
            sched_key = f"{target_id}_{arrival_str.replace(' ', 'T')}"
            if sched_key in cached:
                continue  # already registered

            attacks = []
            for atk_cfg in entry.get("attacks", []):
                source_id = str(atk_cfg.get("source_village_id", ""))
                troops = atk_cfg.get("troops", {})
                is_fake = bool(atk_cfg.get("is_fake", False))

                if not source_id or not troops:
                    self.logger.warning(
                        "Hunter: attack entry missing source_village_id or troops, skipping"
                    )
                    continue

                send_time = None
                duration = self._probe_duration(source_id, target_id, troops)
                if duration is not None:
                    send_time = arrival_ts - duration
                    if send_time < time.time():
                        self.logger.warning(
                            "Hunter: send_time for %s -> %s already passed (%.0fs ago), skipping attack",
                            source_id, target_id, time.time() - send_time
                        )
                        continue
                    self.logger.info(
                        "Hunter: %s -> %s  travel=%.0fs  send_at=%s  [%s]",
                        source_id, target_id, duration,
                        datetime.datetime.fromtimestamp(send_time).strftime(self.DATETIME_FMT),
                        "FAKE" if is_fake else "REAL",
                    )
                else:
                    self.logger.warning(
                        "Hunter: could not probe duration %s -> %s, will retry next cycle",
                        source_id, target_id
                    )

                attacks.append({
                    "source_village_id": source_id,
                    "troops": troops,
                    "is_fake": is_fake,
                    "send_time": send_time,   # None until probed
                    "status": "pending",
                })

            if not attacks:
                self.logger.warning(
                    "Hunter: no valid attacks for schedule %s, skipping", sched_key
                )
                continue

            cached[sched_key] = {
                "target_id": target_id,
                "arrival_time": arrival_ts,
                "arrival_str": arrival_str,
                "status": "pending",
                "attacks": attacks,
            }
            changed = True
            self.logger.info(
                "Hunter: registered schedule %s — %d attack(s) against %s arriving %s",
                sched_key, len(attacks), target_id, arrival_str
            )

        if changed:
            self._save_schedules(cached)

    # ------------------------------------------------------------------
    # Main run — fires due attacks
    # ------------------------------------------------------------------

    def run(self, config):
        """
        Called once per TWB cycle (after the normal village loop).

        For each pending attack whose send_time is within `window` seconds:
          - Sleeps until exact send_time (blocks; priority_mode set on wrapper).
          - Fires the attack via the source village's AttackManager.
          - Deducts troops from TroopManager so farming stays accurate.

        Attacks with no send_time yet (probe failed last cycle) are retried here.
        """
        if not config.get("hunter", {}).get("enabled", False):
            return

        schedules = self._load_schedules()
        if not schedules:
            return

        now = time.time()
        changed = False

        # Resolve travel times for every schedule before choosing what to
        # service. Dict/file order is not chronological: PvP conquest writes
        # the clear schedule before the nobles schedule even though nobles
        # normally depart first. Sleeping on the first dict entry could miss a
        # more urgent command in a later entry.
        for sched_key, sched in schedules.items():
            if sched.get("status") != "pending":
                continue
            if sched.get("arrival_time", 0) < now:
                sched["status"] = "failed"
                changed = True
                continue
            target_id = sched["target_id"]
            for atk in sched.get("attacks", []):
                if atk.get("status") != "pending" or atk.get("send_time") is not None:
                    continue
                last_probe = float(atk.get("last_probe_attempt", 0) or 0)
                if time.time() - last_probe < self.PROBE_RETRY_SECONDS:
                    continue
                atk["last_probe_attempt"] = time.time()
                changed = True
                duration = self._probe_duration(
                    atk["source_village_id"], target_id, atk["troops"]
                )
                if duration is not None:
                    atk["send_time"] = sched["arrival_time"] - duration
                    changed = True

        def next_departure(item):
            _key, sched = item
            departures = [
                float(atk["send_time"])
                for atk in sched.get("attacks", [])
                if atk.get("status") == "pending" and atk.get("send_time") is not None
            ]
            return min(departures) if departures else float("inf")

        ordered_schedules = sorted(schedules.items(), key=next_departure)

        for sched_key, sched in ordered_schedules:
            if sched.get("status") != "pending":
                continue

            target_id = sched["target_id"]
            arrival_ts = sched["arrival_time"]

            if arrival_ts < now:
                self.logger.warning(
                    "Hunter: schedule %s arrival has passed without all attacks being sent — marking failed",
                    sched_key
                )
                sched["status"] = "failed"
                changed = True
                continue

            for atk in sorted(
                    sched["attacks"],
                    key=lambda item: (
                        float(item["send_time"])
                        if item.get("send_time") is not None else float("inf")
                    )):
                if atk["status"] != "pending":
                    continue

                send_time = atk.get("send_time")
                if send_time is None:
                    continue  # still can't probe, try next cycle

                time_to_send = send_time - time.time()

                # A coordinated operation is defined by its arrival time.
                # Sending after the computed departure cannot recover that
                # promise; it only creates a real, late attack.  This path is
                # deliberately strict -- even the explicit PvP scout override
                # never authorizes an expired departure.
                if time_to_send <= 0:
                    atk["status"] = "failed"
                    atk["fail_reason"] = "send_time_missed"
                    atk["missed_by_seconds"] = abs(float(time_to_send))
                    changed = True
                    self.logger.error(
                        "Hunter: refusing late attack %s -> %s; send_time passed %.3fs ago",
                        atk["source_village_id"], target_id, abs(float(time_to_send))
                    )
                    continue

                if time_to_send > self.window:
                    continue  # not our cycle yet

                # --- Within the send window ---
                if hasattr(self.wrapper, "priority_mode"):
                    self.wrapper.priority_mode = True
                if time_to_send > 0:
                    label = "FAKE" if atk.get("is_fake") else "REAL"
                    self.logger.info(
                        "Hunter: [%s] %s -> %s — sleeping %.1fs to hit send_time",
                        label, atk["source_village_id"], target_id, time_to_send
                    )
                    time.sleep(time_to_send)

                # Feature 26: commands with the same source, target and send
                # time can use the game's native train form.  Different troop
                # compositions often have different travel durations; those
                # intentionally remain separate so they still converge on the
                # requested arrival time.
                batch = [
                    candidate for candidate in sched["attacks"]
                    if candidate.get("status") == "pending"
                    and str(candidate.get("source_village_id"))
                    == str(atk.get("source_village_id"))
                    and candidate.get("send_time") is not None
                    and abs(float(candidate["send_time"]) - float(send_time)) < 0.5
                ]

                if len(batch) > 1:
                    self.logger.info(
                        "Hunter: batching %d attacks %s -> %s at one send time",
                        len(batch), atk["source_village_id"], target_id
                    )

                result = self._send_attack_batch(batch, target_id)
                sent_at = int(time.time())
                for batch_atk in batch:
                    batch_atk["status"] = "sent" if result else "failed"
                    batch_atk["sent_at"] = sent_at
                    if len(batch) > 1:
                        batch_atk["batch_size"] = len(batch)
                changed = True

                for batch_atk in batch:
                    label = "FAKE" if batch_atk.get("is_fake") else "REAL"
                    self.logger.info(
                        "Hunter: [%s] %s -> %s — %s%s",
                        label, batch_atk["source_village_id"], target_id,
                        "OK" if result else "FAILED",
                        " (batch)" if len(batch) > 1 else "",
                    )

            if hasattr(self.wrapper, "priority_mode"):
                self.wrapper.priority_mode = False

            pending = [a for a in sched["attacks"] if a["status"] == "pending"]
            if not pending:
                failed = any(a.get("status") == "failed" for a in sched["attacks"])
                sched["status"] = "failed" if failed else "complete"
                self.logger.info(
                    "Hunter: schedule %s %s",
                    sched_key, "failed" if failed else "complete"
                )
                changed = True

        if changed:
            self._save_schedules(schedules)

    # ------------------------------------------------------------------
    # Sleep adjuster (called by twb.py before time.sleep)
    # ------------------------------------------------------------------

    def nearest_send_time(self):
        """
        Returns the nearest pending send_time across all schedules, or None.
        twb.py uses this to shorten the inter-cycle sleep so we wake up in
        time to enter the send window.
        """
        schedules = self._load_schedules()
        nearest = None
        for sched in schedules.values():
            if sched.get("status") != "pending":
                continue
            for atk in sched.get("attacks", []):
                if atk.get("status") != "pending":
                    continue
                st = atk.get("send_time")
                if st and (nearest is None or st < nearest):
                    nearest = st
        return nearest

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _probe_duration(self, source_id, target_id, troops):
        """
        Posts to the confirm page to read the server-computed travel duration.
        Returns seconds (float) or None on failure.
        """
        source_id = str(source_id)
        village = self.villages.get(source_id)
        if not village or not village.area:
            self.logger.debug(
                "Hunter: village %s not ready for duration probe (no area)", source_id
            )
            return None

        if target_id not in village.area.map_pos:
            self.logger.warning(
                "Hunter: target %s not in map_pos for village %s", target_id, source_id
            )
            return None

        url = f"game.php?village={source_id}&screen=place&target={target_id}"
        try:
            pre = self.wrapper.get_url(url)
        except Exception as e:
            self.logger.error("Hunter: probe GET failed: %s", e)
            return None
        if pre is None:
            self.logger.warning("Hunter: probe GET timed out for %s -> %s", source_id, target_id)
            return None

        pre_data = {}
        for k, v in Extractor.attack_form(pre):
            pre_data[k] = v
        pre_data.update(troops)

        x, y = village.area.map_pos[target_id]
        pre_data.update({"x": x, "y": y, "target_type": "coord", "attack": "Aanvallen"})

        confirm_url = f"game.php?village={source_id}&screen=place&try=confirm"
        try:
            conf = self.wrapper.post_url(url=confirm_url, data=pre_data)
        except Exception as e:
            self.logger.error("Hunter: probe POST failed: %s", e)
            return None
        if conf is None:
            self.logger.warning("Hunter: probe POST timed out for %s -> %s", source_id, target_id)
            return None

        if '<div class="error_box">' in conf.text:
            # Logava que houve error_box, nao o que ele dizia -- e a sonda do
            # Hunter existe justamente para descobrir por que um envio nao
            # sairia. Ver Extractor.error_box_text.
            self.logger.warning(
                "Hunter: probe %s -> %s recusada pelo jogo: %s",
                source_id, target_id, Extractor.error_box_text(conf)
            )
            return None

        return Extractor.attack_duration(conf)

    def _send_attack(self, atk, target_id):
        """
        Fires a single attack via the source village's AttackManager.
        Deducts sent troops from TroopManager immediately.
        """
        return self._send_attack_batch([atk], target_id)

    def _send_attack_batch(self, attacks, target_id):
        """
        Fires one or more simultaneous attacks from the same source village.

        A one-item list preserves the old single-command path.  With multiple
        items, AttackManager sends the first command normally and the rest as
        the native ``train[2..N]`` fields captured on br143.  Troops are only
        deducted after the server accepts the whole request.
        """
        if not attacks:
            return False

        source_id = str(attacks[0]["source_village_id"])
        if any(str(atk["source_village_id"]) != source_id for atk in attacks):
            self.logger.error(
                "Hunter: refusing mixed-source batch for target %s", target_id
            )
            return False

        village = self.villages.get(source_id)
        if not village:
            self.logger.error("Hunter: village %s not in managed villages dict", source_id)
            return False
        if not village.attack:
            self.logger.error("Hunter: village %s has no attack manager initialised", source_id)
            return False

        primary_troops = attacks[0]["troops"]
        additional = [atk["troops"] for atk in attacks[1:]]
        if additional:
            result = village.attack.attack(
                target_id,
                troops=primary_troops,
                additional_attacks=additional,
            )
        else:
            # Keep the old call shape for ordinary attacks and for lightweight
            # AttackManager substitutes used by integrations/tests.
            result = village.attack.attack(target_id, troops=primary_troops)
        if result and result != "forced_peace":
            # Keep TroopManager in sync so farming doesn't over-commit
            if village.units:
                sent = {}
                for atk in attacks:
                    for unit, qty in atk["troops"].items():
                        sent[unit] = sent.get(unit, 0) + int(qty)
                for unit, qty in sent.items():
                    current = int(village.units.troops.get(unit, 0))
                    village.units.troops[unit] = str(max(0, current - int(qty)))
            return True

        if result == "forced_peace":
            self.logger.warning(
                "Hunter: attack %s -> %s blocked by forced peace", source_id, target_id
            )
        return False
