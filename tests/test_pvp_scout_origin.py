"""P-PVP-SCOUT -- a espia sai da aldeia com MAIS espioes, e leva o maximo.

Contexto (docs/backend.md 8.12, decidido pelo usuario em 2026-09-21). O passo
antigo iterava `self.villages.items()` e pegava a PRIMEIRA aldeia com
`spy >= scout_amount` que tivesse o alvo no `map_pos`, enviando exatamente
`scout_amount` (5). Nao era a com mais espioes nem a mais perto: era a primeira
da ordem do dict. Cinco exploradores contra aldeia de jogador defendida morrem
sem relatorio, e relatorio que nao chega e o que faz o alvo cair em
`scout_deadline_missed`.

Os numeros de test_o_recorte_real_das_30_aldeias() sao os medidos em
2026-09-21 contra o alvo 44155 (555|288).

Run: python tests/test_pvp_scout_origin.py
"""

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game.pvp_conquest import PvpConquestCache, PvpConquestManager

ALVO = "44155"
ALVO_POS = (555, 288)


class _FakeUnits:
    """
    O minimo que o passo toca. `refreshes` conta as releituras para o teste
    poder afirmar que ela acontece -- e `live` permite que a leitura viva
    discorde da foto velha, que e o caso que motivou a releitura existir.
    """

    def __init__(self, spies, live=None, reserve=None):
        self.troops = {"spy": spies}
        self._live = spies if live is None else live
        self.conquest_reserve = {"algum_dono": dict(reserve)} if reserve else {}
        self.refreshes = 0

    def total_conquest_reserve(self, exclude_owner=None):
        total = {}
        for owner, reservation in self.conquest_reserve.items():
            if exclude_owner is not None and owner == exclude_owner:
                continue
            for unit, qty in reservation.items():
                total[unit] = total.get(unit, 0) + int(qty)
        return total

    def update_totals(self):
        self.refreshes += 1
        self.troops["spy"] = self._live


class _FakeAttack:
    def __init__(self, vid, accept=True):
        self.vid = vid
        self.accept = accept
        self.sent = []

    def attack(self, target_id, troops=None, additional_attacks=None):
        self.sent.append((str(target_id), dict(troops or {})))
        return True if self.accept else False


def _village(vid, x, y, spies, live=None, reserve=None, accept=True, in_map_pos=False,
             my_location=True):
    units = _FakeUnits(spies, live=live, reserve=reserve)
    area = SimpleNamespace(
        map_pos={ALVO: ALVO_POS} if in_map_pos else {},
        my_location=[x, y] if my_location else None,
        get_dist=lambda loc, _x=x, _y=y: (
            ((_x - loc[0]) ** 2 + (_y - loc[1]) ** 2) ** 0.5
        ),
    )
    return SimpleNamespace(units=units, area=area, attack=_FakeAttack(vid, accept))


def _manager(villages, scout_amount=5):
    manager = PvpConquestManager.__new__(PvpConquestManager)
    manager.config = {"pvp_conquest": {"scout_amount": scout_amount}, "villages": {}}
    manager.villages = villages
    manager.farm_suspended_villages = set()
    return manager


def _run_scout(manager, data=None):
    """Roda o passo com o cache e a busca de relatorio neutralizados."""
    data = dict(data or {"status": "pending_scout", "target_location": list(ALVO_POS)})
    escritas = []
    cache_set, find_report = PvpConquestCache.set, PvpConquestManager._find_scout_report
    PvpConquestCache.set = lambda tid, d: escritas.append((str(tid), dict(d)))
    PvpConquestManager._find_scout_report = lambda self, tid: None
    try:
        manager._step_scout(ALVO, data)
    finally:
        PvpConquestCache.set = cache_set
        PvpConquestManager._find_scout_report = find_report
    return data, escritas


def _quem_enviou(villages):
    return [
        (vid, village.attack.sent[0][1]["spy"])
        for vid, village in villages.items()
        if village.attack.sent
    ]


def test_escolhe_a_aldeia_com_mais_espioes_e_nao_a_primeira():
    """
    O caso central, e o que a regra antiga errava: a ordem de insercao poe
    primeiro uma aldeia elegivel com menos espioes.
    """
    villages = {
        "32056": _village("32056", 560, 300, 50),
        "34597": _village("34597", 580, 300, 80),
        "38412": _village("38412", 570, 295, 12),
    }
    _run_scout(_manager(villages))
    assert _quem_enviou(villages) == [("34597", 80)], _quem_enviou(villages)


