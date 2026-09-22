"""
Testes da conquista barbara rodando no INICIO do ciclo (docs/backend.md 8.15).

Ate 2026-09-22 o `BarbarianTrainPlanner` era construido no fim do `while` de
`twb.py`, depois do laco das 30 aldeias. Nessa posicao `village.units` e
`village.area` vinham de graca -- e a reserva de tropa do trem so passava a
valer no ciclo seguinte, porque farm e coleta ja tinham gastado o ciclo todo.

Movido para o inicio, nada disso vem de graca. O que este arquivo cobre e
exatamente o que a mudanca introduziu:

  1. `TWB._maybe_holds_noble()`  -- quem entra na lista do prime, e por que ela
     e deliberadamente um SUPERCONJUNTO (memoria do ciclo passado UNIAO
     snapshot de cache/managed).
  2. `TWB.prime_barbarian_sources()` -- a ancora da conquista ativa entra mesmo
     sem nobre nenhum em casa, e quem a conquista PvP acabou de primar nao e
     lido duas vezes.
  3. `TWB.run_barbarian_conquest()` -- ACOMPANHAR antes de PLANEJAR. Esta e a
     unica das tres que protege contra um bug de verdade: o planejador desiste
     cedo quando `active_conquests()` nao esta vazio, entao com a ordem
     invertida uma conquista que acabou de terminar bloquearia a proxima por um
     ciclo inteiro -- e um ciclo aqui mede horas.

Sem rede e sem estado de jogo: `ConquestCache`, `FileManager` e o proprio
`BarbarianTrainPlanner` sao trocados por duplos dentro do modulo `twb`.

Rodar: python tests/test_conquest_cycle_start.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import twb
from twb import TWB


class FakeUnits:
    def __init__(self, troops=None):
        self.troops = troops or {}


class FakeVillage:
    """So o que os caminhos testados leem de uma Village."""

    def __init__(self, village_id, snob_in_memory=None, prime_ok=True):
        self.village_id = village_id
        self.units = None if snob_in_memory is None else FakeUnits({"snob": snob_in_memory})
        self.config = {"conquest": {"enabled": True}}
        self.prime_ok = prime_ok
        self.primed = 0
        self.conquest_runs = 0
        self.events = None

    def prime_for_conquest(self, config=None):
        self.primed += 1
        return self.prime_ok

    def run_conquest(self):
        self.conquest_runs += 1
        if self.events is not None:
            self.events.append(("track", self.village_id))


class FakeFileManager:
    """cache/managed/{vid}.json sem tocar em disco."""

    def __init__(self, snapshots):
        self.snapshots = snapshots

    def load_json_file(self, path):
        vid = os.path.basename(path).replace(".json", "")
        return self.snapshots.get(vid)


class FakeConquestCache:
    def __init__(self, active):
        self._active = active

    def active_conquests(self):
        return dict(self._active)


def patched(file_manager=None, conquest_cache=None, planner=None):
    """Troca os colaboradores do modulo twb e devolve o estado anterior."""
    saved = (twb.FileManager, twb.ConquestCache, twb.BarbarianTrainPlanner)
    if file_manager is not None:
        twb.FileManager = file_manager
    if conquest_cache is not None:
        twb.ConquestCache = conquest_cache
    if planner is not None:
        twb.BarbarianTrainPlanner = planner
    return saved


def restore(saved):
    twb.FileManager, twb.ConquestCache, twb.BarbarianTrainPlanner = saved


# ----------------------------------------------------------------------
# 1. _maybe_holds_noble
# ----------------------------------------------------------------------

def test_maybe_holds_noble_pelas_duas_fontes():
    saved = patched(file_manager=FakeFileManager({
        # Aldeia que recrutou nobre e ainda nao rodou neste ciclo: a memoria
        # diz zero, o snapshot do ciclo passado diz 2.
        "200": {"troops": {"snob": 2}},
        "300": {"troops": {"snob": 0}},
        # Sem arquivo nenhum (aldeia nova): cai no None do load_json_file.
    }))
    try:
        # Memoria com nobre vence sozinha, mesmo sem snapshot.
        assert TWB._maybe_holds_noble("100", FakeVillage("100", snob_in_memory=3))
        # Memoria zerada + snapshot com nobre -> entra. E o caso que separa a
        # uniao das duas fontes de uma leitura so.
        assert TWB._maybe_holds_noble("200", FakeVillage("200", snob_in_memory=0))
        # Zero nos dois lados -> fica de fora. Sem isto o prime custaria 4
        # requisicoes por aldeia do imperio inteiro, todo ciclo.
        assert not TWB._maybe_holds_noble("300", FakeVillage("300", snob_in_memory=0))
        # Aldeia que nunca rodou e nao tem snapshot: units None, sem arquivo.
        assert not TWB._maybe_holds_noble("400", FakeVillage("400"))
    finally:
        restore(saved)
    print("OK: _maybe_holds_noble le memoria e snapshot, e a uniao dos dois")


# ----------------------------------------------------------------------
# 2. prime_barbarian_sources
# ----------------------------------------------------------------------

def test_prime_inclui_ancora_sem_nobre_e_pula_o_que_o_pvp_ja_leu():
    villages = {
        "100": FakeVillage("100", snob_in_memory=4),   # tem nobre
        "200": FakeVillage("200", snob_in_memory=0),   # nada
        "900": FakeVillage("900", snob_in_memory=0),   # ancora, sem nobre
        "700": FakeVillage("700", snob_in_memory=2),   # ja primada pelo PvP
    }
    saved = patched(
        file_manager=FakeFileManager({}),
        conquest_cache=FakeConquestCache({
            "44155": {"status": "train_sent", "reserved_by": "900"},
        }),
    )
    try:
        primed = TWB.prime_barbarian_sources(
            villages, {"conquest": {"enabled": True}}, already_primed={"700"}
        )
    finally:
        restore(saved)

    # A ancora nao tem nobre nenhum -- ela ja despachou o trem. Mas e ela quem
    # le a lealdade real do relatorio e manda o nobre extra, entao ficar de
    # fora do prime deixaria a conquista em andamento sem acompanhamento no
    # ciclo inteiro.
    assert primed == {"100", "900"}, primed
    assert villages["900"].primed == 1
    assert villages["200"].primed == 0
    # Quem a conquista PvP acabou de ler nao e relido: sao ~4 requisicoes.
    assert villages["700"].primed == 0
    print("OK: o prime inclui a ancora sem nobre e nao repete o que o PvP leu")


def test_prime_nao_conta_aldeia_que_nao_deu_leitura():
    villages = {
        "100": FakeVillage("100", snob_in_memory=4),
        "101": FakeVillage("101", snob_in_memory=4, prime_ok=False),
    }
    saved = patched(
        file_manager=FakeFileManager({}),
        conquest_cache=FakeConquestCache({}),
    )
    try:
        primed = TWB.prime_barbarian_sources(villages, {})
    finally:
        restore(saved)
    # Timeout de requisicao nao pode virar "primada": o planejador contaria
    # nobre de um numero velho achando que e vivo.
    assert primed == {"100"}, primed
    print("OK: aldeia sem leitura viva nao entra no conjunto primado")


# ----------------------------------------------------------------------
# 3. run_barbarian_conquest: acompanhar antes de planejar
# ----------------------------------------------------------------------

def test_acompanhamento_roda_antes_do_planejador_e_uma_vez_por_ancora():
    events = []

    class FakePlanner:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def run(self):
            events.append(("plan", None))

    villages = {
        "900": FakeVillage("900"),
        "901": FakeVillage("901"),
    }
    for v in villages.values():
        v.events = events

    saved = patched(
        conquest_cache=FakeConquestCache({
            # Duas entradas ativas da MESMA ancora: o acompanhamento e por
            # aldeia (`_get_my_conquest` casa por reserved_by), nao por alvo.
            "44155": {"status": "train_sent", "reserved_by": "900"},
            "44156": {"status": "extra_pending", "reserved_by": "900"},
            "44157": {"status": "train_scheduled", "reserved_by": "901"},
        }),
        planner=FakePlanner,
    )
    bot = TWB.__new__(TWB)
    bot.wrapper = None
    bot.hunter = None
    try:
        bot.run_barbarian_conquest(
            managed_villages=villages,
            config={"conquest": {"enabled": True}},
            reservation_board=None,
            world_villages=None,
            reservation_writer=None,
        )
    finally:
        restore(saved)

    assert events[-1] == ("plan", None), events
    tracked = [vid for kind, vid in events if kind == "track"]
    assert sorted(tracked) == ["900", "901"], tracked
    print("OK: acompanhar antes de planejar, uma chamada por ancora")


def test_ancora_sem_config_nao_e_chamada():
    """
    `run_conquest()` faz `self.config.get(...)` de cara. Aldeia que nunca
    primou nem rodou ainda tem `config` None -- chamar ali derrubaria o ciclo
    inteiro por AttributeError, no primeiro caminho do ciclo.
    """
    events = []

    class FakePlanner:
        def __init__(self, **kwargs):
            pass

        def run(self):
            events.append(("plan", None))

    village = FakeVillage("900")
    village.config = None
    village.events = events

    saved = patched(
        conquest_cache=FakeConquestCache({
            "44155": {"status": "train_sent", "reserved_by": "900"},
            # Ancora que nem existe no dict de aldeias gerenciadas.
            "44156": {"status": "train_sent", "reserved_by": "555"},
        }),
        planner=FakePlanner,
    )
    bot = TWB.__new__(TWB)
    bot.wrapper = None
    bot.hunter = None
    try:
        bot.run_barbarian_conquest(
            managed_villages={"900": village},
            config={},
            reservation_board=None,
            world_villages=None,
            reservation_writer=None,
        )
    finally:
        restore(saved)

    assert village.conquest_runs == 0
    assert events == [("plan", None)], events
    print("OK: ancora sem config (ou ausente) e pulada sem derrubar o ciclo")


if __name__ == "__main__":
    test_maybe_holds_noble_pelas_duas_fontes()
    test_prime_inclui_ancora_sem_nobre_e_pula_o_que_o_pvp_ja_leu()
    test_prime_nao_conta_aldeia_que_nao_deu_leitura()
    test_acompanhamento_roda_antes_do_planejador_e_uma_vez_por_ancora()
    test_ancora_sem_config_nao_e_chamada()
    print("\nTodos os testes passaram.")
