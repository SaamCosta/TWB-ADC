"""
Cessão de fases ao gerente de conta, aldeia por aldeia (`core/am_cession.py`,
`Extractor.account_manager_widget`, docs/backend.md §8.68).

O que se protege aqui:
- o widget do gerente na visão geral se lê por linha, e cada linha exige que
  `selected` e `<em>Sem gerência</em>` concordem; discordância ou markup novo
  é None, nunca "ativo" (décimo quinto padrão);
- o rótulo de uma linha não atravessa o `</span>` das anteriores (o bug que a
  primeira versão do regex teve: tropas da BBM 001 saíam None);
- sem widget (conta grátis, ou widget tirado da visão geral) é None;
- só cede com o gerente ativo AGORA (True, não None) E modelo ativo na
  linha; kill switch global e por fase; padrão ligado sem a seção;
- a troca loga uma vez; a primeira decisão só loga se cedeu;
- `Village`: recrutamento cedido não recruta e limpa o pedido de recurso de
  recrutamento; pesquisa cedida não lê o ferreiro e barra a pesquisa que
  `recruit()` tentaria sozinho; gerente vencido devolve a fase ao bot.

Fixtures verbatim de `game.php?village=N&screen=overview`, br143, 18/10/2026:
BBM 051 (os três ativos), BBM 001 (construção e pesquisa sem gerência, tropas
ativas) e BBM 054/81571 (nenhum modelo). O caso "sem widget" é a visão geral
da conta sem gerente (captura gratuita de 08/10), reduzida ao que importa: o
widget não existe nela.

Rodar: python tests/test_am_cession.py
"""
import logging
import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import am_cession  # noqa: E402
from core.extractors import Extractor  # noqa: E402
from game.troopmanager import TroopManager  # noqa: E402
from game.village import Village  # noqa: E402

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


def fixture(name):
    path = os.path.join(ROOT, "tests", "fixtures", "am_widget_%s_br143.html" % name)
    with open(path, encoding="utf-8") as fh:
        return fh.read()


ALL_ACTIVE = fixture("all_active")
TROOPS_ONLY = fixture("troops_only")
NO_TEMPLATE = fixture("no_template")


def test_widget_three_live_states():
    w = Extractor.account_manager_widget(ALL_ACTIVE)
    check(w == {
        "construction": {"active": True, "template": "ADC - DEFENSIVA"},
        "research": {"active": True, "template": "ADC - DEFENSIVA"},
        "troops": {"active": True, "template": "ADC - DEFENSIVA"},
    }, "BBM 051: os tres ativos -> %r" % (w,))
    w = Extractor.account_manager_widget(TROOPS_ONLY)
    check(w and w["construction"] == {"active": False, "template": ""},
          "BBM 001: construcao sem gerencia -> %r" % (w,))
    check(w and w["research"] == {"active": False, "template": ""},
          "BBM 001: pesquisa sem gerencia")
    # O caso que a primeira versao do regex errava: o rotulo engolia os
    # spans das linhas de cima e misturava o <em> delas com este selected.
    check(w and w["troops"] == {"active": True, "template": "ADC - OFENSIVA"},
          "BBM 001: tropas ativas (rotulo nao pode cruzar </span>) -> %r" % (w and w["troops"],))
    w = Extractor.account_manager_widget(NO_TEMPLATE)
    check(w is not None and all(row == {"active": False, "template": ""} for row in w.values()),
          "81571: nenhum modelo -> %r" % (w,))


def test_widget_absent_or_broken():
    check(Extractor.account_manager_widget(None) is None, "resposta None")
    check(Extractor.account_manager_widget(
        '<div id="show_mood" class="vis moveable widget "></div>') is None,
        "visao geral sem o widget (conta sem gerente)")
    # Os dois sinais discordando: selected E <em>Sem gerencia</em>.
    # O primeiro rótulo do widget é o da construção.
    broken = ALL_ACTIVE.replace(
        "ADC - DEFENSIVA                </span>", "<em>Sem gerência</em>                </span>", 1)
    check(broken != ALL_ACTIVE, "montagem do caso quebrado nao casou com a fixture")
    w = Extractor.account_manager_widget(broken)
    check(w and w["construction"] is None, "sinais discordantes viram None -> %r" % (w and w["construction"],))
    check(w and w["research"]["active"] is True, "as outras linhas seguem lidas")
    # Linha que sumiu do markup.
    gone = ALL_ACTIVE.replace('name="research_template"', 'name="outra_coisa"')
    w = Extractor.account_manager_widget(gone)
    check(w and w["research"] is None, "linha ausente vira None")


