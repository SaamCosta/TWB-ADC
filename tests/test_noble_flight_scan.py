"""
§8.71 fase 3: antes de mandar nobre extra, o bot le na praca de cada aldeia
com nobre se ja ha nobre NOSSO a caminho do alvo -- inclusive o que o jogador
mandou a mao -- e nao manda outro por cima.

Caso real: trem contra a Barbara 81800 (650|292) ficou com 2 de 4 nobres em
19/10 (os 2 da BBM 008 sairam atrasados e foram recusados). O usuario pode
completar a mao; o bot precisa perceber.

Fixtures verbatim:
- `place_commands_noble_br143.html`: `screen=place` da BBM 012 (41140) em
  19/10, com os 2 nobres do trem no ar (o `<form>` da praca e o bloco
  `commands_outgoings`, sem token);
- `place_commands_empty_br143.html`: o `<form>` da praca da 44683 em 06/10,
  quando ela nao tinha comando nenhum -- e o jogo nao poe o bloco.
"""

import logging
import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import game.attack as attack_module  # noqa: E402
from core.extractors import Extractor  # noqa: E402
from game.attack import ConquestManager, nobles_heading_to  # noqa: E402

logging.disable(logging.CRITICAL)


def fixture(name):
    with open(os.path.join(ROOT, "tests", "fixtures", name), encoding="utf-8") as fh:
        return fh.read()


NOBLE = fixture("place_commands_noble_br143.html")
EMPTY = fixture("place_commands_empty_br143.html")
TARGET = "81800"
TARGET_LOC = (650, 292)
NOW = 1792440000  # 19/10 ~17:20, trem no ar


# --- 1. Parser contra o markup real --------------------------------------------

def test_parser_le_nobre_destino_e_chegada():
    parsed = Extractor.place_outgoing_commands(NOBLE)
    assert parsed["declared"] == 3 and len(parsed["commands"]) == 3, parsed
    back, n1, n2 = parsed["commands"]
    assert back["command_type"] == "other_back" and not back["has_snob"]
    for cmd, end in ((n1, 1792577466), (n2, 1792577467)):
        assert cmd["command_type"] == "attack" and cmd["has_snob"], cmd
        assert cmd["target_coords"] == "650|292", cmd
        assert cmd["arrival_ts"] == end, cmd


def test_parser_praca_sem_comando_e_lista_vazia_nao_none():
    assert Extractor.place_outgoing_commands(EMPTY) == {"commands": [], "declared": 0}


def test_parser_tela_que_nao_e_a_praca_e_none():
    assert Extractor.place_outgoing_commands("<html>login</html>") is None
    assert Extractor.place_outgoing_commands(None) is None
    # O bloco sozinho, sem o formulario, nao prova que e a praca.
    alone = NOBLE[NOBLE.index('<div id="commands_outgoings"'):]
    assert Extractor.place_outgoing_commands(alone) is None


# --- 2. Classificacao pura -------------------------------------------------------

def parsed_noble():
    return Extractor.place_outgoing_commands(NOBLE)


def test_nobres_do_alvo_contam():
    out = nobles_heading_to({"41140": parsed_noble()}, TARGET_LOC, NOW)
    assert sorted(a for a, _v, _c in out["arrivals"]) == [1792577466, 1792577467], out
    assert out["unknown"] == [] and out["unreadable"] == []


def test_outro_alvo_nao_conta():
    out = nobles_heading_to({"41140": parsed_noble()}, (574, 271), NOW)
    assert out == {"arrivals": [], "unknown": [], "unreadable": []}, out


def test_nobre_ja_pousado_nao_conta():
    out = nobles_heading_to({"41140": parsed_noble()}, TARGET_LOC, 1792577467)
    assert out["arrivals"] == [], out


def test_retorno_com_nobre_nao_conta():
    parsed = parsed_noble()
    for cmd in parsed["commands"]:
        cmd["command_type"] = "return"
    out = nobles_heading_to({"41140": parsed}, TARGET_LOC, NOW)
    assert out["arrivals"] == [] and out["unknown"] == [], out


def test_rotulo_renomeado_e_incerto():
    parsed = parsed_noble()
    parsed["commands"][1]["target_coords"] = None
    out = nobles_heading_to({"41140": parsed}, TARGET_LOC, NOW)
    assert len(out["arrivals"]) == 1 and len(out["unknown"]) == 1, out


def test_icone_ilegivel_e_incerto_nao_sem_nobre():
    """Markup novo do icone nao pode virar 'nenhum nobre no ar' em silencio."""
    changed = NOBLE.replace("data-icon-hint=", "data-icon-title=")
    parsed = Extractor.place_outgoing_commands(changed)
    assert all(c["has_snob"] is None for c in parsed["commands"]), parsed
    out = nobles_heading_to({"41140": parsed}, TARGET_LOC, NOW)
    assert out["arrivals"] == [] and len(out["unknown"]) == 3, out


