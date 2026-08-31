"""
Testes da classificacao high_profile / low_profile do farm (manager.py).

MOTIVACAO. Os flags decidem o tempo de revisita em
AttackManager._should_attack: high = full_loot_away_time (30 min), default =
default_away_time (1 h), low = low_loot_away_time (2 h). A metrica era o saque
MEDIO ABSOLUTO -- >500 alto, <100 baixo -- e sobre 693 ataques reais de
2026-08-31 ela tinha tres problemas:

1. CENSURA. O saque nao pode passar da capacidade enviada, entao "saque medio"
   mede o nosso pacote tanto quanto o alvo. Medido: dos ataques com pacote de
   12.000, 83% voltaram exatamente com 12.000 -- o valor real daqueles alvos e
   desconhecido acima disso.
2. DERIVA. Por depender do tamanho do pacote, o limiar expirou sozinho quando
   a escada de pacotes cresceu (7c85a22): 35 de 62 alvos (56%) viraram "high
   profile". Um rotulo que vale para a maioria nao prioriza nada.
3. FLAGS QUE SO LIGAM. Nada nunca limpava high_profile ou low_profile. Seis
   alvos reais estavam com os DOIS ao mesmo tempo, e como _should_attack testa
   low por ultimo, o alvo 41318 -- que rende 4.517 por viagem -- era tratado
   como pobre e revisitado a cada 2 h.

Rodar: python tests/test_farm_profiles.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from manager import FULL_LOOT_RATIO, _pack_capacity

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


# ------------------------------------------------------------- capacidade

def test_pack_capacity_matches_the_game_carry_table():
    # 15 light * 80 = 1200; foi o menor pacote da escada por muito tempo.
    check(_pack_capacity({"light": 15}) == 1200,
          f"15 light deveria carregar 1200, deu {_pack_capacity({'light': 15})}")
    # spy e ram carregam 0: um ataque so de spy nao e medivel.
    check(_pack_capacity({"spy": 5}) == 0,
          "spy nao carrega nada, capacidade deveria ser 0")
    check(_pack_capacity({"spear": 10, "sword": 10}) == 250 + 150,
          "mistura de unidades deveria somar as capacidades")


def test_pack_capacity_never_raises_on_junk():
    """
    units_sent vem de um parse de relatorio; P2-26 ja mostrou que ele pode vir
    parcial. Capacidade 0 significa "nao medivel" e o chamador ignora o ataque
    -- que e diferente de contar lotacao 0% e empurrar o alvo para low_profile.
    """
    for junk, label in [(None, "None"), ({}, "vazio"),
                        ({"light": "abc"}, "quantidade nao numerica"),
                        ({"unidade_nova": 5}, "unidade desconhecida"),
                        ({"light": None}, "quantidade None")]:
        try:
            out = _pack_capacity(junk)
        except Exception as exc:  # noqa: BLE001 - o teste existe para isto
            failures.append(f"_pack_capacity({label}) levantou {type(exc).__name__}: {exc}")
            continue
        check(isinstance(out, int) and out >= 0,
              f"_pack_capacity({label}) deveria dar int >= 0, deu {out!r}")
    check(_pack_capacity({"light": 5, "unidade_nova": 99}) == 400,
          "unidade desconhecida deveria ser ignorada sem descartar o resto")


# ------------------------------------------------- a regra de classificacao

def classify(observations, high_fill=0.75, low_util=0.35, min_attacks=4,
             percentage_lost=0.0):
    """
    Reproduz a decisao de manager.py a partir de [(saque, capacidade)].
    Mantida em paralelo de proposito: farm_manager() le config.json e varre
    cache/, entao nao da para chamar sem estado de disco.
    """
    filled = measurable = 0
    util_sum = 0.0
    for loot, cap in observations:
        if cap <= 0:
            continue
        measurable += 1
        util_sum += loot / cap
        if loot >= cap * FULL_LOOT_RATIO:
            filled += 1
    if len(observations) < min_attacks or not measurable or percentage_lost > 20:
        return None, None
    fill_rate = filled / measurable
    utilization = util_sum / measurable
    want_high = fill_rate >= high_fill
    want_low = (not want_high) and utilization <= low_util
    return want_high, want_low


def test_flags_are_mutually_exclusive():
    """O bug de campo: 6 alvos com high E low ao mesmo tempo."""
    cases = [
        [(4800, 4800)] * 6,           # lota sempre
        [(100, 4800)] * 6,            # nunca lota, rende pouco
        [(2400, 4800)] * 6,           # meio termo
        [(4800, 4800)] * 3 + [(0, 4800)] * 3,
    ]
    for obs in cases:
        hi, lo = classify(obs)
        check(not (hi and lo), f"{obs[:2]}...: high e low ao mesmo tempo")


def test_full_pack_target_is_high_regardless_of_pack_size():
    """
    O coracao da mudanca: dois alvos que lotam SEMPRE dizem a mesma coisa
    ("tem mais do que eu carrego"), e o limiar absoluto so enxergava o grande.

    As duas capacidades sao reais, do cache de 2026-08-31: 480 (27 ataques
    registrados) e 12.000 (18 ataques). Com a regra antiga o de 480 fica
    ABAIXO do limiar de 500 e nunca seria high, por mais que lotasse todas as
    vezes; o de 12.000 seria high mesmo lotando raramente.

    Primeira versao deste teste usou 640 como "pacote pequeno" e falhou --
    640 ja passa de 500. Decimo nono padrao do CLAUDE.md: a armadilha
    plausivel precisa ser medida antes de virar assercao.
    """
    small = [(480, 480)] * 8
    large = [(12000, 12000)] * 8
    hi_s, lo_s = classify(small)
    hi_l, lo_l = classify(large)
    check(hi_s is True, "alvo que lota um pacote pequeno deveria ser high profile")
    check(hi_l is True, "alvo que lota um pacote grande deveria ser high profile")
    check(lo_s is False and lo_l is False, "nenhum dos dois deveria ser low")
    # A prova de que a metrica antiga discordava do caso pequeno:
    check(sum(l for l, _ in small) / len(small) < 500,
          "o alvo pequeno tem saque medio < 500, logo a regra antiga NAO o "
          "marcaria high -- e este teste existe justamente por isso")


def test_rich_looking_target_that_never_fills_is_not_high():
    """
    Caso real 37755: farm_score 683 (a regra antiga marcava HIGH por passar de
    500) mas lotacao 4%. O saque alto vinha do pacote grande, nao do alvo.
    """
    obs = [(12000, 12000)] + [(3000, 12000)] * 24
    hi, lo = classify(obs)
    check(hi is False, "alvo que lota 4% das vezes nao deveria ser high profile")


def test_poor_target_is_low_by_utilization_not_fill_rate():
    """
    Caso real 44674: lotacao 0%, aproveitamento 22% -- pobre de verdade.
    Contra 37755: lotacao 4%, aproveitamento 55% -- NAO e pobre, so recebe
    pacote grande demais. Lotacao sozinha nao separa os dois.
    """
    poor = [(1050, 4800)] * 6          # ~22% de aproveitamento
    big_pack = [(2640, 4800)] * 6      # ~55%, mesma lotacao (0%)
    hi_p, lo_p = classify(poor)
    hi_b, lo_b = classify(big_pack)
    check(lo_p is True, "alvo com 22% de aproveitamento deveria ser low profile")
    check(lo_b is False,
          "alvo com 55% de aproveitamento NAO deveria ser low profile, mesmo "
          "nunca lotando -- e o que distingue aproveitamento de lotacao")
    check(hi_p is False and hi_b is False, "nenhum dos dois lota, nenhum e high")


def test_needs_minimum_sample():
    check(classify([(4800, 4800)] * 3) == (None, None),
          "3 ataques deveriam ser amostra insuficiente (min_attacks=4)")
    hi, lo = classify([(4800, 4800)] * 4)
    check(hi is True, "4 ataques ja deveriam bastar")


def test_unmeasurable_attacks_do_not_count_as_empty():
    """
    Um relatorio sem units_sent utilizavel da capacidade 0. Conta-lo como
    lotacao 0% empurraria o alvo para low_profile por falta de DADO, nao por
    pobreza -- e o segundo padrao do CLAUDE.md com outra mascara.
    """
    obs = [(4800, 4800)] * 5 + [(0, 0)] * 5
    hi, lo = classify(obs)
    check(hi is True,
          "ataques nao mediveis deveriam ser ignorados, nao contados como vazios")


def test_dangerous_target_is_left_to_the_safety_rule():
    """
    percentage_lost > 20 e regra de seguranca e tem a ultima palavra. O bloco
    de perfil se abstem para os dois nao brigarem e regravarem o cache todo
    ciclo.
    """
    obs = [(4800, 4800)] * 8
    hi, lo = classify(obs, percentage_lost=35.0)
    check((hi, lo) == (None, None),
          "com perda perigosa o bloco de perfil nao deveria opinar")


def test_boundary_is_inclusive_on_high_and_low():
    check(classify([(4800, 4800)] * 3 + [(0, 4800)])[0] is True,
          "lotacao exatamente 75% deveria ser high (limiar inclusivo)")
    check(classify([(1680, 4800)] * 4)[1] is True,
          "aproveitamento exatamente 35% deveria ser low (limiar inclusivo)")


def test_rounding_slack_counts_as_full():
    """
    O jogo divide o saque entre os tres recursos e arredonda, entao um ataque
    cheio pode voltar 1 ou 2 abaixo da capacidade. FULL_LOOT_RATIO existe para
    isso.
    """
    check(classify([(4799, 4800)] * 5)[0] is True,
          "4799 de 4800 deveria contar como lotado")
    check(classify([(4700, 4800)] * 5)[0] is False,
          "4700 de 4800 (98%) NAO deveria contar como lotado")


for fn in [
    test_pack_capacity_matches_the_game_carry_table,
    test_pack_capacity_never_raises_on_junk,
    test_flags_are_mutually_exclusive,
    test_full_pack_target_is_high_regardless_of_pack_size,
    test_rich_looking_target_that_never_fills_is_not_high,
    test_poor_target_is_low_by_utilization_not_fill_rate,
    test_needs_minimum_sample,
    test_unmeasurable_attacks_do_not_count_as_empty,
    test_dangerous_target_is_left_to_the_safety_rule,
    test_boundary_is_inclusive_on_high_and_low,
    test_rounding_slack_counts_as_full,
]:
    fn()

if failures:
    print(f"FALHOU ({len(failures)} problema(s)):")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("OK: classificacao de perfil de farm por lotacao e aproveitamento")
