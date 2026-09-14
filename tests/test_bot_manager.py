"""
BotManager do webmanager -- deteccao do processo e leitura do log de sessao.

Cobre o que mudou em 2026-09-14, quando o "Iniciar processo" do painel deixou
de ser cego:

  * adocao de um twb.py iniciado fora do painel (sem isto o painel dizia "nao
    detectado" para um bot vivo -- e o botao Iniciar subiria um SEGUNDO bot na
    mesma conta, o risco de ban que o P2-32 existia para matar);
  * leitura do `session_latest.log` (o tee do proprio twb.py) em vez do
    `bot_output.log`, que so recebia algo quando o painel redirecionava stdout;
  * o aviso de sono entre ciclos, que separa "parado de proposito" de
    "congelado num prompt de input".

Sem rede e sem processo real: `psutil.Process` e substituido por dublês e o log
e escrito num diretorio temporario. Roda sozinho, sem pytest:
    python tests/test_bot_manager.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import psutil

from webmanager.utils import BotManager

checks = 0


def check(cond, msg):
    global checks
    checks += 1
    if not cond:
        raise AssertionError(msg)


class FakeProc:
    """Dublê de psutil.Process. `raises` simula AccessDenied em cwd()."""

    def __init__(self, cmdline, cwd, running=True, status=psutil.STATUS_RUNNING, cwd_raises=False):
        self._cmdline, self._cwd = cmdline, cwd
        self._running, self._status, self._cwd_raises = running, status, cwd_raises

    def cmdline(self):
        return self._cmdline

    def cwd(self):
        if self._cwd_raises:
            raise psutil.AccessDenied(1)
        return self._cwd

    def is_running(self):
        return self._running

    def status(self):
        return self._status


REPO = BotManager.REPO_DIR


# --- reconhecimento do processo -------------------------------------------
# A linha de comando real medida em 2026-09-14, com o bot rodando: o usuario
# sobe pelo cmd com `python twb.py` e o webmanager com `python webmanager.py`.
check(BotManager._cmdline_is_twb(FakeProc(["python", "twb.py"], REPO)),
      "o twb.py iniciado na mao pelo cmd tem que ser reconhecido")
check(BotManager._cmdline_is_twb(FakeProc([sys.executable, "-u", os.path.join(REPO, "twb.py")], REPO)),
      "a forma que o painel usa (-u + caminho absoluto) tem que ser reconhecida")
check(not BotManager._cmdline_is_twb(FakeProc(["python", "webmanager.py"], REPO)),
      "o proprio webmanager nao pode ser confundido com o bot")
check(not BotManager._cmdline_is_twb(FakeProc(["python", "tests/test_bot_manager.py"], REPO)),
      "um teste que apenas importa o modulo nao e o bot")
# Casar por substring ("twb.py" in arg) pegaria isto e o painel acharia que o
# bot esta no ar por causa de um editor aberto no arquivo.
check(not BotManager._cmdline_is_twb(FakeProc(["python", "ferramenta.py", "--arquivo=twb.py"], REPO)),
      "twb.py como argumento de outro script nao e o bot")
check(not BotManager._cmdline_is_twb(FakeProc(["python", "twb.py"], os.path.join(REPO, "..", "outro-clone"))),
      "um twb.py de outro clone, noutra pasta, nao e o nosso")
check(BotManager._cmdline_is_twb(FakeProc(["python", "twb.py"], None, cwd_raises=True)),
      "cwd ilegivel nao pode virar falso negativo: o custo e subir um bot duplicado")


# --- pid morto / reciclado -------------------------------------------------
def with_fake_process(proc_or_exc, fn):
    original = psutil.Process
    psutil.Process = lambda pid: (_ for _ in ()).throw(proc_or_exc) if isinstance(proc_or_exc, Exception) else proc_or_exc
    try:
        return fn()
    finally:
        psutil.Process = original


check(with_fake_process(psutil.NoSuchProcess(123), lambda: BotManager._is_twb_process(123)) is False,
      "pid inexistente nao pode ser reportado como rodando")
check(with_fake_process(FakeProc(["python", "outra_coisa.py"], REPO), lambda: BotManager._is_twb_process(123)) is False,
      "pid reciclado pelo SO para outro processo nao pode ser reportado como rodando")
check(with_fake_process(FakeProc(["python", "twb.py"], REPO, status=psutil.STATUS_ZOMBIE),
                        lambda: BotManager._is_twb_process(123)) is False,
      "processo zumbi nao esta rodando")


# --- leitura do log de sessao ---------------------------------------------
tmp = tempfile.mkdtemp(prefix="twb_botmanager_")
session_log = os.path.join(tmp, "session_latest.log")


class TmpManager(BotManager):
    SESSION_LOG = session_log
    OUTPUT_LOG = os.path.join(tmp, "bot_output.log")


check(TmpManager.read_output_log() == [], "log inexistente devolve lista vazia, nao excecao")
check(TmpManager.output_log_age() is None, "idade de log inexistente e desconhecida, nao zero")

with open(session_log, "w", encoding="utf-8") as fh:
    fh.write("linha antiga\n\n2026-09-14 19:00:12 - Builder: BBM 003 - INFO - Building market 10 -> 11\n")

lines = TmpManager.read_output_log()
check(lines[0].startswith("2026-09-14 19:00:12"), "a linha mais recente vem primeiro (o painel renderiza nessa ordem)")
check(len(lines) == 2, "linhas em branco nao contam como output: %r" % (lines,))
check(TmpManager.output_log_age() < 60, "log recem-escrito tem idade baixa")

# Bytes NUL: o vigesimo primeiro padrao do CLAUDE.md -- um truncate concorrente
# deixa buracos de NUL no meio do arquivo, e o painel nao pode engasgar neles.
with open(session_log, "wb") as fh:
    fh.write(b"antes\n\x00\x00\x00depois\n")
check(TmpManager.read_output_log() == ["depois", "antes"], "bytes NUL tem que ser descartados sem quebrar a leitura")

# Arquivo grande: le so o fim, e a primeira linha (cortada no meio) e jogada
# fora em vez de aparecer truncada no painel.
with open(session_log, "w", encoding="utf-8") as fh:
    for i in range(20000):
        fh.write("linha %06d %s\n" % (i, "x" * 100))
tail = TmpManager.read_output_log(lines=10)
check(len(tail) == 10, "o limite de linhas e respeitado num log grande: %d" % len(tail))
check(tail[0] == "linha 019999 " + "x" * 100, "a linha mais recente do log grande e a primeira: %r" % tail[0])
check(all(l.startswith("linha ") for l in tail), "nenhuma linha cortada ao meio pode escapar: %r" % (tail,))

# Fallback para o log antigo quando nao ha sessao nenhuma ainda.
os.remove(session_log)
with open(TmpManager.OUTPUT_LOG, "w", encoding="utf-8") as fh:
    fh.write("historico de 2026-06-30\n")
check(TmpManager.read_output_log() == ["historico de 2026-06-30"],
      "sem session_latest.log, cai para o bot_output.log historico")


# --- aviso de sono entre ciclos -------------------------------------------
# Recorte verbatim do session_latest.log de 2026-09-14 (br143).
with open(session_log, "w", encoding="utf-8") as fh:
    fh.write("Dead for 11.62 minutes (next run at: 18:23:52.530554)\n")
hint = TmpManager._sleep_hint()
check(hint == {"minutes": 11.62, "next_run": "18:23:52"}, "aviso de sono real tem que ser lido: %r" % (hint,))

# So vale se for a ULTIMA linha: com o bot voltando a trabalhar, o aviso antigo
# nao pode fazer o painel dizer "dormindo" enquanto ele roda.
with open(session_log, "a", encoding="utf-8") as fh:
    fh.write("2026-09-14 18:23:53 - Village BBM 002 - INFO - Managing market\n")
check(TmpManager._sleep_hint() is None, "aviso de sono superado por atividade nao conta mais")

for name in os.listdir(tmp):
    os.remove(os.path.join(tmp, name))
os.rmdir(tmp)

print("OK - %d checks" % checks)
