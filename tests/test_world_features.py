"""
Testes das mecanicas do mundo lidas de interface.php?func=get_config.

  WorldConfig._parse_features(xml)             -- extrai as tags
  WorldConfig.feature_enabled(cfg, nome, fb)   -- resolve com fallback

Por que existe: em 2026-08-17 o br143 (<archer>0</archer>) rodava com
config.json["world"]["archers_enabled"] = true, e o bot tentava recrutar e
pesquisar arqueiro em toda aldeia defensiva, todo ciclo. Nao foi erro de
leitura -- o WorldConfig ja baixava exatamente este XML e descartava a tag no
parse, e o valor era entao perguntado a um campo digitado a mao que ninguem
atualizou ao entrar no mundo.

Os fixtures sao recortes VERBATIM do servidor (CLAUDE.md: markup de jogo se
copia, nao se inventa), capturados em 2026-08-18:
  br143 -- mundo SEM arqueiro
  br142 -- mundo COM arqueiro

Rodar: python tests/test_world_features.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.world_config import WorldConfig

# --- verbatim: br143 (sem arqueiro), blocos <game> e <build> ---------------
BR143 = """<config>
<build>
  <destroy>1</destroy>
</build>
<game>
  <buildtime_formula>2</buildtime_formula>
  <knight>3</knight>
  <knight_new_items></knight_new_items>
  <knight_archer_bonus>0</knight_archer_bonus>
  <archer>0</archer>
  <tech>2</tech>
  <farm_limit>0</farm_limit>
  <church>0</church>
  <watchtower>1</watchtower>
  <stronghold>0</stronghold>
  <fake_limit>1</fake_limit>
  <barbarian_rise>0.003</barbarian_rise>
  <barbarian_max_points>1000</barbarian_max_points>
  <scavenging>1</scavenging>
</game>
</config>"""

# --- verbatim: br142 (com arqueiro) ---------------------------------------
BR142 = """<config>
<build>
  <destroy>1</destroy>
</build>
<game>
  <buildtime_formula>2</buildtime_formula>
  <knight>3</knight>
  <knight_archer_bonus>0</knight_archer_bonus>
  <archer>1</archer>
  <tech>2</tech>
  <farm_limit>0</farm_limit>
  <church>0</church>
  <watchtower>1</watchtower>
  <stronghold>0</stronghold>
  <fake_limit>2</fake_limit>
