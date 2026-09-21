"""Regression tests for the PvP-conquest "wait for the army to come home" stage.

Background (2026-09-21, target #44155).  `_build_clear_units()` reads
`units.troops` -- what is standing in the village right now -- so the
viability simulation was decided against whatever had not been sent out
farming.  Suspending farm and gather stops *new* departures but cannot recall
troops already in the air, and the old flow simulated immediately, so the
operation was closed as `simulation_failed` with 3% of the army home.

The numbers in test_the_real_44155_snapshot_would_have_held() are the real
ones, read from cache/managed/39472.json and cache/pvp_conquest/44155.json.

Run: python tests/test_pvp_troop_wait.py
"""

import os
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game.pvp_conquest import FileManager, PvpConquestCache, PvpConquestManager


def _village(home, owned):
    return SimpleNamespace(
        units=SimpleNamespace(troops=dict(home), total_troops=dict(owned)),
        area=SimpleNamespace(map_pos={"900": (500, 500)}),
    )


def _manager(villages=None, **cfg):
    manager = PvpConquestManager.__new__(PvpConquestManager)
    base = {
        "enabled": True,
        "troops_home_ratio": 0.9,
        "max_troop_wait_hours": 6,
        "sim_lead_seconds": 1800,
    }
    base.update(cfg)
    manager.config = {"pvp_conquest": base, "villages": {}}
    manager.villages = villages or {}
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


def _no_managed_cache(fn):
    """cache/managed lookups must not reach the real cache during tests."""
    original = FileManager.load_json_file
    FileManager.load_json_file = lambda path: {}
    try:
        fn()
    finally:
        FileManager.load_json_file = original


# ---------------------------------------------------------------------------
# Population accounting
# ---------------------------------------------------------------------------

def test_population_weights_units_and_ignores_non_combat():
    man = PvpConquestManager
    # light = 4 pop, ram = 5 pop, axe = 1 pop
    assert man._population({"axe": 10, "light": 10, "ram": 10}) == 10 + 40 + 50
    # Spies, nobles and the Paladin never join the clear wave or the escorts,
    # so having them home says nothing about readiness.
    assert man._population({"spy": 100, "snob": 5, "knight": 1}) == 0
    assert man._population({}) == 0
    assert man._population(None) == 0
    # Counts arrive as strings from the managed-cache snapshot.
    assert man._population({"axe": "10"}) == 10


# ---------------------------------------------------------------------------
# Measuring how much of the army is home
# ---------------------------------------------------------------------------

def test_ratio_is_none_when_nothing_could_be_measured():
    # None is not 0.0: "no source village had readable troop data" must stay
    # distinguishable from "measured, and the army really is all out".
    def exercise():
        manager = _manager(villages={})
        ratio, sources = manager._home_troop_ratio(
            {"clear_village_id": "100", "noble_villages": ["200"]}
        )
        assert ratio is None
        assert sources == []

    _no_managed_cache(exercise)


def test_ratio_counts_every_distinct_source_once():
    def exercise():
        villages = {
            "100": _village({"axe": 100}, {"axe": 100}),   # all home
            "200": _village({"axe": 0}, {"axe": 100}),     # all out
        }
        manager = _manager(villages)
        ratio, sources = manager._home_troop_ratio({
            "clear_village_id": "100",
            # 200 repeats: one entry per noble attack, not per village.
            "noble_villages": ["200", "200", "100"],
        })
        assert ratio == 0.5
        assert [s["village_id"] for s in sources] == ["100", "200"]
        assert sources[0]["pct"] == 100.0
        assert sources[1]["pct"] == 0.0

    _no_managed_cache(exercise)


