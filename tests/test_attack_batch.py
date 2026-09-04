"""Feature 26: native multi-command batches from the rally point."""

import os
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game.attack import AttackManager
from game.hunter import Hunter


PRE_ATTACK_HTML = """
<form>
  <input type="hidden" name="token" value="pre-token">
</form>
"""

CONFIRM_HTML = """
<form id="command-data-form">
  <input type="hidden" name="attack" value="">
  <input type="hidden" name="ch" value="command-token">
  <input type="hidden" name="cb" value="">
  <input type="hidden" name="x" value="578">
  <input type="hidden" name="y" value="297">
  <input type="hidden" name="source_village" value="41123">
  <input type="hidden" name="village" value="42248">
  <input type="hidden" name="axe" value="98">
  <input type="hidden" name="snob" value="0">
  <input type="hidden" name="light" value="0">
  <input type="hidden" name="h" value="page-token">
</form>
<span class="relative_time" data-duration="9780">2:43:00</span>
"""


class Response:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code


class RecordingWrapper:
    def __init__(self, final_html="<html>Movimento de tropas</html>"):
        self.last_h = "wrapper-token"
        self.final_html = final_html
        self.gets = []
        self.posts = []
        self.api_actions = []

    def get_url(self, url):
        self.gets.append(url)
        return Response(PRE_ATTACK_HTML)

    def post_url(self, url, data):
        self.posts.append((url, dict(data)))
        if "try=confirm" in url:
            return Response(CONFIRM_HTML)
        return Response(self.final_html)

    def get_api_action(self, village_id, action, params=None, data=None):
        self.api_actions.append((village_id, action, params, dict(data or {})))
        return {"ok": True}


def attack_manager(wrapper=None):
    wrapper = wrapper or RecordingWrapper()
    troops = SimpleNamespace(
        troops={"axe": "1000", "light": "10", "snob": "4"}
    )
    map_obj = SimpleNamespace(map_pos={"42248": (578, 297)})
    return AttackManager(
        wrapper=wrapper,
        village_id="41123",
        troopmanager=troops,
        map=map_obj,
    )


def test_batch_uses_captured_action_and_train_numbering():
    wrapper = RecordingWrapper()
    manager = attack_manager(wrapper)

    result = manager.attack(
        "42248",
        troops={"axe": 98},
        additional_attacks=[{"axe": 98}, {"axe": 98, "snob": 1}],
    )

    assert result
    assert len(wrapper.posts) == 2
    final_url, payload = wrapper.posts[-1]
    assert final_url.endswith("screen=place&action=command")
    assert wrapper.api_actions == []

    # Attack #1 remains in the ordinary unprefixed fields.  The live form
    # proved that the first extra row starts at 2, not 1.
    assert payload["axe"] == "98"
    assert not any(key.startswith("train[1]") for key in payload)
    assert payload["train[2][axe]"] == 98
    assert payload["train[2][snob]"] == 0
    assert payload["train[2][light]"] == 0
    assert payload["train[3][axe]"] == 98
    assert payload["train[3][snob]"] == 1
    assert payload["h"] == "wrapper-token"


def test_single_attack_keeps_existing_ajax_path():
    wrapper = RecordingWrapper()
    manager = attack_manager(wrapper)

    result = manager.attack("42248", troops={"axe": 98})

    assert result == {"ok": True}
    assert len(wrapper.posts) == 1  # confirmation only
    assert wrapper.api_actions[0][1] == "popup_command"


def test_batch_is_not_posted_when_total_exceeds_available_troops():
    wrapper = RecordingWrapper()
    manager = attack_manager(wrapper)

    result = manager.attack(
        "42248",
        troops={"axe": 600},
        additional_attacks=[{"axe": 600}],
    )

    assert result is False
    assert manager.last_refusal == "batch requires more units than are available"
    assert len(wrapper.posts) == 1  # confirmation happened; final send did not


def _scheduled_attack(source, send_time, troops=None):
    return {
        "source_village_id": source,
        "troops": troops or {"axe": 98},
        "is_fake": False,
        "send_time": send_time,
        "status": "pending",
    }


