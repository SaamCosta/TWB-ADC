"""
Aldeia sem praca de reuniao (docs/backend.md §8.70): contagem de tropas
desconhecida nao e zero tropa.

A BBM 002 (38409) nao tem praca construida, e
`screen=place&mode=units&display=units` responde so "Praca de reuniao (nao
construido)". Os parsers de tropa devolviam lista vazia, `total_troops` virava
{} e o recrutamento lia "zero exploradores" numa aldeia com 4.075 e template
de 4.000: em 19/10 as 11:15 o bot pediu 4000 e iniciou 25. O mesmo {} fazia o
`troops_are_short` do mint dar sempre "curta", e a coleta pedia uma tela que
nao existe.

O que se protege aqui:
- `Extractor.place_units_unavailable` separa "praca nao construida" de "tela
  ilegivel" e de "tela normal" (ancorado no mesmo `units_home` do parser);
- `update_totals` deixa `total_troops` em None, e nao {}, sem a tabela;
- `Extractor.recruit_screen_counts` le "Na aldeia/total" da tela do predio, e
  o recrutamento so recruta o que falta pelo total de la;
- sem nenhuma das duas leituras, o recrutamento, o nobre e o mint nao agem;
- a coleta nao pede a tela de coleta de uma aldeia sem praca.

Fixtures VERBATIM do br143, BBM 002, 19/10, buscadas com o cliente do bot
(`cache/_probe_train_totals.py`, so GET): `place_units_not_built_br143.html`
(objeto village do game_data e o bloco do content_value) e
`train_stable_counts_br143.html` (o `train_form` do estabulo, h= redigido).

Rodar: python tests/test_place_not_built.py
"""
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.extractors import Extractor  # noqa: E402
from game.snobber import SnobManager  # noqa: E402
from game.troopmanager import TroopManager  # noqa: E402

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


def _fixture(name):
    with open(os.path.join(ROOT, "tests", "fixtures", name), encoding="utf-8") as fh:
        return fh.read()


NOT_BUILT = _fixture("place_units_not_built_br143.html")
WITH_PLACE = _fixture("place_units_transit_br143.html")
STABLE = _fixture("train_stable_counts_br143.html")


class FakeResponse:
    def __init__(self, text):
        self.text = text


class FakeWrapper:
    """Responde place&mode=units e a tela do predio; registra o que saiu."""

    def __init__(self, place=NOT_BUILT, screens=None):
        self.place = place
        self.screens = {"stable": STABLE} if screens is None else screens
        self.urls = []
        self.actions = []
        self.game_data_full = {}
        self.game_data_seen = {}
        self.reuse_game_data_max_age = 0
        self.last_h = "REDACTED"

    def get_action(self, action, village_id):
        self.actions.append(action)
        if action == "overview":
            return FakeResponse(NOT_BUILT)
        text = self.screens.get(action)
        return None if text is None else FakeResponse(text)

    def get_url(self, url):
        self.urls.append(url)
        if "mode=units" in url:
            return None if self.place is None else FakeResponse(self.place)
        return FakeResponse("")

    def post_url(self, url, data):
        raise AssertionError("teste nao pode postar: %s" % url)


def _troop_manager(wrapper, wanted=None):
    tm = TroopManager.__new__(TroopManager)
    tm.wrapper = wrapper
    tm.village_id = "38409"
    tm.resman = None
    tm.logger = None
    tm.wait_for = {"38409": {"barracks": 0, "stable": 0, "garage": 0}}
    tm.wanted = wanted if wanted is not None else {"stable": {"spy": 4000}}
    tm.randomize_unit_queue = False
    tm.recruited = []
    tm.recruit = lambda unit, amount, wait_for=False, building="barracks": (
        tm.recruited.append((building, unit, amount)) or True)
    return tm


def test_extractor_separa_os_tres_casos():
    check(Extractor.place_units_unavailable(NOT_BUILT) == "not_built",
          "fixture sem praca: %r" % Extractor.place_units_unavailable(NOT_BUILT))
    check(Extractor.place_units_unavailable(WITH_PLACE) is None,
          "tela normal (BBM 026) nao e indisponivel")
    check(Extractor.place_units_unavailable(None) == "unreadable", "None e ilegivel")
    check(Extractor.place_units_unavailable("<html>login</html>") == "unreadable",
          "pagina sem game_data e ilegivel, nao 'nao construida'")
    # A armadilha: os parsers de tropa nao distinguem -- lista vazia nos dois.
    check(Extractor.units_in_village(NOT_BUILT) == [], "parser de casa devolve []")
    check(Extractor.units_owned_total(NOT_BUILT) == [], "parser de total devolve []")


def test_extractor_le_na_aldeia_total():
    counts = Extractor.recruit_screen_counts(STABLE)
    check(counts == {"spy": (629, 4075), "light": (0, 0), "heavy": (0, 0)},
          "coluna Na aldeia/total do estabulo: %r" % counts)
    check(Extractor.recruit_screen_counts(NOT_BUILT) is None, "tela sem train_form: None")
    check(Extractor.recruit_screen_counts(None) is None, "sem resposta: None")


