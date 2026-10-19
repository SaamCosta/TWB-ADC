"""
Gerente de conta automático (`core/am_auto.py`, `game/am_auto.py`,
docs/backend.md §8.68, `P-GERENTE-AUTO`).

O que se protege aqui:
- parsers contra recortes verbatim: modelos e linhas de `am_troops`, grupos
  estáticos (com "não classificado" fora da lista) e as opções do widget;
- modelo só é aplicado com "Sem gerência" (ou outro modelo) E o bot sabendo
  que a aldeia não chegou lá; pendência desconhecida não aplica; o mesmo
  modelo não volta antes do `reapply_backoff_hours`;
- reserva do gerente de tropas = reserva do nobre; muda quando o portão muda;
- grupo: entra no do papel, sai dos outros grupos de papel, aldeia não lida e
  papel fora do mapa ficam como estão;
- "dry_run" não grava; os POSTs levam o payload dos formulários do jogo;
  recusa (error_box) não conta como aplicado;
- leitura da conta: grupos página 2 e DEPOIS página 1; tropas sem `page`
  (o `page=-1` fica gravado como preferência do jogador, sondado em 19/10);
- reserva de aldeia fora da página lida = a que o bot gravou.

Rodar: python tests/test_am_auto.py
"""
import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import am_auto  # noqa: E402
from core.extractors import Extractor  # noqa: E402
from game.am_auto import AccountManagerAuto  # noqa: E402

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


def fixture(name):
    with open(os.path.join(ROOT, "tests", "fixtures", name), encoding="utf-8") as fh:
        return fh.read()


TROOPS = fixture("am_troops_br143.html")
GROUPS = fixture("village_groups_br143.html")
WIDGET_ALL = fixture("am_widget_all_active_br143.html")
WIDGET_NONE = fixture("am_widget_no_template_br143.html")

ROLES = {
    "purple_predator_into_off": {"group": "Ataque", "construction": "ADC - OFENSIVA BOT",
                                 "research": "ADC - OFENSIVA", "troops": "ADC - OFENSIVA"},
    "purple_predator_into_def": {"group": "Defesa", "construction": "ADC - DEFENSIVA",
                                 "research": "ADC - DEFENSIVA", "troops": "ADC - DEFENSIVA"},
}
CFG = {"auto_manage": True, "roles": ROLES, "reapply_backoff_hours": 24}
RESERVE = {"wood": 40000, "stone": 50000, "iron": 50000, "pop": 100}
NOW = 1_800_000_000


def test_parsers():
    t = Extractor.account_manager_troops(TROOPS)
    check(t is not None and set(t["templates"]) == {"ADC - OFENSIVA", "ADC - DEFENSIVA", "ADC - TORRE"},
          "modelos de tropa -> %r" % (t and list(t["templates"])))
    off = t["templates"]["ADC - OFENSIVA"]
    check(off["id"] == 3893462 and off["axe"] == 6000 and off["buffer_wood"] == 0, "meta do ADC - OFENSIVA")
    check(t["villages"]["41123"]["axe"] == 6000 and t["villages"]["38409"]["spy"] == 0,
          "linha: meta (a contagem verde/vermelha nao entra)")
    check(t["villages"]["41123"]["buffer_pop"] == 0, "reserva da linha")
    check(Extractor.account_manager_troops("<html></html>") is None, "outra tela -> None")
    g = Extractor.village_groups(GROUPS)
    check(g["groups"] == {"Ataque": 335606, "Defesa": 335607, "Watch Tower": 335608}, "grupos estaticos")
    check(g["villages"]["57580"] == ["Defesa"], "aldeia no grupo")
    check(g["villages"]["81571"] == [], "'nao classificado' nao e grupo")
    o = Extractor.account_manager_widget_options(WIDGET_ALL)
    check(o["construction"]["ADC - OFENSIVA BOT"] == 2108 and o["research"]["ALL"] == 730
          and o["troops"]["ADC - TORRE"] == 3893464, "opcoes do widget -> %r" % (o,))
    check(all(not k.startswith("-") for row in o.values() for k in row), "opcoes de controle ficam de fora")


