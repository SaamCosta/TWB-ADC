"""
§9 item 20: a tela do ferreiro so e lida quando ha pesquisa pedida que o jogo
ainda nao resolveu (`TroopManager.smith_settled_levels` /
`smith_read_needed` / `attempt_upgrade`).

Medido antes: ~40 GETs de `smith` por ciclo diurno em `cache/cycles/`
(44 no ciclo de 03/10 15:23), contra 56 pesquisas iniciadas em toda a
historia dos `cache/logs/twb_*.log`.

Sem rede. A fixture e o recorte verbatim do `<script>` de
`cache/_smith_br143.html` (aldeia 39292, br143, 2026-08-20), capturado com a
sessao do bot.
"""

import logging
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.extractors import Extractor  # noqa: E402
from game.troopmanager import TroopManager  # noqa: E402

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


with open(os.path.join(ROOT, "tests", "fixtures", "smith_techs_br143.html"),
          encoding="utf-8") as fh:
    SMITH_PAGE = fh.read()

SMITH = Extractor.smith_data(SMITH_PAGE)


class SmithWrapper:
    """Conta os GETs do ferreiro; a acao de pesquisa sempre falha."""

    last_h = "redacted"

    def __init__(self, page=SMITH_PAGE):
        self.page = page
        self.smith_gets = 0
        self.research_posts = 0

    def get_action(self, village_id=None, action=None):
        if action == "smith":
            self.smith_gets += 1
            return self.page
        return None

    def get_api_action(self, **_kwargs):
        self.research_posts += 1
        return None


def _manager(wrapper, wanted):
    tm = TroopManager(wrapper=wrapper, village_id="39292")
    tm.logger = logging.getLogger("test")
    tm.game_data = {"village": {"wood": 0, "stone": 0, "iron": 0}}
    tm.wanted_levels = dict(wanted)
    return tm


def test_fixture_le_os_campos_que_o_gate_usa():
    check(SMITH is not None, "fixture nao parseou")
    available = SMITH["available"]
    check(available["light"].get("error_level") is True, "light pesquisado sem error_level")
    check(available["axe"].get("can_research") is True, "axe deveria estar pesquisavel")
    check(available["heavy"].get("error_buildings") is True, "heavy sem error_buildings")


def test_resolvidas():
    # O caso de campo: templates pedem `light: 3` num mundo de nivel unico.
    settled = TroopManager.smith_settled_levels(SMITH, {"spear": 1, "spy": 1, "light": 3})
    check(set(settled) == {"spear", "spy", "light"}, "esperava as tres resolvidas: %r" % settled)
    check(settled["light"] == math.inf, "nivel maximo deveria entrar como inf")

    # Pesquisavel, sem edificio e ausente da tela ficam de fora.
    settled = TroopManager.smith_settled_levels(
        SMITH, {"axe": 1, "heavy": 1, "archer": 1, "sword": 1})
    check(set(settled) == {"sword"}, "so sword resolvida: %r" % settled)

    # Nivel alcancando o pedido sem error_level (mundo de varios niveis).
    fake = {"available": {"spear": {"level": "2"}}}
    check(TroopManager.smith_settled_levels(fake, {"spear": 2}) == {"spear": 2},
          "nivel >= pedido deveria resolver")
    check(TroopManager.smith_settled_levels(fake, {"spear": 3}) == {},
          "nivel < pedido sem error_level nao resolve")

    for bad in (None, {}, {"available": []}, "texto"):
        check(TroopManager.smith_settled_levels(bad, {"spear": 1}) == {},
              "entrada ruim %r deveria dar vazio" % (bad,))


def test_quando_ler():
    need = TroopManager.smith_read_needed
    now = 1_000_000
    settled = {"spear": 1, "light": math.inf}
    check(need({}, settled, now, now) is False, "nada pedido nao le")
    check(need({"spear": 1}, {}, 0, now) is True, "sem leitura anterior le")
    check(need({"spear": 1, "light": 3}, settled, now - 60, now) is False,
          "tudo resolvido e fresco nao deveria ler")
    check(need({"spear": 1, "axe": 1}, settled, now - 60, now) is True,
          "unidade nova pedida deveria ler")
    check(need({"spear": 2}, settled, now - 60, now) is True,
          "nivel pedido acima do resolvido deveria ler")
    check(need({"spear": 1}, settled, now - TroopManager.SMITH_RECHECK_SECONDS, now) is True,
          "leitura vencida deveria ler")


def test_attempt_upgrade_pula_o_get_resolvido():
    w = SmithWrapper()
    tm = _manager(w, {"spear": 1, "spy": 1, "light": 3})
    tm.attempt_upgrade()
    check(w.smith_gets == 1, "primeira chamada deveria ler o ferreiro")
    tm.attempt_upgrade()
    tm.attempt_upgrade()
    check(w.smith_gets == 1, "resolvido e fresco nao deveria ler de novo: %d" % w.smith_gets)
    check(w.research_posts == 0, "nada a pesquisar, nenhum POST")

    # Reconferencia diaria.
    tm._smith_settled_at -= TroopManager.SMITH_RECHECK_SECONDS
    tm.attempt_upgrade()
    check(w.smith_gets == 2, "leitura vencida deveria reler")

    # Estagio novo do template pede axe: le e tenta pesquisar.
    tm.wanted_levels = {"spear": 1, "light": 3, "axe": 1}
    tm.attempt_upgrade()
    check(w.smith_gets == 3, "pedido novo deveria reler")
    check(w.research_posts == 1, "axe pesquisavel deveria tentar o POST")
    check(tm._smith_settled == {}, "com pendencia o gate nao pode ficar armado")
    tm.attempt_upgrade()
    check(w.smith_gets == 4, "com pendencia le todo ciclo, como antes")


def test_falha_de_leitura_nao_arma_o_gate():
    w = SmithWrapper(page=None)
    tm = _manager(w, {"spear": 1})
    tm.attempt_upgrade()
    tm.attempt_upgrade()
    check(w.smith_gets == 2, "leitura falha nao pode virar 'resolvido'")


def test_estado_por_aldeia():
    a = _manager(SmithWrapper(), {"spear": 1})
    b = _manager(SmithWrapper(), {"spear": 1})
    a.attempt_upgrade()
    check(a._smith_settled and not b._smith_settled,
          "o gate de uma aldeia vazou para outra (1o padrao)")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except Exception as exc:
                failures.append("%s: %r" % (name, exc))
    for f in failures:
        print("FALHA", f)
    print("OK" if not failures else "%d falha(s)" % len(failures))
    sys.exit(1 if failures else 0)
