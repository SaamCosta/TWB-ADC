"""
webmanager/utils.py::CycleReader e a pagina /cycles -- o lado que le o que
o medidor de ciclo (core/cycle_meter.py, backend 8.21) grava.

Os resumos sao produzidos pelo PROPRIO CycleMeter com relogio falso, nao
escritos a mao: se o formato do arquivo mudar no produtor, este teste quebra
junto, em vez de continuar verde contra um formato que o bot nao grava mais.

O que se protege (decimo primeiro padrao do CLAUDE.md):
- ciclo abortado fica FORA das medianas e e contado a parte com o motivo;
- media por aldeia e por ciclo EM QUE ELA APARECEU, com `cycles_present`;
- participacao por fase fecha 100%;
- `(sem fase)` acima do limiar vira alerta;
- janela por inicio do ciclo; arquivo ilegivel contado, nao derruba;
- a pagina renderiza nos ramos vazio, so-abortado e cheio.

`CACHE_DIR` e trocado por um diretorio temporario: o bot escreve
cache/cycles enquanto roda (vigesimo primeiro padrao).

Rodar: python tests/test_cycle_reader.py
"""
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "webmanager"))

from core.cycle_meter import CycleMeter  # noqa: E402
from webmanager.utils import CycleReader  # noqa: E402

failures = []
NOW = 1790200000


def check(cond, msg):
    if not cond:
        failures.append(msg)


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def tick(self, s):
        self.t += s


def _cycle(started_at, villages, unphased=1.0, account=10.0, extra=None):
    """
    Um resumo de ciclo real, produzido pelo CycleMeter. `villages` e
    {vid: {fase: (segundos, requisicoes)}}.
    """
    clock = FakeClock()
    m = CycleMeter(clock=clock, wall_clock=lambda: float(started_at))
    m.begin_cycle()
    clock.tick(unphased)
    with m.phase("overview"):
        m.record_request("GET", slept=account * 0.8, net=0.5)
        clock.tick(account)
    for vid, phases in villages.items():
        with m.phase("aldeia", village=vid):
            for phase, (secs, reqs) in phases.items():
                with m.phase(phase):
                    for _ in range(reqs):
                        m.record_request("GET", slept=secs * 0.8 / max(reqs, 1), net=0.3)
                    clock.tick(secs)
    summary = m.end_cycle(extra=extra or {"cycle": 1, "next_sleep_seconds": 600.0})
    # end_cycle usa o wall_clock fixo para ended_at; da uma duracao coerente.
    summary["ended_at"] = int(started_at + summary["total_seconds"])
    return summary


def _aborted(started_at):
    return {
        "started_at": started_at, "ended_at": started_at + 5,
        "total_seconds": 5.4, "requests": 1, "sleep_seconds": 3.0,
        "net_seconds": 2.2, "captcha_seconds": 0.0,
        "buckets": [{"village": None, "phase": "overview", "wall": 5.4,
                     "requests": 1, "gets": 1, "posts": 0, "failed": 0,
                     "sleep": 3.0, "net": 2.2, "captcha": 0.0}],
        "aborted": "overview_unavailable", "requests_between_cycles": 0,
    }


class TempCycles:
    def __init__(self, files):
        self.files = files

    def __enter__(self):
        self.dir = tempfile.mkdtemp()
        for name, payload in self.files.items():
            with open(os.path.join(self.dir, name), "w", encoding="utf-8") as fh:
                fh.write(payload if isinstance(payload, str) else json.dumps(payload))
        self.orig = CycleReader.CACHE_DIR
        CycleReader.CACHE_DIR = self.dir
        CycleReader._cache = {"sig": None, "data": None}
        return self

    def __exit__(self, *exc):
        CycleReader.CACHE_DIR = self.orig
        CycleReader._cache = {"sig": None, "data": None}
        shutil.rmtree(self.dir, ignore_errors=True)


def _two_cycles_and_an_abort():
    c1 = _cycle(NOW - 20000, {
        "100": {"farm": (300.0, 20), "construcao": (30.0, 2)},
        "200": {"farm": (100.0, 6)},
    })
    # A aldeia 200 NAO aparece no segundo ciclo (fora do horario ativo).
    c2 = _cycle(NOW - 8000, {
        "100": {"farm": (500.0, 30), "construcao": (30.0, 2)},
    }, extra={"cycle": 2, "next_sleep_seconds": 700.0})
    ab = _aborted(NOW - 3000)
    return {
        "%d.json" % c1["started_at"]: c1,
        "%d.json" % c2["started_at"]: c2,
        "%d.json" % ab["started_at"]: ab,
    }


