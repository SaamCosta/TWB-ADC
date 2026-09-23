"""
Timer de reserva (game/reservation_sniper.py, docs/backend.md 8.28).

O caso real: a 74694 (583|308) na fila manual, reservada por Asshai ate
"hoje às 17:31" em 2026-09-23. O timer tem que reservar para a conta no minuto
em que essa reserva vence -- e nao antes, e nao para sempre.

Os formatos de validade vem das 441 linhas de cache/debug/reservations_all.html
(captura de 2026-09-21): "hoje às HH:MM", "amanhã às HH:MM",
"em DD.MM. às HH:MM".

Nada aqui toca cache/ nem a rede (21o padrao): FileManager, quadro e escritor
sao dubles.

Rodar: python tests/test_reservation_sniper.py
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import game.reservation_sniper as sniper_mod
from game.reservation_sniper import ReservationSniper, parse_expires

ALVO = "74694"
LOC = [583, 308]
# 2026-09-23 11:44 -- a hora em que o quadro foi lido.
LIDO = datetime.datetime(2026, 9, 23, 11, 44).timestamp()
VENCE = datetime.datetime(2026, 9, 23, 17, 31).timestamp()


def _ts(*a):
    return datetime.datetime(*a).timestamp()


# --------------------------------------------------------------------------
# parse_expires
# --------------------------------------------------------------------------

def test_hoje():
    assert parse_expires("hoje às 17:31", LIDO) == VENCE


def test_amanha():
    assert parse_expires("amanhã às 07:45", LIDO) == _ts(2026, 9, 24, 7, 45)


def test_data():
    assert parse_expires("em 26.09. às 18:02", LIDO) == _ts(2026, 9, 26, 18, 2)


def test_acento_corrompido_ainda_entende():
    """A captura em disco chega com o acento trocado dependendo de quem leu."""
    assert parse_expires("amanh� �s 07:45", LIDO) == _ts(2026, 9, 24, 7, 45)


def test_virada_de_ano():
    dezembro = _ts(2026, 12, 31, 22, 0)
    assert parse_expires("em 02.01. às 10:00", dezembro) == _ts(2027, 1, 2, 10, 0)


def test_texto_desconhecido_devolve_none():
    for texto in ("", None, "ontem", "em breve às 10:00", "hoje"):
        assert parse_expires(texto, LIDO) is None, texto


# --------------------------------------------------------------------------
# Dubles
# --------------------------------------------------------------------------

class _Logger:
    def __init__(self):
        self.linhas = []

    def _log(self, msg, *a):
        self.linhas.append(msg % a if a else msg)

    info = warning = debug = _log


class _Board:
    """Quadro com uma fila de estados: cada refresh(force) avanca um."""

    def __init__(self, estados):
        self.estados = list(estados)
        self.atual = self.estados.pop(0)
        self.fetched_at = LIDO
        self.read_village_id = "41123"
        self.refreshes = 0

    def refresh(self, village_id, force=False):
        self.refreshes += 1
        if self.estados:
            self.atual = self.estados.pop(0)
        return self.atual is not None

    def is_readable(self):
        return self.atual is not None

    def claimed_by_other(self, target_id, location=None):
        c = (self.atual or {}).get(str(target_id))
        return c if c and c.get("by") != "me" else None

    def claimed_by_me(self, target_id, location=None):
        c = (self.atual or {}).get(str(target_id))
        return c if c and c.get("by") == "me" else None


def _asshai(expires="hoje às 17:31"):
    return {ALVO: {"reserved_by_name": "Asshai", "expires_text": expires}}


class _Writer:
    enabled = True

    def __init__(self, aceita=True):
        self.aceita = aceita
        self.chamadas = []

    def claim_target(self, target_id, location, budget_exempt=False):
        self.chamadas.append((target_id, tuple(location), budget_exempt))
        return {"reservation_id": "90001", "expires_text": "em 26.09. às 17:32"} if self.aceita else None


class _Clock:
    def __init__(self, t):
        self.t = t
        self.dormiu = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.dormiu.append(s)
        self.t += s


def _install(fila=None, donos=None):
    fila = {ALVO: {"status": "manual", "queued_at": 1,
                   "target_location": LOC}} if fila is None else fila
    donos = donos or {}
    gravado = {}

    class _FM:
        @staticmethod
        def list_directory(directory, ends_with=None):
            return ["%s.json" % k for k in fila] if "conquest" in directory else []

        @staticmethod
        def load_json_file(path, **k):
            nome = os.path.basename(path).replace(".json", "")
            if "villages" in path:
                return {"owner": donos.get(nome, "0")}
            return dict(fila.get(nome) or {})

        @staticmethod
        def save_json_file(data, path, **k):
            gravado[os.path.basename(path).replace(".json", "")] = data

    sniper_mod.FileManager = _FM
    return gravado


def _sniper(board, writer=None, t=None, snipe=True):
    s = ReservationSniper(
        wrapper=None,
        config={"conquest": {"snipe_expiring_reservations": snipe}},
        board=board, writer=writer or _Writer())
    s.logger = _Logger()
    clock = _Clock(t if t is not None else LIDO)
    s.now, s.sleep = clock.now, clock.sleep
    return s, clock


# --------------------------------------------------------------------------
# Armar
# --------------------------------------------------------------------------

def test_arma_alvo_da_fila_reservado_por_outro():
    _install()
    s, _ = _sniper(_Board([_asshai()]))
    s.arm()
    assert s.armed[ALVO]["expires_at"] == VENCE
    assert s.armed[ALVO]["reserved_by"] == "Asshai"


def test_nao_arma_com_o_gate_desligado():
    _install()
    s, _ = _sniper(_Board([_asshai()]), snipe=False)
    s.arm()
    assert s.armed == {}


def test_nao_arma_alvo_fora_da_fila():
    _install(fila={ALVO: {"status": "train_sent", "target_location": LOC}})
    s, _ = _sniper(_Board([_asshai()]))
    s.arm()
    assert s.armed == {}


def test_alvo_que_sai_da_fila_e_desarmado():
    _install()
    s, _ = _sniper(_Board([_asshai()]))
    s.arm()
    _install(fila={})
    s.arm()
    assert s.armed == {}


# --------------------------------------------------------------------------
# Disparar
# --------------------------------------------------------------------------

def test_longe_do_horario_nao_faz_nada():
    _install()
    board = _Board([_asshai()])
    s, _ = _sniper(board)
    s.arm()
    s.tick()
    assert board.refreshes == 0


def test_perto_do_horario_dorme_e_reserva_depois_do_minuto():
    gravado = _install()
    board = _Board([_asshai(), {}])  # no refresh do disparo a reserva sumiu
    writer = _Writer()
    s, clock = _sniper(board, writer, t=VENCE - 60)
    s.arm()
    s.tick()
    assert clock.dormiu == [60 + ReservationSniper.GRACE]
    assert writer.chamadas == [(ALVO, (583, 308), True)], \
        "tem que reservar fora do orcamento de 1 escrita por ciclo"
    assert s.armed == {}
    assert gravado[ALVO]["target_claim"]["source"] == "reservation_timer"
    assert gravado[ALVO]["status"] == "manual", "reservar nao tira da fila"


def test_reserva_ainda_la_tenta_de_novo_um_minuto_depois():
    _install()
    board = _Board([_asshai(), _asshai(), {}])
    writer = _Writer()
    s, clock = _sniper(board, writer, t=VENCE + 5)
    s.arm()
    s.tick()
    assert writer.chamadas == [] and s.armed[ALVO]["attempts"] == 1
    s.tick()  # logo em seguida: dorme o intervalo inteiro antes de tentar
    assert clock.dormiu == [ReservationSniper.RETRY_INTERVAL]
    assert len(writer.chamadas) == 1 and s.armed == {}


def test_reserva_renovada_rearma_para_o_novo_horario():
    _install()
    board = _Board([_asshai(), _asshai("em 26.09. às 17:31")])
    writer = _Writer()
    s, _ = _sniper(board, writer, t=VENCE + 5)
    s.arm()
    s.tick()
    assert writer.chamadas == []
    assert s.armed[ALVO]["expires_at"] == _ts(2026, 9, 26, 17, 31)
    assert s.armed[ALVO]["attempts"] == 0


def test_aldeia_com_dono_desarma_sem_reservar():
    _install(donos={ALVO: "12345"})
    board = _Board([_asshai(), {}])
    writer = _Writer()
    s, _ = _sniper(board, writer, t=VENCE + 5)
    s.arm()
    s.tick()
    assert writer.chamadas == [] and s.armed == {}


def test_ja_reservado_por_mim_desarma():
    _install()
    board = _Board([_asshai(), {ALVO: {"by": "me"}}])
    writer = _Writer()
    s, _ = _sniper(board, writer, t=VENCE + 5)
    s.arm()
    s.tick()
    assert writer.chamadas == [] and s.armed == {}


def test_desiste_depois_do_teto_de_tentativas():
    _install()
    estados = [_asshai()] + [{}] * 20
    board = _Board(estados)
    writer = _Writer(aceita=False)
    s, clock = _sniper(board, writer, t=VENCE + 5)
    s.arm()
    for _ in range(ReservationSniper.MAX_ATTEMPTS + 3):
        s.tick()
        clock.t += ReservationSniper.RETRY_INTERVAL
    assert len(writer.chamadas) == ReservationSniper.MAX_ATTEMPTS
    assert s.armed == {}


def test_nearest_time_aponta_o_vencimento():
    _install()
    s, _ = _sniper(_Board([_asshai()]))
    assert s.nearest_time() is None
    s.arm()
    assert s.nearest_time() == VENCE + ReservationSniper.GRACE


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
