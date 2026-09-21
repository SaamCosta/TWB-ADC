"""
Trava de instancia unica por conta (core/instance_lock.py).

POR QUE EXISTE. Dois `python twb.py` na mesma conta = duas sequencias de
requisicoes concorrentes (risco de ban) e duas escritas no mesmo cache/. O
webmanager ja cobria "o painel sobe um segundo bot" varrendo processos com
psutil (22o padrao do CLAUDE.md); o que faltava era a trava do lado do proprio
bot, para dois `cmd` abertos na mao.

O TESTE PRECISA DE SUBPROCESSO. Uma trava de arquivo do SO e reentrante dentro
do mesmo processo: travar o mesmo byte duas vezes no mesmo `python` nao
conflita, entao um teste in-process nao conseguiria distinguir "a trava
funciona" de "a trava e no-op" -- que e exatamente o defeito do fork de onde a
ideia veio (`_Lock` faz `if fcntl is None: return self`, no-op no Windows).
Guarda que nao pode falhar e o 15o padrao de cabeca para baixo. Os
subprocessos sao locais, sem rede, e usam um diretorio temporario proprio --
nunca cache/locks do repositorio.

Rodar: python tests/test_instance_lock.py
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.instance_lock import InstanceLock, slugify_key  # noqa: E402

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


# -- helper: um segundo processo tentando a mesma trava ----------------------

_CHILD = r"""
import json, sys
sys.path.insert(0, {root!r})
from core.instance_lock import InstanceLock
lock = InstanceLock({key!r}, lock_dir={lock_dir!r})
ok = lock.acquire()
print(json.dumps({{
    "acquired": ok,
    "degraded": lock.degraded,
    "holder": lock.holder,
    "describe": lock.describe_holder() if not ok else None,
}}))
"""


def second_process(key, lock_dir):
    out = subprocess.run(
        [sys.executable, "-c", _CHILD.format(root=ROOT, key=key, lock_dir=lock_dir)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if out.returncode != 0:
        raise AssertionError("subprocesso falhou: %s" % out.stderr)
    return json.loads(out.stdout.strip().splitlines()[-1])


# -- 1. slug ----------------------------------------------------------------


def test_slug_is_stable_and_filesystem_safe():
    slug = slugify_key("https://br143.tribalwars.com.br/game.php")
    check(
        slug == "https-br143-tribalwars-com-br-game-php",
        "slug do endpoint do br143 saiu %r" % slug,
    )
    check(
        not set(slug) & set('\\/:*?"<>|'),
        "slug contem caractere proibido em nome de arquivo no Windows: %r" % slug,
    )
    # Mundos diferentes nao podem colidir: a trava e POR CONTA.
    check(
        slugify_key("https://br143.tribalwars.com.br/game.php")
        != slugify_key("https://br144.tribalwars.com.br/game.php"),
        "br143 e br144 colidiram no mesmo arquivo de trava",
    )
    check(slugify_key("") == "default", "chave vazia deveria virar 'default'")


# -- 2. o caso que importa: segundo processo e recusado ---------------------


def test_second_process_is_refused_while_first_holds():
    with tempfile.TemporaryDirectory() as tmp:
        key = "https://br143.tribalwars.com.br/game.php"
        first = InstanceLock(key, lock_dir=tmp)
        check(first.acquire() is True, "o primeiro processo nao conseguiu travar")
        check(first.degraded is False, "a trava saiu degradada: %s" % first.error)
        try:
            result = second_process(key, tmp)
            check(
                result["acquired"] is False,
                "SEGUNDO PROCESSO TRAVOU TAMBEM -- a trava e no-op nesta "
                "plataforma, que e exatamente o bug do fork de origem",
            )
            # Diagnostico: o segundo tem que conseguir dizer QUEM segura, o que
            # so funciona porque os metadados ficam fora do byte travado.
            holder = result["holder"]
            check(holder is not None, "o segundo processo nao leu os metadados do dono")
            if holder:
                check(
                    holder.get("pid") == os.getpid(),
                    "metadados apontam pid %r, esperado %r"
                    % (holder.get("pid"), os.getpid()),
                )
                check(holder.get("key") == key, "metadados com chave errada: %r" % holder)
            check(
                result["describe"] and str(os.getpid()) in result["describe"],
                "describe_holder() nao cita o pid do dono: %r" % result["describe"],
            )
        finally:
            first.release()


def test_other_account_is_not_blocked():
    """A trava e por conta, nao global: outro mundo roda em paralelo."""
    with tempfile.TemporaryDirectory() as tmp:
        first = InstanceLock("https://br143.tribalwars.com.br/game.php", lock_dir=tmp)
        check(first.acquire() is True, "nao travou a primeira conta")
        try:
            other = second_process("https://br144.tribalwars.com.br/game.php", tmp)
            check(
                other["acquired"] is True,
                "uma conta diferente foi bloqueada pela trava da primeira",
            )
        finally:
            first.release()


def test_release_frees_the_lock_for_the_next_process():
    with tempfile.TemporaryDirectory() as tmp:
        key = "https://br143.tribalwars.com.br/game.php"
        first = InstanceLock(key, lock_dir=tmp)
        first.acquire()
        first.release()
        result = second_process(key, tmp)
        check(
            result["acquired"] is True,
            "depois do release a trava continuou presa -- PID file morto, o "
            "modo de falha que o desenho existe para evitar",
        )


def test_lock_dies_with_the_process_even_without_release():
    """
    O argumento central contra PID file: quem solta a trava e o SO.

    O filho trava e morre sem soltar (os._exit pula qualquer limpeza, como um
    kill -9 faria). O pai tem que conseguir travar logo depois.
    """
    with tempfile.TemporaryDirectory() as tmp:
        key = "https://br143.tribalwars.com.br/game.php"
        code = (
            "import os, sys;"
            "sys.path.insert(0, %r);"
            "from core.instance_lock import InstanceLock;"
            "lock = InstanceLock(%r, lock_dir=%r);"
            "print(lock.acquire());"
            "sys.stdout.flush();"
            "os._exit(0)" % (ROOT, key, tmp)
        )
        out = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, timeout=60
        )
        check("True" in out.stdout, "o filho nao travou: %r / %s" % (out.stdout, out.stderr))
        survivor = InstanceLock(key, lock_dir=tmp)
        check(
            survivor.acquire() is True,
            "a trava sobreviveu a morte do dono -- estaria presa para sempre",
        )
        survivor.release()


def test_reacquire_in_same_process_is_a_noop():
    """
    `main()` de twb.py recria TWB ate 3 vezes no MESMO processo. Pedir a trava
    de novo nao pode se auto-bloquear.
    """
    with tempfile.TemporaryDirectory() as tmp:
        lock = InstanceLock("k", lock_dir=tmp)
        check(lock.acquire() is True, "primeira aquisicao falhou")
        check(lock.acquire() is True, "reaquisicao no mesmo processo se auto-bloqueou")
        lock.release()


# -- 3. a ordem no twb.py ---------------------------------------------------


def test_twb_takes_the_lock_before_truncating_the_session_log():
    """
    Verificacao de ORDEM NO FONTE (nao de comportamento): a trava tem que ser
    adquirida ANTES do open(..., "w") do tee.

    Motivo concreto: esse open TRUNCA cache/logs/session_latest.log. Se a
    verificacao viesse depois, um segundo `python twb.py` ja teria destruido o
    log do bot que esta rodando antes de ser recusado -- o estrago do 20o
    padrao entrando por outra porta. Testar isso de verdade exigiria subir dois
    bots reais; o que da para garantir barato e a ordem textual.
    """
    with open(os.path.join(ROOT, "twb.py"), encoding="utf-8") as handle:
        source = handle.read()
    acquire_at = source.find("_instance_lock.acquire()")
    truncate_at = source.find('"session_latest.log"')
    check(acquire_at != -1, "nao achei a aquisicao da trava em twb.py")
    check(truncate_at != -1, "nao achei o open que trunca o log de sessao em twb.py")
    if acquire_at != -1 and truncate_at != -1:
        check(
            acquire_at < truncate_at,
            "a trava e adquirida DEPOIS do truncate do log de sessao",
        )


for fn in [
    test_slug_is_stable_and_filesystem_safe,
    test_second_process_is_refused_while_first_holds,
    test_other_account_is_not_blocked,
    test_release_frees_the_lock_for_the_next_process,
    test_lock_dies_with_the_process_even_without_release,
    test_reacquire_in_same_process_is_a_noop,
    test_twb_takes_the_lock_before_truncating_the_session_log,
]:
    fn()

if failures:
    print("FAIL (%d):" % len(failures))
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("test_instance_lock: OK")
