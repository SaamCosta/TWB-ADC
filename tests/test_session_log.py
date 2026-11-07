"""
O log da sessão anterior sobrevive ao reinício (`core/session_log`, §8.89.5).

O `open(..., "w")` do `twb.py` apagava o `session_latest.log` a cada subida, e
a causa da parada do bot em 05/11 se perdeu assim. Tudo aqui roda num
diretório temporário: nada toca o `cache/logs` desta instalação (21º padrão).
A integração com o topo do `twb.py` está em `test_session_log_guard.py`.

Rodar: python tests/test_session_log.py
"""
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import session_log

# A primeira linha do log de 07/11, com os bytes NUL que o arquivo real tem.
FIRST = "2026-11-07 06:59:14 - root - INFO - The bot is up-to-date\n"


def _tmp():
    return tempfile.mkdtemp(prefix="twb-session-log-")


def _write(path, text, mode="w"):
    with open(path, mode, encoding="utf-8") as fh:
        fh.write(text)


def test_guarda_com_a_hora_de_inicio_da_sessao():
    tmp = _tmp()
    try:
        latest = os.path.join(tmp, "session_latest.log")
        _write(latest, "\x00\x00" + FIRST + "2026-11-07 10:18:28 - Recruitment - INFO - ...\n")
        target = session_log.rotate(tmp)
        assert os.path.basename(target) == "session_prev_20261107_065914.log", target
        assert not os.path.exists(latest)
        with open(target, encoding="utf-8") as fh:
            assert "10:18:28" in fh.read()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_sem_log_ou_vazio_nao_faz_nada():
    tmp = _tmp()
    try:
        assert session_log.rotate(tmp) is None
        _write(os.path.join(tmp, "session_latest.log"), "")
        assert session_log.rotate(tmp) is None
        assert sorted(os.listdir(tmp)) == ["session_latest.log"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_mesma_hora_nao_sobrescreve():
    tmp = _tmp()
    try:
        latest = os.path.join(tmp, "session_latest.log")
        _write(latest, FIRST + "primeira\n")
        a = session_log.rotate(tmp)
        _write(latest, FIRST + "segunda\n")
        b = session_log.rotate(tmp)
        assert a != b and os.path.basename(b) == "session_prev_20261107_065914_1.log", b
        with open(a, encoding="utf-8") as fh:
            assert "primeira" in fh.read()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_sem_data_na_primeira_linha_usa_o_mtime():
    tmp = _tmp()
    try:
        latest = os.path.join(tmp, "session_latest.log")
        _write(latest, "Village 100124 was found but no config entry was found\n")
        when = time.mktime((2026, 11, 5, 21, 39, 31, 0, 0, -1))
        os.utime(latest, (when, when))
        target = session_log.rotate(tmp)
        assert os.path.basename(target) == "session_prev_20261105_213931.log", target
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_limpeza_guarda_os_mais_novos_e_nao_toca_nos_nomeados():
    tmp = _tmp()
    try:
        manual = ["session_20261005_1850_campanha.log", "session_pre_restart_20260916_2314.log",
                  "incident_20261019_hunter_furo.log", "twb_1794045557.log"]
        for name in manual:
            _write(os.path.join(tmp, name), "x\n")
        for day in range(1, 6):
            _write(os.path.join(tmp, "session_prev_202611%02d_080000.log" % day), "x\n")
        latest = os.path.join(tmp, "session_latest.log")
        _write(latest, FIRST)
        session_log.rotate(tmp, keep=3)
        prev = sorted(f for f in os.listdir(tmp) if f.startswith("session_prev_"))
        assert prev == ["session_prev_20261104_080000.log", "session_prev_20261105_080000.log",
                        "session_prev_20261107_065914.log"], prev
        for name in manual:
            assert os.path.exists(os.path.join(tmp, name)), name
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_renomear_recusado_cai_na_copia():
    # No Windows, o painel lendo o arquivo impede o rename.
    tmp = _tmp()
    orig = session_log.os.replace

    def busy(src, dst):
        raise PermissionError("em uso")

    try:
        latest = os.path.join(tmp, "session_latest.log")
        _write(latest, FIRST)
        session_log.os.replace = busy
        target = session_log.rotate(tmp)
        assert target and os.path.exists(target) and os.path.exists(latest)
    finally:
        session_log.os.replace = orig
        shutil.rmtree(tmp, ignore_errors=True)


def test_erro_nunca_sobe():
    # Diretório que não existe: None, sem exceção (o bot sobe mesmo assim).
    assert session_log.rotate(os.path.join(_tmp(), "nao", "existe")) is None
    orig = session_log.shutil.copyfile
    tmp = _tmp()
    try:
        _write(os.path.join(tmp, "session_latest.log"), FIRST)
        session_log.os.replace, saved = (lambda s, d: (_ for _ in ()).throw(OSError("x"))), session_log.os.replace
        session_log.shutil.copyfile = lambda s, d: (_ for _ in ()).throw(OSError("disco cheio"))
        try:
            assert session_log.rotate(tmp) is None
        finally:
            session_log.os.replace = saved
    finally:
        session_log.shutil.copyfile = orig
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    falhas = 0
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok   %s" % nome)
            except Exception as exc:
                falhas += 1
                print("FALHA %s: %r" % (nome, exc))
    sys.exit(1 if falhas else 0)
