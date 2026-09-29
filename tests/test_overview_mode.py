"""
A visao geral e pedida com `mode=prod` (docs/backend.md §8.37).

Sem `mode`, o jogo serve a ultima aba aberta, e a aba fica gravada tambem
quando vem pela querystring. `InFlightTracker` le `mode=commands` todo ciclo,
entao a leitura seguinte de `OverviewPage` recebia a tela de Comandos, sem
nenhuma aldeia: o bot ficou parado em 2026-09-29 das 13:57 as 14:18.

Rodar: python tests/test_overview_mode.py
"""
import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pages.overview import OverviewPage  # noqa: E402

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


class FakeWrapper:
    def __init__(self):
        self.urls = []

    def get_url(self, url):
        self.urls.append(url)
        return None


w = FakeWrapper()
OverviewPage._get_overview_villages_data(SimpleNamespace(wrapper=w))
check(len(w.urls) == 1, "esperava 1 GET, veio %r" % w.urls)
url = w.urls[0] if w.urls else ""
check("screen=overview_villages" in url, "tela errada: %r" % url)
check("mode=prod" in url,
      "sem mode=prod o jogo serve a ultima aba (Comandos, vinda do InFlight): %r" % url)

# O InFlight continua lendo a aba de comandos -- e exatamente por isso que a
# visao geral precisa fixar a dela. Se um dia ele parar, este teste nao quebra;
# se a visao geral voltar a omitir o mode, quebra acima.
src = open(os.path.join(ROOT, "game", "in_flight.py"), encoding="utf-8").read()
check("mode=commands" in src, "InFlight mudou de aba; reler a docstring de _get_overview_villages_data")

if failures:
    for f in failures:
        print("FAIL:", f)
    sys.exit(1)
print("OK test_overview_mode")
