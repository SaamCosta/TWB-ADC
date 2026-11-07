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

    NAO ESCREVE NO LOG REAL -- e a versao anterior deste teste escrevia, o que
    o transformava na propria coisa que ele existe para impedir. Ela salvava o
    conteudo, truncava o arquivo para gravar uma sentinela, e restaurava no
    finally. Com o BOT RODANDO isso e destrutivo e racy: o processo do bot tem
    um handle aberto e continua escrevendo no offset dele, entao o truncate
    deixa um buraco de bytes NUL no meio do log e tudo que o bot logou durante
    a janela do teste e perdido no restore. Aconteceu em 2026-08-31 (133 bytes
    NUL, medidos) e o teste ainda reportou falha enganosa -- "o import alterou
    o arquivo" -- quando quem tinha alterado era o bot, escrevendo normalmente.

    A observacao que torna o teste seguro: truncar FAZ O ARQUIVO ENCOLHER, e o
    bot so faz crescer. Entao comparar tamanho e cabecalho detecta a regressao
    sem tocar em nada. Quando o log nao existe nao ha o que perder, e ai a
    assercao forte com sentinela e usada.
    """
    log_dir = os.path.join(ROOT, "cache", "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "session_latest.log")

    if not os.path.exists(log_path):
        # Sem log de producao em risco: da para ser exato.
        sentinel = b"SENTINELA test_session_log_guard -- nao deveria ser apagada\n"
        try:
            with open(log_path, "wb") as fh:
                fh.write(sentinel)
            proc = subprocess.run([sys.executable, "-c", "import twb"],
                                  cwd=ROOT, capture_output=True, timeout=120)
            check(proc.returncode == 0,
                  f"`import twb` falhou: {proc.stderr.decode('utf-8', 'replace')[:400]}")
            with open(log_path, "rb") as fh:
                after = fh.read()
            check(after == sentinel,
                  "importar twb.py alterou cache/logs/session_latest.log -- o "
                  "open(...,'w') voltou a rodar no import")
        finally:
            if os.path.exists(log_path):
                os.remove(log_path)
        return

    # Log de producao presente (bot pode estar rodando): so observa.
    size_before = os.path.getsize(log_path)
    with open(log_path, "rb") as fh:
        head_before = fh.read(512)

    proc = subprocess.run([sys.executable, "-c", "import twb"],
                          cwd=ROOT, capture_output=True, timeout=120)
    check(proc.returncode == 0,
          f"`import twb` falhou: {proc.stderr.decode('utf-8', 'replace')[:400]}")

    size_after = os.path.getsize(log_path)
    with open(log_path, "rb") as fh:
        head_after = fh.read(512)

    check(size_after >= size_before,
          f"cache/logs/session_latest.log ENCOLHEU no import ({size_before} -> "
          f"{size_after} bytes). O bot so faz o arquivo crescer, entao encolher "
          "significa que o open(...,'w') voltou a rodar no import de twb.py")
    check(head_after == head_before,
          "o inicio de cache/logs/session_latest.log mudou durante `import twb` "
          "-- o arquivo foi reaberto em modo de escrita no import")


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
        # PYTHONPATH=ROOT porque o cabecalho passou a importar
        # core.instance_lock (a trava de instancia unica precisa vir ANTES do
        # open(...,"w") do tee, senao um segundo bot trunca o log do primeiro
        # antes de ser recusado). O twb.py de verdade sempre roda da raiz do
        # repositorio, onde `core` e importavel; o probe roda num tmp, entao
        # precisa do caminho explicito.
        env = dict(os.environ, PYTHONPATH=ROOT)
        proc = subprocess.run([sys.executable, probe], cwd=tmp,
                              capture_output=True, timeout=60, env=env)
        check(proc.returncode == 0,
              "o bloco de captura nao funciona mais quando rodado como script: "
              f"{proc.stderr.decode('utf-8', 'replace')[:400]}")


def test_main_keeps_the_previous_session_log():
    """
    §8.89.5: rodando como script, o log anterior vira session_prev_<inicio>.log
    antes do open(...,"w"). Mesmo probe do teste acima, num tmp que ja tem um
    session_latest.log -- nada do cache/logs real e tocado.
    """
    with open(os.path.join(ROOT, "twb.py"), encoding="utf-8") as fh:
        header = fh.read().split("# --- End session log capture")[0]
    with tempfile.TemporaryDirectory() as tmp:
        log_dir = os.path.join(tmp, "cache", "logs")
        os.makedirs(log_dir)
        with open(os.path.join(log_dir, "session_latest.log"), "w", encoding="utf-8") as fh:
            fh.write("2026-11-07 06:59:14 - root - INFO - sessao anterior\n")
        probe = os.path.join(tmp, "probe.py")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write(header + "\nprint('sessao nova')\n")
        env = dict(os.environ, PYTHONPATH=ROOT)
        proc = subprocess.run([sys.executable, probe], cwd=tmp,
                              capture_output=True, timeout=60, env=env)
        check(proc.returncode == 0,
              f"o topo do twb.py falhou: {proc.stderr.decode('utf-8', 'replace')[:400]}")
        prev = os.path.join(log_dir, "session_prev_20261107_065914.log")
        check(os.path.exists(prev),
              f"o log anterior nao foi guardado: {sorted(os.listdir(log_dir))}")
        if os.path.exists(prev):
            with open(prev, encoding="utf-8") as fh:
                check("sessao anterior" in fh.read(), "o log guardado nao e o anterior")
        with open(os.path.join(log_dir, "session_latest.log"), encoding="utf-8") as fh:
            latest = fh.read()
        check("sessao nova" in latest and "sessao anterior" not in latest,
              "o session_latest.log nao comecou do zero")


for fn in [
    test_importing_twb_does_not_truncate_the_session_log,
    test_tee_still_installs_when_run_as_main,
    test_main_keeps_the_previous_session_log,
]:
    fn()

if failures:
    print(f"FALHOU ({len(failures)} problema(s)):")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("OK: importar twb.py nao destroi o log de sessao")
