"""
Testes de `new_world_setup.build_new_config()` e `carry_identity()`
(docs/backend.md §8.91, troca br143 -> br147).

Cobre: a config herdada mantem as preferencias do jogador e zera o que e do
mundo (servidor, aldeias, area de interesse, deteccoes automaticas, receita de
tropa literal sem arqueiro), completa chave nova do template sem disparar o
merge por `build.version`, e o modo `--from-template` antigo. Sem arquivo:
config e template sao dicts montados aqui.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from new_world_setup import build_new_config, carry_identity  # noqa: E402

TEMPLATE = {
    "build": {"version": "9.9"},
    "server": {"server": "nlc1", "endpoint": "https://nlc1/game.php",
               "server_on_twstats": False},
    "bot": {"active_hours": "6-23", "delay_factor": 1.0},
    "farms": {"max_farms": 25},
    "conquest": {"enabled": False, "area_of_interest": {
        "enabled": False, "x_min": 0, "x_max": 0, "y_min": 0, "y_max": 0}},
    "world": {"knight_enabled": None, "flags_enabled": None,
              "quests_enabled": None, "boosters_enabled": None,
              "archers_enabled": True},
    "profile_templates": {"offensive": {"building": "b_off", "units": "off"},
                          "defensive": {"building": "b_def", "units": "def"}},
    "flag_value": {"mode": "dry_run", "attack_block_h": 168},
    "villages": {},
}

OLD = {
    "build": {"version": "5.9"},
    "server": {"server": "br143", "endpoint": "https://br143/game.php",
               "server_on_twstats": True},
    "bot": {"active_hours": "6-23", "delay_factor": 3},
    "farms": {"max_farms": 45},
    "conquest": {"enabled": True, "area_of_interest": {
        "enabled": True, "x_min": 500, "x_max": 650, "y_min": 270, "y_max": 299}},
    "world": {"knight_enabled": True, "flags_enabled": True,
              "quests_enabled": True, "boosters_enabled": True,
              "archers_enabled": True},
    "profile_templates": {"offensive": {"building": "b_off", "units": "off_no_archer"},
                          "defensive": {"building": "b_def", "units": "def_no_archer"},
                          "custom": {"units": "minha"}},
    "flag_value": {"mode": "on"},
    "villages": {"40618": {"farm": True}},
}


def test_herda_preferencias_e_zera_o_mundo():
    new = build_new_config(OLD, TEMPLATE, "br147", "https://br147/game.php")
    assert new["server"] == {"server": "br147", "endpoint": "https://br147/game.php",
                             "server_on_twstats": False}
    assert new["villages"] == {}
    # preferencias do jogador ficam
    assert new["farms"]["max_farms"] == 45
    assert new["conquest"]["enabled"] is True
    assert new["bot"]["delay_factor"] == 3
    assert new["flag_value"]["mode"] == "on"
    # o que e do mundo zera
    assert new["conquest"]["area_of_interest"]["enabled"] is False
    assert new["conquest"]["area_of_interest"]["x_max"] == 0
    for key in ("knight_enabled", "flags_enabled", "quests_enabled", "boosters_enabled"):
        assert new["world"][key] is None, key
    # receita literal sem arqueiro volta ao nome generico (resolvido por arqueiro)
    assert new["profile_templates"]["offensive"]["units"] == "off"
    assert new["profile_templates"]["defensive"]["units"] == "def"
    # perfil que o template nao conhece fica como esta
    assert new["profile_templates"]["custom"]["units"] == "minha"


def test_completa_chave_nova_sem_disparar_merge():
    new = build_new_config(OLD, TEMPLATE, "br147", "https://br147/game.php")
    assert new["flag_value"]["attack_block_h"] == 168
    assert new["build"]["version"] == TEMPLATE["build"]["version"]


def test_nao_mexe_na_config_velha():
    before = repr(OLD)
    build_new_config(OLD, TEMPLATE, "br147", "https://br147/game.php")
    assert repr(OLD) == before


def test_modo_template_antigo():
    new = build_new_config(OLD, TEMPLATE, "br147", "https://br147/game.php",
                           inherit=False)
    assert new["farms"]["max_farms"] == 25
    assert new["bot"]["delay_factor"] == 3
    assert new["server"]["server"] == "br147"
    assert new["villages"] == {}


def test_identidade_ganha_o_mundo_novo_uma_vez():
    ident = {"world": "br143", "player_name": "x", "extra_terms": []}
    out = carry_identity(ident, "br147")
    assert out["world"] == "br143"
    assert out["extra_terms"] == [{"term": "br147", "replacement": "br999"}]
    assert carry_identity(out, "br147")["extra_terms"] == out["extra_terms"]
    assert ident["extra_terms"] == []


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
