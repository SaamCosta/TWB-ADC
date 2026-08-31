"""
Guarda de regressao: importar twb.py NAO pode truncar
cache/logs/session_latest.log.

O QUE ACONTECEU (2026-08-31). O bloco de captura de sessao no topo de twb.py
abria o arquivo com open(..., "w") direto no corpo do modulo, ou seja no
IMPORT. Como tests/test_village_purge_guard.py importa purge_refusal_reason
dali, rodar a suite de testes apagava o log da ultima sessao real do bot --
467 KB de historico de producao, em silencio, e sem nenhuma relacao aparente
com o que se estava fazendo. O dano so apareceu porque a analise seguinte foi
justamente ler esse log e encontrar nele a saida de um teste.

E o terceiro padrao do CLAUDE.md invertido: nao e codigo morto que nunca roda,
e codigo de efeito colateral que roda em contexto onde ninguem o pediu.

Rodar: python tests/test_session_log_guard.py
"""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


def test_importing_twb_does_not_truncate_the_session_log():
    """
    Roda num subprocesso porque o efeito e no import, e o import de twb ja
    pode ter acontecido neste processo por outro teste.
    """
    log_dir = os.path.join(ROOT, "cache", "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "session_latest.log")

    saved = None
    if os.path.exists(log_path):
        with open(log_path, "rb") as fh:
            saved = fh.read()

    sentinel = b"SENTINELA test_session_log_guard -- nao deveria ser apagada\n"
    try:
        with open(log_path, "wb") as fh:
            fh.write(sentinel)

        proc = subprocess.run(
            [sys.executable, "-c", "import twb"],
            cwd=ROOT, capture_output=True, timeout=120,
        )
        check(proc.returncode == 0,
              f"`import twb` falhou: {proc.stderr.decode('utf-8', 'replace')[:400]}")

        with open(log_path, "rb") as fh:
            after = fh.read()
        check(after == sentinel,
              "importar twb.py alterou cache/logs/session_latest.log "
              f"({len(sentinel)} bytes antes, {len(after)} depois) -- o open(...,'w') "
              "voltou a rodar no import e vai apagar log de producao")
    finally:
        # Restaura o que existia, inclusive se o teste falhou.
        if saved is not None:
            with open(log_path, "wb") as fh:
                fh.write(saved)
        elif os.path.exists(log_path):
            os.remove(log_path)


def test_tee_still_installs_when_run_as_main():
    """
    O guard nao pode ter matado a funcionalidade: rodando twb.py como script,
    a captura tem que continuar existindo. Verificado sem subir o bot --
    executa o topo do arquivo ate a linha do tee, num diretorio temporario,
    e confirma que o arquivo foi criado e que stdout virou o tee.
    """
    with open(os.path.join(ROOT, "twb.py"), encoding="utf-8") as fh:
        source = fh.read()
    marker = "# --- End session log capture"
    check(marker in source, "o bloco de captura de sessao sumiu de twb.py")
    header = source.split(marker)[0]
    check("if __name__ == \"__main__\":" in header,
          "o bloco de captura precisa estar sob `if __name__ == \"__main__\"`, "
          "senao volta a truncar o log no import")

    with tempfile.TemporaryDirectory() as tmp:
        probe = os.path.join(tmp, "probe.py")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write(header)
            fh.write(
                "\nimport sys, os\n"
                "assert type(sys.stdout).__name__ == '_TeeStream', "
                "'o tee nao foi instalado ao rodar como __main__'\n"
                "print('tee ok')\n"
                "assert os.path.exists(os.path.join(_LOG_DIR, 'session_latest.log'))\n"
            )
        proc = subprocess.run([sys.executable, probe], cwd=tmp,
                              capture_output=True, timeout=60)
        check(proc.returncode == 0,
              "o bloco de captura nao funciona mais quando rodado como script: "
              f"{proc.stderr.decode('utf-8', 'replace')[:400]}")


for fn in [
    test_importing_twb_does_not_truncate_the_session_log,
    test_tee_still_installs_when_run_as_main,
]:
    fn()

if failures:
    print(f"FALHOU ({len(failures)} problema(s)):")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("OK: importar twb.py nao destroi o log de sessao")
