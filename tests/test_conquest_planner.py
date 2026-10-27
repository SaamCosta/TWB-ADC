"""
Testes do planejador de trem barbaro multi-origem (Feature 8, fase 2).

  BarbarianTrainPlanner._noble_sources()   -- de onde vem os nobres
  BarbarianTrainPlanner._build_plan()      -- um nobre por comando, com escolta
  BarbarianTrainPlanner._schedule()        -- chegada comum e registro no Hunter
  BarbarianTrainPlanner._promote_...()     -- costura Hunter -> cache/conquest
  BarbarianTrainPlanner.run()              -- invariante de um trem por vez

O caso que motivou tudo, medido na conta em 16/09/2026: 5 nobres no imperio,
3 na BBM 001 e 2 na BBM 011, ZERO aldeias com os 4 que o modelo antigo exigia
na mesma aldeia. Nobres de sobra para um trem e nenhum trem possivel.

A fixture abaixo e exatamente esse estado.

Nada aqui toca cache/ nem a rede: FileManager, ConquestCache, HunterReader e a
sondagem de duracao do Hunter sao substituidos por dublês em memoria. O bot
escreve nesses mesmos arquivos enquanto roda (vigesimo primeiro padrao do
CLAUDE.md).

Rodar: python tests/test_conquest_planner.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import game.attack as attack_mod
import game.conquest_planner as planner_mod
from game.conquest_planner import BarbarianTrainPlanner


# --------------------------------------------------------------------------
# Dublês
# --------------------------------------------------------------------------

class _Logger:
    def debug(self, *a, **k): pass
    def info(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def error(self, *a, **k): pass


class _Reporter:
    def report(self, *a, **k): pass


class _Wrapper:
    reporter = _Reporter()


class _Units:
    def __init__(self, troops):
        self.troops = dict(troops)
        self.conquest_reserve = {}

    def total_conquest_reserve(self, exclude_owner=None):
        total = {}
        for owner, troops in self.conquest_reserve.items():
            if owner == exclude_owner:
                continue
            for unit, qty in troops.items():
                total[unit] = total.get(unit, 0) + int(qty)
        return total


class _Area:
    """`Village.area` e o Map da aldeia; daqui so sai a coordenada dela."""

    def __init__(self, my_location=None):
        self.my_location = my_location


class _Village:
    def __init__(self, vid, troops, location=None):
        self.village_id = vid
        self.units = _Units(troops)
        self.area = _Area(location)
        self.attack = None


# Estado real da conta em 16/09/2026, com as coordenadas de campo.
def _empire():
    return {
        "41123": _Village("41123", {"snob": 3, "axe": 4000, "light": 800}, [577, 306]),
        "41140": _Village("41140", {"snob": 2, "axe": 3000, "light": 600}, [585, 304]),
        "44620": _Village("44620", {"snob": 0, "axe": 2000}, [586, 308]),
    }


class _FakeManager:
    """ConquestManager suficiente para o que o planejador pede dele."""
    escort = {"axe": 100}
    target = "49709"
    failed_claims = []
    reach_seen = []

    def __init__(self, *a, **k):
        pass

    def find_target(self, cfg, reach_from=None):
        _FakeManager.reach_seen.append(reach_from)
        return _FakeManager.target

    def _get_village_meta(self, target_id):
        return {"name": "Bárbara", "points": 856, "location": [572, 295]}

    def _build_escort(self, cfg):
        return dict(_FakeManager.escort) if _FakeManager.escort else None

    def _calculate_needed_escort(self, cfg):
        return {"axe": 500}

    def _note_failed_claim(self, target_id):
        _FakeManager.failed_claims.append(target_id)

    @staticmethod
    def world_drop_range(config):
        # A faixa do br143 (<mood> 20..35). O `conquest.loyalty_drop_per_noble`
        # da config (25) NAO e o piso do mundo -- era esse o A26-03.
        return (20, 35)


class _FakeHunter:
    duration = 3600.0

    def __init__(self, *a, **k):
        self.villages = {}

    def _probe_duration(self, source_id, target_id, troops):
        return _FakeHunter.duration


def _install(store=None, schedules=None, active=None):
    """Substitui tudo que sai do processo. Devolve o registro das chamadas."""
    store = {} if store is None else store
    schedules = {} if schedules is None else schedules
    calls = {"schedules": [], "store": store, "hunter_cache": schedules}

    class _Cache:
        ACTIVE_STATUSES = ("train_scheduled", "train_sent", "extra_pending")

        @staticmethod
        def get(tid):
            return store.get(tid)

        @staticmethod
        def set(tid, entry):
            store[tid] = entry

        @staticmethod
        def active_conquests():
            return dict(active or {})

        @staticmethod
        def nobles_in_flight(data, now=None):
            return []

    class _FM:
        @staticmethod
        def load_json_file(path, **k):
            if path.endswith("schedules.json"):
                return schedules
            name = os.path.basename(path).replace(".json", "")
            return store.get(name)

        @staticmethod
        def list_directory(directory, ends_with=None):
            if "conquest" in directory:
                return ["%s.json" % k for k in store]
            return []

    planner_mod.ConquestCache = _Cache
    planner_mod.FileManager = _FM
    # 8.41: a coordenada da origem saiu para `village_location` (attack.py),
    # que le cache/managed pelo FileManager DAQUELE modulo. Sem trocar os
    # dois, o teste passaria a ler o cache/ real.
    attack_mod.FileManager = _FM
    planner_mod.ConquestManager = type(
        "M", (_FakeManager,), {"TRAIN_SIZE": 4}
    )
    planner_mod.Hunter = type("H", (_FakeHunter,), {"SCHEDULE_CACHE": "x/schedules.json"})

    _FakeManager.failed_claims = []
    _FakeManager.escort = {"axe": 100}
    _FakeManager.target = "49709"
    _FakeManager.reach_seen = []
    return calls


def _planner(villages=None, store=None, schedules=None, active=None, cfg=None):
    calls = _install(store, schedules, active)
    p = BarbarianTrainPlanner(
        wrapper=_Wrapper(),
        villages=_empire() if villages is None else villages,
        config=cfg or {"conquest": {"enabled": True}, "hunter": {"enabled": True}},
        hunter=_FakeHunter(),
    )
    p.logger = _Logger()

    def _add(target_id, arrival_str, attacks, label=""):
        calls["schedules"].append(
            {"target_id": target_id, "arrival_str": arrival_str,
             "attacks": attacks, "label": label}
        )
        return True

    p._add_hunter_schedule = lambda t, a, plan: _add(
        t, a, [{"source_village_id": x["source_village_id"],
                "troops": x["troops"]} for x in plan]
    )
    return p, calls


# --------------------------------------------------------------------------
# _noble_sources
# --------------------------------------------------------------------------

def test_soma_nobres_de_aldeias_diferentes():
    """O caso de 16/09: 3+2 dao um trem, e nenhuma aldeia tem 4."""
    p, _ = _planner()
    assert p._noble_sources() == [("41123", 3), ("41140", 2)]


def test_nobre_reservado_por_outro_sistema_nao_conta():
    """
    PvpConquestManager reserva um snob por ataque agendado, e ele fica em casa
    por horas esperando o Hunter. Conta-lo como livre e o double-booking que a
    Feature 27 existe para matar -- na unidade mais cara do jogo.
    """
    villages = _empire()
    villages["41123"].units.conquest_reserve["pvp:900"] = {"snob": 2}
    p, _ = _planner(villages=villages)
    assert p._noble_sources() == [("41140", 2), ("41123", 1)]


def test_aldeia_com_conquest_enabled_false_fica_de_fora():
    p, _ = _planner(cfg={
        "conquest": {"enabled": True}, "hunter": {"enabled": True},
        "villages": {"41123": {"conquest_enabled": False}},
    })
    assert p._noble_sources() == [("41140", 2)]


def test_ancora_e_quem_tem_mais_nobres():
    """
    Importa porque find_target() PONTUA a distancia a partir da ancora:
    ancorar onde esta a maior parte do trem encurta a viagem mais longa, que e
    a que define a chegada comum de todo mundo.

    O que a ancora nao faz mais e decidir quem entra na lista -- ver
    test_alcance_vem_de_todas_as_aldeias_com_nobre.
    """
    p, _ = _planner()
    assert p._anchor_village() == "41123"


# --------------------------------------------------------------------------
# Alcance do imperio (docs/backend.md 8.6)
# --------------------------------------------------------------------------

def test_alcance_vem_de_todas_as_aldeias_com_nobre():
    """
    O defeito de 17/09/2026: a elegibilidade do alvo era medida SO da ancora,
    entao o conjunto de alvos dependia de onde os nobres se acumularam --
    circunstancia, nao geografia. Medido no cache real, isso escondia 10 das
    39 barbaras do K25 com raio 30.
    """
    p, _ = _planner()
    p.run()
    assert _FakeManager.reach_seen == [[(577, 306), (585, 304)]]


def test_aldeia_sem_nobre_nao_conta_para_o_alcance():
    """
    Alcance e "de onde um nobre pode SAIR". A 44620 nao tem nobre, entao um
    alvo que so ela alcanca nao e alcancavel de verdade -- e o trem sairia
    montado com origens que nao chegam la.
    """
    p, _ = _planner()
    p.run()
    assert (586, 308) not in _FakeManager.reach_seen[0]


def test_origem_sem_coordenada_conhecida_nao_entra_no_alcance():
    """
    Sem a guarda, `my_location` None viraria (0, 0) -- coordenada valida no
    mapa do jogo -- e o filtro de raio mediria a partir do canto do mundo.
    """
    villages = _empire()
    villages["41140"].area.my_location = None
    p, _ = _planner(villages=villages)
    p.run()
    assert _FakeManager.reach_seen == [[(577, 306)]]


# --------------------------------------------------------------------------
# _build_plan
# --------------------------------------------------------------------------

def test_plano_tem_um_nobre_por_comando():
    """
    Regra do jogo, nao escolha: cada ataque derruba lealdade uma vez. Quatro
    nobres num comando so seriam um unico golpe com quatro nobres mortos junto.
    """
    p, _ = _planner()
    plan = p._build_plan("49709", p._noble_sources(), {})
    assert len(plan) == 4
    assert all(atk["troops"]["snob"] == 1 for atk in plan)


def test_plano_distribui_conforme_os_nobres_de_cada_aldeia():
    p, _ = _planner()
    plan = p._build_plan("49709", p._noble_sources(), {})
    origens = [atk["source_village_id"] for atk in plan]
    assert origens.count("41123") == 3
    assert origens.count("41140") == 1


def test_escolta_e_redistribuida_quando_a_aldeia_manda_menos_de_quatro():
    """
    _build_escort divide a tropa comprometida por TRAIN_SIZE presumindo 4
    nobres locais. Mandando 1, os outros 3 quinhoes sobrariam em casa sem esta
    correcao -- escolta menor do que a aldeia podia pagar.
    """
    p, _ = _planner()
    plan = p._build_plan("49709", [("41140", 1), ("41123", 3)], {})
    da_41140 = [a for a in plan if a["source_village_id"] == "41140"]
    assert da_41140[0]["troops"]["axe"] == 400  # 100 * (4/1)


def _norte_e_sul():
    """
    Coordenadas reais de 2026-10-04: a BBM 019 (579|318) no sul e as BBM 038
    (572|287) e BBM 036 (575|287) no norte, com o alvo em 570|280, dentro da
    area de interesse. O sul tem MAIS nobres -- era isso que o colocava na
    frente do trem.
    """
    return {
        "35059": _Village("35059", {"snob": 4, "axe": 4000}, [579, 318]),
        "55553": _Village("55553", {"snob": 2, "axe": 3000}, [572, 287]),
        "57689": _Village("57689", {"snob": 2, "axe": 3000}, [575, 287]),
    }


def test_plano_pega_as_origens_mais_perto_do_alvo():
    """
    A chegada comum e a da origem mais lenta, e todo comando anda na
    velocidade do nobre. 4 nobres da BBM 019 (39 campos, ~22,7 h) davam um
    trem pior que 2+2 do norte (~7 e ~9 campos) so por estarem juntos.
    """
    p, _ = _planner(villages=_norte_e_sul())
    plan = p._build_plan("49709", p._noble_sources(), {},
                         target_location=[570, 280])
    origens = [atk["source_village_id"] for atk in plan]
    assert "35059" not in origens
    assert origens.count("55553") == 2 and origens.count("57689") == 2


def test_sem_coordenada_do_alvo_vale_a_ordem_por_quantidade():
    """Controle do teste acima: sem alvo localizado nao ha o que medir."""
    p, _ = _planner(villages=_norte_e_sul())
    plan = p._build_plan("49709", p._noble_sources(), {})
    assert [atk["source_village_id"] for atk in plan] == ["35059"] * 4


def test_origem_sem_coordenada_vai_para_o_fim():
    """
    "Nao sei onde fica" nao pode ganhar de "sei que esta perto". Se a falta
    de coordenada virasse distancia 0, a origem desconhecida furaria a fila.
    """
    villages = _norte_e_sul()
    villages["55553"].area.my_location = None
    p, _ = _planner(villages=villages)
    ordem = [vid for vid, _ in p._order_by_arrival(p._noble_sources(), [570, 280])]
    assert ordem == ["57689", "35059", "55553"]


def test_origem_fora_do_alcance_do_nobre_fica_de_fora():
    """
    O alvo entra na lista por estar no raio de ALGUMA aldeia com nobre; isso
    nao garante que CADA origem chegue la. Nesta conta ainda nao acontece (a
    pior combinacao medida e 50,5 campos contra os 70 do mundo), e a falha
    seria segura -- o jogo recusaria o envio --, mas o log diria apenas "nao
    consegui a duracao pelo servidor", que e sintoma de meia duzia de coisas.

    A 41123 (577|306) esta a 95,2 campos de 500|250. Sem ela sobram 2 nobres,
    e trem parcial nao sai.
    """
    class _WC:
        @staticmethod
        def get(server=None, endpoint=None, force_refresh=False):
            return {"snob": {"max_dist": 70}}

        @staticmethod
        def noble_max_distance(data):
            return (data.get("snob") or {}).get("max_dist")

    p, _ = _planner()
    original = planner_mod.WorldConfig
    planner_mod.WorldConfig = _WC
    try:
        assert p._build_plan("49709", p._noble_sources(), {},
                             target_location=[500, 250]) is None
        # Sem a coordenada do alvo a guarda nao roda -- e o comportamento
        # anterior, que serve de controle: o que barrou acima foi a distancia.
        assert p._build_plan("49709", p._noble_sources(), {}) is not None
    finally:
        planner_mod.WorldConfig = original


def test_alcance_do_nobre_desconhecido_deixa_passar():
    """
    Mundo que nao publica `<snob><max_dist>` e mundo sem limite conhecido.
    Inventar um teto aqui recusaria em casa um envio que o jogo aceitaria.
    """
    p, _ = _planner()
    assert p._build_plan("49709", p._noble_sources(), {},
                         target_location=[500, 250]) is not None


def test_sem_escolta_nao_agenda_trem_parcial():
    """
    Trem parcial e o pior dos mundos: gasta nobre e deixa a barbara viva com
    lealdade baixa para outro levar.
    """
    p, _ = _planner()
    _FakeManager.escort = None
    assert p._build_plan("49709", p._noble_sources(), {}) is None


def test_aldeia_sem_escolta_recebe_reserva_para_juntar():
    """
    Comportamento que existia no run() por aldeia e teria se perdido calado na
    mudanca de dono: sem reserva, farm e gather gastam a tropa que a aldeia
    estava juntando e a escolta nunca fecha.
    """
    villages = _empire()
    p, _ = _planner(villages=villages)
    _FakeManager.escort = None
    p._build_plan("49709", p._noble_sources(), {})
    assert villages["41123"].units.conquest_reserve["barbarian_conquest"] == {"axe": 500}


# --------------------------------------------------------------------------
# _schedule
# --------------------------------------------------------------------------

def test_chegada_comum_cobre_a_viagem_mais_longa():
    p, calls = _planner()
    plan = p._build_plan("49709", p._noble_sources(), {})
    p._schedule("49709", {}, plan, {})
    assert len(calls["schedules"]) == 1
    entry = calls["store"]["49709"]
    # 1h de viagem + 10 min de margem
    assert entry["scheduled_arrival"] - entry["scheduled_at"] >= 3600 + 600


def test_todas_as_origens_entram_no_mesmo_schedule():
    """
    Um schedule so, com uma arrival_time so, e o que faz o Hunter convergir as
    quatro chegadas. Dois schedules dariam duas operacoes independentes.
    """
    p, calls = _planner()
    plan = p._build_plan("49709", p._noble_sources(), {})
    p._schedule("49709", {}, plan, {})
    atks = calls["schedules"][0]["attacks"]
    assert len(atks) == 4
    assert {a["source_village_id"] for a in atks} == {"41123", "41140"}


def test_status_agendado_reserva_o_alvo():
    """
    Entre agendar e o Hunter disparar nao ha nobre no ar nem "train_sent", e
    sem um status proprio find_target() reelegeria o mesmo alvo como livre.
    """
    p, calls = _planner()
    plan = p._build_plan("49709", p._noble_sources(), {})
    p._schedule("49709", {}, plan, {})
    assert calls["store"]["49709"]["status"] == "train_scheduled"
    assert calls["store"]["49709"]["sources"] == {"41123": 3, "41140": 1}


def test_tropa_fica_reservada_ate_o_hunter_mandar():
    """
    send_time e recuado a partir da chegada, entao essa janela e de horas. Sem
    reserva o farm gasta a tropa e o comando falha no disparo.
    """
    villages = _empire()
    p, _ = _planner(villages=villages)
    plan = p._build_plan("49709", p._noble_sources(), {})
    p._schedule("49709", {}, plan, {})
    reserva = villages["41123"].units.conquest_reserve["barb_train:49709"]
    assert reserva["snob"] == 3
    # 133 por comando x 3 comandos: a 41123 manda 3 dos 4 nobres, entao a
    # escolta dela tambem e redistribuida (100 * 4/3), e o reservado tem que
    # bater com o que vai ser enviado de fato -- reservar os 100 originais
    # deixaria 99 lanças de fora da reserva e o farm poderia gasta-las.
    assert reserva["axe"] == 399


def test_sonda_sem_resposta_nao_agenda_nada():
    """
    Sem a duracao do servidor nao da para sincronizar. Chutar uma chegada seria
    inventar o numero que o Hunter existe para medir.
    """
    p, calls = _planner()
    _FakeHunter.duration = None
    try:
        plan = p._build_plan("49709", p._noble_sources(), {})
        assert p._schedule("49709", {}, plan, {}) is None
        assert calls["schedules"] == []
        assert calls["store"] == {}
    finally:
        _FakeHunter.duration = 3600.0


# --------------------------------------------------------------------------
# run — invariantes
# --------------------------------------------------------------------------

def test_um_trem_por_vez_no_imperio():
    """
    A invariante existia por acidente no modelo antigo (cada aldeia precisava
    de 4 nobres proprios). Juntando nobres do imperio, nada garantiria isso e
    dois trens disputariam os mesmos nobres.
    """
    p, calls = _planner(active={"40314": {"status": "train_sent"}})
    assert p.run() is None
    assert calls["schedules"] == []


def test_nobres_insuficientes_no_imperio_inteiro():
    villages = {"41123": _Village("41123", {"snob": 1, "axe": 4000})}
    p, calls = _planner(villages=villages)
    assert p.run() is None
    assert calls["schedules"] == []


def test_hunter_desligado_nao_monta_trem():
    """
    Sem Hunter nao ha sincronizacao, e trem multi-origem sem sincronizacao
    chega esparramado -- exatamente o que este desenho existe para evitar.
    """
    p, calls = _planner(cfg={
        "conquest": {"enabled": True}, "hunter": {"enabled": False},
    })
    assert p.run() is None
    assert calls["schedules"] == []


def test_caminho_feliz_agenda():
    p, calls = _planner()
    assert p.run() == "49709"
    assert len(calls["schedules"]) == 1


def test_falha_de_agendamento_conta_contra_o_alvo_manual():
    """
    A fila manual tem prioridade absoluta em find_target(), entao um alvo que
    nunca chega a ser agendado congelaria a selecao automatica do imperio. A
    guarda mudou de lugar junto com a montagem do trem -- se ela tivesse
    ficado no run() por aldeia, estaria viva no teste e morta em campo.
    """
    p, _ = _planner()
    _FakeManager.escort = None
    assert p.run() is None
    assert _FakeManager.failed_claims == ["49709"]


# --------------------------------------------------------------------------
# _promote_scheduled_trains — a costura com o Hunter
# --------------------------------------------------------------------------

def test_promove_para_enviado_quando_o_hunter_despachou():
    store = {"49709": {
        "status": "train_scheduled", "hunter_schedule_key": "k",
        "hits_needed": 4,
    }}
    schedules = {"k": {
        "arrival_time": 2000000000,
        "attacks": [{"status": "sent"}] * 4,
    }}
    p, _ = _planner(store=store, schedules=schedules)
    p._promote_scheduled_trains()
    assert store["49709"]["status"] == "train_sent"
    assert store["49709"]["hits_done"] == 4
    assert store["49709"]["noble_arrivals"] == [2000000000] * 4
    # Pior caso de propósito com o PISO DO MUNDO: 4 x 20 = 80, sobra 20. Com
    # 25 da config gravava 0, e a estimativa pos-pouso deixava de ser limite
    # superior (A26-03).
    assert store["49709"]["loyalty_after_train"] == 20


def test_nobre_atrasado_promove_com_a_chegada_dele():
    """
    §8.71 fase 4: o par da BBM 008 contra a 81800 saiu 401 s atrasado. Ele
    pousa depois do trem, e a trava de nobre em voo e o tick de eventos
    precisam da chegada DELE, nao da comum -- senao o acompanhamento rodaria
    no pouso do trem com dois nobres ainda no ar.
    """
    store = {"49709": {"status": "train_scheduled", "hunter_schedule_key": "k"}}
    schedules = {"k": {"arrival_time": 2000000000, "attacks": [
        {"status": "sent"}, {"status": "sent"},
        {"status": "sent", "late_by_seconds": 401.8, "arrival_real": 2000000402},
        {"status": "sent", "late_by_seconds": 401.8, "arrival_real": 2000000402},
    ]}}
    p, _ = _planner(store=store, schedules=schedules)
    p._promote_scheduled_trains()
    assert store["49709"]["status"] == "train_sent"
    assert store["49709"]["noble_arrivals"] == [2000000000, 2000000000,
                                                2000000402, 2000000402]
    assert store["49709"]["last_hit_timestamp"] == 2000000402


def test_nao_promove_com_comando_ainda_pendente():
    store = {"49709": {"status": "train_scheduled", "hunter_schedule_key": "k"}}
    schedules = {"k": {"arrival_time": 2000000000, "attacks": [
        {"status": "sent"}, {"status": "pending"},
    ]}}
    p, _ = _planner(store=store, schedules=schedules)
    p._promote_scheduled_trains()
    assert store["49709"]["status"] == "train_scheduled"


def test_envio_parcial_vira_extra_pending():
    """
    3 de 4 sairam: a conquista continua viva e precisa de nobre extra, que e
    exatamente o que _handle_existing() trata.
    """
    store = {"49709": {"status": "train_scheduled", "hunter_schedule_key": "k"}}
    schedules = {"k": {"arrival_time": 2000000000, "attacks": [
        {"status": "sent"}, {"status": "sent"}, {"status": "sent"},
        {"status": "failed"},
    ]}}
    p, _ = _planner(store=store, schedules=schedules)
    p._promote_scheduled_trains()
    assert store["49709"]["status"] == "extra_pending"
    assert store["49709"]["hits_done"] == 3
    assert store["49709"]["loyalty_after_train"] == 40


def test_piso_gravado_no_registro_vence_o_do_mundo():
    """O que o agendamento gravou e o que a promocao usa."""
    store = {"49709": {"status": "train_scheduled", "hunter_schedule_key": "k",
                       "loyalty_drop_per_noble": 30}}
    schedules = {"k": {"arrival_time": 2000000000, "attacks": [{"status": "sent"}] * 3}}
    p, _ = _planner(store=store, schedules=schedules)
    p._promote_scheduled_trains()
    assert store["49709"]["loyalty_after_train"] == 10


def test_agendamento_grava_a_faixa_do_mundo():
    p, calls = _planner()
    plan = p._build_plan("49709", p._noble_sources(), {})
    p._schedule("49709", {}, plan, {})
    entry = calls["store"]["49709"]
    assert entry["loyalty_drop_per_noble"] == 20
    assert entry["loyalty_drop_range"] == [20, 35]


def test_chegada_vencida_com_comando_pendente_promove():
    """
    A26-04. O bot ficou parado durante a janela do trem: 3 sairam, o 4o ficou
    `pending` e a chegada passou. Antes, o registro ficava em
    `train_scheduled` para sempre e o planejador parava ("um trem por vez").
    O schedule aqui continua `pending` de proposito: a guarda olha o relogio,
    nao o campo que o Hunter deveria ter atualizado.
    """
    import time as _t
    villages = _empire()
    villages["41123"].units.conquest_reserve["barb_train:49709"] = {"axe": 300}
    store = {"49709": {"status": "train_scheduled", "hunter_schedule_key": "k"}}
    schedules = {"k": {"status": "pending", "arrival_time": _t.time() - 60, "attacks": [
        {"status": "sent"}, {"status": "sent"}, {"status": "sent"},
        {"status": "pending"},
    ]}}
    p, _ = _planner(villages=villages, store=store, schedules=schedules)
    p._promote_scheduled_trains()
    assert store["49709"]["status"] == "extra_pending"
    assert store["49709"]["hits_done"] == 3
    assert "barb_train:49709" not in villages["41123"].units.conquest_reserve


def test_schedule_ja_falho_com_pendente_herdado_promove():
    """
    Registro gravado antes da correcao do Hunter: schedule `failed`, ataques
    ainda `pending`. Chegada no futuro de proposito, para provar que o status
    do schedule sozinho ja basta.
    """
    store = {"49709": {"status": "train_scheduled", "hunter_schedule_key": "k"}}
    schedules = {"k": {"status": "failed", "arrival_time": 2000000000, "attacks": [
        {"status": "pending"}, {"status": "pending"},
    ]}}
    p, _ = _planner(store=store, schedules=schedules)
    p._promote_scheduled_trains()
    assert store["49709"]["status"] == "invalid"


def test_duracao_sondada_vira_send_time_no_schedule():
    """
    A26-14. O planejador ja sondou a duracao; o schedule nasce com a hora de
    saida e o Hunter nao sonda de novo. Passa pelo HunterReader real, com o
    arquivo trocado por memoria (o bot escreve no de verdade).
    """
    import webmanager.utils as wu
    raw = {}
    saved = (wu.HunterReader._load_raw, wu.HunterReader._save_raw, wu.file_lock)
    wu.HunterReader._load_raw = staticmethod(lambda **_k: raw)
    wu.HunterReader._save_raw = staticmethod(lambda data: raw.update(data))
    # A trava do A26-12 criaria cache/hunter/schedules.json.lock no repo real.
    import contextlib
    wu.file_lock = lambda *_a, **_k: contextlib.nullcontext()
    try:
        p, _ = _planner()
        plan = [
            {"source_village_id": "41123", "troops": {"snob": 1, "axe": 100},
             "duration_seconds": 3600.0},
            {"source_village_id": "41140", "troops": {"snob": 1}},
        ]
        ok = BarbarianTrainPlanner._add_hunter_schedule(
            p, "49709", "2030-01-01 12:00:00", plan
        )
    finally:
        wu.HunterReader._load_raw, wu.HunterReader._save_raw, wu.file_lock = saved
    assert ok
    (sched,) = raw.values()
    first, second = sched["attacks"]
    assert first["send_time"] == sched["arrival_time"] - 3600.0
    # Sem duracao conhecida continua None: o Hunter sonda, como sempre fez.
    assert second["send_time"] is None


def test_nenhum_comando_saiu_libera_o_alvo():
    store = {"49709": {"status": "train_scheduled", "hunter_schedule_key": "k"}}
    schedules = {"k": {"arrival_time": 2000000000, "attacks": [
        {"status": "failed"}, {"status": "failed"},
    ]}}
    p, _ = _planner(store=store, schedules=schedules)
    p._promote_scheduled_trains()
    assert store["49709"]["status"] == "invalid"


def test_reserva_orfa_e_solta():
    """
    Terceira porta do P2-22. force_clear pelo dashboard, limpeza de cache ou
    alvo virando "lost" apagam o registro sem passar pela promocao -- e a
    reserva ficaria subtraindo do farm em silencio, para sempre.
    """
    villages = _empire()
    villages["41123"].units.conquest_reserve["barb_train:99999"] = {"axe": 300}
    villages["41123"].units.conquest_reserve["pvp:900"] = {"snob": 1}
    p, _ = _planner(villages=villages, store={})
    p._release_orphan_reserves()
    reserva = villages["41123"].units.conquest_reserve
    assert "barb_train:99999" not in reserva
    # Reserva de OUTRO dono nao e nossa para soltar (Feature 27)
    assert "pvp:900" in reserva


def test_reserva_de_trem_vivo_nao_e_solta():
    villages = _empire()
    villages["41123"].units.conquest_reserve["barb_train:49709"] = {"axe": 300}
    store = {"49709": {"status": "train_scheduled"}}
    p, _ = _planner(villages=villages, store=store)
    p._release_orphan_reserves()
    assert "barb_train:49709" in villages["41123"].units.conquest_reserve


def test_promocao_solta_a_reserva():
    """
    Tropa que ja voou nao pode continuar reservada em casa -- seria a reserva
    presa para sempre do P2-22, por outra porta.
    """
    villages = _empire()
    villages["41123"].units.conquest_reserve["barb_train:49709"] = {"axe": 300}
    store = {"49709": {"status": "train_scheduled", "hunter_schedule_key": "k"}}
    schedules = {"k": {"arrival_time": 2000000000, "attacks": [{"status": "sent"}]}}
    p, _ = _planner(villages=villages, store=store, schedules=schedules)
    p._promote_scheduled_trains()
    assert "barb_train:49709" not in villages["41123"].units.conquest_reserve


# --------------------------------------------------------------------------
# Escolta de bárbara x escolta de PvP
# --------------------------------------------------------------------------

def test_escolta_barbara_nao_mexe_na_escolta_pvp():
    """
    `conquest.escort_ratio` mora na secao de barbaras mas e lido TAMBEM pelo
    PvpConquestManager (pvp_conquest.py:588 e :905). Os riscos sao opostos:
    contra barbara a escolta grande e desperdicio, contra JOGADOR ela e o que
    impede o defensor de snipar um comando isolado do trem.

    Baixar escort_ratio para economizar contra barbaro afinaria o trem de PvP
    junto, em silencio. Este teste existe para que quem apagar
    `barbarian_escort_ratio` -- ou fizer o PvP passar a le-la -- descubra aqui,
    e nao perdendo um nobre contra um jogador.
    """
    import ast
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    from game.attack import ConquestManager as Real
    assert Real._escort_ratio({"escort_ratio": 0.5,
                               "barbarian_escort_ratio": 0.15}) == 0.15
    # Ausente ou null: nada muda para quem nunca configurou
    assert Real._escort_ratio({"escort_ratio": 0.5}) == 0.5
    assert Real._escort_ratio({"escort_ratio": 0.5,
                               "barbarian_escort_ratio": None}) == 0.5

    # O PvP NAO pode ler a chave de barbara.
    pvp = open(os.path.join(raiz, "game", "pvp_conquest.py"), encoding="utf-8").read()
    assert "barbarian_escort_ratio" not in pvp, (
        "pvp_conquest.py passou a ler barbarian_escort_ratio -- a escolta "
        "contra jogador voltaria a ser afinada junto com a de barbara"
    )

    # E o caminho de barbara nao pode voltar a ler escort_ratio cru.
    attack = open(os.path.join(raiz, "game", "attack.py"), encoding="utf-8").read()
    tree = ast.parse(attack)
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name not in ("_build_escort", "_calculate_needed_escort"):
            continue
        fonte = ast.get_source_segment(attack, node) or ""
        assert 'get("escort_ratio"' not in fonte, (
            "%s voltou a ler escort_ratio direto em vez de _escort_ratio() -- "
            "isso reacopla a escolta de barbara a de PvP" % node.name
        )


def test_config_real_tem_as_duas_chaves_separadas():
    """
    Guarda contra a config em campo, nao so contra o codigo: a separacao so
    serve se o config.json de verdade tiver as duas chaves com valores
    independentes.
    """
    import json
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    caminho = os.path.join(raiz, "config.json")
    if not os.path.exists(caminho):
        return
    with open(caminho, encoding="utf-8") as f:
        c = json.load(f)["conquest"]
    assert "escort_ratio" in c, "escort_ratio sumiu -- o PvP depende dela"
    assert "barbarian_escort_ratio" in c
    print("     (PvP %s · bárbara %s)" % (c["escort_ratio"], c["barbarian_escort_ratio"]))


# --------------------------------------------------------------------------
# §8.71: reforco de trem incompleto, antes do pouso
# --------------------------------------------------------------------------
# Caso real: o trem contra a Barbara 81800 saiu com 2 de 4 nobres em 19/10 e
# pousa em 21/10 07:11:05. A ~64 campos o nobre extra avulso voa ~37,5 h e
# regenera mais do que derruba; o reforco manda os 2 que faltam juntos, para
# pousarem logo depois do trem.

T81800 = 1792577465
SCAN_EMPTY = {"arrivals": [], "unknown": [], "unreadable": []}


def _train(**over):
    data = {"status": "extra_pending", "reserved_by": "41140", "hits_done": 2,
            "hits_needed": 4, "noble_arrivals": [T81800, T81800],
            "loyalty_drop_range": [20, 35], "target_location": [650, 292],
            "target_name": "Bárbara #81800"}
    data.update(over)
    return data


def _reinforce_planner(data=None, scan=None, mine=False, taken=None, blocked=None):
    store = {"81800": _train() if data is None else data}
    p, calls = _planner(store=store, active=store)
    m = planner_mod.ConquestManager
    m._target_is_mine = lambda self, t: mine
    m._target_taken_by_other = lambda self, t: taken
    m._claim_block_reason = lambda self, t, loc=None: blocked
    m._scan_nobles_in_flight = lambda self, loc: dict(scan or SCAN_EMPTY)

    def add(t, a, plan, label="barb"):
        calls["schedules"].append({"target_id": t, "arrival_str": a, "label": label,
                                   "attacks": [dict(x) for x in plan]})
        return True
    p._add_hunter_schedule = add
    p._travel_seconds = lambda vid, loc: 37.5 * 3600  # ~64 campos
    _FakeHunter.duration = 3600.0
    return p, calls, store


def test_reforco_necessidade_regra_pura():
    need = BarbarianTrainPlanner.reinforcement_need
    now = T81800 - 37 * 3600
    assert need(_train(), now, 35)[:2] == (2, T81800)
    assert need(_train(noble_arrivals=[T81800] * 3, hits_done=3), now, 35)[0] is None, \
        "3 x 35 >= 100: o trem pode conquistar sozinho, espera o relatorio"
    assert need(_train(), T81800 + 60, 35)[0] is None, "trem ja pousou: caminho de antes"
    assert need(_train(noble_arrivals=[T81800, None]), now, 35)[0] is None
    assert need(_train(status="train_sent"), now, 35)[0] is None
    assert need(_train(reinforcement={"status": "skipped"}), now, 35)[0] is None
    assert need(_train(hits_done=4), now, 35)[0] is None


def test_reforco_casa_chegadas_da_praca_com_o_trem():
    um = BarbarianTrainPlanner.unmatched_observed
    obs = [(T81800 + 1, "41140", "a"), (T81800 + 2, "41140", "b")]
    assert um(obs, [T81800, T81800]) == [], "os 2 do trem, 1 e 2 s depois do registrado"
    manual = (T81800 + 9000, "41114", "c")
    assert um(obs + [manual], [T81800, T81800]) == [manual]
    assert um(obs, [T81800]) == [obs[1]], "cada registro casa UMA observada"


def test_reforco_81800_agenda_os_dois_que_faltam_logo_depois_do_trem():
    p, calls, store = _reinforce_planner()
    out = p.plan_reinforcements(now=T81800 - 37 * 3600)
    assert out == ["81800"], out
    sched = calls["schedules"][-1]
    assert sched["label"] == "barb_reforco" and len(sched["attacks"]) == 2, sched
    assert all(a["troops"]["snob"] == 1 for a in sched["attacks"])
    rec = store["81800"]["reinforcement"]
    assert rec["status"] == "scheduled" and rec["nobles"] == 2, rec
    assert rec["arrival"] >= T81800 + BarbarianTrainPlanner.REINFORCE_MIN_GAP, \
        "pousa depois do trem, nunca antes: %s" % rec
    assert rec["sched_key"].endswith("_barb_reforco")
    reserved = {vid: v.units.conquest_reserve.get("barb_reforco:81800")
                for vid, v in p.villages.items()}
    assert any(reserved.values()), "a tropa do reforco fica reservada: %s" % reserved
    assert store["81800"]["status"] == "extra_pending"


def test_reforco_decidido_uma_vez_so():
    p, calls, store = _reinforce_planner()
    p.plan_reinforcements(now=T81800 - 37 * 3600)
    p.plan_reinforcements(now=T81800 - 36 * 3600)
    assert len(calls["schedules"]) == 1


def test_nobre_manual_no_ar_nao_agenda_e_registra():
    scan = {"arrivals": [(T81800 + 1, "41140", "a"), (T81800 + 2, "41140", "b"),
                         (T81800 + 9000, "41114", "manual")],
            "unknown": [], "unreadable": []}
    p, calls, store = _reinforce_planner(scan=scan)
    assert p.plan_reinforcements(now=T81800 - 37 * 3600) == []
    assert calls["schedules"] == []
    assert store["81800"]["reinforcement"]["status"] == "skipped"
    assert T81800 + 9000 in store["81800"]["noble_arrivals"]


def test_praca_ilegivel_adia_sem_decidir():
    p, calls, store = _reinforce_planner(scan=dict(SCAN_EMPTY, unreadable=["41114"]))
    p.plan_reinforcements(now=T81800 - 37 * 3600)
    assert calls["schedules"] == [] and "reinforcement" not in store["81800"]


def test_perto_do_alvo_o_extra_avulso_progride_e_nao_ha_reforco():
    p, calls, store = _reinforce_planner()
    p._travel_seconds = lambda vid, loc: 10 * 3600  # 10 h: regenera 10 < 20
    p.plan_reinforcements(now=T81800 - 37 * 3600)
    assert calls["schedules"] == []
    assert store["81800"]["reinforcement"]["reason"] == "extra avulso progride"


def test_reforco_que_pousaria_tarde_demais_nao_sai():
    p, calls, store = _reinforce_planner()
    _FakeHunter.duration = 3600.0 * 80  # pousaria ~43 h depois do trem
    p.plan_reinforcements(now=T81800 - 37 * 3600)
    assert calls["schedules"] == []
    assert store["81800"]["reinforcement"]["reason"] == "pousaria tarde demais"


def test_alvo_perdido_ou_nosso_ou_reservado_nao_reforca():
    for kwargs in ({"mine": True}, {"taken": "848912345"}, {"blocked": ("tribe", {})}):
        p, calls, store = _reinforce_planner(**kwargs)
        p.plan_reinforcements(now=T81800 - 37 * 3600)
        assert calls["schedules"] == [], kwargs


def test_promocao_do_reforco_entra_nas_chegadas():
    key = "81800_2026-10-21T07-12-05_barb_reforco"
    data = _train(reinforcement={"status": "scheduled", "sched_key": key,
                                 "arrival": T81800 + 60, "nobles": 2})
    schedules = {key: {"arrival_time": T81800 + 60, "status": "complete",
                       "attacks": [{"status": "sent"}, {"status": "sent"}]}}
    store = {"81800": data}
    p, _ = _planner(store=store, schedules=schedules, active=store)
    p.villages["41123"].units.conquest_reserve["barb_reforco:81800"] = {"snob": 2}
    p.promote_reinforcements()
    rec = store["81800"]
    assert rec["noble_arrivals"] == [T81800, T81800, T81800 + 60, T81800 + 60], rec
    assert rec["hits_done"] == 4 and rec["reinforcement"]["status"] == "sent"
    assert "barb_reforco:81800" not in p.villages["41123"].units.conquest_reserve


def test_reforco_com_schedule_apagado_vira_lost():
    data = _train(reinforcement={"status": "scheduled", "sched_key": "sumiu",
                                 "arrival": T81800 + 60})
    store = {"81800": data}
    p, _ = _planner(store=store, schedules={"outro": {"attacks": []}}, active=store)
    p.promote_reinforcements()
    assert store["81800"]["reinforcement"]["status"] == "lost"


def test_reserva_do_reforco_segue_o_hunter():
    key = "k_barb_reforco"
    data = _train(reinforcement={"status": "scheduled", "sched_key": key,
                                 "arrival": T81800 + 60})
    schedules = {key: {"attacks": [
        {"status": "pending", "source_village_id": "41123", "troops": {"snob": 1, "axe": 100}},
        {"status": "sent", "source_village_id": "41140", "troops": {"snob": 1, "axe": 100}}]}}
    store = {"81800": data}
    p, _ = _planner(store=store, schedules=schedules, active=store)
    p.villages["41140"].units.conquest_reserve["barb_reforco:81800"] = {"snob": 1}
    p._sync_reinforcement_reserves()
    assert p.villages["41123"].units.conquest_reserve["barb_reforco:81800"] == {"snob": 1, "axe": 100}
    assert "barb_reforco:81800" not in p.villages["41140"].units.conquest_reserve, \
        "comando que ja saiu solta a reserva"


def test_reforco_agendado_conta_como_nobre_no_ar():
    from game.attack import ConquestCache as RealCache
    from game.event_tick import EventTick
    data = _train(noble_arrivals=[T81800 - 10, T81800 - 10],
                  reinforcement={"status": "scheduled", "arrival": T81800 + 60})
    assert RealCache.nobles_in_flight(data, now=T81800) == [T81800 + 60], \
        "trem pousado, reforco agendado: a trava segura o extra avulso"
    assert RealCache.nobles_in_flight(data, now=T81800 + 61) == []
    assert EventTick.landing_of(data) == T81800 + 60, "o tick espera o reforco pousar"
    done = dict(data, reinforcement={"status": "sent", "arrival": T81800 + 60})
    assert RealCache.nobles_in_flight(done, now=T81800) == []


# --------------------------------------------------------------------------
# Grupo de fechamento, depois do pouso (27/10, Barbara #69630)
# --------------------------------------------------------------------------
# O trem de 4 pousou as 02:33 deixando lealdade 1, e toda origem com nobre
# fica a ~30 h: cada extra avulso pousaria com ~41 contra queda maxima 35. O
# grupo e o MENOR que fecha em 85% (escolha do usuario, 27/10): dois juntos
# fecham 41 em ~99%; tres fechariam sempre, com o terceiro pousando depois da
# conquista em quase todo sorteio.

NOW69630 = 1793115867            # 27/10 12:44, o aviso real
READ69630 = NOW69630 - 10 * 3600  # relatorio do pouso: lealdade 1


def _closing_planner(travel_h=30.0, probe_h=None, villages=None, cfg=None):
    store = {"69630": {"status": "train_sent", "reserved_by": "41140",
                       "hits_done": 4, "hits_needed": 4,
                       "noble_arrivals": [READ69630] * 4,
                       "target_location": [531, 263], "target_name": "Bárbara #69630"}}
    p, calls = _planner(villages=villages, store=store, active=store, cfg=cfg)

    def add(t, a, plan, label="barb"):
        calls["schedules"].append({"target_id": t, "arrival_str": a, "label": label,
                                   "attacks": [dict(x) for x in plan]})
        return True
    p._add_hunter_schedule = add
    p._travel_seconds = lambda vid, loc: travel_h * 3600
    _FakeHunter.duration = (travel_h if probe_h is None else probe_h) * 3600.0
    return p, calls, store


def _close(p, store, loyalty=1.0, at=READ69630, flight_block=None):
    return p.plan_closing_group("69630", dict(store["69630"]), loyalty, at, 1, 20, 35,
                                flight_block=flight_block, now=NOW69630)


def test_fechamento_chance_pela_faixa_de_queda():
    chance = attack_mod.closing_chance
    assert chance(2, 40, 20, 35) == 1.0 and chance(2, 71, 20, 35) == 0.0
    assert abs(chance(4, 100, 20, 35) - 0.867) < 0.001, "o trem de 4 fecha em 86,7%"
    assert abs(chance(2, 60, 20, 35) - 0.258) < 0.001
    assert chance(0, 10, 20, 35) == 0.0


def test_fechamento_tamanho_e_o_menor_grupo_que_fecha_em_85():
    size = attack_mod.closing_group_size
    table = {20: 1, 36: 2, 41.2: 2, 48: 2, 49: 3, 60: 3, 74: 3, 75: 4, 100: 4}
    for loyalty, k in table.items():
        assert size(loyalty, 20, 35) == k, (loyalty, size(loyalty, 20, 35), k)
    assert size(0, 20, 35) == 0 and size(-7, 20, 35) == 0 and size(None, 20, 35) == 0
    chance = attack_mod.closing_chance
    for tenth in range(1, 1001):
        loyalty = tenth / 10.0
        k = size(loyalty, 20, 35)
        assert chance(k, loyalty, 20, 35) >= 0.85, (loyalty, k)
        assert k == 1 or chance(k - 1, loyalty, 20, 35) < 0.85,             "nenhum nobre a mais do que o 85%% pede: %s -> %d" % (loyalty, k)


def test_fechamento_69630_agenda_dois_juntos():
    p, calls, store = _closing_planner()
    scans = []
    ok, why = _close(p, store, flight_block=lambda: scans.append(1) or False)
    assert ok is True and why is None, why
    assert scans == [1], "a praca e lida uma vez, so quando o grupo vai sair"
    sched = calls["schedules"][-1]
    assert sched["label"] == "barb_reforco" and len(sched["attacks"]) == 2, sched
    assert all(a["troops"]["snob"] == 1 for a in sched["attacks"])
    rec = store["69630"]["reinforcement"]
    assert rec["status"] == "scheduled" and rec["kind"] == "fechamento", rec
    assert rec["nobles"] == 2 and 41 < rec["loyalty_at_arrival"] < 42, rec
    assert rec["close_chance"] > 0.98, rec
    assert rec["arrival"] == int(NOW69630 + 30 * 3600 + p.ARRIVAL_MARGIN_SECONDS), rec
    reserved = [v.units.conquest_reserve.get("barb_reforco:69630") for v in p.villages.values()]
    assert any(reserved), "a tropa do grupo fica reservada ate o Hunter mandar"
    assert store["69630"]["status"] == "train_sent", "status do trem nao muda"

    from game.attack import ConquestCache as RealCache
    assert RealCache.nobles_in_flight(store["69630"], now=NOW69630 + 60) == [rec["arrival"]], \
        "agendado conta como nobre no ar: nenhum extra avulso sai por cima"


def test_fechamento_com_lealdade_60_manda_tres_e_75_manda_quatro():
    p, calls, store = _closing_planner(travel_h=35.0)
    ok, _ = _close(p, store, loyalty=25.0, at=NOW69630)  # 25 + 35 h = 60
    assert ok and len(calls["schedules"][-1]["attacks"]) == 3, calls["schedules"]
    p, calls, store = _closing_planner(travel_h=35.0)
    ok, _ = _close(p, store, loyalty=40.0, at=NOW69630)  # 75
    assert ok and len(calls["schedules"][-1]["attacks"]) == 4, calls["schedules"]


def test_fechamento_sem_nobres_suficientes_nao_agenda():
    one = {"41123": _Village("41123", {"snob": 1, "axe": 4000, "light": 800}, [577, 306])}
    p, calls, store = _closing_planner(villages=one)
    ok, why = _close(p, store)
    assert ok is False and calls["schedules"] == [] and "pede 2" in why, why
    assert "reinforcement" not in store["69630"]


def test_fechamento_duracao_do_servidor_muda_o_tamanho_e_nao_agenda():
    # Estimativa 30 h (2 nobres); o servidor diz 50 h: lealdade ~61, pede 3.
    p, calls, store = _closing_planner(travel_h=30.0, probe_h=50.0)
    ok, why = _close(p, store)
    assert ok is False and calls["schedules"] == [] and "pede 3" in why, why


def test_fechamento_nobre_nosso_no_ar_nao_agenda():
    p, calls, store = _closing_planner()
    ok, why = _close(p, store, flight_block=lambda: True)
    assert (ok, why) == (False, None) and calls["schedules"] == []
    assert "reinforcement" not in store["69630"]


def test_fechamento_sem_hunter_nao_agenda():
    p, calls, store = _closing_planner(cfg={"conquest": {"enabled": True},
                                            "hunter": {"enabled": False}})
    ok, why = _close(p, store)
    assert ok is False and "Hunter" in why and calls["schedules"] == []


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
