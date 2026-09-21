"""
Smoke de ponta a ponta: `python twb.py` recusa iniciar quando a conta ja tem
dono, e recusa ANTES de truncar cache/logs/session_latest.log.

FORA do glob `tests/test_*.py` de proposito: copia o repositorio, sobe um
processo Python de verdade e toma a trava da conta real por alguns segundos.
Rodar na mao ao mexer em core/instance_lock.py ou no bloco do topo de twb.py.

    python tests/smoke_instance_lock_twb.py

POR QUE UMA COPIA. Nao da para rodar `python twb.py` no proprio repositorio
para testar isto: o tee do topo abre o log de sessao com "w" e o TRUNCA. Se a
trava falhar, o teste destroi o log do bot que estiver rodando -- ou seja, o
teste seria a propria coisa que ele existe para impedir (21o padrao). A copia
tem cache/ proprio, entao o unico log em risco e o dela.

O que a copia NAO isola e a trava, e isso e o ponto: o arquivo de trava mora no
temp do usuario e a chave e o endpoint do config.json, que a copia herda. Se o
teste passa, esta provado que a trava atravessa pastas diferentes.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.instance_lock import InstanceLock  # noqa: E402

failures = []


def check(cond, msg):
    print(("  ok   " if cond else "  FALHA") + " " + msg)
    if not cond:
        failures.append(msg)


def read_key():
    try:
        with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as handle:
            return json.load(handle)["server"]["endpoint"]
    except (OSError, ValueError, KeyError, TypeError):
        return ROOT


def copy_repo(dest):
    shutil.copytree(
        ROOT,
        dest,
        ignore=shutil.ignore_patterns(
            ".git", "__pycache__", "cache", ".claude", "*.pyc"
        ),
    )
    os.makedirs(os.path.join(dest, "cache", "logs"), exist_ok=True)
    sentinel = os.path.join(dest, "cache", "logs", "session_latest.log")
    with open(sentinel, "w", encoding="utf-8") as handle:
        handle.write("SENTINELA-NAO-PODE-SUMIR\n")
    return sentinel


def run_twb_integrity_check(cwd):
    """`-i` faz o bot sair logo apos o startup, sem tocar na rede."""
    return subprocess.run(
        [sys.executable, "twb.py", "-i"],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
    )


def main():
    key = read_key()
    print("chave da conta: %s" % key)
    tmp = tempfile.mkdtemp(prefix="twb-smoke-")
    copy_dir = os.path.join(tmp, "repo")
    sentinel = copy_repo(copy_dir)
    print("copia em: %s" % copy_dir)

    holder = InstanceLock(key)
    print("\n[1] tomando a trava da conta neste processo (pid %d)" % os.getpid())
    check(holder.acquire() is True, "este processo tomou a trava")
    check(holder.degraded is False, "a trava nao saiu degradada (%s)" % holder.error)

    try:
        print("\n[2] `python twb.py -i` na copia, com a conta ja ocupada")
        out = run_twb_integrity_check(copy_dir)
        combined = out.stdout + out.stderr
        check(out.returncode == 1, "saiu com codigo 1 (foi %s)" % out.returncode)
        check(
            "ja existe um bot nesta conta" in combined,
            "explicou o motivo na saida",
        )
        check(str(os.getpid()) in combined, "citou o pid do dono (%d)" % os.getpid())
        with open(sentinel, encoding="utf-8") as handle:
            body = handle.read()
        check(
            "SENTINELA-NAO-PODE-SUMIR" in body,
            "NAO truncou o log de sessao -- recusou antes do tee",
        )
        if failures:
            print("\n--- saida do processo recusado ---")
            print(combined.strip()[:2000])
    finally:
        holder.release()

    print("\n[3] mesma copia, agora com a conta livre")
    time.sleep(0.2)
    out = run_twb_integrity_check(copy_dir)
    combined = out.stdout + out.stderr
    check(
        out.returncode == 0,
        "startup normal passa pela trava (codigo %s)" % out.returncode,
    )
    check(
        "ja existe um bot nesta conta" not in combined,
        "nao recusou com a conta livre",
    )
    if out.returncode != 0:
        print("\n--- saida ---")
        print(combined.strip()[:2000])

    shutil.rmtree(tmp, ignore_errors=True)

    print()
    if failures:
        print("SMOKE FALHOU (%d)" % len(failures))
        sys.exit(1)
    print("smoke_instance_lock_twb: OK")


if __name__ == "__main__":
    main()