def test_owned_total_falls_back_to_managed_cache():
    # TroopManager.update_totals() returns before filling total_troops when
    # can_recruit is false, so an empty dict means "not read", not "no army".
    villages = {"100": _village({"axe": 50}, {})}
    manager = _manager(villages)
    original = FileManager.load_json_file
    FileManager.load_json_file = lambda path: (
        {"troops": {"axe": "200"}} if path == "cache/managed/100.json" else {}
    )
    try:
        ratio, sources = manager._home_troop_ratio({"clear_village_id": "100"})
    finally:
        FileManager.load_json_file = original
    assert ratio == 0.25
    assert sources[0]["total_pop"] == 200


def test_home_never_exceeds_owned():
    # The two numbers come from different reads of the game; support troops
    # parked in the village can make "home" the larger one, which would put
    # the ratio above 1.0 and silently satisfy any threshold.
    def exercise():
        villages = {"100": _village({"axe": 500}, {"axe": 100})}
        manager = _manager(villages)
        ratio, _ = manager._home_troop_ratio({"clear_village_id": "100"})
        assert ratio == 1.0

    _no_managed_cache(exercise)


# ---------------------------------------------------------------------------
# The stage itself
# ---------------------------------------------------------------------------

def _run_step(manager, data, target_id="900"):
    result = {}

    def exercise(writes):
        manager._step_wait_troops(target_id, data)
        result["writes"] = writes

    _no_managed_cache(lambda: _capture_cache_writes(exercise))
    return result["writes"]


def test_holds_while_the_army_is_still_out():
    villages = {"100": _village({"axe": 100}, {"axe": 1000})}
    manager = _manager(villages)
    data = {"status": "pending_troops", "clear_village_id": "100"}

    _run_step(manager, data)

    assert data["status"] == "pending_troops"
    assert data["troops_home_pct"] == 10.0
    assert data["troop_wait_started_at"]


def test_advances_once_the_army_is_home():
    villages = {"100": _village({"axe": 950}, {"axe": 1000})}
    manager = _manager(villages)
    data = {"status": "pending_troops", "clear_village_id": "100"}

    _run_step(manager, data)

    assert data["status"] == "pending_sim"
    assert data["troops_wait_forced_reason"] is None


def test_the_threshold_is_configurable():
    villages = {"100": _village({"axe": 500}, {"axe": 1000})}
    manager = _manager(villages, troops_home_ratio=0.5)
    data = {"status": "pending_troops", "clear_village_id": "100"}

    _run_step(manager, data)

    assert data["status"] == "pending_sim"


def test_departure_deadline_ends_the_wait_early():
    # Waiting past this point is worse than simulating with a thin army: the
    # schedule would miss the departure and _fail_if_scout_deadline_missed()
    # would close the target outright.
    villages = {"100": _village({"axe": 10}, {"axe": 1000})}
    manager = _manager(villages)
    data = {
        "status": "pending_troops",
        "clear_village_id": "100",
        "first_send_time": time.time() + 600,   # inside the 1800s lead
    }

    _run_step(manager, data)

    assert data["status"] == "pending_sim"
    assert data["troops_wait_forced_reason"] == "prazo de saída próximo"


def test_a_distant_departure_does_not_end_the_wait():
    villages = {"100": _village({"axe": 10}, {"axe": 1000})}
    manager = _manager(villages)
    data = {
        "status": "pending_troops",
        "clear_village_id": "100",
        "first_send_time": time.time() + 7200,
    }

    _run_step(manager, data)

    assert data["status"] == "pending_troops"


def test_the_wait_is_capped():
    # Troops that never come back (dead, or sitting as support elsewhere) must
    # not hold an operation open forever.
    villages = {"100": _village({"axe": 10}, {"axe": 1000})}
    manager = _manager(villages, max_troop_wait_hours=1)
    data = {
        "status": "pending_troops",
        "clear_village_id": "100",
        "troop_wait_started_at": int(time.time()) - 3601,
    }

    _run_step(manager, data)

    assert data["status"] == "pending_sim"
    assert data["troops_wait_forced_reason"] == "teto de espera atingido"


