"""
Testes da Feature 30, refinamento de 2026-10-12: a torre nasce de um GRUPO de
aldeias descobertas, no centro dele (docs/backend.md §8.62).

Cobre:
  core/watchtower_plan.py        -- uncovered, clusters, pick_center, plan
  Village.needs_watchtower(...)  -- porta da heranca, com min_cluster
  Village.apply_watchtower_plan  -- passo global do ciclo (grava config.json)

O caso que motivou: a BBM 048 (531|289) caiu a 24,6 campos da aldeia propria
mais proxima e virou torre de si mesma. A 45215 (532|282), a 7,1 dela, chega
depois. Coordenadas reais do br143; nenhum teste toca disco ou rede.

Rodar: python tests/test_watchtower_cluster.py
"""
import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import watchtower_plan as wp
import game.village as _village_mod
from game.village import Village


def _v(x, y, profile="defensive", farm=20, points=1000):
    return {"x": x, "y": y, "profile": profile, "farm": farm, "points": points}


# Recorte real: BBM 023 e a torre mais proxima da regiao nova; BBM 026 e BBM
# 031 sao as vizinhas dela.
BASE = {
    "38412": _v(553, 300, "watchtower", farm=28, points=8337),  # BBM 023
    "39449": _v(565, 302),                                     # BBM 026
    "44167": _v(557, 293),                                     # BBM 031
}
BBM048 = ("40808", 531, 289)
ALVO2 = ("45215", 532, 282)


def _com(*extra, base=BASE):
    out = copy.deepcopy(base)
    for vid, x, y, *rest in extra:
        out[vid] = _v(x, y, *rest)
    return out


# --------------------------------------------------------------------------
# core/watchtower_plan
# --------------------------------------------------------------------------

def test_aldeia_sozinha_nao_vira_torre():
    """O caso da BBM 048: descoberta, mas sozinha -- nada a promover."""
    assert wp.plan(_com(BBM048), 16, 3) == []


def test_par_ainda_nao_basta():
    """Com a 45215 sao 2 -- abaixo de min_cluster=3."""
    vs = _com(BBM048, ALVO2)
    assert sorted(wp.uncovered(vs, 16)) == ["40808", "45215"]
    assert wp.plan(vs, 16, 3) == []


def test_terceira_promove_o_centro_nao_a_ultima():
    """A terceira (535|285) fica no meio; a ultima conquistada na ponta nao vira."""
    vs = _com(BBM048, ALVO2, ("90001", 535, 285))
    assert wp.plan(vs, 16, 3) == [("90001", ["40808", "45215", "90001"])]
    vs = _com(BBM048, ("90001", 535, 285), ("90002", 539, 281))
    # 90001 esta no meio da cadeia 40808 - 90001 - 90002.
    assert wp.plan(vs, 16, 3)[0][0] == "90001"


def test_min_cluster_1_e_a_regra_antiga():
    assert wp.plan(_com(BBM048), 16, 1) == [("40808", ["40808"])]


def test_coberta_nao_conta():
    """A BBM 026 esta a 12,2 da BBM 023: enxergada, fora de qualquer grupo."""
    assert "39449" not in wp.uncovered(_com(BBM048), 16)


def test_sem_torre_nenhuma_nao_planeja():
    """A primeira torre continua manual."""
    vs = {k: _v(500 + i, 500) for i, k in enumerate("abcde")}
    assert wp.plan(vs, 16, 3) == []


def test_ofensiva_so_se_nao_houver_outra():
    vs = _com(("a", 531, 289), ("b", 535, 285, "offensive"), ("c", 539, 281))
    center = wp.plan(vs, 16, 3)[0][0]
    assert center != "b"
    vs = _com(("a", 531, 289, "offensive"), ("b", 535, 285, "offensive"),
              ("c", 539, 281, "offensive"))
    assert wp.plan(vs, 16, 3)[0][0] == "b"


def test_empate_vai_para_a_mais_desenvolvida():
    """Quadrado: os quatro cantos tem o mesmo raio (5,66); vence a fazenda."""
    vs = _com(("a", 530, 280, "defensive", 10), ("b", 534, 280, "defensive", 25),
              ("c", 530, 284, "defensive", 10), ("d", 534, 284, "defensive", 10))
    assert wp.plan(vs, 16, 3) == [("b", ["a", "b", "c", "d"])]


def test_grupo_em_cadeia_longa_gera_mais_de_uma_torre():
    """Cadeia de 8 aldeias a 6 campos: uma torre no meio nao enxerga as pontas
    a >= 16, e as pontas que sobram (>= 3 juntas) ganham a delas."""
    extra = [("c%d" % i, 480 + 6 * i, 400) for i in range(10)]
    vs = _com(*extra)
    plan = wp.plan(vs, 16, 3)
    assert len(plan) >= 2
    towers = [vid for vid, _ in plan]
    assert len(set(towers)) == len(towers)


