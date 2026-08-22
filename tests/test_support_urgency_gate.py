"""
Testes do gate de urgencia do apoio (DefenceManager.support_timing) e do
calculo de tempo de viagem (WorldConfig.travel_seconds / _parse_unit_speeds).

O problema que isto resolve: `my_other_villages[vid]` e um booleano, "sob
ataque sim/nao", que nao sabe QUANDO o ataque chega. Quatro aldeias com
support_others ligado esvaziavam 25% da defesa delas no instante em que um
comando aparecia na tela da vizinha -- inclusive um fake com 100h de viagem,
que e o caso que abriu esta investigacao em 2026-08-21.

Reusar o limiar da evacuacao (1800s) seria errado na direcao oposta: esconder
tropa e instantaneo e quanto mais tarde melhor, mas apoio precisa CHEGAR antes
do impacto e leva horas viajando. Um apoio despachado 30 min antes de um
ataque que esta a 3h de viagem pousa 2h30 depois da batalha.

Rodar: python tests/test_support_urgency_gate.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.world_config import WorldConfig
from game.defence_manager import DefenceManager

# Velocidades verbatim de interface.php?func=get_unit_info do br143, lidas em
# 2026-08-22. Sao min/campo JA EFETIVOS (ver _parse_unit_speeds).
BR143_UNIT_INFO = """<?xml version="1.0" encoding="UTF-8"?>
<config>
<spear><build_time>102</build_time><pop>1</pop><speed>18</speed><carry>25</carry></spear>
<sword><build_time>150</build_time><pop>1</pop><speed>22</speed><carry>15</carry></sword>
<axe><build_time>120</build_time><pop>1</pop><speed>18</speed><carry>10</carry></axe>
<spy><build_time>90</build_time><pop>2</pop><speed>9</speed><carry>0</carry></spy>
<light><build_time>300</build_time><pop>4</pop><speed>10</speed><carry>80</carry></light>
<heavy><build_time>600</build_time><pop>6</pop><speed>11</speed><carry>50</carry></heavy>
<ram><build_time>480</build_time><pop>5</pop><speed>30</speed><carry>0</carry></ram>
<catapult><build_time>640</build_time><pop>8</pop><speed>30</speed><carry>0</carry></catapult>
<snob><build_time>18000</build_time><pop>100</pop><speed>35</speed><carry>0</carry></snob>
</config>
"""

# br139 tem speed=1.4 e unit_speed=0.75, e publica 17.142857 para o lanceiro --
# ou seja, 18/(1.4*0.75). Prova de que o valor ja vem efetivo.
BR139_UNIT_INFO = """<config>
<spear><speed>17.142857142857</speed></spear>
<light><speed>9.5238095238095</speed></light>
</config>
"""


def _check(label, got, expected):
    assert got == expected, f"{label}: esperado {expected!r}, veio {got!r}"
    print(f"  ok  {label}: {got!r}")


def _approx(label, got, expected, tol=1):
    assert abs(got - expected) <= tol, f"{label}: esperado ~{expected}, veio {got}"
    print(f"  ok  {label}: {got}")


class _FakeMap:
    """Mapa minimo: so o que support_travel_seconds usa."""

    def __init__(self, distances):
        self._d = distances
        self.map_pos = {vid: (0, 0) for vid in distances}
        self.my_location = (0, 0)

    def get_dist(self, pos):
        # pos e o valor de map_pos; devolvemos pela identidade do vid
        for vid, p in self.map_pos.items():
            if p is pos:
                return self._d[vid]
        return None


def _dm(distances=None, speeds=None, etas=None, lead=7200):
    dm = DefenceManager(village_id="me")
    dm.unit_speeds = speeds if speeds is not None else WorldConfig._parse_unit_speeds(BR143_UNIT_INFO)
    dm.support_lead_time_sec = lead
    dm.my_other_villages_eta = etas or {}
    if distances:
        # map_pos precisa de objetos distintos por vid para o _FakeMap resolver
        dm.map = _FakeMap(distances)
        dm.map.map_pos = {vid: [0, i] for i, vid in enumerate(distances)}
        dm.map._d = distances

        def get_dist(pos, _d=distances, _mp=dm.map.map_pos):
            for vid, p in _mp.items():
                if p == pos:
                    return _d[vid]
            return None

        dm.map.get_dist = get_dist
    # tropa disponivel: 100 lanceiros e 40 espadas
    class _Units:
        troops = {"spear": "100", "sword": "40"}

    dm.units = _Units()
    return dm


def test_unit_speeds_are_already_effective():
    """
    A descoberta que evitou dividir a velocidade duas vezes. Num mundo de
    velocidade 1 as duas leituras coincidem e o erro seria invisivel; o br139
    e que separa as hipoteses.
    """
    print("test_unit_speeds_are_already_effective")
    br143 = WorldConfig._parse_unit_speeds(BR143_UNIT_INFO)
    _check("br143 lanceiro", br143["spear"], 18.0)
    _check("br143 nobre", br143["snob"], 35.0)
    _check("br143 explorador", br143["spy"], 9.0)

    br139 = WorldConfig._parse_unit_speeds(BR139_UNIT_INFO)
    # 18 / (1.4 * 0.75) == 17.142857...
    _approx("br139 lanceiro ja efetivo", br139["spear"], 18 / (1.4 * 0.75), tol=0.001)


def test_travel_uses_slowest_unit():
    """O comando anda na velocidade do mais lento que carrega."""
    print("test_travel_uses_slowest_unit")
    s = WorldConfig._parse_unit_speeds(BR143_UNIT_INFO)
    _check("so lanceiro, 10 campos", WorldConfig.travel_seconds(s, 10, {"spear": 5}), 10 * 18 * 60)
    _check(
        "lanceiro + espada, 10 campos (espada manda)",
        WorldConfig.travel_seconds(s, 10, {"spear": 5, "sword": 1}),
        10 * 22 * 60,
    )
    # Quantidade zero nao pode pesar na conta: mandar 0 espadas nao deixa o
    # comando lento.
    _check(
        "espada com quantidade 0 e ignorada",
        WorldConfig.travel_seconds(s, 10, {"spear": 5, "sword": 0}),
        10 * 18 * 60,
    )


def test_travel_unknown_is_none_not_zero():
    """
    "Nao sei" tem que ser distinguivel de "instantaneo". O CLAUDE.md registra
    o caso do Extractor.attack_duration(), que devolvia 0 na falha e fazia o
    nobre nascer ja pousado.
    """
    print("test_travel_unknown_is_none_not_zero")
    s = WorldConfig._parse_unit_speeds(BR143_UNIT_INFO)
    _check("sem tabela de velocidade", WorldConfig.travel_seconds({}, 10, {"spear": 5}), None)
    _check("sem distancia", WorldConfig.travel_seconds(s, 0, {"spear": 5}), None)
    _check("sem tropa", WorldConfig.travel_seconds(s, 10, {}), None)
    _check("unidade desconhecida", WorldConfig.travel_seconds(s, 10, {"dragao": 5}), None)
    _check("xml vazio", WorldConfig._parse_unit_speeds(""), {})
    _check("xml sem config", WorldConfig._parse_unit_speeds("<html>nope</html>"), {})


def test_fake_de_100h_nao_move_tropa():
    """
    O caso que originou tudo: ataque a 100h de distancia numa vizinha a 10
    campos. Apoio de lanceiro/espada leva 3h40. Antes do gate, saia na hora.
    """
    print("test_fake_de_100h_nao_move_tropa")
    dm = _dm(distances={"viz": 10}, etas={"viz": 100 * 3600})
    send, reason = dm.support_timing("viz")
    _check("nao envia", send, False)
    assert "cedo demais" in reason, reason
    print(f"  ok  motivo: {reason}")


def test_apoio_que_chegaria_atrasado_nao_sai():
    """
    Ganho novo, que nem existia antes: com 1h de ETA e 3h40 de viagem, o apoio
    pousa 2h40 depois da batalha. O bot mandava assim mesmo.
    """
    print("test_apoio_que_chegaria_atrasado_nao_sai")
    dm = _dm(distances={"viz": 10}, etas={"viz": 3600})
    send, reason = dm.support_timing("viz")
    _check("nao envia", send, False)
    assert "atrasado" in reason, reason
    print(f"  ok  motivo: {reason}")


def test_dentro_da_janela_envia():
    """Viagem 3h40; com lead de 2h a janela e ETA em (3h40, 5h40]."""
    print("test_dentro_da_janela_envia")
    travel = 10 * 22 * 60  # 13200s = 3h40
    dm = _dm(distances={"viz": 10}, etas={"viz": travel + 1800})
    send, reason = dm.support_timing("viz")
    _check("envia", send, True)
    assert "na janela" in reason, reason
    print(f"  ok  motivo: {reason}")

    # Logo acima do limite superior: ainda nao.
    dm.my_other_villages_eta["viz"] = travel + 7200 + 60
    send, _ = dm.support_timing("viz")
    _check("60s acima da janela nao envia", send, False)
    # Exatamente no limite superior: envia (o <= importa, senao a borda vira
    # um buraco de um ciclo inteiro).
    dm.my_other_villages_eta["viz"] = travel + 7200
    send, _ = dm.support_timing("viz")
    _check("exatamente no limite envia", send, True)


def test_desconhecido_preserva_comportamento_antigo():
    """
    Sem ETA ou sem tempo de viagem, envia -- igual a antes do gate. Deixar uma
    aldeia real sem defesa por um parse que falhou e pior que mandar apoio a
    mais. Mesma direcao do _is_urgent(None) = True.
    """
    print("test_desconhecido_preserva_comportamento_antigo")
    dm = _dm(distances={"viz": 10}, etas={"viz": None})
    send, reason = dm.support_timing("viz")
    _check("eta None envia", send, True)
    assert "desconhecido" in reason, reason

    # vid ausente do dict tambem e "nao sei"
    dm2 = _dm(distances={"viz": 10}, etas={})
    _check("vid ausente envia", dm2.support_timing("viz")[0], True)

    # sem mapa -> viagem desconhecida -> envia
    dm3 = _dm(distances=None, etas={"viz": 100 * 3600})
    send, reason = dm3.support_timing("viz")
    _check("sem mapa envia", send, True)
    assert "viagem desconhecida" in reason, reason

    # sem tabela de velocidades -> idem
    dm4 = _dm(distances={"viz": 10}, speeds={}, etas={"viz": 100 * 3600})
    _check("sem velocidades envia", dm4.support_timing("viz")[0], True)


def test_eta_dict_e_por_instancia():
    """
    Primeiro padrao do CLAUDE.md: mutavel no corpo da classe vaza entre
    aldeias. Existe um DefenceManager por aldeia.
    """
    print("test_eta_dict_e_por_instancia")
    a = DefenceManager(village_id="a")
    b = DefenceManager(village_id="b")
    a.my_other_villages_eta["x"] = 123
    _check("b nao herda o dict de a", b.my_other_villages_eta, {})


if __name__ == "__main__":
    test_unit_speeds_are_already_effective()
    test_travel_uses_slowest_unit()
    test_travel_unknown_is_none_not_zero()
    test_fake_de_100h_nao_move_tropa()
    test_apoio_que_chegaria_atrasado_nao_sai()
    test_dentro_da_janela_envia()
    test_desconhecido_preserva_comportamento_antigo()
    test_eta_dict_e_por_instancia()
    print("\nOK - todos os testes do gate de urgencia passaram")
