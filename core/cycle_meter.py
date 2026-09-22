"""
P-CICLO-MEDIDA -- para onde vao as ~4h de um ciclo.

Contexto: docs/backend.md 9 (item 3 da fila anterior: "capturar baseline ...
duracao de ciclo") e 8.14/8.15, que mediram o ciclo em ~4h com 30 aldeias e
reorganizaram a conquista em volta disso -- sem que ninguem soubesse ONDE
essas 4h estavam.

O QUE JA SE SABIA, E POR QUE NAO BASTA
--------------------------------------
`WebWrapper.get_url`/`post_url` dormem `randint(3*delay, 7*delay)` antes de
cada requisicao. Com `bot.delay_factor = 3` (config vivo em 2026-09-22) sao
9-21 s por requisicao, e o log de sessao mostra requisicoes a 13-17 s uma da
outra. Ou seja: a duracao do ciclo e, quase inteira, *numero de requisicoes x
~15 s*. Encurtar o ciclo e cortar requisicao -- e para cortar e preciso saber
QUAIS fases as gastam. O log tem cada GET em DEBUG, mas nao diz a que fase
ele pertence, e o `session_latest.log` e truncado a cada reinicio.

MODELO
------
Uma pilha de fases. Cada requisicao e atribuida a fase do TOPO da pilha, e o
tempo de parede de cada fase e EXCLUSIVO (o tempo gasto numa subfase nao e
contado de novo na fase-mae). Com isso a soma de todos os baldes fecha o
total do ciclo -- percentuais somam 100% e nenhuma fase aparece "maior" por
conter outra. O que acontece fora de qualquer fase nomeada cai no balde
`(sem fase)`, em vez de sumir: um balde grande ali e sinal de instrumentacao
faltando, nao de tempo inexplicavel.

Isto e observabilidade pura: nada aqui altera o que o bot faz, e uma falha
ao fechar/gravar o resumo nunca derruba o ciclo (ver `close_and_report`).
"""
import logging
import time
from contextlib import contextmanager, nullcontext

from core.filemanager import FileManager

logger = logging.getLogger("CycleMeter")

CACHE_DIR = "cache/cycles"
# ~4h por ciclo + 10 min de pausa: 300 arquivos cobrem ~50 dias, acima dos
# 7-14 dias que o baseline da docs/backend.md 9 pede.
KEEP_FILES = 300
UNPHASED = "(sem fase)"


def _new_bucket():
    return {
        "wall": 0.0,
        "requests": 0,
        "gets": 0,
        "posts": 0,
        "failed": 0,
        "sleep": 0.0,
        "net": 0.0,
        "captcha": 0.0,
    }


