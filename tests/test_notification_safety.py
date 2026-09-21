"""
Testes do `core/notification.py`: sem I/O no import, e `send()` que nunca levanta.

MOTIVACAO, duas metades independentes.

1. **I/O no corpo do modulo.** O arquivo termina em `Notification =
   _Notification()`, e o `__init__` lia `config.json`. Ou seja, todo
   `import core.notification` -- que acontece em `core/request.py`, em `twb.py`
   e portanto em varios testes e no webmanager -- abria o config em disco. E o
   vigesimo padrao do CLAUDE.md (efeito no corpo do modulo, que dispara no
   import) na sua versao inofensiva; a versao cara do mesmo padrao truncou 467
   KB de log em 2026-08-31. De brinde, ler preguicosamente faz
   `notifications.enabled` valer ao vivo, sem reiniciar o bot.

2. **`send()` propagava.** `telegram` faz rede e rede falha. Os dois piores
   chamadores sao justamente os dois que existem:
   - `twb.py` chama `Notification.send("TWB crashed: ...")` de DENTRO de um
     `except`. Uma excecao secundaria ali escapa do laco de retry: o bot **sai**
     em vez de reiniciar. O fork LazyTurtle registra isso acontecendo em
     2026-08-03 (`telegram.error.TimedOut` transformando um ciclo perdido em
     parada total).
   - `core/request.py` chama no caminho de bot protection, que esta dentro do
     `try` do `get_url`: a excecao vira um "GET falhou" generico e a espera do
     captcha nunca acontece -- o motivo real some do log.

Rodar: python tests/test_notification_safety.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.notification as notification_module
from core.notification import _Notification

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


class CountingFileManager:
    def __init__(self, config=None):
        self.config = config
        self.reads = 0

    def load_json_file(self, path):
        self.reads += 1
        return self.config


class ExplodingTelegram:
    @staticmethod
    def Bot(token=None):
        raise ValueError("Invalid token")


class _RealFileManagerGuard:
    """Troca o FileManager do modulo e devolve o original no fim."""

    def __init__(self, fm):
        self.fm = fm

    def __enter__(self):
        self.original = notification_module.FileManager
        notification_module.FileManager = self.fm
        return self.fm

    def __exit__(self, *exc):
        notification_module.FileManager = self.original


ENABLED = {"notifications": {"enabled": True, "token": "123:abc", "channel_id": "-1"}}
DISABLED = {"notifications": {"enabled": False}}


def test_construir_nao_le_config():
    fm = CountingFileManager(ENABLED)
    with _RealFileManagerGuard(fm):
        _Notification()
    check(fm.reads == 0,
          "o __init__ leu config.json %d vez(es); tem que ser preguicoso" % fm.reads)


def test_desabilitado_nao_constroi_bot():
    fm = CountingFileManager(DISABLED)
    with _RealFileManagerGuard(fm):
        notifier = _Notification()
        notifier.send("oi")
    check(fm.reads == 1, "send() devia reler o config uma vez, leu %d" % fm.reads)
    check(notifier.bot is None and notifier.loop is None,
          "notificacao desligada nao devia construir bot nem event loop")


def test_config_relida_a_cada_send():
    """`enabled` passa a valer ao vivo: e o efeito colateral bom da preguica."""
    fm = CountingFileManager(DISABLED)
    with _RealFileManagerGuard(fm):
        notifier = _Notification()
        notifier.send("um")
        check(notifier.enabled is False, "deveria comecar desligado")
        fm.config = ENABLED
        original_telegram = notification_module.telegram
        notification_module.telegram = ExplodingTelegram
        try:
            notifier.send("dois")
        finally:
            notification_module.telegram = original_telegram
    check(notifier.enabled is True,
          "ligar no config nao teve efeito sem reiniciar")


def test_token_invalido_nao_levanta():
    # telegram.Bot(token=...) levanta na hora com token malformado, e isso
    # acontecia ANTES de qualquer try/except na versao antiga.
    fm = CountingFileManager(ENABLED)
    original_telegram = notification_module.telegram
    notification_module.telegram = ExplodingTelegram
    try:
        with _RealFileManagerGuard(fm):
            notifier = _Notification()
            notifier.send("oi")
    except Exception as exc:
        failures.append("send() propagou %s: %s" % (type(exc).__name__, exc))
    finally:
        notification_module.telegram = original_telegram


def test_falha_de_rede_no_envio_nao_levanta():
    class ExplodingLoop:
        def create_task(self, coro):
            coro.close()
            raise RuntimeError("telegram timeout")

        def run_until_complete(self, task):
            raise AssertionError("nao deveria chegar aqui")

    fm = CountingFileManager(ENABLED)
    try:
        with _RealFileManagerGuard(fm):
            notifier = _Notification()
            notifier._ensure_bot = lambda: True
            notifier.loop = ExplodingLoop()
            notifier.send("oi")
    except Exception as exc:
        failures.append("send() propagou %s: %s" % (type(exc).__name__, exc))


def test_config_invalido_nao_levanta():
    from core.exceptions import InvalidJSONException

    class BrokenFileManager:
        def load_json_file(self, path):
            raise InvalidJSONException

    try:
        with _RealFileManagerGuard(BrokenFileManager()):
            notifier = _Notification()
            notifier.send("oi")
            check(notifier.enabled is False,
                  "config ilegivel devia deixar a notificacao desligada")
    except Exception as exc:
        failures.append("send() propagou com config invalido: %s" % exc)


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except Exception as exc:
                failures.append("%s levantou %s: %s"
                                % (name, type(exc).__name__, exc))
    if failures:
        print("FAIL (%d)" % len(failures))
        for f in failures:
            print("  - %s" % f)
        sys.exit(1)
    print("OK - Notification preguicoso e a prova de falha")