def test_ligacao_e_estrita():
    """Duas aldeias a exatamente min_spacing NAO se ligam (< link)."""
    vs = {"a": _v(0, 0), "b": _v(16, 0)}
    assert wp.clusters(["a", "b"], vs, 16) == [["a"], ["b"]]


# --------------------------------------------------------------------------
# Village.needs_watchtower / apply_watchtower_plan (FileManager stubado)
# --------------------------------------------------------------------------

_REAL_FM = _village_mod.FileManager


class _StubFM:
    def __init__(self, managed, config_on_disk=None):
        self.files = {"cache/managed/%s.json" % vid: {
            "x": v["x"], "y": v["y"], "points": v["points"],
            "buidling_levels": {"farm": v["farm"]},
        } for vid, v in managed.items()}
        if config_on_disk is not None:
            self.files["config.json"] = config_on_disk
        self.saved = None

    def load_json_file(self, path, *a, **kw):
        data = self.files.get(path)
        return copy.deepcopy(data) if data is not None else None

    def save_json_file(self, data, path):
        assert path == "config.json"
        self.saved = copy.deepcopy(data)

    def __getattr__(self, name):
        return getattr(_REAL_FM, name)


def _config(managed, min_cluster=3):
    return {
        "watchtower": {"enabled": True, "min_spacing": 16, "min_villages": 3,
                       "min_cluster": min_cluster},
        "profile_templates": {"watchtower": {"building": "watchtower_support",
                                             "snobs": 0, "mint_coins": True}},
        "villages": {vid: {"profile": v["profile"], "building": "def",
                           "snobs": 1} for vid, v in managed.items()},
    }


def _with_stub(stub, fn):
    _village_mod.FileManager = stub
    try:
        return fn()
    finally:
        _village_mod.FileManager = _REAL_FM


def test_heranca_aldeia_sozinha_recusa_e_explica():
    managed = _com()
    stub = _StubFM(managed)
    got, why = _with_stub(stub, lambda: Village.needs_watchtower(
        _config(managed), 531, 289, my_vid="40808"))
    assert got is False
    assert "min_cluster is 3" in why, why


def test_heranca_designa_quando_e_o_centro():
    managed = _com(BBM048, ("90002", 539, 281))
    stub = _StubFM(managed)
    got, why = _with_stub(stub, lambda: Village.needs_watchtower(
        _config(managed), 535, 285, my_vid="90001"))
    assert got is True, why


def test_heranca_nao_designa_quando_outra_e_o_centro():
    managed = _com(BBM048, ("90001", 535, 285))
    stub = _StubFM(managed)
    got, why = _with_stub(stub, lambda: Village.needs_watchtower(
        _config(managed), 539, 281, my_vid="90002"))
    assert got is False
    assert "another village is its center" in why, why


def test_passo_global_promove_e_grava_relendo():
    managed = _com(BBM048, ALVO2, ("90001", 535, 285))
    cfg = _config(managed)
    disk = copy.deepcopy(cfg)
    disk["villages"]["39449"]["nota"] = "gravado por outro durante o ciclo"
    stub = _StubFM(managed, config_on_disk=disk)
    done = _with_stub(stub, lambda: Village.apply_watchtower_plan(cfg))
    assert [vid for vid, _ in done] == ["90001"]
    entry = stub.saved["villages"]["90001"]
    assert entry["profile"] == "watchtower" and entry["snobs"] == 0
    assert entry["building"] == "watchtower_support" and entry["mint_coins"] is True
    # Releu antes de gravar: a mudanca alheia sobreviveu.
    assert stub.saved["villages"]["39449"]["nota"].startswith("gravado")
    # Copia em memoria atualizada (ZoneManager le dela logo em seguida).
    assert cfg["villages"]["90001"]["profile"] == "watchtower"


def test_passo_global_parado_com_par():
    managed = _com(BBM048, ALVO2)
    stub = _StubFM(managed, config_on_disk=_config(managed))
    assert _with_stub(stub, lambda: Village.apply_watchtower_plan(_config(managed))) == []
    assert stub.saved is None


def test_passo_global_respeita_min_cluster_1():
    """min_cluster=1 devolve a decisao so para a heranca (regra antiga)."""
    managed = _com(BBM048)
    stub = _StubFM(managed, config_on_disk=_config(managed, 1))
    assert _with_stub(stub, lambda: Village.apply_watchtower_plan(
        _config(managed, 1))) == []


if __name__ == "__main__":
    falhas = 0
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok   %s" % nome)
            except Exception as exc:
                falhas += 1
                print("FALHA %s: %r" % (nome, exc))
    sys.exit(1 if falhas else 0)
