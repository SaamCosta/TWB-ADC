"""
Testes de QUEM ENTRA na lista de alvos da conquista barbara.

  ConquestManager._candidate_pool()  -- de onde saem os candidatos
  ConquestManager.find_target(reach_from=...)  -- quem alcanca o alvo

O DEFEITO QUE ISTO FECHA (docs/backend.md 8.6)
----------------------------------------------
O planejador multi-origem (17/09/2026) elegia como ancora a aldeia com mais
nobres, e `find_target()` usava essa ancora para as duas coisas: pontuar E
decidir quem entra na lista. As duas sao diferentes. Pontuar a partir de quem
manda mais nobres encurta a viagem mais longa, que define a chegada comum --
isso esta certo. Filtrar por ela faz o conjunto de alvos depender de onde os
nobres se acumularam, que e circunstancia e nao geografia.

E eram DOIS funis, nao um. Medido no br143 em 19/09/2026, sobre as 39 barbaras
elegiveis que o imperio conhece no K25:

    alcance  BBM 001 (577|306) chegava em 29 com raio 30, nas 39 com raio 50
    pool     o scan de mapa da BBM 001 continha 23 das 39
             o da BBM 011 (a outra aldeia com nobre) as mesmas 23
             o da BBM 023 (553|300) continha 30
             cache/villages, compartilhado, continha as 39

Ou seja: subir `max_radius` sozinho nao resolvia, porque o raio filtra o que ja
esta na lista -- 16 alvos nunca chegavam a ser filtrados. Com
`farms.map_sector_radius = 0` (o valor em campo) o prefetch de mapa e pequeno e
nao centrado na aldeia (ver map.py:56).

As coordenadas abaixo sao reais: a BBM 001, a BBM 023 e o bolsao oeste que
sumia da lista (#40382 em 543|296 -- 35,4 campos da BBM 001 e 10,8 da BBM 023).

Nada aqui toca cache/ nem a rede: FileManager, ConquestCache e WorldConfig sao
substituidos por dubles em memoria. O bot escreve nesses mesmos arquivos
enquanto roda (vigesimo primeiro padrao do CLAUDE.md).

Rodar: python tests/test_conquest_target_reach.py
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import game.attack as attack_mod
from game.attack import ConquestManager


BBM_001 = (577, 306)   # ancora de hoje: 3 nobres
BBM_023 = (553, 300)   # vizinha do bolsao oeste, sem nobre hoje

OESTE = "40382"        # 543|296 -- 35,4 da BBM 001, 10,8 da BBM 023
PERTO = "51991"        # 570|293 -- 14,8 da BBM 001


def _barbara(x, y, points=900, owner="0"):
    return {"id": "x", "name": "Bárbaras", "location": [x, y],
            "points": points, "owner": owner}


class _Logger:
    def __init__(self):
        self.avisos = []

    def debug(self, *a, **k): pass
    def info(self, *a, **k): pass
    def warning(self, *a, **k): self.avisos.append(a[0] if a else "")
    def error(self, *a, **k): pass


class _Map:
    def __init__(self, villages, my_location=BBM_001):
        self.villages = villages
        self.map_pos = {v: d["location"] for v, d in villages.items()}
        self.my_location = list(my_location)

    def get_dist(self, ext_loc):
        return math.sqrt((self.my_location[0] - ext_loc[0]) ** 2
                         + (self.my_location[1] - ext_loc[1]) ** 2)


def _install(shared, managed=(BBM_001, BBM_023)):
    """Substitui tudo que sai do processo. `shared` e o cache/villages falso."""

    class _FM:
        @staticmethod
        def list_directory(directory, ends_with=None):
            if "villages" in directory:
                return ["%s.json" % vid for vid in shared]
            if "managed" in directory:
                return ["m%d.json" % i for i, _ in enumerate(managed)]
            return []   # cache/conquest vazio: sem alvo manual na fila

        @staticmethod
        def load_json_file(path, **k):
            name = os.path.basename(path).replace(".json", "")
            if "managed" in path:
                x, y = managed[int(name[1:])]
                return {"x": x, "y": y}
            return shared.get(name)

    class _Cache:
        @staticmethod
        def all_reserved():
            return set()

        @staticmethod
        def targets_with_nobles_in_flight():
            return set()

    class _WC:
        @staticmethod
        def get(server=None, endpoint=None, force_refresh=False):
            return {"snob": {"max_dist": 70}}

        @staticmethod
        def noble_max_distance(data):
            return (data.get("snob") or {}).get("max_dist")

    attack_mod.FileManager = _FM
    attack_mod.ConquestCache = _Cache
    attack_mod.WorldConfig = _WC


def _manager(scan, shared, my_location=BBM_001, managed=(BBM_001, BBM_023)):
    _install(shared, managed)
    man = ConquestManager.__new__(ConquestManager)
    man.village_id = "41123"
    man.map = _Map(scan, my_location)
    man.config = {"server": {"server": "br143", "endpoint": "https://x/game.php"}}
    man.logger = _Logger()
    return man


CFG = {"max_radius": 30, "min_points": 100, "max_points": 1100,
       "priority": "fill_gaps"}


# --------------------------------------------------------------------------
# Alcance
# --------------------------------------------------------------------------

def test_bolsao_oeste_some_medindo_so_da_ancora():
    """
    O caso concreto da 8.6: #40382 esta a 35,4 campos da BBM 001 e a 10,8 da
    BBM 023. Com raio 30 medido so da ancora ele nao existe.
    """
    shared = {OESTE: _barbara(543, 296)}
    man = _manager(scan=dict(shared), shared=shared)
    assert man.find_target(CFG) is None


def test_bolsao_oeste_volta_medindo_de_qualquer_origem_com_nobre():
    shared = {OESTE: _barbara(543, 296)}
    man = _manager(scan=dict(shared), shared=shared)
    assert man.find_target(CFG, reach_from=[BBM_001, BBM_023]) == OESTE


def test_raio_maior_tambem_alcanca_pela_ancora():
    """
    Os dois remedios sao independentes e o usuario aplicou os dois: com raio
    50 a BBM 001 sozinha ja chega nas 39 do K25. Este teste existe para que
    fique registrado que o raio NAO substitui a correcao de desenho -- ver
    test_alvo_fora_do_scan_da_ancora_nao_depende_do_raio.
    """
    shared = {OESTE: _barbara(543, 296)}
    man = _manager(scan=dict(shared), shared=shared)
    assert man.find_target({**CFG, "max_radius": 50}) == OESTE


def test_origem_sem_coordenada_nao_vira_zero_zero():
    """
    (0, 0) e uma coordenada valida no mapa do jogo. Uma origem vazia tratada
    como zero mediria o raio a partir do canto do mundo e reprovaria tudo.
    """
    shared = {PERTO: _barbara(570, 293)}
    man = _manager(scan=dict(shared), shared=shared)
    assert man.find_target(CFG, reach_from=[None, [], BBM_001]) == PERTO


def test_sem_coordenada_propria_e_sem_origens_recusa_com_log():
    """
    `get_map()` devolve False numa resposta que nao e a tela de mapa (sessao
    expirada, bot protection), e ai `my_location` fica None. Segundo padrao do
    CLAUDE.md: sem a guarda, o `get_dist` estouraria o ciclo do planejador.
    """
    shared = {PERTO: _barbara(570, 293)}
    man = _manager(scan=dict(shared), shared=shared)
    man.map.my_location = None
    assert man.find_target(CFG) is None
    assert man.logger.avisos, "recusar em silencio esconde sessao expirada"


# --------------------------------------------------------------------------
# Pool de candidatos
# --------------------------------------------------------------------------

def test_alvo_fora_do_scan_da_ancora_nao_depende_do_raio():
    """
    A metade do defeito que a 8.6 nao nomeia: o alvo nem chegava a ser
    filtrado. Com o pool preso ao scan local, raio 70 nao adianta.
    """
    shared = {PERTO: _barbara(570, 293)}
    man = _manager(scan={}, shared=shared)
    assert man.find_target({**CFG, "max_radius": 70}) is None

    man = _manager(scan={}, shared=shared)
    assert man.find_target(CFG, reach_from=[BBM_001]) == PERTO


def test_scan_vivo_vence_o_snapshot_em_disco():
    """
    O snapshot e do ultimo scan que passou por ali, entao ele pode dizer
    "barbara" sobre uma aldeia que ja tem dono. Onde as duas fontes falam, a
    fresca manda -- senao o pool compartilhado teria trazido de volta
    exatamente a classe de alvo que `_handle_existing()` existe para encerrar.
    """
    shared = {PERTO: _barbara(570, 293)}
    scan = {PERTO: _barbara(570, 293, owner="12345")}
    man = _manager(scan=scan, shared=shared)
    assert man.find_target(CFG, reach_from=[BBM_001]) is None


def test_entrada_sem_coordenada_no_snapshot_nao_derruba_o_ciclo():
    """
    Arquivo truncado ou de formato antigo em cache/villages. Sem a guarda, um
    unico registro assim levava junto a selecao do imperio inteiro.
    """
    shared = {
        "99999": {"owner": "0", "points": 500},          # sem location
        "99998": {"owner": "0", "points": 500, "location": [570]},
        PERTO: _barbara(570, 293),
    }
    man = _manager(scan={}, shared=shared)
    assert man.find_target(CFG, reach_from=[BBM_001]) == PERTO


def test_sem_reach_from_o_pool_continua_sendo_so_o_scan_local():
    """
    Guarda do caminho historico: `find_target(cfg)` sem alcance explicito e
    uma aldeia decidindo sozinha, e ela nao deve passar a enxergar o imperio
    inteiro por efeito colateral.
    """
    man = _manager(scan={}, shared={PERTO: _barbara(570, 293)})
    assert man._candidate_pool() == {}
    assert man._candidate_pool(reach_from=[BBM_001]) != {}


# --------------------------------------------------------------------------
# A ancora continua pontuando
# --------------------------------------------------------------------------

def test_pontuacao_continua_medindo_da_ancora():
    """
    O alcance mudou; a pontuacao nao. `_score_target` tem que receber a
    distancia ate ESTA aldeia -- a que manda mais nobres --, e nao a menor
    distancia do imperio, porque e a viagem dela que costuma definir a chegada
    comum do trem.
    """
    shared = {OESTE: _barbara(543, 296)}
    man = _manager(scan=dict(shared), shared=shared)
    vistas = []
    original = man._score_target
    man._score_target = lambda v, d, m, c: vistas.append(d) or original(v, d, m, c)

    man.find_target({**CFG, "max_radius": 50}, reach_from=[BBM_001, BBM_023])

    assert len(vistas) == 1
    assert round(vistas[0], 1) == 35.4, (
        "a distancia pontuada caiu para a da origem mais proxima (10,8) -- "
        "a ancora deixou de ser a referencia do score"
    )


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