</game>
</config>"""


# --------------------------------------------------------------------------
# _parse_features
# --------------------------------------------------------------------------

def test_mundo_sem_arqueiro():
    f = WorldConfig._parse_features(BR143)
    assert f["archer"] == 0, f
    assert f["knight"] == 3
    assert f["church"] == 0
    assert f["watchtower"] == 1
    assert f["tech"] == 2


def test_fake_limit_do_mundo():
    """
    Limite de ataque falso: percentual dos pontos da aldeia ATACANTE que todo
    ataque precisa carregar em populacao. br143 = 1, br142 = 2.
    """
    assert WorldConfig._parse_features(BR143)["fake_limit"] == 1
    assert WorldConfig._parse_features(BR142)["fake_limit"] == 2


def test_min_attack_population_bate_com_o_jogo():
    """
    O numero exato que o servidor devolveu para a BBM 001 em 2026-08-19:
    7.335 pontos x 1% -> "minimo de 73 habitantes". O jogo trunca, nao
    arredonda -- 73,35 virou 73.
    """
    cfg = _cfg(BR143)
    assert WorldConfig.min_attack_population(cfg, 7335) == 73
    assert WorldConfig.min_attack_population(_cfg(BR142), 7335) == 146


def test_min_attack_population_degrada_para_zero():
    """Zero desliga a checagem: sem dado, nao inventamos um piso."""
    assert WorldConfig.min_attack_population(None, 7335) == 0
    assert WorldConfig.min_attack_population({"features": None}, 7335) == 0
    assert WorldConfig.min_attack_population(_cfg(BR143), None) == 0
    assert WorldConfig.min_attack_population(_cfg(BR143), 0) == 0


def test_mundo_sem_limite_de_ataque_falso():
    xml = BR143.replace("<fake_limit>1</fake_limit>", "<fake_limit>0</fake_limit>")
    assert WorldConfig.min_attack_population(_cfg(xml), 99999) == 0


def test_features_complete_invalida_cache_antigo():
    """
    Cache gravado antes de `fake_limit` existir ja tinha "features" e passaria
    numa checagem de presenca -- o bot rodaria ate 6h sem saber o piso. O que
    vale e o conjunto de chaves.
    """
    completo = WorldConfig._parse_features(BR143)
    assert WorldConfig._features_complete(completo) is True
    antigo = {k: v for k, v in completo.items() if k != "fake_limit"}
    assert WorldConfig._features_complete(antigo) is False
    assert WorldConfig._features_complete(None) is False


def test_chave_presente_com_none_continua_valida():
    """Chave existir com None significa "o mundo nao publicou"; nao invalida."""
    parcial = dict.fromkeys(WorldConfig.FEATURE_KEYS, None)
    assert WorldConfig._features_complete(parcial) is True


def test_mundo_com_arqueiro():
    assert WorldConfig._parse_features(BR142)["archer"] == 1


def test_destroy_vem_do_bloco_build_e_nao_do_game():
    """
    <destroy> mora em <build>, nao em <game>. Ler do bloco errado devolveria
    None e o bot cairia no fallback sem perceber.
    """
    assert WorldConfig._parse_features(BR143)["destroy"] == 1
    sem_build = BR143.replace("<build>\n  <destroy>1</destroy>\n</build>\n", "")
    assert WorldConfig._parse_features(sem_build)["destroy"] is None


def test_tag_ausente_vira_none_e_nao_zero():
    """
    A distincao que importa: 0 e "o mundo diz que nao tem", None e "nao
    sabemos". So o segundo pode cair no config.json.
    """
    xml = BR143.replace("<archer>0</archer>", "")
    assert WorldConfig._parse_features(xml)["archer"] is None


def test_xml_vazio_nao_derruba():
    f = WorldConfig._parse_features("")
    assert set(f) == set(WorldConfig.FEATURE_KEYS)
    assert all(v is None for v in f.values())


def test_knight_archer_bonus_nao_e_confundido_com_archer():
    """
    <knight_archer_bonus> contem a substring 'archer'. Um regex frouxo casaria
    com ele -- e no br143 ele vale 0, o mesmo valor de <archer>, entao o erro
    passaria despercebido ali e so apareceria num mundo com arqueiro.
    """
    assert WorldConfig._parse_features(BR142)["archer"] == 1


# --------------------------------------------------------------------------
# feature_enabled -- o mundo vence, o config.json e so rede de seguranca
# --------------------------------------------------------------------------

def _cfg(xml):
    return {"features": WorldConfig._parse_features(xml)}


def test_mundo_vence_o_config_errado():
    """O bug original: config.json dizia true, o mundo diz 0."""
    assert WorldConfig.feature_enabled(_cfg(BR143), "archer", True) is False


def test_mundo_vence_tambem_no_sentido_contrario():
    assert WorldConfig.feature_enabled(_cfg(BR142), "archer", False) is True


def test_knight_3_conta_como_ligado():
    """0 = sem paladino; 1/2/3 sao variantes, todas ligadas."""
    assert WorldConfig.feature_enabled(_cfg(BR143), "knight", False) is True


def test_sem_dado_usa_o_fallback():
    vazio = {"features": None}
    assert WorldConfig.feature_enabled(vazio, "archer", True) is True
    assert WorldConfig.feature_enabled(vazio, "archer", False) is False


def test_world_config_ausente_nao_derruba():
    assert WorldConfig.feature_enabled(None, "archer", True) is True
    assert WorldConfig.feature_enabled({}, "archer", True) is True


def test_nome_desconhecido_usa_o_fallback():
    assert WorldConfig.feature_enabled(_cfg(BR143), "inexistente", True) is True


def test_fallback_nao_e_consultado_quando_o_mundo_responde_zero():
    """
    Guarda contra `value or fallback`, que trataria 0 como ausente e
    ressuscitaria exatamente o bug.
    """
    assert WorldConfig.feature_enabled(_cfg(BR143), "church", True) is False


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
