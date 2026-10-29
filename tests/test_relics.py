"""
Relíquias, Fase 1 (docs/backend.md §8.75): parsers do `Extractor`, a conta
de `core/relics.py` e o custo em GETs do `game/relic_manager.py`.

Fixtures verbatim do br143 de 29/10/2026 (anonimizadas: jogador, paladino,
`h`, nomes de terceiros), recortadas de `cache/debug/relics/`:
  relic_system_br143.html, relic_overview_br143.html,
  overview_effects_relics_br143.html (BBM 001), report_list_other_br143.html.

Os números esperados são os medidos na Fase 0 (§8.74): 5 equipadas cobrindo 8
aldeias, quartel 25% em 5 delas ("+5% aplicado, +5% descartado"), vagas 5/8
com as próximas em 70 e 90 aldeias, achados em 27/10 00:43 e 02:07, 28/10
00:01 e 01:29, 29/10 01:14. Sem rede, e sem tocar o `cache/relics.json` real.

Rodar: python tests/test_relics.py
"""
import datetime
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import relics as R  # noqa: E402
from core.extractors import Extractor  # noqa: E402
from game import relic_manager as RM  # noqa: E402

FIX = os.path.join(ROOT, "tests", "fixtures")
failures = []

# Coordenadas das aldeias da conta em volta do aglomerado BBM 001-011 (K35),
# do mapa público, mais as duas anfitriãs das inativas.
COORDS = {
    "34597": (576, 316), "37318": (577, 315), "38363": (586, 313), "38409": (578, 305),
    "38997": (580, 309), "39292": (579, 308), "39472": (588, 309), "39975": (583, 312),
    "40314": (571, 308), "41114": (584, 309), "41123": (577, 306), "41140": (585, 304),
    "41283": (576, 309), "42134": (571, 299), "44620": (586, 308), "44674": (587, 307),
    "44683": (579, 304), "74689": (578, 306), "74690": (582, 304), "69630": (531, 263),
    "88755": (605, 253),
}
COVERED = ["38409", "38997", "39292", "41123", "41283", "44683", "74689", "74690"]
SERVER_NOW = datetime.datetime(2026, 10, 29, 1, 14, 30)


def check(cond, msg):
    if not cond:
        failures.append(msg)


def fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return fh.read()


def inventory():
    return Extractor.relic_inventory(fixture("relic_system_br143.html"))


def overview():
    return Extractor.relic_overview(fixture("relic_overview_br143.html"))


def board():
    return Extractor.village_bonus_board(fixture("overview_effects_relics_br143.html"))


def test_inventario():
    inv = inventory()
    check(inv is not None, "inventário não lido")
    check(len(inv["relics"]) == 10, "esperava 10 relíquias, veio %d" % len(inv["relics"]))
    check(inv["village_id"] == "44683" and inv["can_equip"] is True
          and inv["loyalty_locked"] is False and inv["is_new_system"] is True
          and inv["materials"] == [] and inv["pp_reroll_cost"] == 100,
          "argumentos do init: %r" % {k: v for k, v in inv.items() if k != "relics"})
    sela = next(r for r in inv["relics"] if r["id"] == "310487")
    check(sela["main"]["key"] == "Estábulo nos custos de recrutamento"
          and sela["main"]["value"] == 8.0 and sela["main"]["sign"] == "-", sela["main"])
    check([s["key"] for s in sela["subs"]] == ["Aríete: poder de ataque",
                                                "Cavalaria leve: poder de defesa"], sela["subs"])
    check(sela["removal_cooldown_sec"] == 23 * 3600 + 40 * 60 + 33, "cooldown da sela")
    check(sela["village_id"] == "44683" and sela["range"] == 3, "anfitriã/alcance da sela")
    alabarda = next(r for r in inv["relics"] if r["id"] == "157444")
    check(alabarda["inactive_sec"] == 18 * 3600 + 8 * 60 + 50, "inativa em segundos")
    check(alabarda["locked_state"].startswith("Bloqueado"), "trava de lealdade")
    parked = [r for r in inv["relics"] if r["village_id"] is None]
    check(len(parked) == 3, "3 paradas no inventário")
    check("jogador" not in repr(inv["relics"]), "discovered_by_name não pode ir para o estado")