def test_missing_troop_data_waits_but_still_respects_the_deadline():
    def exercise():
        manager = _manager(villages={})
        data = {"status": "pending_troops", "clear_village_id": "100"}
        _capture_cache_writes(lambda _w: manager._step_wait_troops("900", data))
        assert data["status"] == "pending_troops"

        manager = _manager(villages={})
        data = {
            "status": "pending_troops",
            "clear_village_id": "100",
            "first_send_time": time.time() + 60,
        }
        _capture_cache_writes(lambda _w: manager._step_wait_troops("900", data))
        assert data["status"] == "pending_sim"
        assert data["troops_wait_forced_reason"] == "sem dados de tropa"

    _no_managed_cache(exercise)


def test_the_real_44155_snapshot_would_have_held():
    # BBM 018 (#39472) as read at 14:20 on 2026-09-21: 46 axes and 16 light
    # cavalry at home out of 1486 and 739 owned, the rest out farming.  The
    # old code simulated this and wrote fail_reason "simulation_failed".
    villages = {
        "39472": _village(
            {"axe": 46, "spy": 59, "light": 16, "ram": 120},
            {"axe": 1486, "spy": 59, "light": 739, "ram": 120, "spear": 152},
        )
    }
    manager = _manager(villages)
    data = {"status": "pending_troops", "clear_village_id": "39472"}

    _run_step(manager, data)

    assert data["status"] == "pending_troops"
    assert data["troops_home_pct"] < 25


# ---------------------------------------------------------------------------
# Wiring: the stage has to keep farm/gather suspended, and be reachable
# ---------------------------------------------------------------------------

def test_the_new_stage_keeps_routine_troop_spending_suspended():
    # If pending_troops were missing here the bot would happily farm away the
    # very army the stage is waiting for.
    assert "pending_troops" in PvpConquestManager.FARM_SUSPEND_STATUSES
    assert "pending_troops" in PvpConquestManager.PREPARING_STATUSES


def test_scout_hands_over_to_the_troop_wait_not_straight_to_the_simulator():
    def exercise(_writes):
        manager = _manager()
        manager._find_scout_report = lambda target_id: {"type": "scout"}
        data = {"status": "pending_scout"}
        manager._step_scout("900", data)
        assert data["status"] == "pending_troops"

        manager = _manager()
        manager._find_scout_report = lambda target_id: None
        data = {"status": "pending_scout", "scout_override": True}
        manager._step_scout("900", data)
        assert data["status"] == "pending_troops"

    _capture_cache_writes(exercise)


def test_run_can_chain_scout_wait_and_simulate_in_one_call():
    # MAX_STEPS_PER_CALL has to have room for the extra stage, otherwise a
    # target that is ready to go all the way loses a whole cycle.
    assert PvpConquestManager.MAX_STEPS_PER_CALL >= 5


TESTS = [
    test_population_weights_units_and_ignores_non_combat,
    test_ratio_is_none_when_nothing_could_be_measured,
    test_ratio_counts_every_distinct_source_once,
    test_owned_total_falls_back_to_managed_cache,
    test_home_never_exceeds_owned,
    test_holds_while_the_army_is_still_out,
    test_advances_once_the_army_is_home,
    test_the_threshold_is_configurable,
    test_departure_deadline_ends_the_wait_early,
    test_a_distant_departure_does_not_end_the_wait,
    test_the_wait_is_capped,
    test_missing_troop_data_waits_but_still_respects_the_deadline,
    test_the_real_44155_snapshot_would_have_held,
    test_the_new_stage_keeps_routine_troop_spending_suspended,
    test_scout_hands_over_to_the_troop_wait_not_straight_to_the_simulator,
    test_run_can_chain_scout_wait_and_simulate_in_one_call,
]


if __name__ == "__main__":
    for test in TESTS:
        test()
        print("ok %s" % test.__name__)
    print("%d passed" % len(TESTS))
