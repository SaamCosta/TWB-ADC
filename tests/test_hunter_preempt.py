"""
§8.71: o detector de furo do Hunter passa a PREEMPTAR, e a leitura de
relatorios fica retomavel.

Incidente que motivou, 19/10/2026: as 15:16 o planejador agendou um trem de 4
nobres contra a Barbara 81800, com os 2 da BBM 008 saindo as 15:25:41. O gate
antes do init da BBM 002 (15:19:39) viu 362 s ate a saida e uma previsao de
init de 76 s, e deixou passar. O init abriu 48 relatorios de apoio voltando,
~15 s cada, sem checkpoint: o detector avisou o furo as 15:20:44, so avisou, e
os dois nobres sairam 401 s atrasados -- recusados.

Sem rede: `WebWrapper.web.get` devolve resposta de mentira e o `time` do modulo
e um relogio falso cujo `sleep` avanca o relogio (a pausa entre requisicoes
vira tempo simulado).
"""

import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import core.request as request_module  # noqa: E402
from core.request import WebWrapper  # noqa: E402
from game import reports as reports_mod  # noqa: E402
from game.reports import ReportManager  # noqa: E402

logging.disable(logging.CRITICAL)

T0 = 1792433979.0  # 19/10 15:19:39, inicio do init da BBM 002
SEND = T0 + 362    # 15:25:41, saida dos 2 nobres da BBM 008


class FakeTime:
    def __init__(self, now=T0):
        self.now = now

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += max(0.0, seconds)


class FakeResponse:
    status_code = 200

    def __init__(self, text, url):
        self.text = text
        self.url = url
        self.headers = {"content-type": "text/html"}


def list_html(ids):
    return "".join(
        '<tr class="report-%s"><td><a class="report-link" data-id="%s"></a></td></tr>'
        % (rid, rid) for rid in ids)


class FakeWeb:
    """`requests.Session` de mentira: lista paginada e paginas de relatorio."""

    def __init__(self, clock, pages, net_seconds=8.0):
        self.clock = clock
        self.pages = pages  # offset -> [ids]
        self.net_seconds = net_seconds
        self.urls = []

    def get(self, url, headers=None, timeout=None):
        self.clock.now += self.net_seconds
        self.urls.append((self.clock.now, url))
        if "&view=" in url:
            return FakeResponse('<div class="report_ReportSupportBack">', url)
        offset = int(url.split("from=")[1]) if "from=" in url else 0
        return FakeResponse(list_html(self.pages.get(offset, [])), url)


def wrapper(clock, pages):
    w = WebWrapper("https://example.invalid/", endpoint="https://example.invalid/")
    w.web = FakeWeb(clock, pages)
    w.delay = 1.0
    return w


def with_clock(fn):
    def run():
        clock = FakeTime()
        orig_req, orig_rep = request_module.time, reports_mod.time
        request_module.time = clock
        reports_mod.time = clock
        try:
            fn(clock)
        finally:
            request_module.time = orig_req
            reports_mod.time = orig_rep
    run.__name__ = fn.__name__
    return run


def manager(w):
    rm = ReportManager(wrapper=w, village_id="41123")
    rm.last_reports = {"seed": {"type": "attack"}}  # nao rele cache/reports
    reports_mod.ReportCache.set_cache = staticmethod(lambda rid, entry: None)
    return rm


# --- 1. Replay do incidente -----------------------------------------------------

@with_clock
def test_incidente_81800_leitura_longa_entrega_ao_hunter_antes_da_saida(clock):
    ids = [str(208956286 - i) for i in range(48)]
    w = wrapper(clock, {0: ids})
    calls = []

    def preempt():
        # O Hunter de verdade dorme ate o segundo exato e manda.
        calls.append(clock.now)
        clock.now = max(clock.now, SEND)
        calls.append("sent")

    w.hunter_next_send_reader = lambda: SEND if "sent" not in calls else None
    w.hunter_preempt = preempt
    rm = manager(w)
    rm.read(full_run=False)

    assert calls and calls[1] == "sent", calls
    assert SEND - 300 <= calls[0] < SEND, (
        "o Hunter tem de receber o controle dentro da janela e antes da saida: "
        "%.0f s antes" % (SEND - calls[0]))
    views = [u for _, u in w.web.urls if "&view=" in u]
    assert len(views) == 48, "a leitura segue depois da saida: %d abertos" % len(views)
    assert w.web.urls[-1][0] - T0 > 362, "a leitura de fato passa da hora de saida"


@with_clock
def test_sem_preempcao_a_leitura_atravessa_a_saida(clock):
    """O comportamento de antes, para provar que o cenario do teste reproduz o
    furo: so o aviso, e a leitura passa por cima da saida."""
    ids = [str(208956286 - i) for i in range(48)]
    w = wrapper(clock, {0: ids})
    w.hunter_next_send = SEND
    rm = manager(w)
    rm.read(full_run=False)
    assert w.web.urls[-1][0] > SEND


# --- 2. Regras do detector ------------------------------------------------------