def test_missing_and_empty_dir():
    orig = CycleReader.CACHE_DIR
    CycleReader.CACHE_DIR = os.path.join(tempfile.gettempdir(), "nao-existe-twb-cycles")
    CycleReader._cache = {"sig": None, "data": None}
    try:
        out = CycleReader.load(now=NOW)
        check(out["available"] is False, "diretorio ausente nao e 'available'")
    finally:
        CycleReader.CACHE_DIR = orig
    with TempCycles({}):
        out = CycleReader.load(now=NOW)
        check(out["available"] is False and out["on_disk"] == 0, "diretorio vazio")


def test_aborted_is_out_of_medians():
    with TempCycles(_two_cycles_and_an_abort()):
        out = CycleReader.load(days=14, now=NOW)
        check(out["available"], "tem dado")
        check(out["complete_count"] == 2, "2 completos, veio %r" % out["complete_count"])
        check(out["aborted_count"] == 1, "1 abortado")
        check(out["aborted_reasons"] == [("overview_unavailable", 1)],
              "motivo do aborto preservado: %r" % out["aborted_reasons"])
        # O mais novo em disco e o abortado; o 'ultimo completo' nao.
        check(out["latest"]["aborted"] == "overview_unavailable",
              "latest e o arquivo mais novo, abortado ou nao")
        check(out["latest"]["next_start_fmt"] is None,
              "abortado nao grava sono, entao nao ha proximo inicio previsto")
        # Mediana entre 2 ciclos: se o abortado (5 s) entrasse, a minima seria 5s.
        check(out["medians"]["min_fmt"] != "5s", "abortado nao entra na minima")
        check(out["last"]["requests"] == 1 + 32, "ultimo completo = c2: %r" % out["last"]["requests"])


def test_village_mean_is_per_cycle_present():
    with TempCycles(_two_cycles_and_an_abort()):
        out = CycleReader.load(days=14, now=NOW, managed={
            "100": {"public": {"name": "BBM 001"}},
        })
        rows = {r["village_id"]: r for r in out["villages"]}
        check(rows["200"]["cycles_present"] == 1, "200 apareceu em 1 ciclo")
        check(rows["100"]["cycles_present"] == 2, "100 apareceu em 2")
        # 6 req num ciclo em que apareceu: 6/ciclo, nao 3.
        check(abs(rows["200"]["req_per_cycle"] - 6.0) < 1e-9,
              "media da 200 dividida pela presenca: %r" % rows["200"]["req_per_cycle"])
        check(rows["100"]["name"] == "BBM 001", "nome vem do managed")
        check(rows["200"]["name"] == "#200", "sem managed cai no id")
        check(rows[None]["is_account"] and rows[None]["name"] == "Conta inteira",
              "fases sem aldeia viram 'Conta inteira'")
        top = [t["phase"] for t in rows["100"]["top_phases"]]
        check(top[0] == "farm", "fase dominante da 100 e farm: %r" % top)


def test_phase_shares_close_100():
    with TempCycles(_two_cycles_and_an_abort()):
        out = CycleReader.load(days=14, now=NOW)
        total = sum(p["share_pct"] for p in out["phases"])
        check(abs(total - 100.0) < 0.5, "participacoes somam 100: %r" % total)
        farm = next(p for p in out["phases"] if p["phase"] == "farm")
        check(farm["cycles_present"] == 2, "farm presente nos 2")
        check(abs(farm["req_per_cycle"] - 28.0) < 1e-9, "(26+30)/2 = 28 req/ciclo")
        check(out["phases"][0]["phase"] == "farm", "maior fase primeiro")
        vtotal = sum(v["share_pct"] for v in out["villages"])
        check(abs(vtotal - 100.0) < 0.5, "participacoes por aldeia somam 100: %r" % vtotal)