def test_update_totals_marca_desconhecido():
    w = FakeWrapper()
    tm = _troop_manager(w)
    tm.update_totals()
    check(tm.total_troops is None, "total sem praca deve ser None, nao %r" % (tm.total_troops,))
    check(tm.troops == {}, "em casa fica {}: sem praca nada sai (%r)" % (tm.troops,))
    check(tm.place_built is False, "place_built deve ser False: %r" % (tm.place_built,))

    w2 = FakeWrapper(place="<html>sessao expirada</html>")
    tm2 = _troop_manager(w2)
    tm2.update_totals()
    check(tm2.total_troops is None and tm2.place_built is None,
          "tela ilegivel: total None e praca nao lida (%r, %r)"
          % (tm2.total_troops, tm2.place_built))

    w3 = FakeWrapper(place=WITH_PLACE)
    tm3 = _troop_manager(w3)
    tm3.update_totals()
    check(isinstance(tm3.total_troops, dict) and tm3.total_troops,
          "com praca o total continua lido: %r" % (tm3.total_troops,))
    check(tm3.place_built is True, "com praca: place_built True")


def test_recrutamento_usa_a_tela_do_predio():
    w = FakeWrapper()
    tm = _troop_manager(w)
    tm.update_totals()
    tm.start_update("stable")
    check(tm.recruited == [], "4075 >= 4000: nao recruta (recrutou %r)" % tm.recruited)
    check(w.actions.count("stable") == 1, "uma leitura da tela do estabulo: %r" % w.actions)
    check(tm.known_totals("stable") == {"spy": 4075, "light": 0, "heavy": 0},
          "total do estabulo guardado no ciclo: %r" % tm.known_totals("stable"))

    w = FakeWrapper()
    tm = _troop_manager(w, wanted={"stable": {"spy": 5000}})
    tm.update_totals()
    tm.start_update("stable")
    check(tm.recruited == [("stable", "spy", 925)],
          "recruta so o que falta pelo total do predio: %r" % tm.recruited)


def test_desconhecido_nao_recruta():
    w = FakeWrapper(screens={})
    tm = _troop_manager(w)
    tm.update_totals()
    check(tm.start_update("stable") is False, "start_update sem contagem devolve False")
    check(tm.recruited == [], "sem contagem nenhuma: nao recruta as cegas (%r)" % tm.recruited)
    check(tm.known_totals("stable") is None, "contagem continua desconhecida")


def test_coleta_nao_pede_tela_sem_praca():
    w = FakeWrapper()
    tm = _troop_manager(w)
    tm.update_totals()
    before = list(w.urls)
    tm.can_gather = True
    check(tm.gather() is False, "coleta sem praca devolve False")
    check(w.urls == before, "nenhum GET de coleta: %r" % w.urls[len(before):])


def _snob(tm):
    man = SnobManager(wrapper=FakeWrapper(), village_id="38409")
    man.troop_manager = tm
    man.resman = types.SimpleNamespace(requested={}, actual={}, update=lambda g: None)
    man.building_level = 1
    return man


def test_snob_e_mint_nao_agem_no_desconhecido():
    tm = _troop_manager(FakeWrapper(screens={}))
    tm.update_totals()
    man = _snob(tm)
    check(man.troops_are_short() is None, "template sem contagem: None (%r)" % man.troops_are_short())
    man.mint_only = True
    check(man.mint_coins() is False and man.wrapper.actions == [],
          "mint nao age (nem pede a academia) com contagem desconhecida: %r" % man.wrapper.actions)

    man.mint_only = False
    man.wanted = 1
    check(man.run() is False and man.wrapper.actions == [],
          "nobre nao e recrutado com contagem desconhecida: %r" % man.wrapper.actions)
    check(man.needs_noble is False, "nao declara precisar de nobre sem saber quantos tem")

    tm2 = _troop_manager(FakeWrapper())
    tm2.update_totals()
    tm2.start_update("stable")
    check(_snob(tm2).troops_are_short() is False,
          "com o estabulo lido no ciclo, 4075 >= 4000 nao e curta")


for fn in [
    test_extractor_separa_os_tres_casos,
    test_extractor_le_na_aldeia_total,
    test_update_totals_marca_desconhecido,
    test_recrutamento_usa_a_tela_do_predio,
    test_desconhecido_nao_recruta,
    test_coleta_nao_pede_tela_sem_praca,
    test_snob_e_mint_nao_agem_no_desconhecido,
]:
    try:
        fn()
    except Exception as exc:
        import traceback
        traceback.print_exc()
        failures.append(f"{fn.__name__} levantou {exc!r}")

if failures:
    for f in failures:
        print("FALHA:", f)
    sys.exit(1)
print("OK - test_place_not_built")
