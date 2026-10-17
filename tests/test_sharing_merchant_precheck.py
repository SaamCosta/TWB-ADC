"""
Leitura de mercadores so quando ha envio possivel (docs/backend.md §8.63).

`run()` e `run_mint_route()` baixavam `screen=market&mode=send` (para ler os
mercadores livres) antes de saber se o plano tinha alvo. Em 4 ciclos de
15-16/10, 71 de 161 leituras terminaram sem envio. Os dois planejadores so
encolhem quando a carga encolhe, entao "vazio com carga ilimitada" prova
"vazio com qualquer carga" e o GET pode ser pulado.

Cobre: a propriedade de monotonia nos dois planejadores (o que torna o corte
seguro), e os dois caminhos sem e com GET. Nada escreve em `cache/`: as
gravacoes de remessa e de evento sao trocadas por no-op na instancia.

Rodar: python tests/test_sharing_merchant_precheck.py
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import game.resource_sharing as rs
from game import mint_planner
from game.resource_sharing import ResourceSharingManager, UNBOUNDED_CARRY

RES = ("wood", "stone", "iron")
COST = {"wood": 28000, "stone": 30000, "iron": 25000}


class _Resman:
    def __init__(self, actual, storage=400000):
        self.actual = dict(actual)
        self.storage = storage
        self.sent = []
        self.last_send_travel_seconds = 1800

    def send_resources(self, target_village_id, resources, target_coords):
        self.sent.append((target_village_id, dict(resources)))
        return True

    def in_need_amount(self, res):
        return 0


def _mgr(cfg=None):
    m = ResourceSharingManager(wrapper=None, current_village_id="1",
                               config={"resource_sharing": cfg or {"enabled": True, "min_send_amount": 1000}})
    m.budget_reads = 0

    def budget(_cfg):
        m.budget_reads += 1
        return 13000, 13, 1000
    m._get_carry_budget = budget
    m._load_pending = lambda: {}
    m._record_pending = lambda *a, **k: None
    m._log_event = lambda *a, **k: None
    return m


def _route(m, resman, hub_state, floor):
    orig = rs.FileManager.load_json_file
    rs.FileManager.load_json_file = staticmethod(lambda path: hub_state)
    try:
        m.run_mint_route(resman, {"hub": "2", "floor": floor, "fill_max_pct": 0.95})
    finally:
        rs.FileManager.load_json_file = orig


HUB = {"storage": 400000, "x": 500, "y": 500,
       "resources": {"wood": 10000, "stone": 10000, "iron": 10000}}


def test_rota_sem_sobra_acima_do_piso_nao_le_mercadores():
    m, resman = _mgr(), _Resman({"wood": 20000, "stone": 20000, "iron": 20000})
    _route(m, resman, HUB, floor=50000)
    assert m.budget_reads == 0 and resman.sent == []


def test_rota_com_hub_cheio_nao_le_mercadores():
    full = dict(HUB, resources={r: 390000 for r in RES})
    m, resman = _mgr(), _Resman({r: 200000 for r in RES})
    _route(m, resman, full, floor=0)
    assert m.budget_reads == 0 and resman.sent == []


def test_rota_com_sobra_le_mercadores_e_envia_dentro_da_carga_real():
    m, resman = _mgr(), _Resman({r: 200000 for r in RES})
    _route(m, resman, HUB, floor=50000)
    assert m.budget_reads == 1
    assert len(resman.sent) == 1 and sum(resman.sent[0][1].values()) == 13000, resman.sent


def test_run_sem_receptora_nao_le_mercadores():
    m = _mgr()
    m._load_all_village_states = lambda: {
        "1": {"storage": 400000},
        # sem mercado: nunca e receptora
        "2": {"storage": 400000, "x": 1, "y": 1, "buidling_levels": {}},
    }
    m._calculate_giveable = lambda resman, storage, cfg: ({"wood": 50000}, {"wood": 50000})
    m.run(_Resman({"wood": 300000}))
    assert m.budget_reads == 0


def test_run_com_receptora_le_mercadores():
    m = _mgr()
    m._load_all_village_states = lambda: {
        "1": {"storage": 400000},
        "2": {"storage": 400000, "x": 1, "y": 1, "buidling_levels": {"market": 5},
              "resources": {"wood": 1000}, "required_resources": {"building": {"wood": 20000}}},
    }
    m._calculate_giveable = lambda resman, storage, cfg: ({"wood": 50000}, {})
    resman = _Resman({"wood": 300000})
    m.run(resman)
    assert m.budget_reads == 1 and resman.sent, resman.sent


def test_monotonia_plan_route():
    rnd = random.Random(7)
    for _ in range(400):
        args = dict(
            donor_res={r: rnd.choice([0, 500, 3000, 90000]) for r in RES},
            floor=rnd.choice([0, 1000, 50000]),
            hub_res={r: rnd.choice([0, 100000, 379000]) for r in RES},
            hub_storage=400000,
            hub_inflight={r: rnd.choice([0, 5000]) for r in RES},
            cost=COST, fill_max_pct=0.95, min_send=1000,
        )
        if not mint_planner.plan_route(carry=UNBOUNDED_CARRY, per_merchant=1000, **args):
            for carry in (0, 999, 1000, 5000, 13000, 77000):
                for per in (500, 1000, 1500):
                    assert not mint_planner.plan_route(carry=carry, per_merchant=per, **args), args


def test_monotonia_build_plan():
    rnd = random.Random(11)
    m = _mgr()
    cfg = {"min_send_amount": 1000, "receiver_fill_max_pct": 90, "max_sends_per_cycle": 3}
    for _ in range(300):
        states = {}
        for vid in ("2", "3", "4"):
            states[vid] = {
                "storage": 400000, "x": 1, "y": 1,
                "buidling_levels": {"market": rnd.choice([0, 3])},
                "under_attack": rnd.random() < 0.2,
                "resources": {r: rnd.choice([0, 200000, 359000]) for r in RES},
                "required_resources": {"building": {r: rnd.choice([0, 0, 800, 30000]) for r in RES}},
                "points": rnd.randint(100, 9000),
            }
        giveable = {r: rnd.choice([0, 900, 5000, 80000]) for r in RES}
        overflow = {r: min(giveable[r], rnd.choice([0, 3000])) for r in RES}
        if not m._build_plan(states, giveable, overflow, cfg, UNBOUNDED_CARRY, 1000, {}):
            for carry in (0, 999, 1000, 4000, 13000):
                assert not m._build_plan(states, giveable, overflow, cfg, carry, 1000, {}), (states, giveable)


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
