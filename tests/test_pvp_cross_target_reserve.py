"""Regression tests for §6.4 of docs/backend.md: PvP troop overcommit.

Until 2026-09-22 every PvP composition step read `units.troops` raw, so a
second target simulated and scheduled against troops a first target (or the
barbarian noble train) had already reserved, and the escort floor
`max(1, ...)` asked for one unit of every type per noble even when the village
had fewer than that.  Whichever Hunter command fired second would be refused
by the server, hours after the decision.

Pure logic, no network, no real cache: the Hunter file and the target cache
are replaced by fixtures.

Run: python tests/test_pvp_cross_target_reserve.py
"""

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game.pvp_conquest import FileManager, PvpConquestManager


def _village(reserve=None, **troops):
    return SimpleNamespace(
        units=SimpleNamespace(troops=dict(troops), conquest_reserve=dict(reserve or {})),
        area=SimpleNamespace(map_pos={}),
    )


def _manager(villages, **cfg):
    manager = PvpConquestManager.__new__(PvpConquestManager)
    manager.config = {
        "pvp_conquest": {"enabled": True, "clear_ratio": 0.8, **cfg},
        "conquest": {"escort_ratio": 0.5},
        "villages": {},
    }
    manager.villages = villages
    manager.farm_suspended_villages = set()
    manager._active_targets = {}
    return manager


def _sum_by_village(attacks):
    totals = {}
    for atk in attacks:
        bucket = totals.setdefault(atk["source_village_id"], {})
        for unit, qty in atk["troops"].items():
            bucket[unit] = bucket.get(unit, 0) + qty
    return totals


def test_clear_skips_troops_reserved_by_another_target():
    village = _village(
        reserve={"pvp:A": {"axe": 800, "light": 100}}, axe=1000, light=100
    )
    manager = _manager({"100": village})
    clear = manager._build_clear_units(village, target_id="B")
    # 200 axes free -> 80% = 160; light fully reserved -> absent.
    assert clear == {"axe": 160}, clear


def test_own_reservation_is_not_counted_against_itself():
    village = _village(reserve={"pvp:B": {"axe": 800}}, axe=1000)
    manager = _manager({"100": village})
    assert manager._build_clear_units(village, target_id="B") == {"axe": 800}


def test_barbarian_train_reserve_is_respected():
    village = _village(
        reserve={"barbarian_conquest": {"axe": 500, "snob": 1}}, axe=1000, snob=2
    )
    manager = _manager({"100": village})
    assert manager._build_clear_units(village, target_id="B") == {"axe": 400}
    assert manager._select_noble_attack_plan(4, "B") == ["100"]


def test_escort_never_exceeds_what_the_village_has():
    # The §6.4 case: 2 rams, ratio 0.5, 4 nobles from one village.  Old code
    # asked max(1, 1 // 4) = 1 ram per attack -> 4 rams out of 2.
    village = _village(ram=2, axe=1000, snob=4)
    manager = _manager({"100": village})
    attacks = manager._build_noble_attacks(
        "999", {}, ["100"] * 4, escort_ratio=0.5, noble_count=4, target_id="B"
    )
    totals = _sum_by_village(attacks)["100"]
    assert totals["ram"] <= 1, totals  # budget = int(2 * 0.5)
    assert totals["axe"] == 500, totals
    assert totals["snob"] == 4
    assert all(atk["troops"]["snob"] == 1 for atk in attacks)


def test_escort_of_clear_village_adds_up_to_at_most_everything():
    village = _village(axe=1000, light=3, snob=2)
    manager = _manager({"100": village})
    clear = manager._build_clear_units(village, target_id="B")
    attacks = manager._build_noble_attacks(
        "100", clear, ["100", "100"], target_id="B"
    )
    escort = _sum_by_village(attacks)["100"]
    for unit, have in village.units.troops.items():
        if unit == "snob":
            continue
        assert clear.get(unit, 0) + escort.get(unit, 0) <= have, (unit, clear, escort)


def test_escort_uses_only_free_troops():
    village = _village(reserve={"pvp:A": {"axe": 600}}, axe=1000, snob=1)
    manager = _manager({"100": village})
    attacks = manager._build_noble_attacks(
        "999", {}, ["100"], noble_count=1, target_id="B"
    )
    assert attacks[0]["troops"]["axe"] == 200  # (1000 - 600) * 0.5


def test_noble_plan_skips_nobles_locked_by_a_preparing_target():
    villages = {"100": _village(snob=2), "200": _village(snob=2)}
    manager = _manager(villages)
    manager._active_targets = {
        "A": {"status": "pending_scout", "noble_villages": ["100", "100"]},
        "B": {"status": "pending_scout"},
    }
    assert manager._select_noble_attack_plan(4, "B") == ["200", "200"]
    # The target never counts its own lock against itself.
    assert manager._select_noble_attack_plan(4, "A") == ["100", "100", "200", "200"]


