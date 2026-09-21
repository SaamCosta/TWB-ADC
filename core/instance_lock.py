"""
Trava de instância única por conta (endpoint do jogo).

Motivação: dois `python twb.py` na mesma conta é risco de ban -- o jogo vê duas
sequências de requisições concorrentes, e os dois processos escrevem no mesmo
`cache/`. O webmanager já cobre o caso "o painel sobe um segundo bot" varrendo
os processos com `psutil` (22º padrão), mas isso não cobre o usuário abrindo
dois `cmd`. Esta é a trava do lado do próprio bot.

Desenho, e por que não é um PID file:

- A trava é uma **região de 1 byte** (o byte 0) de `cache/locks/<chave>.lock`,
  travada pelo **sistema operacional** (`msvcrt.locking` no Windows,
  `fcntl.flock` no resto). Isso importa porque o SO solta a trava quando o
  processo morre, inclusive em `kill -9` ou tela azul. PID file precisa de
  detecção de staleness, que erra nos dois sentidos (PID reciclado = trava
  eterna; processo vivo mal lido = dois bots).
- Os metadados (pid, início, endpoint, cwd) ficam a partir do **byte 1**, fora
  da região travada, justamente para que o segundo processo consiga lê-los e
  dizer *quem* está segurando. No Windows uma trava exclusiva impede até a
  leitura da região, então quem inspeciona precisa pular o byte 0 -- é o que
  `read_holder()` faz.

Política de falha (a assimetria é deliberada): conflito de trava = **fecha**
(não roda). Erro inesperado de I/O na própria trava = **abre** com WARNING,
porque um mecanismo de guarda quebrado não pode ser o que impede o bot de
rodar. Os dois casos são distinguíveis pelo retorno de `acquire()`.

Sem dependência de terceiros e sem rede: só stdlib.
"""

import json
import os
import re
import sys
import tempfile
import time

try:  # Windows
    import msvcrt
except ImportError:  # pragma: no cover - não existe no Windows
    msvcrt = None

try:  # POSIX
    import fcntl
except ImportError:  # pragma: no cover - não existe no POSIX
    fcntl = None


# O diretório é do USUÁRIO, não do repositório, e isso é deliberado. A trava é
# "por conta"; se o arquivo morasse em `cache/locks/` do checkout, dois clones
# do repositório apontando para a mesma conta não se enxergariam -- e a chave
# ser o endpoint viraria decoração, porque na prática só existe um config.json
# por checkout. O temp do usuário é o menor escopo que cobre "mesma pessoa,
# mesma conta, qualquer pasta". Limpador de temp apagando o arquivo é inócuo:
# o que vale é a trava do SO sobre o handle aberto, e no Windows nem dá para
# apagar um arquivo com região travada.
DEFAULT_LOCK_DIR = os.path.join(tempfile.gettempdir(), "twb-locks")

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify_key(key):
    """
    Transforma a chave da conta num nome de arquivo estável e seguro.

    `https://br143.tribalwars.com.br/game.php` -> `https-br143-tribalwars-com-br-game-php`.
    Só perde informação se duas chaves diferirem apenas por pontuação, o que
    para endpoint de mundo não acontece.
    """
    slug = _SLUG_RE.sub("-", str(key).strip().lower()).strip("-")
    return slug or "default"


class LockBusy(Exception):
    """A trava está com outro processo."""