def widget(construction=False, research=False, troops=False, ctpl="", rtpl="", ttpl=""):
    return {"construction": {"active": construction, "template": ctpl},
            "research": {"active": research, "template": rtpl},
            "troops": {"active": troops, "template": ttpl}}


OPTIONS = Extractor.account_manager_widget_options(WIDGET_ALL)
TEMPLATES = Extractor.account_manager_troops(TROOPS)["templates"]


def actions(w, pending, applied=None, reserve=None, row=None, role="purple_predator_into_off"):
    return am_auto.village_actions(CFG, role, w, OPTIONS, pending, applied, reserve, NOW,
                                   troop_templates=TEMPLATES, troop_row=row)


def test_village_actions():
    zero = {k: 0 for k in am_auto.BUFFER_KEYS}
    a = actions(widget(), {"construction": True, "research": True, "troops": True}, row=zero)
    check([x["phase"] for x in a] == ["construction", "research", "troops"], "sem modelo e pendente: aplica")
    check(a[0]["template_id"] == 2108 and a[1]["template_id"] == 707 and a[2]["template_id"] == 3893462,
          "ids pelo nome -> %r" % [x["template_id"] for x in a])
    check(actions(widget(), {"construction": False, "research": None, "troops": False}, row=zero) == [],
          "cumprido ou desconhecido: nao aplica")
    same = widget(True, True, True, "ADC - OFENSIVA BOT", "ADC - OFENSIVA", "ADC - OFENSIVA")
    check(actions(same, {"construction": True, "research": True, "troops": True}, row=zero) == [],
          "modelo certo ativo: nada")
    other = actions(widget(True, False, False, "ADC - DEFENSIVA"), {"construction": True}, row=zero)
    check(other and other[0]["reason"].startswith("modelo trocado"), "papel trocado: troca o modelo")
    back = {"construction": {"at": NOW - 3600, "template": 2108}}
    check(actions(widget(), {"construction": True}, applied=back, row=zero) == [],
          "mesmo modelo aplicado ha 1 h: espera o backoff")
    back["construction"]["at"] = NOW - 25 * 3600
    check(len(actions(widget(), {"construction": True}, applied=back, row=zero)) == 1, "passou o backoff")
    t = actions(widget(), {"troops": True}, reserve=RESERVE, row=zero)
    check(t and t[0]["buffer"] == {"buffer_wood": 40000, "buffer_stone": 50000, "buffer_iron": 50000,
                                   "buffer_pop": 100} and t[0]["meta"]["axe"] == 6000,
          "tropas com a reserva do nobre e a meta do modelo")
    active = widget(False, False, True, ttpl="ADC - OFENSIVA")
    r = actions(active, {}, reserve=RESERVE, row=zero)
    check(r and r[0]["reason"].startswith("reserva do nobre"), "portao escolheu: grava a reserva")
    held = dict(zero, buffer_wood=40000, buffer_stone=50000, buffer_iron=50000, buffer_pop=100)
    check(actions(active, {}, reserve=RESERVE, row=held) == [], "reserva ja certa: nada")
    r = actions(active, {}, reserve={}, row=held)
    check(r and r[0]["buffer"] == zero, "portao tirou: reserva volta a zero")
    check(am_auto.village_actions(CFG, "basic", widget(), OPTIONS, {"construction": True}, None, None, NOW,
                                  TEMPLATES, zero) == [], "papel fora do mapa: nada")
    check(am_auto.village_actions(CFG, "purple_predator_into_off", None, OPTIONS, {"construction": True},
                                  None, None, NOW, TEMPLATES, zero) == [], "sem widget: nada")


