"""
Checagem de termino gratis sem o segundo GET de `main` (docs/backend.md §8.63).

Depois de enfileirar, `start_update()` baixava `screen=main` de novo so para
procurar o `BuildInstantFree`. A resposta do proprio upgrade ja e essa tela:
medido em 2026-10-17 na BBM 009, o GET `main&action=upgrade_building` volta
`302 -> screen=main`, com a fila nova e o mesmo id/`data-available-from` de
um GET de `main` feito 20 s depois. Eram ~22 GETs por ciclo.

O HTML do jogo nao entra aqui (traz token de sessao): o Extractor e trocado
por um falso que le marcadores de texto, e o teste conta as requisicoes.

Rodar: python tests/test_builder_fresh_main.py
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import game.buildingmanager as bm_mod
from game.buildingmanager import BuildingManager


class _Resp:
    def __init__(self, text, url="x"):
        self.text = text
        self.url = url


def _page(queue, instant=False):
    text = "MAIN queue=%d" % queue
    if instant:
        text += " 777, 'BuildInstantFree' data-available-from=\"1\""
    return text


class _FakeExtractor:
    @staticmethod
    def game_state(res):
        if res is None or "MAIN" not in res.text:
            return None
        return {"village": {"name": "V", "buildings": {"hide": 1, "farm": 1},
                            "wood": 10 ** 6, "stone": 10 ** 6, "iron": 10 ** 6,
                            "pop": 0, "pop_max": 10 ** 6},
                "link_base_pure": "game.php?village=1&screen=", "csrf": "c"}

    @staticmethod
    def building_data(res):
        if res is None or "MAIN" not in res.text:
            return {}
        return {b: {"id": b, "can_build": True, "wood": 1, "stone": 1, "iron": 1,
                    "pop": 0, "build_time": 60} for b in ("hide", "farm")}

    @staticmethod
    def active_building_queue(res):
        return int(res.text.split("queue=")[1].split()[0])


class _Wrapper:
    def __init__(self, build_pages, main_pages):
        self.build_pages = list(build_pages)
        self.main_pages = list(main_pages)
        self.mains = 0
        self.urls = []
        self.last_h = "h"

    def get_action(self, village_id, action):
        self.mains += 1
        return _Resp(self.main_pages.pop(0))

    def get_url(self, url):
        self.urls.append(url)
        if "build_order_reduce" in url:
            return _Resp(_page(1))
        page = self.build_pages.pop(0)
        return None if page is None else _Resp(page)

    class reporter:
        @staticmethod
        def report(*a, **k):
            pass


class _Resman:
    storage = 10 ** 6
    requested = {}

    def update(self, game_state):
        pass

    def in_need_of(self, res):
        return False

    def request(self, **k):
        pass


def _run(build_pages, main_pages):
    orig = bm_mod.Extractor
    bm_mod.Extractor = _FakeExtractor
    try:
        w = _Wrapper(build_pages, main_pages)
        b = BuildingManager(w, "1")
        b.logger = logging.getLogger("test_builder")
        b.queue = ["hide:5", "farm:5"]
        b.max_lookahead = 2
        b.resman = _Resman()
        result = b.start_update(build=True)
        return w, result
    finally:
        bm_mod.Extractor = orig


def test_duas_construcoes_um_get_de_main_so():
    w, result = _run([_page(1), _page(2)], [_page(0)])
    assert result is True
    assert w.mains == 1, w.mains


def test_termino_gratis_lido_da_resposta_do_upgrade():
    # a resposta do 2o upgrade oferece o termino; o reduce sai sem GET extra
    w, _ = _run([_page(1), _page(2, instant=True), _page(2)], [_page(0), _page(1)])
    assert any("build_order_reduce" in u and "id=777" in u for u in w.urls), w.urls
    # o GET que sobra e o do start_update() recursivo, que ja existia
    assert w.mains == 2, w.mains


def test_upgrade_sem_resposta_nao_usa_a_tela_do_anterior():
    # Com fila de 2, o put_wait() do upgrade que falhou ja ocupa a vaga: o
    # laco devolve False e nao ha checagem de termino, como antes. Em especial,
    # o termino oferecido na resposta do 1o upgrade nao e usado as cegas.
    w, result = _run([_page(1, instant=True), None], [_page(0)])
    assert result is False
    assert not any("build_order_reduce" in u for u in w.urls), w.urls
    assert w.mains == 1, w.mains


def test_resposta_irreconhecivel_volta_ao_get():
    w, _ = _run([_page(1), "captcha"], [_page(0), _page(2)])
    assert w.mains == 2, w.mains


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
