"""
P-OVERVIEW-SOMBRA (docs/backend.md §9, item 20a): o modo sombra das
releituras da visao geral.

O que se protege aqui:
- `game_data` sai tanto de HTML (`updateGameData`) quanto do envelope JSON do
  `TribalWars-Ajax` (setimo padrao), e JSON sem `game_data` nao inventa nada;
- a comparacao separa "igual", "so producao do intervalo" e "diverge", e o
  esperado respeita o teto do armazem;
- o WebWrapper guarda o ultimo game_data POR ALDEIA a partir do `game_data`,
  nao da URL, e a captura "antes" nao e sobrescrita pelo GET de releitura;
- a comparacao so vale quando a releitura veio mesmo da visao geral;
- wrapper sem suporte (ou MagicMock) vira no-op, e nada disso levanta.

Fixture: o `game_data` e verbatim de cache/debug/ally_index.html (br143, BBM
020, capturado pela sessao do bot).

Rodar: python tests/test_overview_shadow.py
"""
import json
import os
import shutil
import sys
import tempfile
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import game_data_shadow as gds  # noqa: E402
from core.request import WebWrapper  # noqa: E402

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


GAME_DATA = (
    '{"player":{"id":5955651,"name":"sccj","ally":"987","villages":"30","incomings":"0",'
    '"points":"117088"},"features":{"Premium":{"possible":true,"active":true}},'
    '"village":{"id":32056,"name":"BBM 020","display_name":"BBM 020 (574|317) K35",'
    '"wood":10120,"wood_prod":0.41398226673385,"wood_float":10120.07335360709,'
    '"stone":10252,"stone_prod":0.41398226673385,"stone_float":10252.07335360709,'
    '"iron":3265,"iron_prod":0.30600896678423,"iron_float":3264.5361288123463,'
    '"pop":5987,"pop_max":6737,"x":574,"y":317,"trader_away":0,"storage_max":18037,'
    '"player_id":5955651,"modifications":0,"points":2411,"last_res_tick":1789884583000,'
    '"coord":"574|317","is_farm_upgradable":true},"csrf":"0fd18c93","world":"br143",'
    '"screen":"ally","mode":null,"time_generated":1789884583710}'
)
HTML = ('<html><script>TribalWars.updateGameData(%s);</script></html>' % GAME_DATA)


def game_data(**village):
    gd = json.loads(GAME_DATA)
    for key, value in village.items():
        if key in ("screen", "time_generated"):
            gd[key] = value
        else:
            gd["village"][key] = value
    return gd


def html(gd):
    return '<html><script>TribalWars.updateGameData(%s);</script></html>' % json.dumps(gd)


class FakeResponse:
    def __init__(self, text, url, content_type="text/html"):
        self.text = text
        self.url = url
        self.headers = {"content-type": content_type}


def test_extract_html_and_json():
    gd = gds.extract_game_data(HTML)
    check(gd and gd["village"]["id"] == 32056, "HTML verbatim nao extraiu game_data")
    envelope = json.dumps({"response": {"success": True}, "game_data": json.loads(GAME_DATA)})
    gd = gds.extract_game_data(envelope)
    check(gd and gd["village"]["name"] == "BBM 020", "envelope TribalWars-Ajax nao extraiu game_data")
    check(gds.extract_game_data('{"inventory": [], "data": {}}') is None,
          "JSON sem game_data devolveu algo")
    check(gds.extract_game_data("<html>login</html>") is None, "pagina sem game_data devolveu algo")
    check(gds.extract_game_data(None) is None, "None devolveu algo")


def test_snapshot_uses_float_and_server_clock():
    snap = gds.snapshot(json.loads(GAME_DATA))
    check(snap["village_id"] == "32056", "village_id deveria ser str do game_data")
    check(abs(snap["iron"] - 3264.536) < 0.01, "deveria usar iron_float, nao o inteiro")
    check(abs(snap["at"] - 1789884583.71) < 0.01, "at deveria vir de time_generated")
    check(snap["screen"] == "ally", "screen perdida")
    check(gds.snapshot({"village": {"id": 1}}) is None, "snapshot sem recurso deveria ser None")