def test_pending_and_mode():
    check(am_auto.construction_pending(["main:20", "farm:30"], {"main": 20, "farm": 29}) is True, "farm 29<30")
    check(am_auto.construction_pending(["main:20"], {"main": 20}) is False, "cumprido")
    check(am_auto.construction_pending(None, {"main": 1}) is None, "sem template: desconhecido")
    off = TEMPLATES["ADC - OFENSIVA"]
    check(am_auto.troops_pending(off, {"axe": 5784, "light": 3000}) is True, "machado abaixo")
    full = {u: v for u, v in off.items() if u != "id" and not u.startswith("buffer_")}
    check(am_auto.troops_pending(off, full) is False, "meta cheia")
    check(am_auto.troops_pending(off, None) is None, "sem contagem")
    check(am_auto.troops_pending(off, {}) is None, "contagem vazia (aldeia sem praca, BBM 002) nao e zero")
    check(am_auto.mode({}) == "off" and am_auto.mode({"auto_manage": "dry_run"}) == "dry_run"
          and am_auto.mode({"auto_manage": True}) == "on", "modos")


def test_group_changes():
    groups = {"Ataque": 335606, "Defesa": 335607, "Watch Tower": 335608, "Outro": 1}
    membership = {"1": [], "2": ["Ataque"], "3": ["Ataque", "Defesa", "Outro"], "4": ["Defesa"]}
    roles = {"1": "purple_predator_into_def", "2": "purple_predator_into_off",
             "3": "purple_predator_into_off", "4": "basic", "5": "purple_predator_into_def"}
    c = am_auto.group_changes(CFG, roles, membership, groups)
    check(c["add"] == {335607: ["1"]}, "sem grupo entra no do papel -> %r" % c["add"])
    check(c["remove"] == {335607: ["3"]}, "sai do grupo do outro papel, 'Outro' fica -> %r" % c["remove"])


class FakeWrapper:
    last_h = "redacted"

    def __init__(self, posts_reply=""):
        self.gets, self.posts = [], []
        self.posts_reply = posts_reply
        self.paid_features = SimpleNamespace(active=lambda n: True)

    def get_url(self, url):
        self.gets.append(url)
        if "am_troops" in url:
            return SimpleNamespace(text=TROOPS)
        if "mode=groups" in url:
            return SimpleNamespace(text=GROUPS)
        return None

    def post_url(self, url, data):
        self.posts.append((url, data))
        return SimpleNamespace(text=self.posts_reply)


def executor(wrapper):
    return AccountManagerAuto(wrapper, clock=lambda: NOW, path=None)


def test_refresh_account_pages():
    w = FakeWrapper()
    ex = executor(w)
    check(ex.refresh_account(CFG, "41123", True), "primeira leitura")
    check(len(w.gets) == 3, "3 GETs -> %r" % w.gets)
    check(w.gets[0].endswith("screen=am_troops"), "tropas sem page (page=-1 fica gravado)")
    check(w.gets[1].endswith("page=1") and w.gets[2].endswith("page=0"), "grupos: pagina 2 e depois a 1")
    check(ex.account["troop_units"] == ["axe", "catapult", "heavy", "light", "ram", "spear", "spy", "sword"],
          "unidades do formulario = colunas da lista")
    check(not ex.refresh_account(CFG, "41123", True), "dentro da validade nao rele")
    ex.applied = {"41123": {"construction": {"at": NOW, "template": 2108}}}
    ex.refresh_account(CFG, "41123", False)
    check(ex.refresh_account(CFG, "41123", True), "gerente voltou: rele na hora")
    check(ex.applied == {}, "renovacao zera a trava de reaplicacao")