def test_inventario_quebrado_e_none():
    check(Extractor.relic_inventory(None) is None, "None de rede")
    check(Extractor.relic_inventory("<html>login</html>") is None, "página sem o init")
    cut = fixture("relic_system_br143.html").split("44683,\n        true,")[0] + "44683);"
    check(Extractor.relic_inventory(cut) is None, "init com argumentos faltando não pode passar")


def test_visao_geral():
    ov = overview()
    check(ov is not None, "visão geral não lida")
    check((ov["slots_used"], ov["slots_free"]) == (5, 3), "vagas %r" % ((ov["slots_used"], ov["slots_free"]),))
    check(ov["next_thresholds"] == [70, 90], "limiares %r" % ov["next_thresholds"])
    hosts = sorted(e["host_id"] for e in ov["equipped"])
    check(hosts == ["38409", "39292", "41123", "44683", "74689"], "anfitriãs %r" % hosts)
    sela = next(e for e in ov["equipped"] if e["host_id"] == "44683")
    check(sela["relic_id"] == "310487" and sorted(sela["affected"]) == ["38409", "41123", "74689", "74690"],
          "lista da sela %r" % sela)
    check("44683" not in sela["affected"], "a lista 'Outras aldeias' não inclui a anfitriã")
    check([(i["host_id"], i["remaining_sec"]) for i in ov["inactive"]]
          == [("69630", 18 * 3600 + 7 * 60 + 15), ("88755", 23 * 3600 + 23 * 60 + 43)],
          "inativas %r" % ov["inactive"])
    check(ov["coords"].get("74690") == (582, 304), "coordenada da âncora")
    check(Extractor.relic_overview("<html></html>") is None, "sem relic_slots = None")


def test_quadro_da_aldeia():
    b = board()
    check(b is not None, "quadro não lido")
    check(len(b["relics"]) == 5, "5 relíquias alcançam a BBM 001")
    check(sorted(r["host_id"] for r in b["relics"]) == ["38409", "39292", "41123", "44683", "74689"],
          "anfitriãs no quadro %r" % b["relics"])
    quartel = next(x for x in b["benefits"] if x["key"] == "Quartel na velocidade de recrutamento")
    check(quartel["total"] == 20 and quartel["applied"] == 5 and quartel["discarded"] == 5, quartel)
    check([s["value"] for s in quartel["sources"] if s["relic"]] == [10, 5, 10], quartel["sources"])
    check(sum(1 for s in quartel["sources"] if s["partial"]) == 1, "uma contribuição parcial")
    ferro = next(x for x in b["benefits"] if x["key"] == "na produção de ferro")
    check(ferro["total"] == 55, "ferro 55%")
    check([(s["value"], s["relic"]) for s in ferro["sources"]] == [(30, False), (10, True), (15, False)],
          "item e paladino não são relíquia: %r" % ferro["sources"])
    check(ferro["applied"] is None and ferro["discarded"] is None, "sem detalhamento = None")
    check(Extractor.village_bonus_board("<div>outra tela</div>") is None, "sem widget = None")
    empty = '<div id="show_effects" class="vis"><table><tr><td>x</td></tr></table>'
    check(Extractor.village_bonus_board(empty) == {"relics": [], "benefits": []},
          "widget sem relíquia é legítimo, não None")


def test_cobertura_reproduz_o_jogo():
    inv, ov = inventory(), overview()
    state = R.build_state(inv, ov, COORDS, 1000.0)
    check(state["coverage_check"] == {"divergences": [], "unplaced": []},
          "divergências %r" % state["coverage_check"])
    check(sorted(state["villages"]) == COVERED, "aldeias cobertas %r" % sorted(state["villages"]))
    check(state["counts"] == {"equipped": 5, "inactive": 2, "inventory": 3}, state["counts"])
    check(state["slots"] == {"used": 5, "free": 3, "total": 8, "next_thresholds": [70, 90]}, state["slots"])
    capped = sorted(v for v, a in state["villages"].items()
                    if a.get("Quartel na velocidade de recrutamento", {}).get("discarded") == 5)
    check(capped == ["38409", "39292", "41123", "44683", "74689"], "quartel 25%% em 5 aldeias: %r" % capped)
    check(state["totals"]["discarded_pct"] == 25.0, state["totals"])
    sela = next(r for r in state["relics"] if r["id"] == "310487")
    check(sela["removable_at"] == 1000 + sela["removal_cooldown_sec"], "removable_at absoluto")
    check(sela["covers"] == ["38409", "41123", "44683", "74689", "74690"], sela["covers"])