def test_hunter_groups_only_same_source_and_send_time():
    now = time.time()
    attacks = [
        _scheduled_attack("41123", now + 0.1),
        _scheduled_attack("41123", now + 0.1),
        _scheduled_attack("99999", now + 0.7),
        _scheduled_attack("41123", now + 1.3),
    ]
    schedules = {
        "test": {
            "target_id": "42248",
            "arrival_time": now + 3600,
            "status": "pending",
            "attacks": attacks,
        }
    }

    hunter = Hunter(wrapper=SimpleNamespace(priority_mode=False))
    hunter._load_schedules = lambda: schedules
    saved = []
    hunter._save_schedules = lambda data: saved.append(data)
    calls = []
    hunter._send_attack_batch = lambda batch, target: calls.append(
        ([atk["source_village_id"] for atk in batch], target)
    ) or True

    hunter.run({"hunter": {"enabled": True}})

    assert [len(batch_sources) for batch_sources, _ in calls] == [2, 1, 1]
    assert all(target == "42248" for _, target in calls)
    assert schedules["test"]["status"] == "complete"
    assert all(atk["status"] == "sent" for atk in attacks)
    assert attacks[0]["batch_size"] == 2
    assert attacks[1]["batch_size"] == 2
    assert "batch_size" not in attacks[2]
    assert saved


class RecordingAttackManager:
    def __init__(self, result=True):
        self.result = result
        self.calls = []

    def attack(self, target_id, troops=None, additional_attacks=None):
        self.calls.append((target_id, troops, additional_attacks))
        return self.result


def test_hunter_batch_deducts_total_only_after_success():
    attack = RecordingAttackManager()
    units = SimpleNamespace(troops={"axe": "500", "snob": "4"})
    village = SimpleNamespace(attack=attack, units=units)
    hunter = Hunter()
    hunter.villages = {"41123": village}
    batch = [
        _scheduled_attack("41123", 0, {"axe": 100, "snob": 1}),
        _scheduled_attack("41123", 0, {"axe": 120, "snob": 1}),
    ]

    assert hunter._send_attack_batch(batch, "42248") is True
    assert attack.calls == [
        ("42248", {"axe": 100, "snob": 1}, [{"axe": 120, "snob": 1}])
    ]
    assert units.troops == {"axe": "280", "snob": "2"}


def test_hunter_batch_does_not_deduct_on_failure():
    attack = RecordingAttackManager(result=False)
    units = SimpleNamespace(troops={"axe": "500", "snob": "4"})
    hunter = Hunter()
    hunter.villages = {"41123": SimpleNamespace(attack=attack, units=units)}
    batch = [
        _scheduled_attack("41123", 0, {"axe": 100, "snob": 1}),
        _scheduled_attack("41123", 0, {"axe": 120, "snob": 1}),
    ]

    assert hunter._send_attack_batch(batch, "42248") is False
    assert units.troops == {"axe": "500", "snob": "4"}


def test_hunter_never_sends_after_send_time():
    now = time.time()
    attack = _scheduled_attack("41123", now - 0.01)
    schedules = {
        "late": {
            "target_id": "42248",
            "arrival_time": now + 3600,
            "status": "pending",
            "attacks": [attack],
        }
    }
    hunter = Hunter(wrapper=SimpleNamespace(priority_mode=False))
    hunter._load_schedules = lambda: schedules
    saved = []
    hunter._save_schedules = lambda data: saved.append(data)
    hunter._send_attack_batch = lambda *_args: (_ for _ in ()).throw(
        AssertionError("late attack was sent")
    )

    hunter.run({"hunter": {"enabled": True}})

    assert attack["status"] == "failed"
    assert attack["fail_reason"] == "send_time_missed"
    assert schedules["late"]["status"] == "failed"
    assert saved


def test_hunter_services_schedules_by_departure_not_file_order():
    now = time.time()
    schedules = {
        # Deliberately inserted in the wrong order.
        "later": {
            "target_id": "2",
            "arrival_time": now + 3600,
            "status": "pending",
            "attacks": [_scheduled_attack("41123", now + 0.3)],
        },
        "earlier": {
            "target_id": "1",
            "arrival_time": now + 3600,
            "status": "pending",
            "attacks": [_scheduled_attack("41123", now + 0.1)],
        },
    }
    hunter = Hunter(wrapper=SimpleNamespace(priority_mode=False))
    hunter._load_schedules = lambda: schedules
    hunter._save_schedules = lambda _data: None
    sent = []
    hunter._send_attack_batch = lambda _batch, target: sent.append(target) or True

    hunter.run({"hunter": {"enabled": True}})

    assert sent == ["1", "2"]


def test_farm_loop_services_hunter_between_targets():
    manager = AttackManager.__new__(AttackManager)
    manager.troopmanager = SimpleNamespace(can_attack=True, troops={"axe": "10"})
    manager.max_farms = 2
    manager.targets = []
    manager.get_targets = lambda: setattr(
        manager,
        "targets",
        [[{"id": "1"}, 1, 1], [{"id": "2"}, 2, 2]],
    )
    manager._ordered_templates = lambda _target_id: []
    checkpoints = []
    manager.hunter_service_callback = lambda: checkpoints.append(True)

    manager.run()

    assert len(checkpoints) == 2


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
