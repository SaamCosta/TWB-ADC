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
    """
    Stub do ReportManager. `last_seen_value` e a observacao mais recente sobre
    o alvo -- estoque visto pelo explorador OU saque do ultimo ataque, o que
    for mais novo.
    """

    def __init__(self, por_alvo):
        self.por_alvo = por_alvo

    def last_seen_value(self, vid):
        return self.por_alvo.get(vid, 0)


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


def test_observacao_recente_vence_o_score_capado():
    """
    O caso que motiva a feature: mandamos pacote de 1.200, o score ficou preso
    em 1.200, mas o relatorio mais recente mostra 40.000 no alvo.
    """
    man = _man(cache={"1": {"farm_score": 1200}}, repman=_RepMan({"1": 40000}))
    assert man._expected_loot("1") == 40000


def test_score_vence_quando_a_observacao_e_menor():
    man = _man(cache={"1": {"farm_score": 9000}}, repman=_RepMan({"1": 300}))
    assert man._expected_loot("1") == 9000


def test_alvo_sem_score_usa_a_observacao():
    """
    O bug de 2026-08-19: farm_score ainda None (farm_manager nao pontuou) e o
    relatorio mais novo era de ataque, entao o caminho antigo devolvia 0 e o
    alvo levava o menor pacote da escada -- inclusive um com 10.292 parados.
    """
    man = _man(cache={"1": {"farm_score": None}}, repman=_RepMan({"1": 10292}))
    assert man._expected_loot("1") == 10292
    assert man._ordered_templates("1")[0] == GRANDE


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


def test_valor_exatamente_na_capacidade_escala_um_degrau():
    """
    Saque igual a capacidade nao e medicao, e observacao CENSURADA: significa
    "tinha isso ou mais". Com `>=` o alvo fixaria o score no teto do pacote que
    o censurou e escolheria esse mesmo pacote para sempre. Havia 18 alvos com
    farm_score exatamente 1.600 no cache de 2026-08-19, todos capados pelo
    pacote antigo de 20 cavalarias.
    """
    man = _man(cache={"1": {"farm_score": 1200}})
    assert man._ordered_templates("1")[0] == MEDIO, "1200 e o teto do pacote de 1200"

    man = _man(cache={"2": {"farm_score": 4000}})
    assert man._ordered_templates("2")[0] == GRANDE, "4000 e o teto do pacote de 4000"


def test_censura_no_maior_pacote_nao_tem_para_onde_escalar():
    """No topo da escada nao ha degrau acima; devolve o maior e segue."""
    man = _man(cache={"1": {"farm_score": 12000}})
    assert man._ordered_templates("1")[0] == GRANDE


def test_um_a_menos_que_a_capacidade_ainda_usa_o_pacote():
    """A escalada e so no valor exato do teto, nao um degrau para todo mundo."""
    man = _man(cache={"1": {"farm_score": 1199}})
    assert man._ordered_templates("1")[0] == PEQUENO


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


# --------------------------------------------------------------------------
# ReportManager.last_seen_value -- a fonte fresca de _expected_loot
# --------------------------------------------------------------------------

from game.reports import ReportManager


def _repman(*reports):
    """
    Monta um ReportManager com relatorios sinteticos no formato real:
    exploracao carrega `resources`, ataque carrega `loot`.
    """
    man = ReportManager.__new__(ReportManager)
    man.last_reports = {str(i): r for i, r in enumerate(reports)}
    return man


def _scout(vid, when, total):
    return {"dest": vid, "type": "scout",
            "extra": {"when": when, "resources": {"wood": str(total), "stone": "0", "iron": "0"}}}


def _attack(vid, when, total):
    return {"dest": vid, "type": "attack",
            "extra": {"when": when, "loot": {"wood": str(total), "stone": "0", "iron": "0"}}}


def test_relatorio_de_ataque_conta_pelo_saque():
    assert _repman(_attack("1", 100, 1520)).last_seen_value("1") == 1520


def test_exploracao_conta_pelo_estoque():
    assert _repman(_scout("1", 100, 10292)).last_seen_value("1") == 10292


def test_ataque_mais_novo_nao_apaga_a_exploracao_anterior():
    """
    O bug exato de 2026-08-19: has_resources_left pegava so o mais novo, via
    que era um ataque sem `resources`, e devolvia False -- descartando a
    exploracao logo abaixo. Aqui o mais novo vence por ser mais novo, mas a
    exploracao continua utilizavel quando ela E a mais nova.
    """
    man = _repman(_scout("1", 100, 10292), _attack("1", 200, 1520))
    assert man.last_seen_value("1") == 1520, "o ataque e mais novo, entao manda"

    man = _repman(_attack("1", 100, 1520), _scout("1", 200, 10292))
    assert man.last_seen_value("1") == 10292, "agora a exploracao e a mais nova"


def test_relatorio_sem_numero_nao_apaga_o_anterior():
    """Relatorio sem `resources` nem `loot` e ignorado, nao zera o sinal."""
    vazio = {"dest": "1", "type": "support", "extra": {"when": 300}}
    man = _repman(_scout("1", 100, 5000), vazio)
    assert man.last_seen_value("1") == 5000


def test_outro_alvo_nao_vaza():
    man = _repman(_scout("1", 100, 5000), _scout("2", 200, 99999))
    assert man.last_seen_value("1") == 5000


def test_sem_relatorio_devolve_zero():
    assert _repman().last_seen_value("1") == 0
    assert _repman(_scout("2", 100, 5000)).last_seen_value("1") == 0


def test_relatorio_sem_when_e_ignorado():
    sem_when = {"dest": "1", "type": "scout", "extra": {"resources": {"wood": "9999"}}}
    assert _repman(sem_when).last_seen_value("1") == 0


def test_valor_com_lixo_nao_derruba():
    ruim = {"dest": "1", "type": "scout",
            "extra": {"when": 200, "resources": {"wood": "abc"}}}
    man = _repman(_scout("1", 100, 5000), ruim)
    assert man.last_seen_value("1") == 5000


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