def test_cobertura_divergente_e_sem_coordenada():
    inv, ov = inventory(), overview()
    moved = dict(COORDS, **{"74690": (583, 304)})  # 4,0 da sela (alcance 3)
    check_ = R.build_state(inv, ov, moved, 0)["coverage_check"]
    check([(d["vid"], d["kind"]) for d in check_["divergences"]] == [("74690", "only_game")],
          "divergência esperada: %r" % check_)
    missing = {k: v for k, v in COORDS.items() if k != "74690"}
    check_ = R.build_state(inv, ov, missing, 0)["coverage_check"]
    check(check_["divergences"] == [] and check_["unplaced"] == ["74690"],
          "sem coordenada não é divergência: %r" % check_)


def test_quadro_confere_com_o_calculo():
    inv = inventory()
    active = R.active_relics(inv)
    computed = R.coverage(active, COORDS)
    attrs = R.village_attributes(active, computed)
    check(R.board_check("41123", board(), active, computed, attrs) == [], "BBM 001 bate")
    without = [r for r in active if r["id"] != "310487"]
    comp2 = R.coverage(without, COORDS)
    msgs = R.board_check("41123", board(), without, comp2, R.village_attributes(without, comp2))
    check(any("relíquias que alcançam" in m for m in msgs), "falta de relíquia tem que aparecer: %r" % msgs)
    check(any(m.startswith("Aríete: poder de ataque") for m in msgs), "e a soma do atributo também")


def test_achados_por_dia():
    rows = Extractor.report_list_rows(fixture("report_list_other_br143.html"))
    check(len(rows) == 44, "44 linhas, veio %d" % len(rows))
    days = R.found_by_day(rows, SERVER_NOW)
    check(sorted(days) == ["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29"], sorted(days))
    check([days[d]["found"] for d in sorted(days)] == [0, 2, 2, 1],
          "encontradas por dia %r" % [(d, days[d]["found"]) for d in sorted(days)])
    check(all(e["complete"] for e in days.values()), "44 < 50: a categoria inteira está na página")
    check(sum(e["acquired"] for e in days.values()) == 3 and
          sum(e["unlocked"] for e in days.values()) == 4, "adquiridas 3, transferidas 4")
    full = R.found_by_day(rows, SERVER_NOW, page_size=44)
    check(not full["2026-10-26"]["complete"] and full["2026-10-29"]["complete"],
          "página cheia: o dia mais antigo pode seguir na próxima")
    renamed = [dict(r, title="minha relíquia") if r["id"] == "225467212" else r for r in rows]
    check(R.found_by_day(renamed, SERVER_NOW)["2026-10-29"]["renamed"] == 1, "renomeada não é achado")
    odd = [dict(r, received="xyz. 29, 01:14") if r["id"] == "225467212" else r for r in rows]
    check(not any(e["complete"] for e in R.found_by_day(odd, SERVER_NOW).values()),
          "relíquia sem data legível deixa os dias incompletos")
    check(R.received_date("dez. 31, 23:00", SERVER_NOW) == datetime.date(2025, 12, 31),
          "mês à frente do servidor é do ano anterior")


def test_merge_dos_dias():
    hist = {"2026-10-27": {"found": 2, "complete": True}}
    out = R.merge_found(hist, {"2026-10-27": {"found": 1, "complete": False},
                               "2026-10-29": {"found": 1, "complete": False}},
                        today=datetime.date(2026, 10, 29))
    check(out["2026-10-27"]["found"] == 2, "incompleto não sobrescreve completo")
    check(out["2026-10-29"]["found"] == 1, "dia novo entra")
    old = R.merge_found({"2026-10-01": {"found": 2, "complete": True}}, {},
                        today=datetime.date(2026, 10, 29))
    check(old == {}, "fora da janela de 14 dias sai")


class FakeWrapper:
    def __init__(self):
        self.urls = []
        self.pages = {
            "screen=relic_system&mode=overview": fixture("relic_overview_br143.html"),
            "screen=report&mode=other": fixture("report_list_other_br143.html"),
            "screen=relic_system": fixture("relic_system_br143.html"),
        }

    def get_url(self, url):
        self.urls.append(url)
        for key, page in self.pages.items():
            if url.endswith(key):
                return type("Res", (), {"text": page})()
        return None