def test_praca_ilegivel_ou_cortada():
    cut = parsed_noble()
    cut["declared"] = 7
    out = nobles_heading_to({"1": None, "2": cut}, TARGET_LOC, NOW)
    assert out["unreadable"] == ["1", "2"], out


# --- 3. Integracao: o bloqueio dentro do ConquestManager -------------------------

class Notes:
    def __init__(self):
        self.sent = []

    def send(self, message):
        self.sent.append(message)


def manager(pages):
    cm = ConquestManager.__new__(ConquestManager)
    cm.village_id = "41140"
    cm.config = {"villages": {}}
    cm.logger = logging.getLogger("test")
    urls = []

    def get_url(url):
        urls.append(url)
        vid = url.split("village=")[1].split("&")[0]
        page = pages.get(vid)
        return None if page is None else SimpleNamespace(text=page)

    cm.wrapper = SimpleNamespace(get_url=get_url, reporter=SimpleNamespace(report=lambda *a: None))
    cm.urls = urls

    def village(snob_total, snob_home, location):
        units = SimpleNamespace(total_troops={"snob": snob_total}, troops={"snob": str(snob_home)})
        return SimpleNamespace(units=units, area=SimpleNamespace(my_location=list(location)))

    cm.villages = {
        "41140": village(3, 1, (640, 290)),   # BBM 012, os 2 do trem no ar
        "41114": village(2, 2, (641, 291)),   # BBM 008, nobres em casa
        "39975": village(0, 0, (642, 292)),   # sem nobre: nao e lida
        "99999": village(1, 1, (200, 200)),   # alem do alcance: nao e lida
    }
    cm._world_travel_params = lambda: ({}, 70)
    return cm


class Env:
    def __init__(self):
        self.written = []
        self.notes = Notes()

    def __enter__(self):
        self.saved = (attack_module.ConquestCache.set, attack_module.Notification,
                      attack_module.FileManager, attack_module.time)
        attack_module.ConquestCache.set = staticmethod(lambda t, e: self.written.append((t, dict(e))))
        attack_module.Notification = self.notes
        attack_module.FileManager = SimpleNamespace(load_json_file=lambda path: None)
        attack_module.time = SimpleNamespace(time=lambda: NOW)
        return self

    def __exit__(self, *exc):
        (attack_module.ConquestCache.set, attack_module.Notification,
         attack_module.FileManager, attack_module.time) = self.saved
        return False


def record():
    return {"target_id": TARGET, "status": "extra_pending", "reserved_by": "41140",
            "target_name": "Barbara #81800", "target_location": list(TARGET_LOC),
            "noble_arrivals": [1792577465, 1792577465], "last_hit_timestamp": 1792577465}


def test_nobre_a_caminho_bloqueia_e_e_registrado():
    cm = manager({"41140": NOBLE, "41114": EMPTY})
    data = record()
    with Env() as env:
        blocked = cm._nobles_in_flight_block(TARGET, data, TARGET_LOC, 1792577465)
    assert blocked is True
    read = sorted(u.split("village=")[1].split("&")[0] for u in cm.urls)
    assert read == ["41114", "41140"], "so quem tem nobre e esta no alcance: %s" % read
    assert data["noble_arrivals"] == [1792577466, 1792577467], data["noble_arrivals"]
    assert {o["village_id"] for o in data["observed_nobles"]} == {"41140"}
    assert env.written and env.written[-1][1]["noble_arrivals"] == [1792577466, 1792577467]
    assert env.notes.sent and "nao mando nobre extra" in env.notes.sent[0], env.notes.sent


def test_nada_no_ar_libera():
    cm = manager({"41140": EMPTY, "41114": EMPTY})
    data = record()
    with Env() as env:
        blocked = cm._nobles_in_flight_block(TARGET, data, TARGET_LOC, 1792577465)
    assert blocked is False and env.written == [] and env.notes.sent == []


def test_praca_que_nao_responde_bloqueia_sem_registrar():
    cm = manager({"41140": EMPTY})  # 41114 -> None
    data = record()
    with Env() as env:
        blocked = cm._nobles_in_flight_block(TARGET, data, TARGET_LOC, 1792577465)
    assert blocked is True
    assert data["noble_arrivals"] == [1792577465, 1792577465], "nao inventa chegada"
    assert env.notes.sent and "praca ilegivel" in env.notes.sent[0], env.notes.sent


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
