"""
Relatório "onde estão as tropas" da aba Apoios (2026-10-18):
`TroopLocationReader.view()` agrupando por destino o `troop_locations` que
cada aldeia grava no `cache/managed`, lido com `Extractor.place_troop_locations`
da praça real da BBM 026 (tests/fixtures/place_units_transit_br143.html).

Cobre: comandos a caminho da mesma origem viram uma linha; apoio voltando;
apoio pousado em outro jogador; aldeia própria fora do cache/managed (a
recém-conquistada) reconhecida pela falta de "(Jogador)" no rótulo; apoio
pousado entre aldeias próprias lido pela aldeia que o recebe e sem contar
duas vezes quando a origem também o lista.

Rodar: python tests/test_troop_locations.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.extractors import Extractor
from webmanager.utils import TroopLocationReader

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
with open(os.path.join(FIX, "place_units_transit_br143.html"), encoding="utf-8") as fh:
    TRANSIT = fh.read()


def _check(label, got, expected):
    assert got == expected, f"{label}: esperado {expected!r}, veio {got!r}"
    print(f"  ok  {label}: {got!r}")


def _view(managed):
    original = TroopLocationReader._managed
    TroopLocationReader._managed = staticmethod(lambda: managed)
    try:
        return TroopLocationReader.view(now=1792363600)
    finally:
        TroopLocationReader._managed = original


def test_agrupa_por_destino():
    print("test_agrupa_por_destino")
    loc = Extractor.place_troop_locations(TRANSIT)
    view = _view({"39449": {"name": "BBM 026", "troop_locations": dict(loc, read_at=1792360000)},
                  "45215": {"name": "BBM 049", "troop_locations": None}})
    by = {g["vid"]: g for g in view["groups"]}
    _check("quatro destinos", sorted(by), ["45215", "58044", "62938", "74966"])
    bbm055 = by["74966"]
    _check("BBM 055 é própria mesmo fora do cache/managed", bbm055["own"], True)
    _check("rótulo com nome e id", bbm055["label"], "BBM 055 (74966)")
    _check("7 comandos a caminho viram uma linha",
           [(s["vid"], s["status"], s["commands"]) for s in bbm055["sources"]],
           [("39449", "transit", 7)])
    _check("lança a caminho somada", bbm055["by_status"]["transit"]["spear"], 2640)
    _check("voltando da BBM 049", by["45215"]["status_pop"]["back"], 4)
    _check("outro jogador", (by["58044"]["own"], by["58044"]["player"]), (False, "JogadorA"))
    _check("próprias primeiro", view["groups"][0]["own"], True)
    _check("uma aldeia lida, uma não", (view["read"], view["unread"]), (1, 1))
    _check("leitura de 1 h", view["oldest_age_h"], 1.0)


def test_pousado_entre_proprias_sem_duplicar():
    print("test_pousado_entre_proprias_sem_duplicar")
    empty = {"transit": [], "away": [], "home_support": [], "read_at": 1792360000}
    support = {"vid": "1", "name": "A", "player_name": None, "troops": {"heavy": 100}}
    managed = {"1": {"name": "A", "troop_locations": dict(empty)},
               "2": {"name": "B", "troop_locations": dict(empty, home_support=[support])}}
    view = _view(managed)
    _check("pousado lido pela aldeia que recebe",
           [(g["vid"], g["sources"][0]["vid"], g["status_pop"]["stationed"]) for g in view["groups"]],
           [("2", "1", 600)])
    managed["1"]["troop_locations"] = dict(empty, away=[dict(support, vid="2")])
    view = _view(managed)
    _check("listado pelas duas pontas conta uma vez", view["groups"][0]["status_pop"]["stationed"], 600)


if __name__ == "__main__":
    test_agrupa_por_destino()
    test_pousado_entre_proprias_sem_duplicar()
    print("\nOK - relatório de onde estão as tropas")
