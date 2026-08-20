"""
Testes de integridade dos templates de builder (templates/builder/*.txt).

Motivacao: o formato e lido com `.strip().split()` e cada token vira
`nome:nivel` via `entry.split(":")` desempacotado em DUAS variaveis
(game/buildingmanager.py). Um token malformado -- um comentario, uma linha
com espaco no meio, um nivel nao numerico -- nao gera aviso: gera ValueError
no caminho quente do bot. Nao existia nenhuma verificacao disso.

Os max_level abaixo foram lidos do servidor em 2026-08-20, de
`interface.php?func=get_building_info` (endpoint publico, sem autenticacao),
conferidos IDENTICOS em br143 e br144. Nao vieram de wiki.

Ressalva deliberada sobre esses numeros, no espirito do decimo quarto padrao:
max_level e config de mundo, entao um mundo futuro pode divergir. Por isso o
teste so os usa para pegar erro de digitacao grosseiro (nivel muito acima do
teto conhecido), e nao como regra de jogo.

Nota sobre os templates herdados: purple_predator, purple_predator_into_def e
purple_predator_into_off contem entradas nao ascendentes (ex.: `smith:15`
depois de `smith:20`) e `snob:2`/`snob:3` acima do max_level 1. Foram
verificadas como INERTES: get_next_building_action() remove a entrada quando
`min_lvl <= get_level(entry)` e tambem quando o max_level e excedido, em
ambos os casos sem gastar a janela de max_lookahead. Por isso o teste de
ordem estrita vale so para os templates escritos neste projeto.

Rodar: python tests/test_builder_templates.py
"""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.templates import TemplateManager

# interface.php?func=get_building_info, br143 e br144, 2026-08-20.
MAX_LEVEL = {
    "main": 30, "barracks": 25, "stable": 20, "garage": 15, "watchtower": 20,
    "snob": 1, "smith": 20, "place": 1, "statue": 1, "market": 25,
    "wood": 30, "stone": 30, "iron": 30, "farm": 30, "storage": 30,
    "hide": 10, "wall": 20,
}

# Edificios cujo max_level varia por mundo, e para os quais a assercao
# estatica acima nao vale. `snob` e o caso concreto: e 1 no br143 e no br144,
# mas mundos com multiplas academias usam 3 -- e purple_predator*, herdado do
# bot base, pede snob:2 e snob:3 justamente por isso. Nao e erro do template:
# get_next_building_action() le o max_level do servidor em runtime e descarta
# a entrada sozinho quando o mundo nao suporta.
WORLD_DEPENDENT_MAX = {"snob", "watchtower"}

# Templates escritos neste projeto, aos quais a ordem estrita se aplica.
OURS = {"premium_seller", "watchtower_support"}

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


def parse(name):
    """Devolve [(indice, edificio, nivel)] ou estoura como o bot estouraria."""
    out = []
    for i, token in enumerate(TemplateManager.get_template("builder", name)):
        check(token.count(":") == 1,
              f"{name}: token {i} {token!r} nao tem exatamente um ':' "
              f"-- isso e ValueError em get_next_building_action()")
        if token.count(":") != 1:
            continue
        building, level = token.split(":")
        check(level.isdigit(), f"{name}: token {i} {token!r} tem nivel nao numerico")
        if not level.isdigit():
            continue
        out.append((i, building, int(level)))
    return out


def test_all_templates_parse():
    for path in sorted(glob.glob("templates/builder/*.txt")):
        name = os.path.basename(path)[:-4]
        entries = parse(name)
        check(len(entries) > 0, f"{name}: template vazio")
        for i, building, level in entries:
            check(building in MAX_LEVEL,
                  f"{name}: token {i} tem edificio desconhecido {building!r}")
            if building in MAX_LEVEL and building not in WORLD_DEPENDENT_MAX:
                check(level <= MAX_LEVEL[building],
                      f"{name}: token {i} pede {building}:{level}, acima do "
                      f"max_level conhecido {MAX_LEVEL[building]}")