def test_decide_matrix():
    on = Extractor.account_manager_widget(ALL_ACTIVE)
    off = Extractor.account_manager_widget(NO_TEMPLATE)
    for phase in ("construction", "research", "recruitment"):
        ceded, reason = am_cession.decide(phase, None, True, on)
        check(ceded and reason == "modelo ADC - DEFENSIVA", "%s: cede sem a secao (padrao ligado)" % phase)
        check(am_cession.decide(phase, {}, True, off) == (False, "sem modelo"), "%s: sem modelo" % phase)
        check(am_cession.decide(phase, {}, False, on) == (False, "gerente vencido"), "%s: vencido" % phase)
        check(am_cession.decide(phase, {}, None, on) == (False, "gerente ainda não lido"),
              "%s: nao lido nao cede" % phase)
        check(am_cession.decide(phase, {}, True, None)[0] is False, "%s: sem widget nao cede" % phase)
        check(am_cession.decide(phase, {"cede_enabled": False}, True, on)[0] is False,
              "%s: kill switch global" % phase)
        check(am_cession.decide(phase, {"cede_" + phase: False}, True, on)[0] is False,
              "%s: kill switch da fase" % phase)
    broken = dict(on, troops=None)
    check(am_cession.decide("recruitment", {}, True, broken) == (False, "linha do widget ilegível"),
          "linha ilegivel nao cede")
    check(am_cession.decide("farm", {}, True, on)[0] is False, "fase que o gerente nao faz")
    check(am_cession.decide("construction", {}, 1, on)[0] is False, "so True literal conta como ativo")


def test_transition_messages():
    t = am_cession.transition_message
    check(t("construction", None, (False, "sem modelo")) is None, "primeira decisao 'bot faz' e silenciosa")
    check(t("construction", None, (True, "modelo X")) == "Gerente: construção cedida ao gerente (modelo X)",
          "primeira decisao cedida loga")
    check(t("research", (True, "modelo X"), (True, "modelo X")) is None, "sem troca, sem log")
    check(t("recruitment", (True, "modelo X"), (False, "gerente vencido"))
          == "Gerente: recrutamento retomada pelo bot -- gerente vencido", "retomada loga o motivo")
    check(t("construction", (False, "sem modelo"), (True, "modelo Y"))
          == "Gerente: construção cedida ao gerente (modelo Y)", "cedida depois de retomada loga")


class Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def village(manager, widget, cfg=None, recruit_cfg=True):
    v = Village.__new__(Village)
    v.village_id = "41123"
    detector = SimpleNamespace(active=lambda name: manager if name == "AccountManager" else None)
    v.wrapper = SimpleNamespace(paid_features=detector)
    v.config = {
        "units": {"recruit": recruit_cfg, "upgrade": True,
                  "remove_manual_queued": False, "randomize_unit_queue": True},
        "villages": {"41123": {"prioritize_building": False, "prioritize_snob": False}},
    }
    if cfg is not None:
        v.config["account_manager"] = cfg
    v.am_widget = widget
    v._am_cession = {}
    v._am_cession_at = {}
    cap = Capture()
    v.logger = logging.getLogger("test_am_cession.%d" % id(v))
    v.logger.addHandler(cap)
    v.logger.setLevel(logging.INFO)
    v.logger.propagate = False
    calls = {"start_update": 0, "attempt_upgrade": 0}
    v.units = SimpleNamespace(
        wanted={"barracks": {"spear": 100}}, wanted_levels={"light": 1},
        research_ceded=False,
        start_update=lambda b, d: calls.__setitem__("start_update", calls["start_update"] + 1),
        attempt_upgrade=lambda: calls.__setitem__("attempt_upgrade", calls["attempt_upgrade"] + 1),
    )
    v.resman = SimpleNamespace(requested={"recruitment_spear": {"wood": 10}, "snob": {"wood": 5}})
    v.builder = SimpleNamespace(get_level=lambda b: 10)
    v.snobman = None
    v.disabled_units = []
    return v, calls, cap