def test_scheduled_target_is_counted_once_not_twice():
    # Scheduled: nobles already in the in-memory reserve; the cache lock of a
    # scheduled target must not be subtracted a second time.
    villages = {"100": _village(reserve={"pvp:A": {"snob": 1}}, snob=3)}
    manager = _manager(villages)
    manager._active_targets = {
        "A": {"status": "scheduled", "noble_villages": ["100"]},
    }
    assert manager._select_noble_attack_plan(4, "B") == ["100", "100"]


def test_clear_ranking_uses_free_army():
    villages = {
        "100": _village(reserve={"pvp:A": {"light": 900}}, light=1000),
        "200": _village(light=300),
    }
    manager = _manager(villages)
    assert manager._select_clear_village("B") == "200"
    assert manager._select_clear_village("A") == "100"


def _with_schedules(schedules, fn):
    original = FileManager.load_json_file
    FileManager.load_json_file = lambda path: (
        schedules if path == "cache/hunter/schedules.json" else {}
    )
    try:
        fn()
    finally:
        FileManager.load_json_file = original


def test_restart_rebuilds_reserve_from_pending_hunter_commands():
    villages = {"100": _village(axe=1000, snob=2), "200": _village(axe=50, snob=1)}
    manager = _manager(villages)
    schedules = {
        "A_clear": {"target_id": "A", "label": "clear", "status": "pending",
                    "attacks": [{"source_village_id": "100", "status": "pending",
                                 "troops": {"axe": 800}}]},
        "A_nobles": {"target_id": "A", "label": "nobles", "status": "pending",
                     "attacks": [
                         {"source_village_id": "100", "status": "pending",
                          "troops": {"axe": 100, "snob": 1}},
                         {"source_village_id": "200", "status": "sent",
                          "troops": {"axe": 25, "snob": 1}},
                     ]},
    }
    targets = {"A": {"status": "scheduled"}}

    def exercise():
        villages["200"].units.conquest_reserve["pvp:A"] = {"axe": 25, "snob": 1}
        manager._sync_scheduled_reserves(targets)
        assert villages["100"].units.conquest_reserve["pvp:A"] == {"axe": 900, "snob": 1}
        # 200's command already left: its troops are not at home any more.
        assert "pvp:A" not in villages["200"].units.conquest_reserve
        # And a second target now sees only the free remainder.
        assert manager._build_clear_units(villages["100"], "B") == {"axe": 80}

    _with_schedules(schedules, exercise)


def test_unreadable_hunter_file_keeps_memory_reserve():
    villages = {"100": _village(reserve={"pvp:A": {"axe": 800}}, axe=1000)}
    manager = _manager(villages)

    def exercise():
        manager._sync_scheduled_reserves({"A": {"status": "scheduled"}})
        assert villages["100"].units.conquest_reserve["pvp:A"] == {"axe": 800}

    _with_schedules(None, exercise)
    _with_schedules({}, exercise)
    # A file without this target's schedules leaves it alone too.
    _with_schedules({"x": {"target_id": "Z", "label": "clear", "attacks": []}}, exercise)


def test_released_or_terminal_targets_are_not_rehydrated():
    villages = {"100": _village(axe=1000)}
    manager = _manager(villages)
    schedules = {"A": {"target_id": "A", "label": "clear", "attacks": [
        {"source_village_id": "100", "status": "pending", "troops": {"axe": 800}}]}}

    def exercise():
        manager._sync_scheduled_reserves({
            "A": {"status": "scheduled", "reserve_released": True},
        })
        manager._sync_scheduled_reserves({"A": {"status": "failed"}})
        assert villages["100"].units.conquest_reserve == {}

    _with_schedules(schedules, exercise)


def _simulate_with_fully_reserved_clear(arrival_offset):
    import time
    from game.pvp_conquest import PvpConquestCache
    village = _village(reserve={"pvp:A": {"axe": 1000}}, axe=1000, snob=1)
    manager = _manager({"100": village})
    manager._find_scout_report = lambda _t: None
    scheduled = []
    manager._hunter_add_schedule = lambda **kw: scheduled.append(kw)
    data = {
        "status": "pending_sim",
        "scout_override": True,
        "clear_village_id": "100",
        "noble_villages": ["100"],
        "arrival_time": time.time() + arrival_offset,
    }
    original = PvpConquestCache.set
    PvpConquestCache.set = lambda *_a: None
    try:
        manager._step_simulate("B", data)
    finally:
        PvpConquestCache.set = original
    return data, scheduled


def test_empty_clear_waits_instead_of_scheduling_nobles_alone():
    data, scheduled = _simulate_with_fully_reserved_clear(10000)
    assert data["status"] == "pending_sim", data
    assert scheduled == []


def test_empty_clear_fails_once_arrival_has_passed():
    data, scheduled = _simulate_with_fully_reserved_clear(-1)
    assert data["status"] == "failed"
    assert data["fail_reason"] == "no_free_clear_troops"
    assert scheduled == []


def test_old_floor_would_have_overcommitted():
    # Guard that the fixture really exercises the bug: the pre-2026-09-22
    # formula on the same numbers asks for more rams than exist.
    ram, ratio, nobles = 2, 0.5, 4
    old_total = nobles * max(1, int(ram * ratio) // nobles)
    assert old_total > ram


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