def test_envia_o_maximo_e_nao_o_scout_amount():
    """
    A segunda metade da decisao. `scout_amount` deixa de ser a quantidade e
    passa a ser piso -- se ele continuasse mandando 5, este teste falharia com
    a origem certa e a quantidade errada, que e o erro mais facil de nao notar.
    """
    villages = {"34597": _village("34597", 580, 300, 80)}
    _run_scout(_manager(villages, scout_amount=5))
    assert villages["34597"].attack.sent == [(ALVO, {"spy": 80})]


def test_scout_amount_continua_valendo_como_piso():
    """
    A chave nao virou morta (4o padrao do CLAUDE.md): quem tem menos que o piso
    nao e origem. Com piso 20, a aldeia de 12 espioes some da lista e a de 50
    passa a ser a melhor.
    """
    villages = {
        "38412": _village("38412", 570, 295, 12),
        "32056": _village("32056", 560, 300, 50),
    }
    _run_scout(_manager(villages, scout_amount=20))
    assert _quem_enviou(villages) == [("32056", 50)]


def test_empate_de_espioes_e_decidido_pela_menor_distancia():
    """
    A distancia entra como desempate, nao como peso. As duas aldeias tem 80;
    ganha a que fica a 10 campos, nao a que fica a 40.
    """
    villages = {
        "35059": _village("35059", 595, 288, 80),   # 40 campos
        "34597": _village("34597", 565, 288, 80),   # 10 campos
    }
    _run_scout(_manager(villages))
    assert _quem_enviou(villages) == [("34597", 80)]


def test_a_reserva_de_conquista_e_descontada():
    """
    Enviar "o maximo disponivel" e o caminho que gastaria uma reserva de espiao
    sem aviso. Hoje nenhum dono reserva `spy`, mas a subtracao tem que estar no
    lugar antes de alguem passar a reservar.
    """
    villages = {
        "34597": _village("34597", 580, 300, 80, reserve={"spy": 78}),  # sobram 2
        "32056": _village("32056", 560, 300, 50),
    }
    _run_scout(_manager(villages))
    assert _quem_enviou(villages) == [("32056", 50)]


def test_a_contagem_e_relida_ao_vivo_antes_de_enviar():
    """
    A armadilha que trocar 5 pelo maximo cria: `units.troops` no inicio do
    ciclo e a foto do fim do ciclo passado (~4h com 30 aldeias), e o jogo recusa
    o ataque INTEIRO por falta de uma unidade. Aqui a foto diz 80 e a leitura
    viva diz 30 -- o envio tem que ser de 30, nao de 80.
    """
    villages = {"34597": _village("34597", 580, 300, 80, live=30)}
    _run_scout(_manager(villages))
    assert villages["34597"].units.refreshes == 1
    assert villages["34597"].attack.sent == [(ALVO, {"spy": 30})]


def test_origem_que_desabou_abaixo_do_piso_cede_para_a_proxima():
    """
    Sem este caminho, trocar 5 pelo maximo trocaria uma espia lenta por NENHUMA
    espia: a melhor origem da foto velha some na leitura viva e o passo
    desistiria com 29 outras aldeias disponiveis.
    """
    villages = {
        "34597": _village("34597", 580, 300, 80, live=1),
        "32056": _village("32056", 560, 300, 50),
    }
    data, escritas = _run_scout(_manager(villages))
    assert _quem_enviou(villages) == [("32056", 50)]
    assert data["status"] == "pending_troops"
    assert data["scout_village_id"] == "32056"
    assert data["scout_spies_sent"] == 50
    assert escritas and escritas[-1][0] == ALVO


def test_recusa_do_jogo_cai_para_a_proxima_origem():
    """Comportamento que ja existia e nao pode regredir."""
    villages = {
        "34597": _village("34597", 580, 300, 80, accept=False),
        "32056": _village("32056", 560, 300, 50),
    }
    data, _ = _run_scout(_manager(villages))
    assert _quem_enviou(villages) == [("34597", 80), ("32056", 50)]
    assert data["scout_village_id"] == "32056"


