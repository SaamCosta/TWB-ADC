"""
Oferta de bandeira e frescor do inventario (DefenceManager).

MOTIVACAO (docs/backend.md 6.3). A politica de bandeira por aldeia resolve o
sintoma do Bug 1 comparando bandeira atual x desejada, e a pergunta aberta era
se ela conta a OFERTA: "se dez aldeias quiserem um tipo do qual possuimos tres,
o que acontece?". Duas medicoes de 2026-09-20 respondem:

1. Bandeira e inventario DE CONTA, e bandeira equipada SAI do inventario.
   `setFlagCounts` do br143 publica ZERO para os tipos 1, 2 e 7, enquanto 28
   das 30 aldeias usam justamente um desses tres. Logo `flag_set` nao copia
   bandeira: ele MOVE a unica que existe, tirando-a de quem a usava.

2. O bot descartava a quantidade. `manage_flags` colapsava o inventario em
   {tipo: maior nivel com amount > 0}, entao "tenho uma sobrando" e "tenho
   cinco" eram o mesmo dado.

O que fecha o buraco nao e um ledger entre aldeias -- o servidor JA e esse
ledger, porque a bandeira sai do inventario quando equipada. O que faltava era
nao decidir sobre uma leitura velha: `manage_flags()` so le de fato a cada 3 a
8 runs (randomizacao) e o DefenceManager sobrevive entre ciclos, entao
`flag_logic` decidia com um inventario de varios ciclos atras.

Evidencia de que a crenca envelhece ERRADO, medida no cache real em
2026-09-20: o cache/managed da BBM 029 dizia `6: 7` enquanto o servidor ja nao
tinha nenhuma bandeira tipo 6 acima do nivel 4 -- a de nivel 7 tinha sido
equipada pela BBM 030. Agir sobre essa crenca arrancaria a bandeira da BBM 030.

Rodar: python tests/test_flag_supply.py
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


# O JSON abaixo e VERBATIM do br143, lido em 2026-09-20 por
# tests/smoke_flag_inventory.py (game.php?village=41123&screen=flags).
# Repare nos tipos 1, 2 e 7 inteiramente zerados: sao os tres tipos que as
# aldeias efetivamente usam. O HTML em volta e andaime minimo -- so o
# `setFlagCounts` e a `div#current_flag` importam para o parser.
REAL_SET_FLAG_COUNTS = (
    '{"1":{"1":"0","2":"0","3":"0","4":"0","5":"0","6":"0","7":"0"},'
    '"2":{"1":"0","2":"0","3":"0","4":"0","5":"0","6":"0","7":"0"},'
    '"3":{"1":"0","2":"1","3":"1","4":"0","5":"0","6":"1","7":"1"},'
    '"4":{"1":"2","2":"2","3":"1","4":"2","5":"0","6":"1","7":"1"},'
    '"5":{"1":"1","2":"2","3":"2","4":"1","5":"2","6":"1","7":"1"},'
    '"6":{"1":"0","2":"1","3":"2","4":"1","5":"0","6":"0","7":"0"},'
    '"7":{"1":"0","2":"0","3":"0","4":"0","5":"0","6":"0","7":"0"},'
    '"8":{"1":"1","2":"1","3":"1","4":"2","5":"1","6":"2","7":"1"}}'
)

REAL_FLAGS_PAGE = (
    '<div id="current_flag" style="margin-top: 10px">'
    '<img src="https://dsbr.innogamescdn.com/asset/x/graphic/flags/big/7_2.webp">'
    '<p>-12% nos custos de moedas</p></div>'
    '<script>FlagsScreen.setFlagCounts(' + REAL_SET_FLAG_COUNTS + ');</script>'
)

# O inventario colapsado que essa pagina produz, e que e exatamente o que o
# cache/managed das 30 aldeias mostrava.
COLLAPSED = {3: 7, 4: 7, 5: 7, 6: 4, 8: 7}


class FakeResponse:
    def __init__(self, text):
        self.text = text


class FakeWrapper:
    """Wrapper minimo: conta GETs e devolve a pagina real."""

    def __init__(self, text=REAL_FLAGS_PAGE):
        self.text = text
        self.gets = []
        self.last_h = "abc"

    def get_url(self, url):
        self.gets.append(url)
        return FakeResponse(self.text) if self.text is not None else None


def make(wrapper=None, has_academy=False, current=None, inventory=None,
         flags_fresh=True):
    d = DefenceManager(village_id="99999", wrapper=wrapper)
    d.logger = logging.getLogger("test-flag-supply")
    d.manage_flags_enabled = True
    d.has_academy = has_academy
    d.current_flag = list(current) if current else None
    d.flags = dict(COLLAPSED if inventory is None else inventory)
    d._can_change_flag = True
    d._flag_state_confirmed = True
    d._flags_fresh = flags_fresh
    d.sent = []
    d.flag_set = lambda flag, level: d.sent.append((flag, level)) or True
    return d


# ------------------------------------------------- leitura guarda a oferta

def test_manage_flags_keeps_the_amounts():
    d = make(wrapper=FakeWrapper())
    d.flag_upgrade = lambda flag, level: False
    d.manage_flags(force=True)
    check(d.flag_supply.get(6) == {2: 1, 3: 2, 4: 1},
          f"oferta do tipo 6 deveria ser {{2:1,3:2,4:1}}, veio {d.flag_supply.get(6)}")
    check(d.flag_supply.get(1) in (None, {}),
          f"tipo 1 esta zerado no servidor, nao deveria ter oferta: {d.flag_supply.get(1)}")
    check(d.flags == COLLAPSED,
          f"o inventario colapsado deveria continuar {COLLAPSED}, veio {d.flags}")


def test_supply_of_one_is_distinguishable_from_supply_of_many():
    """O dado que faltava: 'tenho uma' contra 'tenho cinco'."""
    d = make(wrapper=FakeWrapper())
    d.flag_upgrade = lambda flag, level: False
    d.manage_flags(force=True)
    check(d.flag_type_supply(6) == 4,
          f"tipo 6 tem 1+2+1 = 4 sobrando, veio {d.flag_type_supply(6)}")
    check(d.flag_type_supply(7) == 0,
          f"tipo 7 esta todo equipado, deveria ser 0, veio {d.flag_type_supply(7)}")
    check(d.flag_type_supply(1) == 0,
          f"tipo 1 esta todo equipado, deveria ser 0, veio {d.flag_type_supply(1)}")


def test_supply_is_empty_before_any_read():
    d = DefenceManager(village_id="1", wrapper=None)
    check(d.flag_supply == {}, "oferta deveria nascer vazia")
    check(d.flag_type_supply(6) == 0,
          "oferta desconhecida deveria contar 0, nao levantar")


def test_flag_supply_is_per_instance_not_per_class():
    """Primeiro padrao do CLAUDE.md: mutavel declarado na classe vaza."""
    a = DefenceManager(village_id="a", wrapper=None)
    b = DefenceManager(village_id="b", wrapper=None)
    a.flag_supply[6] = {4: 1}
    a._unmet_logged.add(("a", (1,)))
    check(b.flag_supply == {},
          f"oferta vazou entre instancias: {b.flag_supply}")
    check(b._unmet_logged == set(),
          f"_unmet_logged vazou entre instancias: {b._unmet_logged}")


# --------------------------------------------------------- gate de frescor

def test_stale_inventory_does_not_move_a_flag():
    """
    O caso BBM 029 x BBM 030. A aldeia acredita num tipo 6 nivel 7 que ja foi
    para outra aldeia; agir arrancaria a bandeira de la.
    """
    d = make(current=[8, 2], inventory={6: 7}, flags_fresh=False)
    d.flag_logic(d.preferred_flags())
    check(d.sent == [],
          f"com inventario nao lido neste ciclo nao deveria mover nada, mandou {d.sent}")


def test_fresh_inventory_does_move_the_same_flag():
    """
    Controle do teste acima -- sem ele o gate poderia estar simplesmente
    desligando a feature, e um teste verde nao distinguiria guarda de no-op
    (21o padrao do CLAUDE.md).
    """
    d = make(current=[8, 2], inventory={6: 7}, flags_fresh=True)
    d.flag_logic(d.preferred_flags())
    check(d.sent == [(6, 7)],
          f"com inventario fresco deveria equipar (6, 7), mandou {d.sent}")


def test_stale_inventory_still_leaves_a_correct_flag_alone():
    """Caminho no-op nao deve virar erro nem log de adiamento."""
    d = make(current=[6, 4], inventory={6: 4}, flags_fresh=False)
    d.flag_logic(d.preferred_flags())
    check(d.sent == [], f"bandeira ja correta nao deveria ser tocada, mandou {d.sent}")


def test_stale_gate_also_covers_the_village_without_any_flag():
    """
    O pior caso: aldeia recem-conquistada, sem bandeira. Duas delas decidindo
    sobre a mesma leitura velha disputariam a mesma unica bandeira.
    """
    d = make(current=None, flags_fresh=False)
    d.flag_logic(d.preferred_flags())
    check(d.sent == [],
          f"aldeia sem bandeira tambem espera leitura fresca, mandou {d.sent}")


def test_update_clears_freshness_before_reading():
    """
    O frescor vale para UM update(). Se `manage_flags` pular pela
    randomizacao, o ciclo tem que comecar marcado como nao lido.
    """
    d = make(wrapper=FakeWrapper(), flags_fresh=True)
    d.manage_flags_enabled = False  # forca manage_flags a retornar cedo
    d.units = None
    d.update(main="", with_defence=False)
    check(d._flags_fresh is False,
          "update() deveria zerar o frescor antes de chamar manage_flags()")


# ------------------------------- cada saida antecipada e "nao li o inventario"

def test_timeout_does_not_mark_the_inventory_as_fresh():
    d = make(wrapper=FakeWrapper(text=None), flags_fresh=False)
    d.manage_flags(force=True)
    check(d._flags_fresh is False,
          "request que voltou None nao pode marcar o inventario como lido")


def test_unparseable_page_does_not_mark_the_inventory_as_fresh():
    d = make(wrapper=FakeWrapper(text="<html>pagina de login</html>"), flags_fresh=False)
    d.manage_flags(force=True)
    check(d._flags_fresh is False,
          "pagina sem setFlagCounts nao pode marcar o inventario como lido")


def test_disabled_management_does_not_mark_the_inventory_as_fresh():
    d = make(wrapper=FakeWrapper(), flags_fresh=False)
    d.manage_flags_enabled = False
    d.manage_flags(force=True)
    check(d._flags_fresh is False,
          "com manage_flags desligado o inventario nunca foi lido")


def test_successful_read_marks_it_fresh():
    d = make(wrapper=FakeWrapper(), flags_fresh=False)
    d.flag_upgrade = lambda flag, level: False
    d.manage_flags(force=True)
    check(d._flags_fresh is True,
          "leitura completa deveria marcar o inventario como lido")


def test_force_bypasses_the_randomizer():
    """
    Sem `force` a releitura pos-upgrade re-sorteia a randomizacao e pode
    simplesmente nao acontecer, deixando self.flags com a contagem anterior ao
    upgrade -- que e o que a releitura existe para refletir.
    """
    d = make(wrapper=FakeWrapper(), flags_fresh=False)
    d.flag_upgrade = lambda flag, level: False
    d.runs = 7  # valor que a randomizacao pularia na maioria dos sorteios
    fired = []
    for _ in range(30):
        d._flags_fresh = False
        d.manage_flags(force=True)
        fired.append(d._flags_fresh)
    check(all(fired), "force=True deveria ler SEMPRE, sem depender do sorteio")


# --------------------------------------------------- oferta zerada e visivel

def test_unmet_preference_is_reported_once():
    """
    15o padrao: alerta que sai em todo ciclo e indistinguivel de alerta
    quebrado. Uma vez por aldeia por processo.
    """
    records = []

    class Collector(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    logger = logging.getLogger("test-unmet")
    logger.handlers = [Collector()]
    logger.setLevel(logging.INFO)
    logger.propagate = False

    d = make(has_academy=True, current=[8, 1])
    d.logger = logger
    d.flag_supply = {6: {4: 1}, 8: {1: 1}}
    for _ in range(5):
        d.flag_logic(d.preferred_flags())

    unmet = [m for m in records if "sem oferta no inventario" in m
             or "sem oferta no inventário" in m]
    check(len(unmet) == 1,
          f"o aviso de oferta zerada deveria sair 1 vez, saiu {len(unmet)}")
    if unmet:
        check("[7, 1, 2]" in unmet[0],
              f"o aviso deveria nomear os tipos sem oferta, veio: {unmet[0]}")


def test_no_unmet_warning_when_the_first_choice_is_available():
    records = []

    class Collector(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    logger = logging.getLogger("test-unmet-quiet")
    logger.handlers = [Collector()]
    logger.setLevel(logging.INFO)
    logger.propagate = False

    d = make(has_academy=True, current=None, inventory={7: 5})
    d.logger = logger
    d.flag_logic(d.preferred_flags())
    unmet = [m for m in records if "sem oferta" in m]
    check(unmet == [],
          f"com o tipo preferido disponivel nao deveria avisar nada: {unmet}")


def test_unmet_warning_does_not_announce_a_swap_that_the_guard_blocks():
    """
    Caso de campo de 2026-09-22 (BBM 001-004): cunhagem (tipo 7) equipada,
    tipos 7 e 1 sem oferta, melhor disponivel tipo 2 nivel 1. A guarda de
    rebaixamento mantem o 7 -- e a linha antiga dizia "usando tipo 2 nivel 1",
    anunciando uma troca que nao aconteceu, na validacao que conta trocas.
    """
    records = []

    class Collector(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    logger = logging.getLogger("test-unmet-no-swap")
    logger.handlers = [Collector()]
    logger.setLevel(logging.INFO)
    logger.propagate = False

    d = make(has_academy=True, current=[7, 4], inventory={2: 1})
    d.logger = logger
    d.flag_logic([7, 1, 2])

    check(d.sent == [], f"a guarda deveria segurar o tipo 7, mandou {d.sent}")
    unmet = [m for m in records if "sem oferta" in m]
    check(len(unmet) == 1, f"deveria haver 1 aviso de oferta, houve {len(unmet)}")
    if unmet:
        msg = unmet[0]
        check("usando" not in msg,
              f"o aviso nao pode anunciar troca que a guarda bloqueia: {msg}")
        check("melhor disponível: tipo 2 nível 1" in msg,
              f"o aviso deveria dizer o que esta disponivel: {msg}")
        check("equipada: tipo 7 nível 4" in msg,
              f"o aviso deveria mostrar a bandeira que fica: {msg}")


# ---------------------------------------- o quadro real medido em 2026-09-20

def test_the_real_account_inventory_falls_back_to_population():
    """
    Com o inventario real, TODAS as 30 aldeias escolhem o mesmo (6, 4) -- e
    existe exatamente UMA bandeira tipo 6 nivel 4 na conta. E este o quadro
    que torna o gate de frescor necessario: o unico motivo de nao haver
    vaivem hoje e que quase toda aldeia usa um tipo mais alto na preferencia,
    e a guarda de rebaixamento a segura.
    """
    academy = make(has_academy=True, current=None)
    academy.flag_logic(academy.preferred_flags())
    check(academy.sent == [(6, 4)],
          f"aldeia de academia sem bandeira deveria cair para (6, 4), mandou {academy.sent}")

    plain = make(has_academy=False, current=None)
    plain.flag_logic(plain.preferred_flags())
    check(plain.sent == [(6, 4)],
          f"aldeia sem academia tambem cai para (6, 4), mandou {plain.sent}")


def test_downgrade_guard_is_what_protects_the_current_allocation():
    """
    BBM 001 usa (7, 2) e o tipo 7 esta zerado no inventario. O escolhido seria
    (6, 4); quem impede a troca e a guarda de rebaixamento, nao a oferta.
    """
    d = make(has_academy=True, current=[7, 2])
    d.flag_logic(d.preferred_flags())
    check(d.sent == [],
          f"BBM 001 nao deveria trocar cunhagem por populacao, mandou {d.sent}")


for fn in [
    test_manage_flags_keeps_the_amounts,
    test_supply_of_one_is_distinguishable_from_supply_of_many,
    test_supply_is_empty_before_any_read,
    test_flag_supply_is_per_instance_not_per_class,
    test_stale_inventory_does_not_move_a_flag,
    test_fresh_inventory_does_move_the_same_flag,
    test_stale_inventory_still_leaves_a_correct_flag_alone,
    test_stale_gate_also_covers_the_village_without_any_flag,
    test_update_clears_freshness_before_reading,
    test_timeout_does_not_mark_the_inventory_as_fresh,
    test_unparseable_page_does_not_mark_the_inventory_as_fresh,
    test_disabled_management_does_not_mark_the_inventory_as_fresh,
    test_successful_read_marks_it_fresh,
    test_force_bypasses_the_randomizer,
    test_unmet_preference_is_reported_once,
    test_no_unmet_warning_when_the_first_choice_is_available,
    test_unmet_warning_does_not_announce_a_swap_that_the_guard_blocks,
    test_the_real_account_inventory_falls_back_to_population,
    test_downgrade_guard_is_what_protects_the_current_allocation,
]:
    fn()

if failures:
    print(f"FALHOU ({len(failures)} problema(s)):")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("OK: oferta de bandeira, frescor do inventario e aviso de oferta zerada")
