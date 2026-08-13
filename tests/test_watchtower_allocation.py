"""
Testes da Feature 30 -- alocacao territorial de aldeias de torre de vigia.

Duas funcoes puras em game/village.py:

  Village.get_needed_profile(config)   -- proporcao ofensiva/defensiva do
      imperio, agora ignorando os perfis de NON_RATIO_PROFILES.
  Village.needs_watchtower(config, x, y) -- decide se uma aldeia recem
      conquistada deve virar torre, por distancia ate a torre mais proxima.

O ponto da feature: uma aldeia de torre e defensiva por natureza, mas a
necessidade dela e territorial, nao numerica. Se contasse na proporcao, o bot
criaria torres pela contagem de aldeias em vez de pela geografia e os raios se
sobreporiam -- cada torre custa 11.607 de populacao e 4,85M de recursos.

Coordenadas reais usadas nos testes: BBM 002 em 578|305 (br143, conta sccj).

Rodar: python tests/test_watchtower_allocation.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game.village import Village

BBM002_X, BBM002_Y = 578, 305


def _cfg(perfis, off=1, dfn=3, **watchtower):
    """Config minima: uma aldeia por perfil da lista."""
    cfg = {
        "empire": {"offensive_ratio": off, "defensive_ratio": dfn},
        "villages": {str(i): {"profile": p} for i, p in enumerate(perfis)},
    }
    if watchtower:
        cfg["watchtower"] = watchtower
    return cfg


# --------------------------------------------------------------------------
# get_needed_profile -- a torre fora da proporcao
# --------------------------------------------------------------------------

def test_proporcao_3_para_1_defensivo():
    """Alvo 25% ofensivas: 2/7 = 28,6% ja passou, entao a proxima e defensiva."""
    assert Village.get_needed_profile(
        _cfg(["offensive"] * 2 + ["defensive"] * 5)
    ) == "defensive"
    assert Village.get_needed_profile(
        _cfg(["offensive"] * 1 + ["defensive"] * 5)
    ) == "offensive"


def test_torre_nao_desloca_a_proporcao():
    """
    O coracao da feature. Adicionar torres nao pode mudar qual perfil a proxima
    conquista recebe -- se mudasse, o bot alocaria torres por contagem.
    """
    base = _cfg(["offensive"] + ["defensive"] * 3)
    for n_torres in (1, 3, 10):
        com_torres = _cfg(
            ["offensive"] + ["defensive"] * 3 + ["watchtower"] * n_torres
        )
        assert Village.get_needed_profile(com_torres) == Village.get_needed_profile(base)


def test_perfil_ausente_ainda_conta_como_defensiva():
    """
    Retrocompatibilidade: so os perfis explicitamente listados em
    NON_RATIO_PROFILES saem da conta. Aldeia sem a chave 'profile' mantem o
    comportamento antigo, senao config existente mudaria de significado.
    """
    cfg = {
        "empire": {"offensive_ratio": 1, "defensive_ratio": 3},
        "villages": {"a": {}, "b": {}, "c": {}, "d": {"profile": "offensive"}},
    }
    assert Village.get_needed_profile(cfg) == "defensive"


def test_proporcao_zerada_nao_divide_por_zero():
    """Config invalida nao pode derrubar a heranca da aldeia conquistada."""
    assert Village.get_needed_profile(_cfg([], off=0, dfn=0)) == "defensive"


def test_imperio_vazio():
    assert Village.get_needed_profile(_cfg([])) == "offensive"


# --------------------------------------------------------------------------
# needs_watchtower -- decisao territorial
# --------------------------------------------------------------------------

def _cfg_torre(min_spacing=16, min_villages=5, n_villages=7, com_torre=False):
    cfg = _cfg(["defensive"] * n_villages)
    cfg["watchtower"] = {
        "enabled": True,
        "min_spacing": min_spacing,
        "min_villages": min_villages,
    }
    if com_torre:
        cfg["villages"]["38409"] = {"profile": "watchtower"}
    return cfg


def test_desligado_nunca_designa():
    cfg = _cfg_torre(com_torre=True)
    cfg["watchtower"]["enabled"] = False
    assert Village.needs_watchtower(cfg, 999, 999)[0] is False


def test_imperio_jovem_nao_designa():
    """min_villages protege conta nova de converter aldeia que nao sustenta."""
    cfg = _cfg_torre(n_villages=2, com_torre=True)
    assert Village.needs_watchtower(cfg, 999, 999)[0] is False


def test_primeira_torre_nunca_e_automatica():
    """
    Sem nenhuma torre designada, NENHUMA conquista vira torre -- em qualquer
    coordenada. Tres razoes, todas no comentario da funcao:
      1. a primeira torre define o centro da malha inteira;
      2. esta funcao so roda para aldeia recem conquistada, que esta na
         fronteira -- a primeira torre nasceria na borda;
      3. aldeia recem conquistada e o pior sitio possivel para o projeto.
    """
    cfg = _cfg_torre(com_torre=False)
    for x, y in ((BBM002_X, BBM002_Y), (590, 320), (700, 700), (571, 308)):
        designa, motivo = Village.needs_watchtower(cfg, x, y)
        assert designa is False, (x, y)
        assert "must be chosen by hand" in motivo


def test_limiar_de_espacamento():
    """
    Com a BBM 002 designada, o limiar e exatamente min_spacing. 16 fica logo
    acima do raio de 15,0 do nivel 20: 'aldeia que nenhuma torre enxerga vira
    torre'. Ver a secao 7 de docs/watchtower.md para a simulacao que fixou 16.
    """
    cfg = _cfg_torre(com_torre=True)
    casos = [(0, False), (10, False), (15.9, False), (16, True), (16.1, True), (40, True)]
    for distancia, esperado in casos:
        got = Village.needs_watchtower(cfg, BBM002_X + distancia, BBM002_Y)[0]
        assert got is esperado, (distancia, got, esperado)


def test_espacamento_e_configuravel():
    cfg = _cfg_torre(min_spacing=26, com_torre=True)
    assert Village.needs_watchtower(cfg, BBM002_X + 20, BBM002_Y)[0] is False
    assert Village.needs_watchtower(cfg, BBM002_X + 26, BBM002_Y)[0] is True


def test_distancia_e_euclidiana_nos_dois_eixos():
    """3-4-5: uma aldeia em (+12, +16) esta a 20 campos, nao a 12 nem a 16."""
    cfg = _cfg_torre(min_spacing=19, com_torre=True)
    assert Village.needs_watchtower(cfg, BBM002_X + 12, BBM002_Y + 16)[0] is True
    cfg19 = _cfg_torre(min_spacing=21, com_torre=True)
    assert Village.needs_watchtower(cfg19, BBM002_X + 12, BBM002_Y + 16)[0] is False


def test_motivo_sempre_explica_a_decisao():
    """O chamador loga esse texto em nivel info; nao pode vir vazio."""
    for cfg in (_cfg_torre(com_torre=True), _cfg_torre(com_torre=False),
                _cfg_torre(n_villages=1, com_torre=True)):
        _, motivo = Village.needs_watchtower(cfg, 600, 400)
        assert motivo and isinstance(motivo, str)


def test_perfil_de_torre_esta_na_lista_de_exclusao():
    assert "watchtower" in Village.NON_RATIO_PROFILES
    assert isinstance(Village.NON_RATIO_PROFILES, tuple), (
        "mutavel no corpo da classe e o primeiro padrao de bug do CLAUDE.md"
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
