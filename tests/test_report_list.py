"""
§8.46 P-RELATORIO-LISTA: o `ReportManager` nao abre a pagina de relatorio de
comercio -- a miniatura da linha da lista ja diz que ele nao interessa a
nenhum consumidor do bot. E a paginacao da lista segue o tamanho real da
pagina (50 no br143), nao os 12 que o codigo assumia.

Medido antes: dos 793 relatorios gravados em `cache/reports` nos 7 dias ate
2026-10-04, 534 eram `ReportTrade` e mais 26 `ReportAccept`, cada um custando
um GET de `report/all/view` so para gravar o tipo.

Sem rede. A fixture e o recorte verbatim de `screen=report&mode=all`
(`tests/fixtures/report_list_br143.html`, capturado com o wrapper do bot).
"""

import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.extractors import Extractor  # noqa: E402
from game import reports as reports_mod  # noqa: E402
from game.reports import ReportManager  # noqa: E402

logging.disable(logging.CRITICAL)

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


with open(os.path.join(ROOT, "tests", "fixtures", "report_list_br143.html"),
          encoding="utf-8") as fh:
    LIST_HTML = fh.read()

SCOUT, ATTACK, TRADE, ACCEPT, NO_ICON = (
    "174932184", "174931011", "174926018", "174688697", "174575399")

# --- 1. Extractor.report_list_icons contra o markup real ----------------------

icons = Extractor.report_list_icons(LIST_HTML)
check(set(icons) == {SCOUT, ATTACK, TRADE, ACCEPT, NO_ICON},
      "report_list_icons deveria achar as 5 linhas: %s" % sorted(icons))
check(icons.get(TRADE) == {"thumb": "report_trade", "commands": []},
      "linha de comercio: %s" % icons.get(TRADE))
# A miniatura e a mesma no ReportAccept: e por isso que o tipo gravado e
# "trade", e nao "ReportTrade".
check(icons.get(ACCEPT) == {"thumb": "report_trade", "commands": []},
      "linha de oferta aceita: %s" % icons.get(ACCEPT))
check(icons.get(SCOUT, {}).get("commands") == ["attack_small", "spy"]
      and icons[SCOUT]["thumb"] is None,
      "linha de exploracao: %s" % icons.get(SCOUT))
check(icons.get(ATTACK) == {"thumb": None, "commands": ["attack_small"]},
      "linha de ataque: %s" % icons.get(ATTACK))
check(icons.get(NO_ICON) == {"thumb": None, "commands": []},
      "linha sem icone (fila do gerente): %s" % icons.get(NO_ICON))
check(Extractor.report_list_icons(None) == {}, "None deveria dar {}")
check(Extractor.report_table(LIST_HTML) == [SCOUT, ATTACK, TRADE, ACCEPT, NO_ICON],
      "report_table mudou de ordem/conteudo")


# --- 2. ReportManager.read com wrapper e cache de mentira ---------------------

class FakeResponse:
    def __init__(self, text, url=""):
        self.text = text
        self.url = url


class FakeWrapper:
    def __init__(self, pages, views):
        self.pages = pages          # offset -> html da lista
        self.views = views          # id -> html da pagina do relatorio
        self.urls = []

    def get_url(self, url):
        self.urls.append(url)
        if "&view=" in url:
            rid = url.rsplit("view=", 1)[1]
            return FakeResponse(self.views.get(rid, '<div class="report_ReportX">'))
        offset = int(url.split("from=")[1]) if "from=" in url else 0
        return FakeResponse(self.pages.get(offset, ""))


saved = {}
reports_mod.ReportCache.set_cache = staticmethod(lambda rid, entry: saved.__setitem__(rid, entry))
reports_mod.ReportCache.cache_grab = staticmethod(lambda: {"seed": {"type": "attack"}})
reports_mod.Extractor.game_state = staticmethod(lambda res: {"player": {"id": "1"}})