def test_executor_posts_and_dry_run():
    w = FakeWrapper()
    ex = executor(w)
    ex.refresh_account(CFG, "41123", True)
    pending = {"construction": True, "research": False, "troops": True}
    dry = dict(CFG, auto_manage="dry_run")
    check(ex.run_village(dry, "999", "purple_predator_into_off", widget(), OPTIONS, pending, RESERVE) == []
          and w.posts == [], "dry_run nao grava")
    done = ex.run_village(CFG, "999", "purple_predator_into_off", widget(), OPTIONS, pending, RESERVE)
    check([d["phase"] for d in done] == ["construction", "troops"], "aplicou construcao e tropas")
    url, data = w.posts[0]
    check("screen=am_village&action=village_mass" in url and ("action", "apply") in data
          and ("template", "2108") in data and ("villages[]", "999") in data, "payload de construcao")
    url, data = w.posts[1]
    d = dict(data)
    check("screen=am_troops&action=save_village" in url and d["axe"] == "6000" and d["template_id"] == "3893462"
          and d["buffer_stone"] == "50000" and d["edit[]"] == "999" and "archer" not in d,
          "payload de tropas -> %r" % (data,))
    check(ex.troop_row("999")["buffer_iron"] == 50000, "aldeia fora da pagina: vale a reserva gravada")
    check(ex.applied["999"]["construction"]["template"] == 2108, "aplicado registrado")
    w2 = FakeWrapper(posts_reply='<div class="error_box">Ação inválida</div>')
    ex2 = executor(w2)
    ex2.refresh_account(CFG, "41123", True)
    check(ex2.run_village(CFG, "999", "purple_predator_into_off", widget(), OPTIONS,
                          {"construction": True}, RESERVE) == [] and not ex2.applied,
          "recusa do jogo nao conta como aplicado")


def test_sync_groups():
    w = FakeWrapper(posts_reply="<html></html>")
    ex = executor(w)
    ex.refresh_account(CFG, "41123", True)
    roles = {"57580": "purple_predator_into_def", "81571": "purple_predator_into_off",
             "74966": "basic"}
    check(ex.sync_groups(dict(CFG, auto_manage="dry_run"), roles, "41123") == 0 and not w.posts,
          "dry_run nao grava grupo")
    check(ex.sync_groups(CFG, roles, "41123") == 1, "um POST: 81571 entra em Ataque")
    url, data = w.posts[0]
    check("action=bulk_edit_villages&mode=groups&type=static" in url
          and ("village_ids[]", "81571") in data and ("selected_group", "335606") in data
          and ("add_to_group", "Adicionar") in data, "payload de grupo -> %r" % (data,))
    check(ex.account["membership"]["81571"] == ["Ataque"], "membresia atualizada")
    check(ex.sync_groups(CFG, roles, "41123") == 0, "segunda passada: nada")


def test_village_phase():
    from game.village import Village
    calls = []
    v = Village.__new__(Village)
    v.village_id = "41123"
    v.config = {"account_manager": dict(CFG), "villages": {"41123": {"building": "purple_predator_into_off"}}}
    v.am_auto = SimpleNamespace(troop_templates=lambda: TEMPLATES,
                                run_village=lambda *a: calls.append(a))
    v.wrapper = SimpleNamespace(paid_features=SimpleNamespace(active=lambda n: True))
    v.am_widget, v.am_widget_options = widget(), OPTIONS
    v.builder = SimpleNamespace(raw_template=["main:20", "statue:1"], levels={"main": 20, "statue": 0})
    v.knight_enabled = False
    v.units = SimpleNamespace(research_pending=None, total_troops={"axe": 10})
    v.snobman = None
    v._noble_reserve_logged = {}
    v.logger = None
    v.run_am_auto()
    check(len(calls) == 1, "fase roda com gerente ativo e papel no mapa")
    pending = calls[0][5]
    check(pending == {"construction": False, "research": None, "troops": True},
          "estatua fora (mundo sem paladino), pesquisa desconhecida, machado abaixo -> %r" % (pending,))
    v.config["account_manager"]["auto_manage"] = False
    v.run_am_auto()
    v.config["account_manager"]["auto_manage"] = True
    v.wrapper.paid_features.active = lambda n: False
    v.run_am_auto()
    check(len(calls) == 1, "desligado ou gerente vencido: nao chama")


for fn in [
    test_village_phase,
    test_parsers,
    test_village_actions,
    test_pending_and_mode,
    test_group_changes,
    test_refresh_account_pages,
    test_executor_posts_and_dry_run,
    test_sync_groups,
]:
    try:
        fn()
    except Exception as exc:
        import traceback
        traceback.print_exc()
        failures.append(f"{fn.__name__} levantou {exc!r}")

if failures:
    print(f"FALHOU ({len(failures)} problema(s)):")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("OK: gerente de conta automatico")
