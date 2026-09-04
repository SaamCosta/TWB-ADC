"""Regression tests for PvP-conquest source-village troop protection.

The protection begins before scouting/simulation, when no exact troop reserve
exists yet, and ends only when the target becomes terminal or Hunter resolves
the scheduled commands.

Run: python tests/test_pvp_farm_suspension.py
"""

import os
import sys
import tempfile
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game.pvp_conquest import FileManager, PvpConquestCache, PvpConquestManager
from game.village import Village
from webmanager.utils import PvpConquestReader


class _SilentLogger:
    def __getattr__(self, _name):
        return lambda *args, **kwargs: None


def _village(axe=0, light=0, snob=0):
    return SimpleNamespace(
        units=SimpleNamespace(
            troops={"axe": axe, "light": light, "snob": snob},
            conquest_reserve={},
        ),
        area=SimpleNamespace(map_pos={"900": (500, 500)}),
    )


def _manager():
    manager = PvpConquestManager.__new__(PvpConquestManager)
    manager.config = {
        "pvp_conquest": {"enabled": True, "nobles_per_target": 4},
        "villages": {
            "100": {"profile": "offensive"},
            "200": {"profile": "defensive"},
        },
    }
    manager.villages = {
        "100": _village(axe=1000, snob=2),
        "200": _village(light=700, snob=3),
    }
    manager.farm_suspended_villages = set()
    return manager


def _capture_cache_writes(fn):
    original = PvpConquestCache.set
    writes = []
    PvpConquestCache.set = lambda target_id, data: writes.append(
        (str(target_id), dict(data))
    )
    try:
        fn(writes)
    finally:
        PvpConquestCache.set = original


def test_sources_are_selected_and_locked_before_scout():
    def exercise(writes):
        manager = _manager()
        data = {"status": "pending_scout"}

        manager._prepare_source_locks("900", data)
        manager._sync_source_locks("900", data)

        # Offensive profile doubles village 100's proxy power, but village 200
        # still wins on 700 light cavalry.  Noble entries repeat because each
        # occurrence is one separate attack.
        assert data["clear_village_id"] == "200"
        assert data["noble_villages"] == ["100", "100", "200", "200"]
        assert data["farm_suspended_villages"] == ["100", "200"]
        assert manager.farm_suspended_villages == {"100", "200"}
        assert writes

    _capture_cache_writes(exercise)


def test_explicit_clear_is_normalized_and_preserved():
    def exercise(_writes):
        manager = _manager()
        data = {"status": "pending_sim", "clear_village_id": 100}
        manager._prepare_source_locks("900", data)
        manager._sync_source_locks("900", data)
        assert data["clear_village_id"] == "100"
        assert "100" in manager.farm_suspended_villages

    _capture_cache_writes(exercise)


def test_first_cycle_uses_managed_cache_for_not_yet_loaded_villages():
    manager = _manager()
    manager.villages["200"].units = None
    original = FileManager.load_json_file
    FileManager.load_json_file = lambda path: (
        {"available_troops": {"light": "700", "snob": "3"}}
        if path == "cache/managed/200.json" else {}
    )
    try:
        assert manager._select_clear_village() == "200"
        assert manager._select_noble_attack_plan(4) == ["100", "100", "200", "200"]
    finally:
        FileManager.load_json_file = original


def test_terminal_and_resolved_targets_release_source_locks():
    def exercise(_writes):
        manager = _manager()
        manager.farm_suspended_villages = {"old"}

        failed = {
            "status": "failed",
            "clear_village_id": "100",
            "noble_villages": ["200"],
            "farm_suspended_villages": ["100", "200"],
        }
        manager._sync_source_locks("900", failed)
        assert failed["farm_suspended_villages"] == []

        resolved = {
            "status": "scheduled",
            "reserve_released": True,
            "clear_village_id": "100",
            "noble_villages": ["200"],
            "farm_suspended_villages": ["100", "200"],
        }
        manager._sync_source_locks("901", resolved)
        assert resolved["farm_suspended_villages"] == []
        assert manager.farm_suspended_villages == {"old"}

    _capture_cache_writes(exercise)


def test_run_rebuilds_locks_when_target_is_deleted_or_feature_disabled():
    original_all = PvpConquestCache.all
    try:
        manager = _manager()
        manager.farm_suspended_villages = {"100"}
        PvpConquestCache.all = lambda: {}
        manager.run()
        assert manager.farm_suspended_villages == set()

        manager.farm_suspended_villages = {"200"}
        manager.config["pvp_conquest"]["enabled"] = False
        manager.run()
        assert manager.farm_suspended_villages == set()
    finally:
        PvpConquestCache.all = original_all


class _LockedVillage:
    village_id = "100"
    logger = _SilentLogger()
    config = {"conquest": {"enabled": True}}

    def _pvp_troop_spending_suspended(self):
        return True

    def __getattr__(self, name):
        raise AssertionError("locked path continued into %s" % name)