def _manager(tmp):
    RM.CACHE_PATH = os.path.join(tmp, "relics.json")
    RM._coords_from_disk = lambda own_ids: dict(COORDS)
    wrapper = FakeWrapper()
    return RM.RelicManager(wrapper=wrapper, config={"relics": {"enabled": True}}), wrapper


def test_custo_em_gets_do_leitor():
    tmp = tempfile.mkdtemp()
    man, wrapper = _manager(tmp)
    own = list(COORDS)
    check(man.run("41123", own_ids=own) is True, "primeira leitura")
    check(len(wrapper.urls) == 3, "primeira: inventário, visão geral e relatórios (%r)" % wrapper.urls)
    check(man.state["found"]["2026-10-29"]["found"] == 1, "contador do dia")
    check(os.path.exists(RM.CACHE_PATH), "estado gravado no caminho do teste")
    wrapper.urls.clear()
    man.run("41123", own_ids=own)
    check(len(wrapper.urls) == 1, "nada mudou: 1 GET (%r)" % wrapper.urls)
    wrapper.urls.clear()
    man.note_report("ReportAttack", "1")
    check(man.pending is None, "ataque não é gatilho")
    man.note_report("ReportRelicAcquired", "225467212")
    check(man.pending and "ReportRelicAcquired" in man.pending, "relíquia é gatilho")
    man.run("41123", own_ids=own, reason=man.pending)
    check(len(wrapper.urls) == 2 and wrapper.urls[1].endswith("mode=other"),
          "achado: inventário e relatórios, sem visão geral (%r)" % wrapper.urls)
    check(man.pending is None, "gatilho consumido")
    wrapper.urls.clear()
    man.run("41123", own_ids=own + ["99999"])
    check(len(wrapper.urls) == 2 and wrapper.urls[1].endswith("mode=overview"),
          "aldeia nova: relê a visão geral (vaga) (%r)" % wrapper.urls)


def test_leitor_nao_apaga_estado_com_leitura_ruim():
    tmp = tempfile.mkdtemp()
    man, wrapper = _manager(tmp)
    man.run("41123", own_ids=list(COORDS))
    before = man.state
    wrapper.pages = {}
    check(man.run("41123", own_ids=list(COORDS)) is False, "sem resposta = False")
    check(man.state is before, "estado anterior fica")
    wrapper.pages = {"screen=relic_system": "<html>login</html>"}
    check(man.run("41123", own_ids=list(COORDS)) is False, "login = False")


def test_quadro_divergente_pede_releitura():
    tmp = tempfile.mkdtemp()
    man, wrapper = _manager(tmp)
    man.run("41123", own_ids=list(COORDS))
    check(man.check_board("41123", board()) == [], "quadro que bate")
    check(man.state["boards"]["41123"]["ok"] is True, "resultado gravado")
    man.state["fetched_at"] -= 3600
    altered = board()
    altered["relics"] = altered["relics"][1:]
    msgs = man.check_board("41123", altered)
    check(msgs and man.pending, "estado de 1 h e quadro diverge: releitura pedida")
    wrapper.urls.clear()
    man.run("41123", own_ids=list(COORDS), reason=man.pending)
    check(man.state["boards"]["41123"]["ok"] is False, "segue sem bater depois de reler")
    check(not man._board_mismatch, "lista de reconferência zerada")
    man.pending = None
    man.check_board("41123", altered)
    check(man.pending is None, "estado recente: só avisa, não relê de novo")
    man.state["fetched_at"] -= 7200
    man._last_board_reread = 0
    man.check_board("41123", altered)
    check(man.pending is None, "a mesma divergência que sobreviveu à releitura não relê de novo")


def test_visao_geral_sem_vagas_e_markup_novo():
    page = '<div id="page_relic_overview"><div id="relic_slots"><p>novo</p></div>RelicSystem.Overview.init'
    check(Extractor.relic_overview(page) is None, "relic_slots sem nenhuma vaga = markup novo")


if __name__ == "__main__":
    import logging
    logging.disable(logging.CRITICAL)
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except Exception as exc:
                import traceback
                traceback.print_exc()
                failures.append("%s levantou %r" % (name, exc))
    if failures:
        print("FALHAS (%d):" % len(failures))
        for f in failures:
            print(" -", f)
        sys.exit(1)
    print("OK: relíquias (inventário, visão geral, quadro, cobertura, teto, achados, custo)")
