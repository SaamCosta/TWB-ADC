"""
A26-05 e A26-12 (`docs/backend.md` §8.32): a fila do Hunter e a gravacao de
`cache/hunter/schedules.json`.

A26-05 -- o Hunter servia um schedule ate o fim antes de olhar o proximo. Com
A em T+10 e T+100 e B em T+50, dormia ate T+100 dentro de A e o comando de B
virava `send_time_missed`. Agora ha uma fila unica por `send_time`.

A26-12 -- o `_run()` lia o arquivo, dormia ate 120 s e gravava a copia inteira
de volta. O que o painel criasse nesse intervalo sumia, e o que ele apagasse
voltava. Agora a gravacao rele o disco sob `core.file_lock` e aplica so as
mudancas deste processo, e o comando e reconferido depois da espera.

Sem rede. Os testes de arquivo usam um diretorio temporario como raiz do
`FileManager`, nunca o `cache/` real. A trava e testada com um subprocesso de
verdade: trava de arquivo do SO nao se prova dentro de um processo so.
"""

import os
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.file_lock import file_lock
from core.filemanager import FileManager
from game.hunter import Hunter


def _atk(source, send_time, troops=None):
    return {
        "source_village_id": source,
        "troops": troops or {"axe": 10},
        "is_fake": False,
        "send_time": send_time,
        "status": "pending",
    }


def _sched(target, attacks, arrival):
    return {"target_id": target, "arrival_time": arrival,
            "status": "pending", "attacks": attacks}


class _TmpRoot:
    """Troca a raiz do FileManager por um diretorio temporario."""

    def __enter__(self):
        self.dir = tempfile.mkdtemp(prefix="twb-hunter-")
        os.makedirs(os.path.join(self.dir, "cache", "hunter"))
        self._orig = FileManager.__dict__["get_root"]
        FileManager.get_root = staticmethod(lambda: self.dir)
        return self

    def __exit__(self, *exc):
        FileManager.get_root = self._orig

    def write(self, data):
        FileManager.save_json_file(data, Hunter.SCHEDULE_CACHE)

    def read(self):
        return FileManager.load_json_file(Hunter.SCHEDULE_CACHE)


# --------------------------------------------------------------------------
# A26-05 -- fila unica
# --------------------------------------------------------------------------

def test_comando_de_outro_schedule_no_meio_nao_se_perde():
    """
    O caso do diagnostico, em escala de decimos de segundo: A sai em +0.1 e
    +0.5, B em +0.3. Na ordem antiga, B era servido depois de +0.5 e recusado
    como atrasado.
    """
    now = time.time()
    schedules = {
        "A": _sched("1", [_atk("41123", now + 0.1), _atk("74690", now + 0.5)], now + 3600),
        "B": _sched("2", [_atk("74689", now + 0.3)], now + 3600),
    }
    hunter = Hunter(wrapper=SimpleNamespace(priority_mode=False))
    hunter._load_schedules = lambda: schedules
    hunter._save_schedules = lambda *_a: None
    sent = []
    hunter._send_attack_batch = lambda batch, target: sent.append(
        (batch[0]["source_village_id"], target)) or True

    hunter.run({"hunter": {"enabled": True}})

    assert sent == [("41123", "1"), ("74689", "2"), ("74690", "1")], sent
    assert schedules["A"]["status"] == "complete"
    assert schedules["B"]["status"] == "complete"
    assert all(a.get("fail_reason") is None
               for s in schedules.values() for a in s["attacks"])


def test_priority_mode_desliga_no_fim():
    now = time.time()
    schedules = {"A": _sched("1", [_atk("41123", now + 0.05)], now + 3600)}
    wrapper = SimpleNamespace(priority_mode=False)
    hunter = Hunter(wrapper=wrapper)
    hunter._load_schedules = lambda: schedules
    hunter._save_schedules = lambda *_a: None
    seen = []
    hunter._send_attack_batch = lambda *_a: seen.append(wrapper.priority_mode) or True

    hunter.run({"hunter": {"enabled": True}})

    assert seen == [True]
    assert wrapper.priority_mode is False


# --------------------------------------------------------------------------
# A26-12 -- merge puro
# --------------------------------------------------------------------------

def test_merge_preserva_o_que_o_outro_lado_criou_e_apagou():
    baseline = {
        "mudou": {"status": "pending", "n": 1},
        "igual": {"status": "pending", "n": 1},
        "apagado_e_mudou": {"status": "pending", "n": 1},
        "apagado_e_igual": {"status": "pending", "n": 1},
    }
    mine = {
        "mudou": {"status": "complete", "n": 1},
        "igual": {"status": "pending", "n": 1},
        "apagado_e_mudou": {"status": "failed", "n": 1},
        "apagado_e_igual": {"status": "pending", "n": 1},
        "criado_por_mim": {"status": "pending", "n": 9},
    }
    disk = {
        "mudou": {"status": "pending", "n": 1},
        # o painel mexeu num schedule que o Hunter nao tocou
        "igual": {"status": "pending", "n": 2},
        "criado_pelo_painel": {"status": "pending", "n": 5},
    }

    merged, dropped = Hunter.merge_schedule_changes(disk, mine, baseline)

    assert merged["mudou"]["status"] == "complete"
    assert merged["igual"]["n"] == 2, "a edicao do outro lado foi desfeita"
    assert "criado_pelo_painel" in merged, "o schedule novo do painel sumiu"
    assert "criado_por_mim" in merged
    assert "apagado_e_mudou" not in merged, "schedule apagado voltou"
    assert "apagado_e_igual" not in merged, "schedule apagado voltou"
    assert dropped == ["apagado_e_mudou"]


