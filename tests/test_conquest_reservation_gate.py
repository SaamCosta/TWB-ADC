"""
A exclusao de alvo reservado, nos QUATRO caminhos de conquista.

  ConquestManager.find_target()/_candidate_pool()  -- selecao automatica
  ConquestManager._get_manual_target()             -- fila manual do painel
  ConquestManager._handle_existing()               -- conquista em andamento
  BarbarianTrainPlanner._cancel_reserved_targets() -- trem AGENDADO
  PvpConquestManager._block_if_reserved()          -- conquista de jogador

O INCIDENTE (docs/backend.md 8.7)
---------------------------------
Em 2026-09-20 o usuario relatou que o bot nobrou uma barbara que outro jogador
do SQUAD 02 tinha reservado. O bot nao tinha o conceito de reserva.

O que torna isto diferente de quase todo filtro do projeto e a ASSIMETRIA: um
falso negativo (pular alvo livre) custa uma barbara entre dezenas; um falso
positivo (nobrar reserva alheia) custa capital social, e irreversivel, e o bot
ja gastou 4 nobres e uma moeda para causar isso. Por isso exclusao DURA, e nao
preferencia como `_prefer_area_of_interest()`, e por isso "na duvida, pular".

O parser e o quadro estao em tests/test_tribe_reservations.py. Aqui o quadro e
um duble: o que se testa e se cada caminho CONSULTA e OBEDECE.

Nada aqui toca cache/ nem a rede -- o bot escreve nesses mesmos arquivos
enquanto roda (21o padrao do CLAUDE.md).

Rodar: python tests/test_conquest_reservation_gate.py
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import game.attack as attack_mod
import game.conquest_planner as planner_mod
import game.pvp_conquest as pvp_mod
from game.attack import ConquestManager
from game.conquest_planner import BarbarianTrainPlanner
from game.pvp_conquest import PvpConquestManager

ALVO = "40808"          # 531|289 -- a barbara reservada por terceiro
LIVRE = "51991"         # 570|293 -- ninguem reservou
BBM_001 = (577, 306)


class _Board:
    """
    Duble do ReservationBoard. So o contrato importa aqui: `claimed_by_other`
    devolve a reserva de TERCEIRO (None para livre e para a minha), e
    `is_readable` diz se houve leitura.
    """

    def __init__(self, claimed=(ALVO,), readable=True):
        self.claimed = set(claimed)
        self.readable = readable
        self.enabled = True

    def claimed_by_other(self, target_id, location=None):
        if str(target_id) not in self.claimed:
            return None
        return {"reserved_by_id": "919714218",
                "reserved_by_name": "Conde Strahd von Zarovch",
                "reserved_by_tribe": "RANDOW",
                "expires_text": "hoje às 07:45"}

    def is_readable(self):
        return self.readable


class _Logger:
    def __init__(self):
        self.avisos = []

    def debug(self, *a, **k): pass
    def info(self, *a, **k): self.avisos.append(a[0] % a[1:] if len(a) > 1 else a[0])
    def warning(self, *a, **k): self.avisos.append(a[0] % a[1:] if len(a) > 1 else a[0])
    def error(self, *a, **k): pass


class _Map:
    def __init__(self, villages):
        self.villages = villages
        self.map_pos = {v: d["location"] for v, d in villages.items()}
        self.my_location = list(BBM_001)

    def get_dist(self, loc):
        return math.sqrt((self.my_location[0] - loc[0]) ** 2
                         + (self.my_location[1] - loc[1]) ** 2)


class _Reporter:
    def __init__(self): self.sent = []
    def report(self, *a, **k): self.sent.append(a)


class _Wrapper:
    def __init__(self): self.reporter = _Reporter()


def _barbara(x, y, points=900):
    return {"id": "x", "name": "Bárbaras", "location": [x, y],
            "points": points, "owner": "0"}


SCAN = {ALVO: _barbara(531, 289), LIVRE: _barbara(570, 293)}
CFG = {"max_radius": 60, "min_points": 100, "max_points": 1100,
       "priority": "fill_gaps"}


def _install(conquest_files=None):
    """Substitui tudo que sai do processo. Devolve o dict de escritas."""
    written = {}
    files = conquest_files or {}

    class _FM:
        @staticmethod
        def list_directory(directory, ends_with=None):
            if "conquest" in directory:
                return ["%s.json" % k for k in files]
            return []

        @staticmethod
        def load_json_file(path, **k):
            name = os.path.basename(path).replace(".json", "")
            if "villages" in path:
                return SCAN.get(name)
            return files.get(name)

        @staticmethod
        def save_json_file(data, path, **k):
            written[os.path.basename(path).replace(".json", "")] = data

    class _Cache:
        @staticmethod
        def all_reserved(): return set()

        @staticmethod
        def targets_with_nobles_in_flight(): return set()

        @staticmethod
        def set(target_id, entry): written[str(target_id)] = entry

        @staticmethod
        def get(target_id): return files.get(str(target_id))

        @staticmethod
        def nobles_in_flight(data): return False

    class _WC:
        @staticmethod
        def get(**k): return {"snob": {"max_dist": 70}}

        @staticmethod
        def noble_max_distance(data): return 70

        @staticmethod
        def loyalty_drop_range(data, fallback=25): return (fallback, fallback)

    attack_mod.FileManager = _FM
    attack_mod.ConquestCache = _Cache
    attack_mod.WorldConfig = _WC
    return written


def _manager(board, conquest_files=None):
    written = _install(conquest_files)
    man = ConquestManager.__new__(ConquestManager)
    man.village_id = "41123"
    man.map = _Map(dict(SCAN))
    man.config = {"conquest": {}, "server": {}}
    man.logger = _Logger()
    man.wrapper = _Wrapper()
    man.reservation_board = board
    man._drop_min, man._drop_max = 20, 25
    return man, written


# --------------------------------------------------------------------------
# Caminho 1 -- selecao automatica
# --------------------------------------------------------------------------

def test_automatico_pula_alvo_reservado_e_pega_o_livre():
    man, _ = _manager(_Board(claimed=[ALVO]))
    assert man.find_target(CFG) == LIVRE


def test_automatico_sem_alternativa_devolve_nada():
    """
    Pular e o comportamento certo mesmo quando NAO sobra alvo. Devolver o alvo
    reservado "porque era o unico" e exatamente o incidente.
    """
    man, _ = _manager(_Board(claimed=[ALVO, LIVRE]))
    assert man.find_target(CFG) is None


def test_sem_quadro_nenhum_o_comportamento_e_o_antigo():
    """
    `reservation_board=None` (testes, smoke, Village.run() isolado) nao pode
    travar a conquista -- so desliga a consulta.
    """
    man, _ = _manager(None)
    assert man.find_target(CFG) in (ALVO, LIVRE)


def test_quadro_ilegivel_nao_inicia_conquista_nova():
    """
    O CONTRATO assimetrico. Sem leitura o bot nao sabe o que e de quem, entao
    nao elege nada -- nem o alvo que ninguem reservou. E o inverso do
    `_source_reaches`, onde um falso positivo so custava um comando recusado.
    """
    man, _ = _manager(_Board(claimed=[], readable=False))
    assert man.find_target(CFG) is None
    assert any("sem leitura do quadro" in a for a in man.logger.avisos), \
        "bloqueou calado -- o motivo tem que aparecer no log"


def test_exclusao_manual_por_config_sem_quadro():
    man, _ = _manager(None)
    man.config = {"conquest": {"excluded_targets": [ALVO]}, "server": {}}
    assert man.find_target(CFG) == LIVRE


def test_exclusao_manual_por_coordenada():
    man, _ = _manager(None)
    man.config = {"conquest": {"excluded_targets": ["531|289"]}, "server": {}}
    assert man.find_target(CFG) == LIVRE


# --------------------------------------------------------------------------
# Caminho 2 -- fila manual
# --------------------------------------------------------------------------

def test_alvo_manual_reservado_nao_e_entregue_e_fica_esperando():
    """
    A fila e um estado parado; o quadro da tribo nao e. Um alvo enfileirado a
    mao ontem pode ter sido reservado hoje (6o padrao: reconferir no momento de
    agir). E `find_target()` devolve alvo manual ANTES de qualquer filtro, entao
    sem esta guarda o caminho manual passaria as cegas.

    Desde 2026-09-23 a reserva de terceiro NAO tira da fila: o alvo continua
    "manual", anotado com quem reservou, e e pulado ate a reserva sumir.
    """
    files = {ALVO: {"status": "manual", "queued_at": 1, "target_id": ALVO}}
    man, written = _manager(_Board(claimed=[ALVO]), conquest_files=files)

    assert man._get_manual_target() is None
    assert written[ALVO]["status"] == "manual"
    espera = written[ALVO]["waiting_reservation"]
    assert espera["reserved_by_name"] == "Conde Strahd von Zarovch"
    assert espera["reservation_expires"] == "hoje às 07:45"


def test_alvo_manual_esperando_nao_segura_o_proximo_da_fila():
    """Pular o reservado nao pode travar a fila: o seguinte e entregue."""
    files = {ALVO: {"status": "manual", "queued_at": 1, "target_id": ALVO},
             LIVRE: {"status": "manual", "queued_at": 2, "target_id": LIVRE}}
    man, _written = _manager(_Board(claimed=[ALVO]), conquest_files=files)
    assert man._get_manual_target() == LIVRE


def test_espera_inalterada_nao_reescreve_o_arquivo_todo_ciclo():
    ja_anotado = {"status": "manual", "queued_at": 1, "target_id": ALVO,
                  "waiting_reservation": {
                      "reserved_by_name": "Conde Strahd von Zarovch",
                      "reserved_by_tribe": "RANDOW",
                      "reservation_expires": "hoje às 07:45",
                      "since": 123}}
    man, written = _manager(_Board(claimed=[ALVO]), conquest_files={ALVO: ja_anotado})
    assert man._get_manual_target() is None
    assert written == {}


def test_reserva_vencida_libera_o_alvo_esperando():
    """O caso da 74694: a reserva saiu do quadro e a aldeia segue barbara."""
    esperando = {"status": "manual", "queued_at": 1, "target_id": ALVO,
                 "waiting_reservation": {"reserved_by_name": "Asshai",
                                         "since": 123}}
    man, written = _manager(_Board(claimed=[]), conquest_files={ALVO: esperando})
    assert man._get_manual_target() == ALVO
    assert written[ALVO]["status"] == "manual"
    assert "waiting_reservation" not in written[ALVO]


def test_reserva_vencida_mas_nobrada_pelo_dono_vira_invalid():
    """
    Quem reservou nobrou antes de a reserva sair. O cache local ainda diz
    barbara (ele nao fica sabendo de conquista -- 27o padrao); o village.txt
    ja diz dono. Uma fonte com dono basta.
    """
    class _World:
        def rows(self):
            return {ALVO: (531, 289, "919714218", 10285, "x")}

    esperando = {"status": "manual", "queued_at": 1, "target_id": ALVO,
                 "waiting_reservation": {"reserved_by_name": "Asshai"}}
    man, written = _manager(_Board(claimed=[]), conquest_files={ALVO: esperando})
    man.world_villages = _World()
    assert man._get_manual_target() is None
    assert written[ALVO]["status"] == "invalid"


def test_village_txt_ilegivel_nao_bloqueia():
    class _World:
        def rows(self):
            raise OSError("sem rede")

    files = {LIVRE: {"status": "manual", "queued_at": 1, "target_id": LIVRE}}
    man, _written = _manager(_Board(claimed=[]), conquest_files=files)
    man.world_villages = _World()
    assert man._get_manual_target() == LIVRE


def test_exclusao_por_config_continua_tirando_da_fila():
    """
    `excluded_targets` e o proprio usuario dizendo "nunca": ai sim "blocked".
    E "blocked", nao "invalid", porque a causa e reversivel (tirar da config).
    """
    files = {ALVO: {"status": "manual", "queued_at": 1, "target_id": ALVO}}
    man, written = _manager(None, conquest_files=files)
    man.config = {"conquest": {"excluded_targets": [ALVO]}, "server": {}}
    assert man._get_manual_target() is None
    assert written[ALVO]["status"] == "blocked"
    assert written[ALVO]["blocked_reason"] == "excluded_targets"


def test_alvo_manual_livre_continua_passando():
    files = {LIVRE: {"status": "manual", "queued_at": 1, "target_id": LIVRE}}
    man, written = _manager(_Board(claimed=[ALVO]), conquest_files=files)
    assert man._get_manual_target() == LIVRE
    assert written == {}, "alvo livre nao devia ter sido reescrito"


# --------------------------------------------------------------------------
# Caminho 3 -- conquista em andamento
# --------------------------------------------------------------------------

def _existing(man, status="train_sent"):
    return {"target_id": ALVO, "status": status, "hits_done": 4,
            "loyalty_after_train": 20, "last_hit_timestamp": 0}


def test_conquista_em_andamento_reservada_e_encerrada():
    """
    O trem leva ~4h e a reserva pode nascer nesse intervalo. Nao desfaz nada
    (nobre que saiu nao volta) -- para de comprometer nobres NOVOS.
    """
    man, written = _manager(_Board(claimed=[ALVO]))
    man._target_is_mine = lambda t: False
    man._target_taken_by_other = lambda t: None

    assert man._handle_existing(_existing(man), CFG) is False
    assert written[ALVO]["status"] == "blocked"
    assert written[ALVO]["reserved_by_name"] == "Conde Strahd von Zarovch"
    assert written[ALVO]["reservation_expires"] == "hoje às 07:45"


def test_falha_de_leitura_nao_aborta_trem_em_voo():
    """
    A metade menos obvia do contrato. Sem leitura o bot NAO inicia conquista
    nova -- mas abortar uma em andamento por nao conseguir abrir uma pagina
    jogaria fora tropa real que ja esta voando. Por isso `_handle_existing()`
    nao consulta `_may_start_new_conquest()`.
    """
    man, written = _manager(_Board(claimed=[], readable=False))
    man._target_is_mine = lambda t: False
    man._target_taken_by_other = lambda t: None
    man._noble_flight_guard = lambda t, d: True   # tem nobre no ar

    man._handle_existing(_existing(man), CFG)
    assert ALVO not in written, (
        "encerrou a conquista por falha de LEITURA -- isso descarta os 4 "
        "nobres que ja estao no ar"
    )


def test_posse_confirmada_vence_a_reserva():
    """
    Se a aldeia ja e NOSSA, a reserva de terceiro e irrelevante -- o alvo tem
    que ser marcado como conquistado, nao como bloqueado, senao o registro
    fica mentindo e o alvo nunca sai do caminho.
    """
    man, written = _manager(_Board(claimed=[ALVO]))
    man._target_is_mine = lambda t: True

    man._handle_existing(_existing(man), CFG)
    assert written[ALVO]["status"] == "conquered"


# --------------------------------------------------------------------------
# Caminho 4 -- trem AGENDADO (o unico onde ainda da para evitar a ofensa)
# --------------------------------------------------------------------------

def test_trem_agendado_cancela_o_schedule_do_hunter():
    """
    Em "train_scheduled" nada saiu: o Hunter esta dormindo ate o send_time.
    Marcar o registro como bloqueado sem apagar o SCHEDULE seria bloqueio
    cosmetico -- o Hunter nao conhece conquista, ele so manda ataque na hora
    marcada, e despacharia o trem inteiro contra a reserva alheia.
    """
    schedules = {"k1": {"attacks": [{"status": "pending"}], "arrival_time": 999}}
    conquest = {ALVO: {"status": "train_scheduled", "target_id": ALVO,
                       "hunter_schedule_key": "k1"}}
    written = {}
    released = []

    class _FM:
        @staticmethod
        def load_json_file(path, **k):
            return schedules if "hunter" in path else None

        @staticmethod
        def save_json_file(data, path, **k):
            if "hunter" in path:
                schedules.clear()
                schedules.update(data)

        @staticmethod
        def list_directory(d, ends_with=None): return []

    class _Cache:
        @staticmethod
        def active_conquests(): return dict(conquest)

        @staticmethod
        def set(tid, entry): written[str(tid)] = entry

    planner_mod.FileManager = _FM
    planner_mod.ConquestCache = _Cache

    p = BarbarianTrainPlanner.__new__(BarbarianTrainPlanner)
    p.villages = {}
    p.config = {"conquest": {}}
    p.logger = _Logger()
    p.reservation_board = _Board(claimed=[ALVO])
    p._release = lambda tid: released.append(tid)

    p._cancel_reserved_targets()

    assert "k1" not in schedules, "o schedule do Hunter sobreviveu -- o trem sairia"
    assert written[ALVO]["status"] == "blocked"
    assert released == [ALVO], "a reserva de TROPA do trem ficou presa (P2-22)"


def test_trem_agendado_livre_nao_e_cancelado():
    schedules = {"k1": {"attacks": [{"status": "pending"}]}}
    conquest = {LIVRE: {"status": "train_scheduled", "target_id": LIVRE,
                        "hunter_schedule_key": "k1"}}
    written = {}

    class _FM:
        @staticmethod
        def load_json_file(path, **k):
            return schedules if "hunter" in path else None

        @staticmethod
        def save_json_file(data, path, **k): pass

        @staticmethod
        def list_directory(d, ends_with=None): return []

    class _Cache:
        @staticmethod
        def active_conquests(): return dict(conquest)

        @staticmethod
        def set(tid, entry): written[str(tid)] = entry

    planner_mod.FileManager = _FM
    planner_mod.ConquestCache = _Cache

    p = BarbarianTrainPlanner.__new__(BarbarianTrainPlanner)
    p.villages = {}
    p.config = {"conquest": {}}
    p.logger = _Logger()
    p.reservation_board = _Board(claimed=[ALVO])
    p._release = lambda tid: None

    p._cancel_reserved_targets()
    assert "k1" in schedules
    assert written == {}


# --------------------------------------------------------------------------
# Caminho 5 -- conquista PvP (aldeia de jogador)
# --------------------------------------------------------------------------

def _pvp(board, claimed_written):
    class _Cache:
        @staticmethod
        def set(tid, data): claimed_written[str(tid)] = dict(data)

    pvp_mod.PvpConquestCache = _Cache
    man = PvpConquestManager.__new__(PvpConquestManager)
    man.config = {"conquest": {}, "pvp_conquest": {}}
    man.villages = {}
    man.reservation_board = board
    man.farm_suspended_villages = set()
    man._sync_source_locks = lambda tid, data: None
    return man


def test_pvp_cancela_alvo_reservado():
    """
    Por decisao do usuario o sistema vale para TODA conquista, nao so a
    barbara: furar reserva de companheiro numa aldeia de jogador custa o mesmo
    capital social.
    """
    written = {}
    man = _pvp(_Board(claimed=[ALVO]), written)
    data = {"status": "pending_scout"}

    assert man._block_if_reserved(ALVO, data) is True
    assert data["status"] == "failed", (
        "status 'failed' e o que faz _sync_source_locks soltar as travas de "
        "origem -- um status novo exigiria reler todo consumidor (P2-22)"
    )
    assert written[ALVO]["blocked_reason"] == "tribe_reservation"


def test_pvp_alvo_livre_segue():
    written = {}
    man = _pvp(_Board(claimed=[ALVO]), written)
    data = {"status": "pending_scout"}
    assert man._block_if_reserved(LIVRE, data) is False
    assert data["status"] == "pending_scout"
    assert written == {}


def test_pvp_nao_remexe_alvo_terminal():
    written = {}
    man = _pvp(_Board(claimed=[ALVO]), written)
    for status in ("complete", "failed"):
        data = {"status": status}
        assert man._block_if_reserved(ALVO, data) is False
        assert data["status"] == status
    assert written == {}


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
