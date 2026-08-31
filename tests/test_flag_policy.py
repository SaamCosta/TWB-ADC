"""
Politica de bandeira fora de combate (DefenceManager.preferred_flags /
flag_logic).

MOTIVACAO (medida em 2026-08-31). O bot tinha UM id fixo para paz
(set_flag_not_under_attack = 1, producao). O inventario da conta nao tinha
nenhuma bandeira do tipo 1 sobrando -- as 13 existentes estavam todas
equipadas -- entao get_highest_flag_possible(1) devolvia None e flag_logic()
nao fazia nada em nenhuma das 18 aldeias. Resultado real: BBM 016 e BBM 017
ficaram SEM bandeira nenhuma, com sete tipos disponiveis no inventario.

A politica, definida pelo usuario:
  - aldeia com academia   -> cunhagem (7) sempre; a moeda e da conta inteira,
                             entao o desconto vale mais onde se cunha;
  - aldeia sem academia   -> producao (1), a prioritaria geral;
  - preenchimento         -> recrutamento (2) > populacao (6) > saque (8),
                             porque recrutamento tem o maior efeito da tabela
                             (+20% no nivel 9 contra +10% dos outros);
  - ataque (3) e sorte (5) -> manuais, o bot nunca equipa nem remove;
  - defesa (4)            -> automatica, mas so pelo caminho de under_attack,
                             e vence qualquer preferencia.

O CUSTO DE ERRAR E ALTO: o cooldown de troca de bandeira e de 24 h
(FlagsScreen.cooldown_hours, lido ao vivo), e em 2026-08-02 uma troca errada
rebaixou producao de 16% para 12% sem reversao possivel no mesmo dia.

Rodar: python tests/test_flag_policy.py
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game.defence_manager import DefenceManager

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


# Inventario REAL da conta em 2026-08-31 (maior nivel disponivel por tipo),
# lido de cache/managed/*.json. Note a ausencia do tipo 1: e o estado que
# deixou duas aldeias sem bandeira.
REAL_INVENTORY = {2: 7, 3: 7, 4: 6, 5: 7, 6: 7, 7: 4, 8: 7}


def make(has_academy=False, current=None, inventory=None, can_change=True,
         confirmed=True):
    d = DefenceManager(village_id="99999", wrapper=None)
    d.logger = logging.getLogger("test-flags")
    d.manage_flags_enabled = True
    d.has_academy = has_academy
    d.current_flag = list(current) if current else None
    d.flags = dict(REAL_INVENTORY if inventory is None else inventory)
    d._can_change_flag = can_change
    d._flag_state_confirmed = confirmed
    d.sent = []
    d.flag_set = lambda flag, level: d.sent.append((flag, level)) or True
    return d


# ------------------------------------------------------------- preferencia

def test_academy_prefers_coin_cost():
    check(make(has_academy=True).preferred_flags()[0] == 7,
          "aldeia com academia deveria preferir cunhagem (7)")


def test_no_academy_prefers_production():
    check(make(has_academy=False).preferred_flags()[0] == 1,
          "aldeia sem academia deveria preferir producao (1)")


def test_fill_order_is_recruitment_population_loot():
    tail = [f for f in make(has_academy=False).preferred_flags() if f != 1]
    check(tail == [2, 6, 8],
          f"ordem de preenchimento deveria ser recrutamento, populacao, saque; e {tail}")


def test_manual_types_are_never_in_the_preference():
    for has_academy in (True, False):
        pref = make(has_academy=has_academy).preferred_flags()
        for manual in (3, 5):
            check(manual not in pref,
                  f"tipo {manual} e manual e nao deveria estar na preferencia {pref}")
        check(4 not in pref,
              f"defesa (4) nao deveria estar na preferencia de PAZ: {pref}")


def test_unknown_academy_abstains():
    """
    has_academy None = niveis de construcao ainda nao lidos (primeiro ciclo
    depois de um restart, porque setup_defence_manager roda antes de
    run_builder). Cair na lista sem academia seria pior que nao agir: ela nao
    tem o tipo 7, entao a aldeia de cunhagem viraria producao e o cooldown de
    24 h tornaria isso irreversivel no mesmo dia.
    """
    d = make(has_academy=None, current=[7, 4])
    check(d.preferred_flags() == [],
          "com academia desconhecida a preferencia deveria ser vazia")
    d.flag_logic(d.preferred_flags())
    check(d.sent == [],
          f"com academia desconhecida o bot nao deveria trocar nada, mandou {d.sent}")


# -------------------------------------------------------------- flag_logic

def test_equips_first_available_when_preferred_is_gone():
    """O caso BBM 016/017: sem bandeira, e sem tipo 1 no inventario."""
    d = make(has_academy=False, current=None)
    d.flag_logic(d.preferred_flags())
    check(d.sent == [(2, 7)],
          f"deveria equipar recrutamento nivel 7 (o primeiro disponivel), mandou {d.sent}")


def test_academy_village_gets_coin_flag():
    """O caso BBM 003: tem academia, esta com producao, ha cunhagem sobrando."""
    d = make(has_academy=True, current=[1, 7])
    d.flag_logic(d.preferred_flags())
    check(d.sent == [(7, 4)],
          f"aldeia com academia deveria trocar para cunhagem, mandou {d.sent}")


def test_does_not_touch_a_correct_flag():
    d = make(has_academy=True, current=[7, 4])
    d.flag_logic(d.preferred_flags())
    check(d.sent == [], f"bandeira ja correta nao deveria ser trocada, mandou {d.sent}")


def test_does_not_downgrade_to_a_lower_preference():
    """
    A aldeia esta com producao (1) e so ha recrutamento (2) no inventario.
    Trocar seria descer na preferencia E gastar o cooldown de 24 h.
    """
    d = make(has_academy=False, current=[1, 5], inventory={2: 7, 6: 7, 8: 7})
    d.flag_logic(d.preferred_flags())
    check(d.sent == [],
          f"nao deveria rebaixar producao para recrutamento, mandou {d.sent}")


def test_does_upgrade_to_a_higher_preference():
    """O inverso: esta com saque (8) e apareceu producao (1)."""
    d = make(has_academy=False, current=[8, 3], inventory={1: 6, 2: 7})
    d.flag_logic(d.preferred_flags())
    check(d.sent == [(1, 6)],
          f"deveria subir de saque para producao, mandou {d.sent}")


def test_manual_flag_is_left_alone():
    """Ataque e sorte sao escolha tatica do jogador."""
    for manual in (3, 5):
        d = make(has_academy=False, current=[manual, 7])
        d.flag_logic(d.preferred_flags())
        check(d.sent == [],
              f"bandeira manual tipo {manual} nao deveria ser trocada, mandou {d.sent}")


def test_defence_overrides_even_a_manual_flag():
    """
    Reagir a ataque tem precedencia sobre qualquer preferencia, inclusive
    manual -- mesma regra da Feature 23 (humanizacao nao degrada defesa).
    """
    d = make(has_academy=False, current=[3, 7])
    d.flag_logic(d.set_flag_under_attack)
    check(d.sent == [(4, 6)],
          f"defesa deveria sobrepor a bandeira manual, mandou {d.sent}")


def test_defence_still_works_for_academy_village():
    d = make(has_academy=True, current=[7, 4])
    d.flag_logic(d.set_flag_under_attack)
    check(d.sent == [(4, 6)],
          f"aldeia de cunhagem sob ataque deveria ir para defesa, mandou {d.sent}")


def test_cooldown_blocks_the_change():
    d = make(has_academy=False, current=None, can_change=False)
    d.flag_logic(d.preferred_flags())
    check(d.sent == [], f"cooldown deveria impedir a troca, mandou {d.sent}")


def test_unconfirmed_state_blocks_everything():
    d = make(has_academy=False, current=None, confirmed=False)
    d.flag_logic(d.preferred_flags())
    check(d.sent == [], f"estado nao confirmado nao deveria agir, mandou {d.sent}")


def test_empty_inventory_does_nothing_and_does_not_raise():
    d = make(has_academy=True, current=None, inventory={})
    try:
        d.flag_logic(d.preferred_flags())
    except Exception as exc:  # noqa: BLE001
        failures.append(f"inventario vazio levantou {type(exc).__name__}: {exc}")
        return
    check(d.sent == [], f"inventario vazio nao deveria equipar nada, mandou {d.sent}")


def test_local_state_updates_so_it_does_not_refire():
    d = make(has_academy=False, current=None)
    d.flag_logic(d.preferred_flags())
    first = list(d.sent)
    d.flag_logic(d.preferred_flags())
    check(d.sent == first,
          f"segunda chamada no mesmo estado nao deveria reenviar, mandou {d.sent}")


def test_higher_level_of_the_same_type_is_an_upgrade():
    """Mesmo tipo, nivel melhor disponivel: vale trocar."""
    d = make(has_academy=False, current=[1, 3], inventory={1: 7})
    d.flag_logic(d.preferred_flags())
    check(d.sent == [(1, 7)],
          f"deveria subir producao de nivel 3 para 7, mandou {d.sent}")


def test_the_real_18_village_snapshot():
    """
    Passa o estado real das 18 aldeias de 2026-08-31 e confere que a politica
    so mexe em quem deve: as duas sem bandeira e a BBM 003 (academia com
    producao). As demais ficam quietas.
    """
    snapshot = [
        # (nome, tem_academia, bandeira_atual)
        ("BBM 001", True, [7, 7]), ("BBM 011", True, [7, 5]),
        ("BBM 010", True, [7, 7]), ("BBM 003", True, [1, 7]),
        ("BBM 002", False, [1, 2]), ("BBM 005", False, [1, 5]),
        ("BBM 004", False, [1, 7]), ("BBM 006", False, [1, 4]),
        ("BBM 007", False, [1, 4]), ("BBM 012", False, [1, 2]),
        ("BBM 009", False, [1, 3]), ("BBM 008", False, [1, 1]),
        ("BBM 016", False, None), ("BBM 013", False, [1, 2]),
        ("BBM 014", False, [1, 1]), ("BBM 017", False, None),
        ("BBM 015", False, [1, 1]), ("BBM 018", False, [4, 7]),
    ]
    moved = {}
    for name, academy, current in snapshot:
        d = make(has_academy=academy, current=current)
        d.flag_logic(d.preferred_flags())
        if d.sent:
            moved[name] = d.sent[0]

    check(set(moved) == {"BBM 003", "BBM 016", "BBM 017", "BBM 018"},
          f"a politica deveria mexer em BBM 003, 016, 017 e 018; mexeu em {sorted(moved)}")
    check(moved.get("BBM 003") == (7, 4),
          f"BBM 003 (academia com producao) deveria ir para cunhagem, foi {moved.get('BBM 003')}")
    for v in ("BBM 016", "BBM 017"):
        check(moved.get(v) == (2, 7),
              f"{v} (sem bandeira) deveria receber recrutamento, recebeu {moved.get(v)}")
    # BBM 018 esta com defesa (4) fora de combate: 4 nao esta na preferencia de
    # paz, entao a politica a devolve para a fila normal quando o ataque passa.
    check(moved.get("BBM 018") == (2, 7),
          f"BBM 018 deveria voltar para a preferencia de paz, foi {moved.get('BBM 018')}")


for fn in [
    test_academy_prefers_coin_cost,
    test_no_academy_prefers_production,
    test_fill_order_is_recruitment_population_loot,
    test_manual_types_are_never_in_the_preference,
    test_unknown_academy_abstains,
    test_equips_first_available_when_preferred_is_gone,
    test_academy_village_gets_coin_flag,
    test_does_not_touch_a_correct_flag,
    test_does_not_downgrade_to_a_lower_preference,
    test_does_upgrade_to_a_higher_preference,
    test_manual_flag_is_left_alone,
    test_defence_overrides_even_a_manual_flag,
    test_defence_still_works_for_academy_village,
    test_cooldown_blocks_the_change,
    test_unconfirmed_state_blocks_everything,
    test_empty_inventory_does_nothing_and_does_not_raise,
    test_local_state_updates_so_it_does_not_refire,
    test_higher_level_of_the_same_type_is_an_upgrade,
    test_the_real_18_village_snapshot,
]:
    fn()

if failures:
    print(f"FALHOU ({len(failures)} problema(s)):")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("OK: politica de bandeira por academia, preferencia ordenada e guardas")