def test_compare_verdicts():
    base = gds.snapshot(game_data(screen="main"))
    same = gds.snapshot(game_data(screen="overview"))
    r = gds.compare(base, same)
    check(r["verdict"] == "igual", "mesmo instante deveria ser igual, veio %s" % r["verdict"])

    # 1000 s depois, so producao: wood_prod 0.414/s -> +414.
    t = 1789884583710 + 1000 * 1000
    produced = gds.snapshot(game_data(
        screen="overview", time_generated=t,
        wood_float=10120.07 + 413.98, stone_float=10252.07 + 413.98,
        iron_float=3264.54 + 306.01))
    r = gds.compare(base, produced)
    check(r["verdict"] == "producao", "so producao deveria ser 'producao', veio %s" % r["verdict"])
    check(r["age_sec"] == 1000.0, "idade errada: %s" % r["age_sec"])

    # Recrutamento gastou 500 de ferro e subiu a pop: a resposta anterior nao sabia.
    spent = gds.snapshot(game_data(screen="overview", iron_float=2764.54, pop=6087))
    r = gds.compare(base, spent)
    check(r["verdict"] == "diverge", "gasto deveria divergir")
    check(r["resources"]["iron"]["residual"] == -500.0,
          "residual do ferro deveria ser -500, veio %s" % r["resources"]["iron"]["residual"])
    check(r["other"].get("pop") == [5987, 6087], "mudanca de pop nao registrada")

    # Armazem cheio: producao nao passa do teto.
    full = gds.snapshot(game_data(screen="main", wood_float=18037.0))
    later = gds.snapshot(game_data(screen="overview", time_generated=t, wood_float=18037.0))
    r = gds.compare(full, later)
    check(r["resources"]["wood"]["residual"] == 0.0, "teto do armazem ignorado")

    other = gds.snapshot(game_data(id=99))
    check(gds.compare(other, same) is None, "aldeias diferentes deveriam dar None")
    check(gds.compare(None, same) is None, "sem anterior deveria dar None")


def test_wrapper_keeps_per_village_and_before_survives_reread():
    tmp = tempfile.mkdtemp()
    try:
        path = os.path.join(tmp, "shadow", "overview.jsonl")
        w = WebWrapper("https://x/", endpoint="https://x/")
        # Resposta de outra tela, da aldeia 32056, depois de gastar ferro.
        w.post_process(FakeResponse(
            html(game_data(screen="train", iron_float=2764.54)),
            "https://x/game.php?village=32056&screen=train"))
        check("32056" in w.game_data_seen, "wrapper nao guardou o game_data da aldeia")
        prev = gds.before(w, 32056)
        check(prev["screen"] == "train", "before deveria trazer a tela de origem")

        # A releitura da visao geral sobrescreve o registro do wrapper...
        w.post_process(FakeResponse(
            html(game_data(screen="overview", iron_float=2764.54)),
            "https://x/game.php?village=32056&screen=overview"))
        check(prev["screen"] == "train", "before foi alterado pelo GET seguinte (copia rasa?)")
        # ...e a comparacao usa o anterior capturado antes dela.
        r = gds.record_reread(w, 32056, "update_totals", prev, path=path)
        check(r and r["verdict"] == "igual", "train -> overview sem mudanca deveria ser igual")
        with open(path, encoding="utf-8") as fh:
            lines = [json.loads(line) for line in fh]
        check(len(lines) == 1 and lines[0]["point"] == "update_totals"
              and lines[0]["source_screen"] == "train", "jsonl sem a linha esperada")

        # Resposta JSON com envelope Ajax tambem alimenta o registro.
        envelope = json.dumps({"response": {}, "game_data": game_data(screen="api")})
        w.post_process(FakeResponse(envelope, "https://x/game.php?screen=api",
                                    content_type="application/json"))
        check(w.game_data_seen["32056"]["ajax"] is True, "resposta JSON nao marcada como ajax")

        # Releitura que nao veio da visao geral (ex.: login) nao compara.
        check(gds.record_reread(w, 32056, "market", prev, path=path) is None,
              "comparou com um registro que nao e da visao geral")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_noop_without_support():
    check(gds.before(object(), 1) is None, "wrapper sem game_data_seen deveria dar None")
    check(gds.before(mock.MagicMock(), 1) is None, "MagicMock deveria virar no-op")
    check(gds.record_reread(mock.MagicMock(), 1, "init", None) is None,
          "record_reread com MagicMock deveria ser no-op")
    w = WebWrapper("https://x/", endpoint="https://x/")
    w.post_process(FakeResponse("<html>sem game data</html>", "https://x/"))
    check(w.game_data_seen == {}, "resposta sem game_data nao deveria registrar nada")
    other = WebWrapper("https://x/", endpoint="https://x/")
    check(other.game_data_seen is not w.game_data_seen, "game_data_seen compartilhado entre instancias")


for fn in [
    test_extract_html_and_json,
    test_snapshot_uses_float_and_server_clock,
    test_compare_verdicts,
    test_wrapper_keeps_per_village_and_before_survives_reread,
    test_noop_without_support,
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
print("OK: sombra da visao geral")