def test_locked_village_skips_all_routine_troop_spenders():
    village = _LockedVillage()
    assert Village.run_farming(village) is None
    assert Village.do_gather(village) is None
    assert Village.run_conquest(village) is None


def test_scout_report_expires_after_24_hours():
    manager = _manager()
    manager.config["pvp_conquest"]["scout_max_age_hours"] = 24
    now = time.time()
    fresh = {"type": "scout", "dest": "900"}
    manager._scout_report_index = lambda: {"900": (now - 86399, fresh)}
    assert manager._find_scout_report("900") is fresh

    manager._scout_report_index = lambda: {"900": (now - 86401, fresh)}
    assert manager._find_scout_report("900") is None


class _DeadlineProbe:
    def __init__(self):
        self.villages = {}

    def _probe_duration(self, source_id, target_id, troops):
        return 5000 if troops.get("snob") else 3600


def test_first_departure_is_probed_before_scout_arrives():
    def exercise(_writes):
        manager = _manager()
        manager.wrapper = None
        manager.config["conquest"] = {"escort_ratio": 0.5}
        manager._deadline_hunter = _DeadlineProbe()
        arrival = time.time() + 10000
        data = {
            "status": "pending_scout",
            "arrival_time": arrival,
            "clear_village_id": "100",
            "noble_villages": ["100", "100"],
        }
        manager._prepare_departure_deadlines("900", data)
        assert len(data["departure_deadlines"]) == 3
        assert data["first_send_time"] == arrival - 5000

    _capture_cache_writes(exercise)


def test_missing_scout_fails_at_first_departure_without_schedule():
    def exercise(_writes):
        manager = _manager()
        manager._find_scout_report = lambda _target_id: None
        data = {
            "status": "pending_sim",
            "first_send_time": time.time() - 1,
        }
        assert manager._fail_if_scout_deadline_missed("900", data) is True
        assert data["status"] == "failed"
        assert data["fail_reason"] == "scout_deadline_missed"

    _capture_cache_writes(exercise)


def test_manual_override_schedules_without_inventing_scout_data():
    def exercise(_writes):
        manager = _manager()
        manager.config["conquest"] = {"escort_ratio": 0.5}
        manager.sim = SimpleNamespace(
            attack_sum=lambda units: units,
            get_sum=lambda values: sum(values.values()),
        )
        manager._find_scout_report = lambda _target_id: None
        schedules = []
        manager._hunter_add_schedule = lambda **kwargs: schedules.append(kwargs)
        manager._reserve_troops = lambda *args: None
        data = {
            "status": "pending_sim",
            "arrival_time": time.time() + 10000,
            "clear_village_id": "100",
            "noble_villages": ["100", "100"],
            "scout_override": True,
        }

        manager._step_simulate("900", data)

        assert data["status"] == "scheduled"
        assert data["last_simulation"]["overridden"] is True
        assert [item["label"] for item in schedules] == ["clear", "nobles"]

    _capture_cache_writes(exercise)


def test_webmanager_override_refuses_an_expired_departure():
    original_dir = PvpConquestReader._dir
    with tempfile.TemporaryDirectory() as tmp:
        PvpConquestReader._dir = staticmethod(lambda: tmp)
        try:
            PvpConquestReader._save("900", {
                "status": "pending_scout",
                "first_send_time": time.time() - 1,
            })
            assert PvpConquestReader.set_scout_override("900") is False
            data = PvpConquestReader._load_all()["900"]
            assert data.get("scout_override") is not True
        finally:
            PvpConquestReader._dir = original_dir


def test_hunter_late_failure_immediately_fails_pvp_target():
    original_load = FileManager.load_json_file
    manager = _manager()
    released = []
    manager._release_reserve = lambda target_id, data: released.append(target_id)
    FileManager.load_json_file = lambda path: ({
        "schedule": {
            "target_id": "900",
            "label": "nobles",
            "status": "failed",
            "attacks": [{
                "status": "failed",
                "fail_reason": "send_time_missed",
            }],
        }
    } if path == "cache/hunter/schedules.json" else {})

    def exercise(_writes):
        data = {"status": "scheduled"}
        manager._step_check_complete("900", data)
        assert data["status"] == "failed"
        assert data["fail_reason"] == "hunter_schedule_failed"
        assert data["hunter_fail_reason"] == "send_time_missed"
        assert data["reserve_released"] is True
        assert released == ["900"]

    try:
        _capture_cache_writes(exercise)
    finally:
        FileManager.load_json_file = original_load


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok   %s" % name)
            except Exception as exc:
                failures += 1
                print("FALHA %s: %r" % (name, exc))
    sys.exit(1 if failures else 0)