class InstanceLock:
    """
    Trava exclusiva por chave de conta, mantida enquanto o processo viver.

    Uso:
        lock = InstanceLock(endpoint)
        if not lock.acquire():
            print(lock.describe_holder())
            sys.exit(1)

    O objeto precisa ficar vivo (referência de módulo) pelo tempo que a trava
    deve valer: se ele for coletado, o `__del__` solta a trava.
    """

    def __init__(self, key, lock_dir=None):
        self.key = str(key)
        self.lock_dir = lock_dir or DEFAULT_LOCK_DIR
        self.path = os.path.join(self.lock_dir, "%s.lock" % slugify_key(self.key))
        self.fd = None
        self.acquired = False
        # Preenchido quando `acquire()` falha por conflito; None se não deu
        # para ler (arquivo ainda sem metadados, por exemplo).
        self.holder = None
        # True quando a trava não pôde ser avaliada (erro de I/O inesperado).
        # Nesse caso `acquire()` devolve True -- fail-open com aviso.
        self.degraded = False
        self.error = None

    # -- aquisição ---------------------------------------------------------

    def acquire(self):
        """
        Tenta travar. True = pode rodar (travou, ou a trava está degradada).
        False = outro processo já está com a conta.
        """
        if self.acquired:
            return True
        try:
            os.makedirs(self.lock_dir, exist_ok=True)
            self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        except OSError as exc:
            self.degraded = True
            self.error = exc
            return True

        try:
            _lock_first_byte(self.fd)
        except LockBusy:
            self.holder = self.read_holder()
            self._close()
            return False
        except OSError as exc:
            # Não é conflito: sistema de arquivos que não suporta trava (rede,
            # alguns containers). Fail-open com aviso -- ver o docstring.
            self.degraded = True
            self.error = exc
            self._close()
            return True

        self.acquired = True
        self._write_metadata()
        return True

    def release(self):
        """Solta a trava. Idempotente."""
        if self.fd is not None and self.acquired:
            try:
                _unlock_first_byte(self.fd)
            except OSError:
                pass
        self.acquired = False
        self._close()

    def _close(self):
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.release()

    def __del__(self):  # pragma: no cover - depende do GC
        try:
            self.release()
        except Exception:
            pass

    # -- metadados ---------------------------------------------------------

    def _write_metadata(self):
        payload = json.dumps(
            {
                "pid": os.getpid(),
                "key": self.key,
                "started_at": time.time(),
                "cwd": os.getcwd(),
                "argv": sys.argv,
            }
        ).encode("utf-8")
        try:
            os.lseek(self.fd, 1, os.SEEK_SET)
            os.write(self.fd, payload)
            os.ftruncate(self.fd, 1 + len(payload))
        except OSError:
            # Metadado é conveniência de diagnóstico; a trava já vale sem ele.
            pass

    def read_holder(self):
        """
        Lê os metadados de quem segura a trava, ou None.

        Abre um handle próprio e começa no byte 1: o byte 0 está travado e,
        no Windows, nem leitura passa por ele.
        """
        try:
            with open(self.path, "rb") as handle:
                handle.seek(1)
                raw = handle.read()
            if not raw:
                return None
            return json.loads(raw.decode("utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            return None

    def describe_holder(self):
        """Uma linha legível sobre o dono atual, para imprimir ao recusar."""
        holder = self.holder or self.read_holder()
        if not holder:
            return (
                "Outro processo já está rodando esta conta (%s), mas ele não "
                "deixou metadados em %s." % (self.key, self.path)
            )
        started = holder.get("started_at")
        when = (
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started))
            if isinstance(started, (int, float))
            else "?"
        )
        return "Outro processo já está rodando esta conta (%s): pid %s, iniciado em %s, cwd %s" % (
            self.key,
            holder.get("pid", "?"),
            when,
            holder.get("cwd", "?"),
        )


def _lock_first_byte(fd):
    """
    Trava exclusiva e não-bloqueante sobre o byte 0. Levanta `LockBusy` se
    outro processo já tem, e `OSError` para qualquer outra falha.
    """
    if msvcrt is not None:
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            # Medido no Windows 10 / Python 3.13 em 2026-09-20 com dois
            # processos de verdade: vem `PermissionError(13)`, sem `winerror`.
            # A documentação do CRT descreve EDEADLOCK (36) para o caso
            # bloqueante que esgota as tentativas, então os dois entram.
            if exc.errno in (13, 36):
                raise LockBusy() from exc
            raise
        return
    if fcntl is not None:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            # EACCES/EAGAIN = ocupado.
            if exc.errno in (11, 13, 35):
                raise LockBusy() from exc
            raise
        return
    raise OSError("nem msvcrt nem fcntl disponíveis nesta plataforma")


def _unlock_first_byte(fd):
    if msvcrt is not None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        return
    if fcntl is not None:
        fcntl.flock(fd, fcntl.LOCK_UN)
