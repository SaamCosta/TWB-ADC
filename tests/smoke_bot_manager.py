"""
Smoke end-to-end do BotManager com processo real, num repo falso.

Nao encosta na conta do jogo: o "twb.py" aqui e um script que so escreve no
log e dorme. Exercita o que o teste unitario nao alcanca -- console novo,
adocao por outra instancia (webmanager reiniciado), recusa de subir um segundo
bot, leitura do log ao vivo e stop().

**Nao se chama `test_*.py` de proposito:** o runner da suite roda
`tests/test_*.py` em lote, e este aqui abre janelas de console de verdade e
leva ~5 s. Rodar na mao ao mexer em `BotManager`:
    python tests/smoke_bot_manager.py

Vale o passo extra: a primeira versao deste smoke acusou "subiu um segundo
bot", e o culpado era o proprio decoy, que nao compilava. Se este arquivo
falhar, conferir antes de tudo se o processo filho nasceu vivo -- com
CREATE_NEW_CONSOLE o traceback morre junto com a janela.
"""
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from webmanager.utils import BotManager

DECOY = "\n".join([
    "import os, time",
    "log = os.path.join('cache', 'logs', 'session_latest.log')",
    "for i in range(600):",
    "    with open(log, 'a', encoding='utf-8') as fh:",
    "        fh.write('linha %d' % i + chr(10))",
    "    print(i)",
    "    time.sleep(0.5)",
    "",
])

repo = tempfile.mkdtemp(prefix="twb_fake_repo_")
os.makedirs(os.path.join(repo, "cache", "logs"))
with open(os.path.join(repo, "twb.py"), "w", encoding="utf-8") as fh:
    fh.write(DECOY)


class Fake(BotManager):
    REPO_DIR = repo
    PID_FILE = os.path.join(repo, "cache", "bot.pid")
    SESSION_LOG = os.path.join(repo, "cache", "logs", "session_latest.log")
    OUTPUT_LOG = os.path.join(repo, "cache", "logs", "bot_output.log")


def brief(status):
    return {k: v for k, v in status.items() if k != "started_at"}


try:
    bm = Fake()
    assert not bm.status()["running"], "repo limpo nao pode ter bot rodando"
    print("antes de iniciar : parado, como esperado")

    st = bm.start()
    assert st["running"], "start() nao subiu o processo: %r" % (st,)
    assert st["started_by_panel"], "processo iniciado pelo painel tem que ser marcado como tal"
    print("apos start       :", brief(st))
    time.sleep(2.5)
    assert bm.status()["running"], "processo morreu logo depois de subir"

    # Outra instancia = webmanager reiniciado, ou bot iniciado pelo cmd.
    outra = Fake()
    st2 = outra.status()
    assert st2["running"], "outra instancia tem que ADOTAR o processo vivo: %r" % (st2,)
    assert st2["pid"] == st["pid"], "adotou o pid errado"
    assert not st2["started_by_panel"], "processo nao iniciado por esta instancia nao pode se dizer dela"
    print("outra instancia  :", brief(st2))

    # O que protege a conta: com um bot vivo, start() nao pode subir outro.
    outra.start()
    assert outra.pid == st["pid"], "SUBIU UM SEGUNDO BOT (pid %s vs %s)" % (outra.pid, st["pid"])
    print("segundo start    : recusado, mesmo pid %d" % outra.pid)

    linhas = outra.read_output_log(lines=3)
    assert linhas and linhas[0].startswith("linha "), "log ao vivo nao chegou: %r" % (linhas,)
    assert outra.status()["log_age"] < 10, "log deveria estar fresco"
    print("output ao vivo   :", linhas[:2])

    outra.stop()
    time.sleep(1.0)
    final = outra.status()
    assert not final["running"], "stop() nao encerrou o processo: %r" % (final,)
    assert not os.path.exists(Fake.PID_FILE), "pid file tem que sumir depois do stop"
    print("apos stop        :", brief(final))
    print("OK - smoke end-to-end passou")
finally:
    try:
        Fake().stop()
    except Exception:
        pass
    shutil.rmtree(repo, ignore_errors=True)