def _hms(seconds):
    seconds = int(round(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return "%dh%02d" % (hours, minutes)
    if minutes:
        return "%dmin%02d" % (minutes, secs)
    return "%ds" % secs


class CycleMeter:
    """Contabilidade de tempo e requisicoes por (aldeia, fase) num ciclo."""

    def __init__(self, clock=time.monotonic, wall_clock=time.time):
        self._clock = clock
        self._wall_clock = wall_clock
        # Tudo mutavel em __init__ (primeiro padrao do CLAUDE.md).
        self.buckets = {}
        self._stack = []
        self.active = False
        self.started_at = None
        self._started_mono = None
        self._resumed = None
        # Requisicoes feitas fora de um ciclo aberto (startup, o Hunter que
        # roda depois do sono). Nao pertencem a ciclo nenhum, mas contar evita
        # que elas desaparecam sem rastro.
        self.outside_requests = 0

    # -- ciclo ---------------------------------------------------------------

    def begin_cycle(self):
        """Abre um ciclo novo. Descarta qualquer estado de ciclo anterior --
        inclusive uma pilha suja deixada por uma excecao no meio do laco."""
        now = self._clock()
        self.buckets = {}
        self._stack = [(None, UNPHASED)]
        self.active = True
        self.started_at = self._wall_clock()
        self._started_mono = now
        self._resumed = now
        outside, self.outside_requests = self.outside_requests, 0
        return outside

    def end_cycle(self, extra=None):
        """Fecha o ciclo e devolve o resumo (dict serializavel), ou None se
        nenhum ciclo estava aberto."""
        if not self.active:
            return None
        now = self._clock()
        self._charge_top(now)
        self.active = False
        self._stack = []
        total = now - self._started_mono
        rows = []
        for (village, phase), b in self.buckets.items():
            row = {"village": village, "phase": phase}
            row.update({k: (round(v, 2) if isinstance(v, float) else v) for k, v in b.items()})
            rows.append(row)
        rows.sort(key=lambda r: -r["wall"])
        summary = {
            "started_at": int(self.started_at),
            "ended_at": int(self._wall_clock()),
            "total_seconds": round(total, 2),
            "requests": sum(r["requests"] for r in rows),
            "sleep_seconds": round(sum(r["sleep"] for r in rows), 2),
            "net_seconds": round(sum(r["net"] for r in rows), 2),
            "captcha_seconds": round(sum(r["captcha"] for r in rows), 2),
            "buckets": rows,
        }
        if extra:
            summary.update(extra)
        return summary

    # -- fases ---------------------------------------------------------------

    def _bucket(self, village, phase):
        key = (village, phase)
        if key not in self.buckets:
            self.buckets[key] = _new_bucket()
        return self.buckets[key]

    def _charge_top(self, now):
        """Credita ao topo da pilha o tempo desde a ultima retomada."""
        if not self._stack:
            return
        village, phase = self._stack[-1]
        self._bucket(village, phase)["wall"] += now - self._resumed
        self._resumed = now

    @contextmanager
    def phase(self, name, village=None):
        """Marca uma fase. Aninhavel; fora de ciclo aberto e um no-op.

        `village=None` numa subfase herda a aldeia da fase-mae, para que o
        `builder` chamado de dentro da aldeia 41123 caia em (41123, builder)
        sem que cada chamador precise repetir o id. Fases de conta inteira
        (Hunter, quadro de reservas) passam `village=False` para NAO herdar.
        """
        if not self.active:
            yield
            return
        if village is None:
            village = self._stack[-1][0] if self._stack else None
        elif village is False:
            village = None
        self._charge_top(self._clock())
        depth = len(self._stack)
        self._stack.append((village, name))
        try:
            yield
        finally:
            if self.active and len(self._stack) > depth:
                self._charge_top(self._clock())
                del self._stack[depth:]

    # -- requisicoes ---------------------------------------------------------

    def record_request(self, method, slept=0.0, net=0.0, captcha=0.0, ok=True):
        if not self.active or not self._stack:
            self.outside_requests += 1
            return
        village, phase = self._stack[-1]
        b = self._bucket(village, phase)
        b["requests"] += 1
        if method == "POST":
            b["posts"] += 1
        else:
            b["gets"] += 1
        if not ok:
            b["failed"] += 1
        b["sleep"] += slept
        b["net"] += net
        b["captcha"] += captcha


def meter_phase(wrapper, name, village=None):
    """`with meter_phase(self.wrapper, "farm"):` -- tolera wrapper sem medidor
    (testes com wrapper de mentira, webmanager) virando no-op. O `isinstance`
    e de proposito: um `MagicMock` tem `.meter` e devolveria um mock que nao
    e context manager."""
    meter = getattr(wrapper, "meter", None)
    if not isinstance(meter, CycleMeter):
        return nullcontext()
    return meter.phase(name, village=village)


def by_phase(summary):
    """Agrega os baldes por fase, somando todas as aldeias."""
    agg = {}
    for row in summary.get("buckets", []):
        a = agg.setdefault(row["phase"], _new_bucket())
        for key in a:
            a[key] += row[key]
    return sorted(agg.items(), key=lambda kv: -kv[1]["wall"])


def by_village(summary):
    """Agrega os baldes por aldeia (None = fases de conta inteira)."""
    agg = {}
    for row in summary.get("buckets", []):
        a = agg.setdefault(row["village"], _new_bucket())
        for key in a:
            a[key] += row[key]
    return sorted(agg.items(), key=lambda kv: -kv[1]["wall"])


def format_summary(summary, top=6):
    """Duas linhas de log legiveis: o total e as fases que dominam."""
    total = summary["total_seconds"] or 1.0
    villages = [v for v, _ in by_village(summary) if v is not None]
    head = (
        "Ciclo: %s em %d aldeia(s), %d requisicao(oes); dormindo antes delas "
        "%s (%.0f%%), rede %s"
        % (
            _hms(summary["total_seconds"]), len(villages), summary["requests"],
            _hms(summary["sleep_seconds"]),
            100.0 * summary["sleep_seconds"] / total,
            _hms(summary["net_seconds"]),
        )
    )
    if summary.get("captcha_seconds"):
        head += ", captcha %s" % _hms(summary["captcha_seconds"])
    parts = []
    for phase, b in by_phase(summary)[:top]:
        parts.append(
            "%s %.0f%% (%d req)" % (phase, 100.0 * b["wall"] / total, b["requests"])
        )
    return head, "Ciclo por fase: " + ", ".join(parts)


def save_summary(summary):
    """Grava `cache/cycles/<inicio>.json` e poda para os KEEP_FILES mais novos."""
    FileManager.create_directories([CACHE_DIR])
    name = "%s/%d.json" % (CACHE_DIR, summary["started_at"])
    FileManager.save_json_file(summary, name)
    files = sorted(
        FileManager.list_directory(CACHE_DIR, ends_with=".json") or [],
        key=lambda f: int(f.split(".")[0]) if f.split(".")[0].isdigit() else 0,
    )
    for old in files[:-KEEP_FILES]:
        FileManager.remove_file("%s/%s" % (CACHE_DIR, old))
    return name


def close_and_report(meter, extra=None):
    """Fecha o ciclo, loga o resumo e persiste. Nunca levanta."""
    try:
        summary = meter.end_cycle(extra=extra)
        if not summary:
            return None
        head, phases = format_summary(summary)
        logger.info(head)
        logger.info(phases)
        save_summary(summary)
        return summary
    except Exception as exc:
        logger.warning("Medidor de ciclo falhou ao fechar: %s", exc)
        return None