@with_clock
def test_post_avisa_mas_nao_preempta(clock):
    w = wrapper(clock, {})
    calls = []
    w.hunter_preempt = lambda: calls.append(clock.now)
    w.hunter_next_send = T0 + 100
    w._check_hunter_silence("POST", "x")
    assert calls == [], "POST e o fim de um formulario: o Hunter nao entra no meio"
    w._check_hunter_silence("GET", "y")
    assert len(calls) == 1


@with_clock
def test_uma_vez_por_saida_e_nunca_dentro_do_hunter(clock):
    w = wrapper(clock, {})
    calls = []
    w.hunter_preempt = lambda: calls.append(1)
    w.hunter_next_send = T0 + 100
    w.hunter_active = True
    w._check_hunter_silence("GET", "a")
    assert calls == [], "requisicao do proprio Hunter nao preempta"
    w.hunter_active = False
    w._check_hunter_silence("GET", "b")
    w._check_hunter_silence("GET", "c")
    assert calls == [1], "uma vez por saida: %s" % calls
    w.hunter_next_send = T0 + 200
    w._check_hunter_silence("GET", "d")
    assert calls == [1, 1], "saida nova, preempcao nova"


@with_clock
def test_fora_da_janela_ou_ja_passada_nao_preempta(clock):
    w = wrapper(clock, {})
    calls = []
    w.hunter_preempt = lambda: calls.append(1)
    for nxt in (T0 + 301, T0 - 1, None):
        w.hunter_next_send = nxt
        w._check_hunter_silence("GET", "a")
    assert calls == []


@with_clock
def test_preempcao_que_faz_requisicao_nao_reentra(clock):
    w = wrapper(clock, {0: []})
    calls = []

    def preempt():
        calls.append(1)
        w.get_url("game.php?screen=place")  # o Hunter tambem faz GET

    w.hunter_preempt = preempt
    # O prazo muda a cada leitura (o Hunter mandou um e o seguinte ja esta na
    # janela): sem a trava de reentrancia, o GET de dentro preemptaria de novo.
    deadlines = iter(T0 + 100 + i for i in range(1000))
    w.hunter_next_send_reader = lambda: next(deadlines)
    w.get_url("game.php?screen=overview")
    assert calls == [1], calls
    assert [u for _, u in w.web.urls][0].endswith("screen=place"), (
        "o GET do Hunter sai antes do GET da tarefa")


@with_clock
def test_leitor_de_prazo_ve_schedule_criado_depois_do_gate(clock):
    w = wrapper(clock, {})
    calls = []
    w.hunter_preempt = lambda: calls.append(1)
    w.hunter_next_send = None  # o gate nao viu nada
    w.hunter_next_send_reader = lambda: T0 + 120
    w._check_hunter_silence("GET", "a")
    assert calls == [1]
    assert w.hunter_next_send == T0 + 120, "o prazo lido fica publicado (OwnDefense le)"


@with_clock
def test_leitor_que_falha_fica_com_o_publicado(clock):
    w = wrapper(clock, {})
    calls = []
    w.hunter_preempt = lambda: calls.append(1)
    w.hunter_next_send = T0 + 100

    def broken():
        raise ValueError("schedules.json corrompido")
    w.hunter_next_send_reader = broken
    w._check_hunter_silence("GET", "a")
    assert calls == [1]


# --- 3. Leitura de relatorios retomavel -----------------------------------------

@with_clock
def test_leitura_interrompida_retoma_e_pagina(clock):
    page0 = [str(1000 - i) for i in range(50)]
    page1 = [str(900 - i) for i in range(10)]
    w = wrapper(clock, {0: page0, 50: page1})
    rm = manager(w)

    real_get = w.web.get
    opened = []

    def dying_get(url, headers=None, timeout=None):
        if "&view=" in url:
            opened.append(url)
            if len(opened) == 20:
                raise SystemExit("reinicio no meio da leitura")
        return real_get(url, headers=headers, timeout=timeout)

    w.web.get = dying_get
    try:
        rm.read(full_run=False)
    except SystemExit:
        pass
    assert len(rm.last_reports) == 1 + 19
    w.web.get = real_get
    before = len(w.web.urls)
    rm.read(full_run=False)
    lists = [u for _, u in w.web.urls[before:] if "&view=" not in u]
    assert any("from=50" in u for u in lists), (
        "a pagina 0 so em parte nova, mas com o mais antigo novo, tem de paginar: %s" % lists)
    for rid in page0 + page1:
        assert rid in rm.last_reports, "relatorio %s ficou para tras" % rid


@with_clock
def test_nada_novo_continua_custando_so_a_lista(clock):
    page0 = [str(1000 - i) for i in range(50)]
    w = wrapper(clock, {0: page0})
    rm = manager(w)
    rm.last_reports.update({rid: {"type": "x"} for rid in page0})
    rm.read(full_run=False)
    assert len(w.web.urls) == 1, w.web.urls


@with_clock
def test_so_os_mais_novos_sao_novos_nao_pagina(clock):
    page0 = [str(1000 - i) for i in range(50)]
    w = wrapper(clock, {0: page0, 50: [str(900)]})
    rm = manager(w)
    rm.last_reports.update({rid: {"type": "x"} for rid in page0[5:]})
    rm.read(full_run=False)
    lists = [u for _, u in w.web.urls if "&view=" not in u]
    assert len(lists) == 1, lists


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