def test_village_recruitment_ceded():
    v, calls, cap = village(True, Extractor.account_manager_widget(ALL_ACTIVE))
    v.do_recruit()
    check(calls["start_update"] == 0, "recrutamento cedido nao pode recrutar")
    check("recruitment_spear" not in v.resman.requested, "pedido de recurso de recrutamento ficou")
    check("snob" in v.resman.requested, "pedido do nobre nao e do recrutamento e fica")
    check(v.units.research_ceded is True, "do_recruit arma a trava da pesquisa de recruit()")
    check("Gerente: recrutamento cedida ao gerente (modelo ADC - DEFENSIVA)" in cap.lines,
          "log da cessao -> %r" % cap.lines)
    check(v._am_cession["recruitment"] == (True, "modelo ADC - DEFENSIVA"), "estado guardado")


def test_village_resumes_when_manager_expires():
    widget = Extractor.account_manager_widget(ALL_ACTIVE)
    v, calls, cap = village(True, widget)
    v.do_recruit()
    # O gerente vence no meio do processo: o detector passa a dizer False.
    v.wrapper.paid_features.active = lambda name: False
    v.do_recruit()
    check(calls["start_update"] == 1, "gerente vencido: o bot volta a recrutar")
    check(v.units.research_ceded is False, "pesquisa tambem volta ao bot")
    check("Gerente: recrutamento retomada pelo bot -- gerente vencido" in cap.lines,
          "log da retomada -> %r" % cap.lines)


def test_village_no_template_is_bot_work():
    v, calls, cap = village(True, Extractor.account_manager_widget(NO_TEMPLATE))
    v.do_recruit()
    v.run_unit_upgrades()
    check(calls["start_update"] == 1 and calls["attempt_upgrade"] == 1,
          "81571 sem modelo: o bot recruta e pesquisa")
    check(cap.lines == [], "estado de sempre nao loga -> %r" % cap.lines)


def test_village_research_ceded_only():
    # BBM 001 ao contrario: so a pesquisa com modelo.
    widget = {"construction": {"active": False, "template": ""},
              "research": {"active": True, "template": "ADC - OFENSIVA"},
              "troops": {"active": False, "template": ""}}
    v, calls, _ = village(True, widget)
    v.run_unit_upgrades()
    check(calls["attempt_upgrade"] == 0, "pesquisa cedida nao le o ferreiro")
    v.do_recruit()
    check(calls["start_update"] == 1, "recrutamento sem modelo segue com o bot")
    check(v.units.research_ceded is True, "recruit() nao pode pesquisar sozinho")


def test_village_kill_switch_and_missing_widget():
    widget = Extractor.account_manager_widget(ALL_ACTIVE)
    v, calls, _ = village(True, widget, cfg={"cede_enabled": False})
    v.do_recruit()
    check(calls["start_update"] == 1, "kill switch: o bot recruta")
    v, calls, _ = village(True, None)
    v.do_recruit()
    check(calls["start_update"] == 1, "sem widget lido: o bot recruta")
    check(v.am_ceded("construction") is False, "sem widget: o bot constroi")


def test_troopmanager_attempt_research_respects_cession():
    tm = TroopManager.__new__(TroopManager)
    check(tm.research_ceded is False, "padrao de classe para quem nasce por __new__")
    tm.research_ceded = True
    tm.logger = logging.getLogger("test_am_cession.tm")
    tm.wrapper = SimpleNamespace(get_action=lambda **kw: 1 / 0)
    check(tm.attempt_research("axe") is False, "pesquisa cedida nao pode ir ao ferreiro")


for fn in [
    test_widget_three_live_states,
    test_widget_absent_or_broken,
    test_decide_matrix,
    test_transition_messages,
    test_village_recruitment_ceded,
    test_village_resumes_when_manager_expires,
    test_village_no_template_is_bot_work,
    test_village_research_ceded_only,
    test_village_kill_switch_and_missing_widget,
    test_troopmanager_attempt_research_respects_cession,
]:
    try:
        fn()
    except Exception as exc:
        failures.append(f"{fn.__name__} levantou {exc!r}")

if failures:
    print(f"FALHOU ({len(failures)} problema(s)):")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("OK: cessao de fases ao gerente de conta")