def test_our_templates_are_strictly_ascending():
    for name in sorted(OURS):
        seen = {}
        for i, building, level in parse(name):
            if building in seen:
                check(level > seen[building],
                      f"{name}: token {i} pede {building}:{level} mas o template "
                      f"ja pediu {building}:{seen[building]} antes -- entrada morta")
            seen[building] = level


def test_premium_seller_respects_prerequisites():
    """
    max_lookahead = 2: se a entrada do topo nao puder ser construida, o bot olha
    UMA adiante e desiste do ciclo. Entao os pre-requisitos precisam estar
    satisfeitos com folga, nao no limite.

    Os requisitos abaixo NAO foram lidos do servidor -- os endpoints publicos
    (get_building_info, get_unit_info) nao publicam requisito de edificio, e a
    tela do jogo so mostra "Requisitos em falta" para o que ainda falta. Sao
    portanto o conservador: exigir que main e storage subam bem antes de quem
    depende deles. Se a regra real for mais frouxa, o teste continua valido
    (so e mais exigente que o necessario).
    """
    entries = parse("premium_seller")
    first = {}
    for i, building, level in entries:
        first.setdefault((building, level), i)

    def first_at_least(building, level):
        for i, b, l in entries:
            if b == building and l >= level:
                return i
        return None

    def first_any(building):
        for i, b, _ in entries:
            if b == building:
                return i
        return None

    main3 = first_at_least("main", 3)
    check(main3 is not None, "premium_seller: nunca sobe main para 3")

    for dependent in ("barracks", "market"):
        idx = first_any(dependent)
        check(idx is not None, f"premium_seller: nunca constroi {dependent}")
        if idx is not None and main3 is not None:
            check(main3 < idx,
                  f"premium_seller: {dependent} aparece no token {idx}, antes de "
                  f"main:3 (token {main3})")

    storage2 = first_at_least("storage", 2)
    market1 = first_any("market")
    check(storage2 is not None and market1 is not None and storage2 < market1,
          "premium_seller: market aparece antes de storage:2")

    # O perfil vendedor nao tem militar alem de quartel e um ferreiro minimo.
    for forbidden in ("stable", "garage", "snob", "watchtower"):
        check(first_any(forbidden) is None,
              f"premium_seller: contem {forbidden}, que nao pertence ao perfil vendedor")

    # O gargalo da venda e o mercador: o mercado precisa chegar na faixa 17-21.
    check(first_at_least("market", 17) is not None,
          "premium_seller: mercado nunca chega a 17 -- o gargalo da venda e o mercador")


def test_premium_seller_pop_budget_fits_the_farm():
    """
    2000 lanceiros + 600 espadachins = 2600 de populacao, mais os edificios.
    A capacidade da fazenda e round(240 * 1.1721^(nivel-1)), formula conferida
    em 2026-08-20 contra DUAS aldeias reais do br143 no mesmo dia:
    fazenda 15 -> pop_max 2216 (calculado 2217) e fazenda 26 -> 12715 (exato).
    """
    def farm_cap(level):
        return round(240 * 1.1721 ** (level - 1))

    check(farm_cap(15) in (2216, 2217), f"formula da fazenda mudou: 15 -> {farm_cap(15)}")
    check(farm_cap(26) == 12715, f"formula da fazenda mudou: 26 -> {farm_cap(26)}")

    entries = parse("premium_seller")
    top_farm = max((l for _, b, l in entries if b == "farm"), default=0)
    # 2600 de tropa + ~605 de edificios no pior caso (mercado 21).
    check(farm_cap(top_farm) >= 2600 + 605,
          f"premium_seller: fazenda para em {top_farm} (cap {farm_cap(top_farm)}), "
          f"insuficiente para 2600 de tropa + ~605 de edificios")


for fn in [
    test_all_templates_parse,
    test_our_templates_are_strictly_ascending,
    test_premium_seller_respects_prerequisites,
    test_premium_seller_pop_budget_fits_the_farm,
]:
    fn()

if failures:
    print(f"FALHOU ({len(failures)} problema(s)):")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("OK: templates de builder integros")