def test_unphased_warning_threshold():
    quiet = _cycle(NOW - 1000, {"100": {"farm": (100.0, 5)}}, unphased=1.0)
    loud = _cycle(NOW - 500, {"100": {"farm": (100.0, 5)}}, unphased=60.0)
    with TempCycles({"a.json": quiet}):
        out = CycleReader.load(now=NOW)
        check(not out["unphased_warn"], "1 s sem fase nao alerta: %r" % out["unphased_pct"])
    with TempCycles({"b.json": loud}):
        out = CycleReader.load(now=NOW)
        check(out["unphased_warn"], "60 s de ~170 sem fase alerta: %r" % out["unphased_pct"])


def test_window_by_start_and_unreadable_files():
    old = _cycle(NOW - 20 * 86400, {"100": {"farm": (100.0, 5)}})
    new = _cycle(NOW - 3600, {"100": {"farm": (100.0, 5)}})
    with TempCycles({"old.json": old, "new.json": new, "bad.json": "{meio arquivo",
                     "weird.json": [1, 2, 3], "note.txt": "ignorado"}):
        out = CycleReader.load(days=14, now=NOW)
        check(out["on_disk"] == 2, "2 validos em disco: %r" % out["on_disk"])
        check(out["unreadable"] == 2, "JSON parcial e formato estranho contados: %r" % out["unreadable"])
        check(out["complete_count"] == 1, "so o novo entra em 14 dias")
        out = CycleReader.load(days=0, now=NOW)
        check(out["complete_count"] == 2, "days=0 e tudo")


def test_cache_invalidates_when_a_cycle_lands():
    first = _cycle(NOW - 3600, {"100": {"farm": (100.0, 5)}})
    with TempCycles({"1.json": first}) as t:
        check(CycleReader.load(now=NOW)["complete_count"] == 1, "um ciclo")
        second = _cycle(NOW - 60, {"100": {"farm": (100.0, 5)}})
        with open(os.path.join(t.dir, "2.json"), "w", encoding="utf-8") as fh:
            json.dump(second, fh)
        check(CycleReader.load(now=NOW)["complete_count"] == 2,
              "arquivo novo invalida o cache do reader")


def test_page_renders_all_branches():
    import webmanager.server as srv
    srv.app.jinja_env.auto_reload = True
    srv.app.jinja_env.cache = {}
    client = srv.app.test_client()

    with TempCycles({}):
        resp = client.get("/cycles")
        html = resp.get_data(as_text=True)
        check(resp.status_code == 200, "vazio: 200")
        check("Nenhum ciclo gravado ainda" in html, "vazio: diz que nao ha ciclo")

    only_abort = _aborted(int(__import__("time").time()) - 60)
    with TempCycles({"x.json": only_abort}):
        html = client.get("/cycles").get_data(as_text=True)
        check("Nenhum ciclo completo na janela" in html, "so abortado: diz que nao ha completo")
        check("overview_unavailable" in html, "so abortado: mostra o motivo")

    now = int(__import__("time").time())
    files = {
        "a.json": _cycle(now - 7200, {"100": {"farm": (300.0, 20)}}),
        "b.json": _cycle(now - 3600, {"100": {"farm": (200.0, 10)}}),
    }
    with TempCycles(files):
        resp = client.get("/cycles?days=abc")
        html = resp.get_data(as_text=True)
        check(resp.status_code == 200, "days invalido nao derruba")
        check("Por fase, somando todas as aldeias" in html, "cheio: tabela de fases")
        check("Conta inteira" in html, "cheio: linha da conta")
        check('aria-current="page"' in html and 'href="/cycles"' in html, "link na navegacao")
        check(client.get("/cycles?days=999").status_code == 200, "days fora da faixa e cortado")


for fn in [
    test_missing_and_empty_dir,
    test_aborted_is_out_of_medians,
    test_village_mean_is_per_cycle_present,
    test_phase_shares_close_100,
    test_unphased_warning_threshold,
    test_window_by_start_and_unreadable_files,
    test_cache_invalidates_when_a_cycle_lands,
    test_page_renders_all_branches,
]:
    try:
        fn()
    except Exception as exc:
        failures.append(f"{fn.__name__} levantou {exc!r}")

if failures:
    print(f"FALHOU ({len(failures)} problema(s)):")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("OK: leitor de ciclos e pagina /cycles")
