"""
Relíquias, Fase 5 (docs/backend.md §8.80): o número que o bot lê da tela já
inclui o bônus da relíquia (17º padrão), e a conta do jogo, medida (19º).

Fixture `tests/fixtures/relic_effects_br143.json`: recortes verbatim do br143
de 30/10/2026 00:07-00:24, pelo `get_url` do WebWrapper do bot, de uma aldeia
COBERTA e de uma NÃO coberta na mesma tela e no mesmo nível de prédio:
- quartel 25 e estábulo 20: BBM 001 (41123: Quartel -10% custo, +20% velocidade
  das relíquias; Estábulo -8% e +5%) contra BBM 012 (41140, sem relíquia);
- academia: BBM 008 (41114, nobre -5%) contra BBM 012;
- edifício principal 20: BBM 002 (38409, +5% construção) contra BBM 022 (40618).

O que isto segura: `TroopManager.recruit`, `SnobManager.attempt_recruit` e
`BuildingManager` decidem com o custo e o tempo da tela, então nenhum deles
soma bônus de relíquia por conta própria. E o `RelicManager.note_unit_costs`
só guarda custo NOMINAL de aldeia sem desconto, porque a tela da coberta já
vem descontada.

Rodar: python tests/test_relic_effects.py
"""
import json
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.extractors import Extractor  # noqa: E402
from game import relic_manager as RM  # noqa: E402
from game.snobber import SnobManager  # noqa: E402

with open(os.path.join(ROOT, "tests", "fixtures", "relic_effects_br143.json"), encoding="utf-8") as fh:
    FIX = json.load(fh)

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


def _pct(row, pattern):
    m = re.search(pattern, FIX[row])
    return float(m.group(1)) / 100.0 if m else None


# As duas fontes de velocidade de recrutamento da BBM 001 que NÃO são relíquia,
# lidas do widget "Efeitos ativos" (fora dos totais `benefit`, §8.77).
MODIFICATION = _pct("effects_41123_modification", r"\+(\d+)% recrutamento mais r\S+pido no Quartel")
FLAG = _pct("effects_41123_flag", r"\+(\d+)% na velocidade de recrutamento")
RELIC_BARRACKS, RELIC_STABLE = 0.20, 0.05


def test_custo_de_recrutamento_ja_vem_com_desconto():
    for building, discount in (("barracks", 0.10), ("stable", 0.08)):
        covered = Extractor.recruit_data(FIX["%s_41123" % building])
        plain = Extractor.recruit_data(FIX["%s_41140" % building])
        check(covered and plain and set(covered) == set(plain), "%s: as duas telas lidas" % building)
        for unit, entry in (plain or {}).items():
            for res in ("wood", "stone", "iron"):
                want = int(round(entry[res] * (1 - discount)))
                check(covered[unit][res] == want,
                      "%s %s %s: %s, esperado %s" % (building, unit, res, covered[unit][res], want))
    check(Extractor.recruit_data(FIX["barracks_41140"])["spear"]["iron"] == 10,
          "lanceiro sem desconto custa 10 de ferro (o Simulator diz 20)")


def test_tempo_de_recrutamento_e_aditivo():
    check(MODIFICATION == 0.10 and FLAG == 0.06,
          "widget da BBM 001: modificação %r e bandeira %r" % (MODIFICATION, FLAG))
    plain = Extractor.recruit_data(FIX["barracks_41140"])
    # BBM 012 é a base neutra: lanceiro 1020 s x 2/3 x 1,06^-25 (quartel 25).
    check(abs(float(plain["spear"]["build_time"]) - 1020 * 2 / 3 * 1.06 ** -25) < 1e-6,
          "BBM 012 sem bônus de velocidade")
    for building, relic in (("barracks", RELIC_BARRACKS), ("stable", RELIC_STABLE)):
        extra = (MODIFICATION if building == "barracks" else 0.0) + FLAG
        covered = Extractor.recruit_data(FIX["%s_41123" % building])
        plain = Extractor.recruit_data(FIX["%s_41140" % building])
        for unit in plain:
            ratio = float(plain[unit]["build_time"]) / float(covered[unit]["build_time"])
            # tempo / (1 + soma): 1,36 no quartel, 1,11 no estábulo.
            check(abs(ratio - (1 + relic + extra)) < 1e-6,
                  "%s %s: razão %.6f, aditiva %.6f" % (building, unit, ratio, 1 + relic + extra))
            # As leituras rivais (19º padrão) erram por mais que o arredondamento.
            check(abs(ratio - (1 + relic) * (1 + extra)) > 1e-3, "%s %s: não é o produto" % (building, unit))
            check(abs(1 / ratio - (1 - relic - extra)) > 1e-3, "%s %s: não é x (1 - S)" % (building, unit))


def test_nobre_ja_vem_com_desconto():
    covered = SnobManager.next_snob_cost(FIX["snob_41114"])
    plain = SnobManager.next_snob_cost(FIX["snob_41140"])
    check(plain == {"wood": 40000, "stone": 50000, "iron": 50000}, "nobre sem desconto %r" % plain)
    check(covered == {r: int(v * 0.95) for r, v in (plain or {}).items()}, "nobre -5%% %r" % covered)


def test_construcao_ja_vem_com_bonus():
    covered = Extractor.building_data(FIX["main_38409"])["main"]
    plain = Extractor.building_data(FIX["main_40618"])["main"]
    check(covered["level"] == plain["level"], "mesmo nível do principal")
    check(round(plain["build_time"] / 1.05) == covered["build_time"],
          "principal: %s / 1,05 = %s" % (plain["build_time"], covered["build_time"]))


def test_custo_nominal_so_de_aldeia_sem_desconto():
    RM.CACHE_PATH = os.path.join(tempfile.mkdtemp(), "relics.json")
    man = RM.RelicManager(wrapper=None, config={"relics": {"enabled": True}})
    man.state = {"villages": {"41123": {
        "Quartel nos custos de recrutamento": {"sum": 10.0, "applied": 10.0},
        "Estábulo nos custos de recrutamento": {"sum": 8.0, "applied": 8.0}}}}
    for building in ("barracks", "stable"):
        man.note_unit_costs("41123", building, Extractor.recruit_data(FIX["%s_41123" % building]))
    check(not man.state.get("unit_costs"), "a tela descontada não vira custo nominal")
    man.note_unit_costs("41140", "barracks", Extractor.recruit_data(FIX["barracks_41140"]))
    got = (man.state.get("unit_costs") or {}).get("spear") or {}
    check([got.get(r) for r in ("wood", "stone", "iron")] == [50, 30, 10], "nominal da BBM 012 %r" % got)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    if failures:
        print("FALHOU (%d):" % len(failures))
        for f in failures:
            print(" -", f)
        sys.exit(1)
    print("ok")