VIEWS = {
    SCOUT: '<table class="report_ReportAttack">',
    ATTACK: '<table class="report_ReportAttack">',
    ACCEPT: '<table class="report_ReportAccept">',
    NO_ICON: '<table class="report_ReportAMemptyQueue">',
}


def manager(pages, views=VIEWS):
    rm = ReportManager(wrapper=FakeWrapper(pages, views), village_id="41123")
    rm.attack_report = lambda text, rid: rm.last_reports.__setitem__(rid, {"type": "attack"})
    return rm


saved.clear()
rm = manager({0: LIST_HTML})
rm.read(full_run=False)
views_opened = [u.rsplit("view=", 1)[1] for u in rm.wrapper.urls if "&view=" in u]
check(TRADE not in views_opened and ACCEPT not in views_opened,
      "comercio nao deveria ser aberto: %s" % views_opened)
check(sorted(views_opened) == sorted([SCOUT, ATTACK, NO_ICON]),
      "deveriam ser abertos so ataque, exploracao e o desconhecido: %s" % views_opened)
check(saved.get(TRADE) == {"type": "trade", "origin": None, "dest": None, "losses": {},
                           "extra": {"source": "report_list", "list_icon": "report_trade"}},
      "registro de comercio pela lista: %s" % saved.get(TRADE))
check(saved.get(ACCEPT, {}).get("type") == "trade",
      "oferta aceita tambem vira 'trade' pela lista: %s" % saved.get(ACCEPT))
check(saved.get(NO_ICON, {}).get("type") == "ReportAMemptyQueue"
      and saved[NO_ICON]["extra"] == {},
      "linha sem miniatura continua aberta e sem list_icon: %s" % saved.get(NO_ICON))
check(TRADE in rm.last_reports and ACCEPT in rm.last_reports,
      "relatorio gravado pela lista tem de entrar em last_reports, senao volta")
# 5 de 5 novos numa pagina de 5 -> pede a seguinte, a partir de 5 (nao 12).
list_urls = [u for u in rm.wrapper.urls if "&view=" not in u]
check(len(list_urls) == 2 and list_urls[1].endswith("&from=5"),
      "pagina inteira nova deveria pedir from=5: %s" % list_urls)

# Segunda leitura: nada novo -> nenhuma pagina de relatorio, nenhuma paginacao.
before = len(rm.wrapper.urls)
rm.read(full_run=False)
check(len(rm.wrapper.urls) == before + 1,
      "nada novo deveria custar so a lista: %s" % rm.wrapper.urls[before:])

# Miniatura de comercio COM icone de comando (combinacao nunca vista) -> abre.
saved.clear()
odd = LIST_HTML.replace(
    'class="report-thumb" />',
    'class="report-thumb" /><img src="x/graphic/command/support.webp" />', 1)
rm = manager({0: odd})
rm.read(full_run=False)
opened = [u.rsplit("view=", 1)[1] for u in rm.wrapper.urls if "&view=" in u]
check(TRADE in opened, "comercio com icone de comando deveria ser aberto: %s" % opened)
check(saved.get(TRADE, {}).get("extra") == {"list_icon": "report_trade"},
      "o aberto guarda a miniatura para a tabela poder crescer: %s" % saved.get(TRADE))

# Teto de paginas: todas as paginas sempre novas param em MAX_PAGES.
def fresh_page(n):
    return LIST_HTML.replace("data-id=\"174", "data-id=\"9%02d" % n).replace("report-174", "report-9%02d" % n)


rm = manager({i * 5: fresh_page(i) for i in range(10)}, views={})
rm.read(full_run=False)
list_urls = [u for u in rm.wrapper.urls if "&view=" not in u]
check(len(list_urls) == ReportManager.MAX_PAGES,
      "deveria parar em %d paginas: %d" % (ReportManager.MAX_PAGES, len(list_urls)))

# Resposta None na lista nao derruba.
rm = manager({})
rm.wrapper.get_url = lambda url: None
rm.read(full_run=False)

if failures:
    print("FAIL test_report_list:")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("OK test_report_list")
