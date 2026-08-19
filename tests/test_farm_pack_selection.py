"""
Testes da escolha de pacote de farm por saque esperado.

Tres metodos de game/attack.py::AttackManager, todos sem rede:

  _pack_capacity(template)   -- capacidade de saque de um pacote
  _expected_loot(vid)        -- quanto o alvo deve render agora
  _ordered_templates(vid)    -- qual pacote comecar, mais os menores

O que a feature corrige: run() sempre comecava pelo PRIMEIRO item do
template, entao aldeia cheia mandava o maior pacote em todo alvo e aldeia
vazia sempre o menor -- independente do que o alvo tinha. Medido em
2026-08-17 sobre 336 ataques reais: dos envios com capacidade 8.000, 46%
voltaram exatamente com 8.000 (valor real desconhecido, cegos acima disso);
e os 68 alvos pobres recebiam o mesmo pacote de 100+ cavalarias para buscar
algumas centenas de recurso.

A armadilha que estes testes protegem: `farm_score` e a media do que NOS
saqueamos, logo e capado pelo pacote que mandamos. Usa-lo sozinho fecha um
ciclo -- pacote pequeno gera score pequeno, que escolhe pacote pequeno para
sempre. Por isso _expected_loot tambem le `resources` do relatorio de
exploracao, que e independente do nosso pacote.

Rodar: python tests/test_farm_pack_selection.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game.attack import AttackManager
import game.attack as attack_mod

GRANDE = {"light": 150}   # 12.000
MEDIO = {"light": 50}     # 4.000
PEQUENO = {"light": 15}   # 1.200
ESCADA = [GRANDE, MEDIO, PEQUENO]


class _RepMan:
    """Stub do ReportManager: devolve o que o explorador viu no alvo."""

    def __init__(self, por_alvo):
        self.por_alvo = por_alvo

    def has_resources_left(self, vid):
        res = self.por_alvo.get(vid)
        return (True, res) if res else (False, {})


def _man(template=None, cache=None, repman=None, monkey=True):
    man = AttackManager.__new__(AttackManager)
    man.template = ESCADA if template is None else template
    man.repman = repman
    if monkey:
        # AttackCache le disco; aqui o cache e injetado por alvo.
        attack_mod.AttackCache.get_cache = staticmethod(
            lambda vid, _c=(cache or {}): _c.get(vid)
        )
    return man


# --------------------------------------------------------------------------
# _pack_capacity
# --------------------------------------------------------------------------

def test_capacidade_usa_a_carga_real_da_unidade():
    man = _man()
    assert man._pack_capacity({"light": 150}) == 12000
    assert man._pack_capacity({"spear": 100}) == 2500
    assert man._pack_capacity({"axe": 100}) == 1000


def test_unidade_sem_carga_nao_soma():
    man = _man()
    assert man._pack_capacity({"light": 10, "spy": 50, "ram": 20}) == 800


def test_quantidade_como_string_nao_quebra():
    man = _man()
    assert man._pack_capacity({"light": "10"}) == 800


# --------------------------------------------------------------------------
# _expected_loot -- as duas fontes, e a maior vencendo
# --------------------------------------------------------------------------

def test_sem_dado_nenhum_e_zero():
    man = _man(cache={})
    assert man._expected_loot("999") == 0


def test_le_o_farm_score_do_cache():
    man = _man(cache={"1": {"farm_score": 3000}})
    assert man._expected_loot("1") == 3000


def test_relatorio_do_explorador_vence_o_score_capado():
    """
    O caso que motiva a feature: mandamos pacote de 1.200, o score ficou
    preso em 1.200, mas o explorador viu 40.000 parados no alvo.
    """
    man = _man(
        cache={"1": {"farm_score": 1200}},
        repman=_RepMan({"1": {"wood": "15000", "stone": "15000", "iron": "10000"}}),
    )
    assert man._expected_loot("1") == 40000


def test_score_vence_quando_o_relatorio_e_menor():
    man = _man(
        cache={"1": {"farm_score": 9000}},
        repman=_RepMan({"1": {"wood": "100", "stone": "100", "iron": "100"}}),
    )
    assert man._expected_loot("1") == 9000


def test_sem_repman_nao_quebra():
    man = _man(cache={"1": {"farm_score": 500}}, repman=None)
    assert man._expected_loot("1") == 500


def test_farm_score_zero_nao_e_confundido_com_ausente():
    """
    P1-8 no CLAUDE.md: `score or default` tratava 0 (farm que nao rende) como
    "sem historico". Aqui 0 e 0 mesmo.
    """
    man = _man(cache={"1": {"farm_score": 0}})
    assert man._expected_loot("1") == 0


def test_recurso_com_lixo_no_valor_nao_derruba():
    man = _man(
        cache={"1": {"farm_score": 700}},
        repman=_RepMan({"1": {"wood": "abc", "stone": "1"}}),
    )
    assert man._expected_loot("1") == 700


# --------------------------------------------------------------------------
# _ordered_templates -- a escada
# --------------------------------------------------------------------------

def test_alvo_rico_leva_o_maior():
    man = _man(cache={"1": {"farm_score": 11000}})
    assert man._ordered_templates("1")[0] == GRANDE


def test_alvo_pobre_leva_o_menor():
    man = _man(cache={"1": {"farm_score": 300}})
    assert man._ordered_templates("1")[0] == PEQUENO


def test_alvo_medio_leva_o_menor_que_ainda_cobre():
    man = _man(cache={"1": {"farm_score": 3500}})
    assert man._ordered_templates("1")[0] == MEDIO


def test_esperado_acima_de_todos_leva_o_maior():
    man = _man(cache={"1": {"farm_score": 999999}})
    assert man._ordered_templates("1")[0] == GRANDE


def test_devolve_a_cauda_para_a_queda_por_falta_de_tropa():
    """
    A queda para pacote menor quando falta tropa em casa ja existia em run()
    e precisa continuar valendo -- por isso o retorno e o escolhido MAIS os
    menores, nunca so o escolhido.
    """
    man = _man(cache={"1": {"farm_score": 3500}})
    assert man._ordered_templates("1") == [MEDIO, PEQUENO]


def test_sem_historico_sonda_com_o_menor():
    man = _man(cache={})
    assert man._ordered_templates("1") == [PEQUENO]


def test_ordem_do_arquivo_nao_inverte_a_escada():
    """
    A ordenacao e por capacidade, nao pela ordem em que foram escritos: um
    template com os pacotes fora de ordem nao pode inverter a escada em
    silencio.
    """
    man = _man(template=[PEQUENO, GRANDE, MEDIO], cache={"1": {"farm_score": 11000}})
    assert man._ordered_templates("1") == [GRANDE, MEDIO, PEQUENO]


def test_template_unico_como_dict_continua_funcionando():
    man = _man(template={"light": 20}, cache={"1": {"farm_score": 5}})
    assert man._ordered_templates("1") == [{"light": 20}]


def test_template_com_um_item_so_nao_consulta_o_alvo():
    """Com um pacote so nao ha escolha a fazer; nao pode exigir cache."""
    man = _man(template=[GRANDE], cache={})
    assert man._ordered_templates("1") == [GRANDE]


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
