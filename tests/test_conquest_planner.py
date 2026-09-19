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
    # Pior caso de propósito: 4 x 25 = 100, a estimativa vira limite SUPERIOR
    assert store["49709"]["loyalty_after_train"] == 0


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
    assert store["49709"]["loyalty_after_train"] == 25


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