def test_o_teto_de_tentativas_limita_o_gasto_de_requisicao():
    """
    Cada tentativa custa quatro requisicoes. Com as origens em ordem
    decrescente de espiao, cinco falhas seguidas nao sao "esta aldeia": varrer
    as outras so gasta orcamento num ciclo que vai terminar sem espia.
    """
    villages = {
        str(9000 + i): _village(str(9000 + i), 560, 300, 80 - i, accept=False)
        for i in range(12)
    }
    _run_scout(_manager(villages))
    tentadas = [vid for vid, v in villages.items() if v.attack.sent]
    assert len(tentadas) == PvpConquestManager.SCOUT_MAX_ATTEMPTS, tentadas


def test_alcance_nao_depende_mais_do_prefetch_de_mapa_da_origem():
    """
    O teste antigo era `target_id not in village.area.map_pos`, e com
    `farms.map_sector_radius = 0` esse prefetch cobre pouco mais de um setor de
    20x20 -- a aldeia com mais espioes podia ser descartada por um motivo que
    nao tem a ver com alcance. `AttackManager._resolve_position()` aceita a
    coordenada do snapshot compartilhado `cache/villages`, ou seja, o envio
    funciona. Nenhuma aldeia aqui tem o alvo no `map_pos`; a coordenada vem do
    cadastro, como o painel a grava.
    """
    villages = {"34597": _village("34597", 580, 300, 80, in_map_pos=False)}
    _run_scout(_manager(villages))
    assert villages["34597"].attack.sent == [(ALVO, {"spy": 80})]


def test_sem_coordenada_nenhuma_nao_ha_origem():
    """
    A degradacao certa quando nem o `map_pos` nem o cadastro sabem onde o alvo
    fica: nenhum envio. `_resolve_position` devolveria None e o ataque falharia
    de todo jeito, so gastando a requisicao da praca.
    """
    villages = {"34597": _village("34597", 580, 300, 80, in_map_pos=False)}
    data, _ = _run_scout(_manager(villages), data={"status": "pending_scout"})
    assert _quem_enviou(villages) == []
    assert data["status"] == "pending_scout"


def test_aldeia_sem_my_location_continua_elegivel():
    """
    `Map.my_location` e None quando a aldeia nao apareceu nos setores lidos.
    Distancia desconhecida nao pode virar inelegibilidade: o envio nao depende
    dela, so o desempate depende.
    """
    villages = {"34597": _village("34597", 580, 300, 80, my_location=False)}
    _run_scout(_manager(villages))
    assert villages["34597"].attack.sent == [(ALVO, {"spy": 80})]


def test_o_recorte_real_das_30_aldeias():
    """
    Os numeros medidos em 2026-09-21 contra o alvo 44155. Provam que a regra
    nova escolhe uma origem MAIS DISTANTE que a antiga -- consequencia aceita
    pelo usuario, nao efeito colateral esquecido: relatorio que chega vale mais
    que relatorio que chega cedo.

    Duas aldeias empatavam em 80 espioes, a 35,0 e a 38,4 campos; o desempate
    por distancia escolhe a de 35,0. A regra antiga escolhia a primeira da
    ordem de id, com 50 espioes a 34,7 campos.
    """
    villages = {
        "32056": _village("32056", 555 + 34, 288 + 7, 50),   # ~34,7 campos
        "34597": _village("34597", 555 + 35, 288, 80),        # 35,0 campos
        "35059": _village("35059", 555 + 38, 288 + 5, 80),    # ~38,4 campos
    }
    manager = _manager(villages)
    candidatos = manager._scout_candidates(ALVO, {"target_location": list(ALVO_POS)})
    assert [c[0] for c in candidatos] == ["34597", "35059", "32056"]
    assert candidatos[0][2] == 80
    assert candidatos[0][3] < candidatos[1][3]
    # A antiga (32056, 34,7 campos) e mais PERTO que a nova (34597, 35,0).
    antiga = [c for c in candidatos if c[0] == "32056"][0]
    assert antiga[3] < candidatos[0][3]


if __name__ == "__main__":
    for nome, fn in sorted(list(globals().items())):
        if nome.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {nome}")
    print("\ntodos os testes passaram")