# --------------------------------------------------------------------------
# A26-12 -- ponta a ponta, com arquivo de verdade num diretorio temporario
# --------------------------------------------------------------------------

def test_schedule_criado_durante_a_espera_sobrevive():
    now = time.time()
    with _TmpRoot() as root:
        root.write({"A": _sched("1", [_atk("41123", now + 0.05)], now + 3600)})
        hunter = Hunter(wrapper=SimpleNamespace(priority_mode=False))

        def send(batch, target):
            # O painel grava um schedule novo enquanto o Hunter segura a
            # copia que leu antes de dormir.
            disk = root.read()
            disk["NOVO"] = _sched("9", [_atk("1", now + 9000)], now + 9999)
            root.write(disk)
            return True

        hunter._send_attack_batch = send
        hunter.run({"hunter": {"enabled": True}})

        disk = root.read()
        assert "NOVO" in disk, "a gravacao do Hunter apagou o schedule do painel"
        assert disk["A"]["status"] == "complete"
        assert disk["A"]["attacks"][0]["status"] == "sent"


def test_schedule_apagado_durante_a_espera_nao_sai_nem_volta():
    now = time.time()
    with _TmpRoot() as root:
        root.write({
            "A": _sched("1", [_atk("41123", now + 0.05)], now + 3600),
            "B": _sched("2", [_atk("74690", now + 9000)], now + 9999),
        })
        hunter = Hunter(wrapper=SimpleNamespace(priority_mode=False))

        def panel_deletes(_source_id, _config):
            disk = root.read()
            disk.pop("A")
            root.write(disk)

        hunter._ensure_source_ready = panel_deletes
        sent = []
        hunter._send_attack_batch = lambda batch, target: sent.append(target) or True
        hunter.run({"hunter": {"enabled": True}})

        assert sent == [], "o comando de um schedule apagado saiu"
        disk = root.read()
        assert "A" not in disk, "o schedule apagado voltou"
        assert "B" in disk


def test_releitura_ilegivel_na_janela_nao_segura_o_comando():
    """
    Checagem de "apagado?" depois da espera: se a releitura levantar (JSON
    corrompido), o comando sai assim mesmo -- a guarda nao pode ser o motivo
    de um nobre nao sair.
    """
    now = time.time()
    schedules = {"A": _sched("1", [_atk("41123", now + 0.05)], now + 3600)}
    calls = []

    def load():
        calls.append(1)
        if len(calls) > 1:
            raise ValueError("JSON invalido")
        return schedules

    hunter = Hunter(wrapper=SimpleNamespace(priority_mode=False))
    hunter._load_schedules = load
    hunter._save_schedules = lambda *_a: None
    sent = []
    hunter._send_attack_batch = lambda batch, target: sent.append(target) or True

    hunter.run({"hunter": {"enabled": True}})

    assert sent == ["1"]
    assert len(calls) == 2, "a releitura depois da espera nao aconteceu"


def test_remove_schedule_rele_o_disco():
    with _TmpRoot() as root:
        root.write({"k1": {"status": "pending"}, "k2": {"status": "pending"}})
        assert Hunter.remove_schedule("k1") == {"status": "pending"}
        assert Hunter.remove_schedule("nao_existe") is None
        assert root.read() == {"k2": {"status": "pending"}}


# --------------------------------------------------------------------------
# A trava em si, entre dois processos
# --------------------------------------------------------------------------

_HOLDER = """
import sys, time
sys.path.insert(0, {root!r})
from core.file_lock import file_lock
with file_lock({path!r}) as lock:
    print("held" if lock.held else "not-held", flush=True)
    time.sleep({hold})
"""


def test_trava_espera_o_outro_processo_e_desiste_no_timeout():
    tmp = tempfile.mkdtemp(prefix="twb-lock-")
    path = os.path.join(tmp, "schedules.json")
    child = subprocess.Popen(
        [sys.executable, "-c", _HOLDER.format(root=ROOT, path=path, hold=1.5)],
        stdout=subprocess.PIPE, text=True,
    )
    try:
        assert child.stdout.readline().strip() == "held"

        t0 = time.monotonic()
        with file_lock(path, timeout=0.3) as lock:
            assert lock.held is False, "pegou a trava que outro processo segura"
        assert time.monotonic() - t0 < 1.0

        t0 = time.monotonic()
        with file_lock(path, timeout=10) as lock:
            waited = time.monotonic() - t0
            assert lock.held is True
        assert waited > 0.5, "nao esperou o outro processo soltar (%.2fs)" % waited
    finally:
        child.wait(timeout=10)


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok   %s" % name)
            except Exception as exc:
                failures += 1
                print("FALHA %s: %r" % (name, exc))
    sys.exit(1 if failures else 0)
