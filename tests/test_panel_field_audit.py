"""
Os cinco achados de gravidade alta da auditoria de campo do painel
(docs/frontend.md §2.8, 2026-09-23): o painel contradizia o jogo.

- W1/W4: ataque chegando e "0 sob ataque". `core/account_pulse.py` guarda o
  `player.incomings` do `game_data` de toda resposta; o painel mostra; aldeia
  gerenciada sem snapshot entra em "dados incompletos" em vez de sumir.
- W6: `/conquest` dizia "nenhuma atenção" com o último nobre vencido há 2h38,
  e o contador e a lista de atenção eram duas cópias divergentes da regra.
- W7: coberto em `tests/test_cycle_reader.py` (ciclo sem aldeia fora das
  medianas).
- W10: `/farmscores` punha aldeias nossas (ex-farms conquistados) em 1º e 4º.
- W11: `pending` com chegada vencida contado como agendamento vivo.

Fixture do `game_data`: o mesmo recorte verbatim de
cache/debug/ally_index.html (br143) que `tests/test_overview_shadow.py` usa.

Rodar: python tests/test_panel_field_audit.py
"""
import json
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import account_pulse  # noqa: E402
from core.request import WebWrapper  # noqa: E402

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


GAME_DATA = (
    '{"player":{"id":5955651,"name":"sccj","ally":"987","villages":"30","incomings":"0",'
    '"supports":"0","points":"117088"},"features":{"Premium":{"possible":true,"active":true}},'
    '"village":{"id":32056,"name":"BBM 020","display_name":"BBM 020 (574|317) K35",'
    '"wood":10120,"wood_prod":0.41398226673385,"wood_float":10120.07335360709,'
    '"stone":10252,"stone_prod":0.41398226673385,"stone_float":10252.07335360709,'
    '"iron":3265,"iron_prod":0.30600896678423,"iron_float":3264.5361288123463,'
    '"pop":5987,"pop_max":6737,"x":574,"y":317,"trader_away":0,"storage_max":18037,'
    '"player_id":5955651,"modifications":0,"points":2411,"last_res_tick":1789884583000,'
    '"coord":"574|317","is_farm_upgradable":true},"csrf":"0fd18c93","world":"br143",'
    '"screen":"ally","mode":null,"time_generated":1789884583710}'
)


def gd(**player):
    data = json.loads(GAME_DATA)
    data["player"].update(player)
    return data


class FakeResponse:
    def __init__(self, text, url="https://x/game.php", content_type="text/html"):
        self.text = text
        self.url = url
        self.headers = {"content-type": content_type}


class Clock:
    def __init__(self, t=1789884600.0):
        self.t = t

    def __call__(self):
        return self.t


# ---------------------------------------------------------------- W1 / W4

def test_extract_verbatim_and_failure_is_not_zero():
    p = account_pulse.extract(json.loads(GAME_DATA))
    check(p and p["incomings"] == 0 and p["supports"] == 0 and p["villages"] == 30,
          "recorte verbatim: %r" % p)
    check(abs(p["at"] - 1789884583.71) < 0.01, "at vem do time_generated do servidor")
    check(account_pulse.extract(gd(incomings="3"))["incomings"] == 3, "string '3' vira 3")
    # Valor de falha distinguivel (6o padrao, corolario): ilegivel nao e zero.
    check(account_pulse.extract(gd(incomings="")) is None, "incomings vazio nao vira 0")
    check(account_pulse.extract(gd(incomings="x")) is None, "incomings lixo nao vira 0")
    check(account_pulse.extract({"village": {"id": 1}}) is None, "sem player")
    check(account_pulse.extract(None) is None, "None")


def test_unarmed_never_writes_armed_writes_on_change():
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "pulse.json")
    try:
        account_pulse.disarm()
        clock = Clock()
        pulse = account_pulse.AccountPulse(path=path, clock=clock)
        check(pulse.observe(json.loads(GAME_DATA)) is False and not os.path.exists(path),
              "desarmado nao grava (a suite nao pode reescrever o arquivo do painel)")

        account_pulse.arm()
        check(pulse.observe(json.loads(GAME_DATA)) is True, "armado grava na primeira")
        first = json.load(open(path, encoding="utf-8"))
        check(first["incomings"] == 0 and first["changed_at"] == first["at"], "registro: %r" % first)

        clock.t += 10
        check(pulse.observe(json.loads(GAME_DATA)) is False, "igual e dentro de 60 s: nao regrava")
        clock.t += 5
        check(pulse.observe(gd(incomings="2")) is True, "mudou: grava na hora")
        rec = json.load(open(path, encoding="utf-8"))
        check(rec["incomings"] == 2, "gravou o 2")

        clock.t += account_pulse.WRITE_EVERY + 1
        check(pulse.observe(gd(incomings="2")) is True, "igual depois de 60 s: regrava a idade")
        rec2 = json.load(open(path, encoding="utf-8"))
        check(rec2["changed_at"] == rec["changed_at"],
              "changed_at so anda quando o numero muda: %r x %r" % (rec2["changed_at"], rec["changed_at"]))

        # O wrapper alimenta o pulso em todo post_process.
        w = WebWrapper("https://x/", endpoint="https://x/")
        w.account_pulse = account_pulse.AccountPulse(path=path, clock=Clock(1789900000.0))
        w.post_process(FakeResponse(
            '<html><script>TribalWars.updateGameData(%s);</script></html>'
            % json.dumps(gd(incomings="5"))))
        check(json.load(open(path, encoding="utf-8"))["incomings"] == 5,
              "post_process nao alimentou o pulso")
        other = WebWrapper("https://x/", endpoint="https://x/")
        check(other.account_pulse is not w.account_pulse, "pulso compartilhado entre wrappers")
    finally:
        account_pulse.disarm()
        shutil.rmtree(tmp, ignore_errors=True)


def test_read_absent_bad_and_age():
    tmp = tempfile.mkdtemp()
    try:
        path = os.path.join(tmp, "pulse.json")
        check(account_pulse.read(path) == {"available": False}, "ausente = nao se sabe")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{meio")
        check(account_pulse.read(path) == {"available": False}, "JSON ruim = nao se sabe")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"incomings": 4, "supports": 1, "at": 1000.0}, fh)
        out = account_pulse.read(path, now=1000.0 + 125)
        check(out["available"] and out["incomings"] == 4 and out["age_seconds"] == 125,
              "leitura: %r" % out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _client():
    import webmanager.server as srv
    srv.app.jinja_env.auto_reload = True
    srv.app.jinja_env.cache = {}
    return srv


def test_pages_show_pulse_and_missing_snapshot():
    srv = _client()
    base = {"attacks": {}, "villages": {}, "reports": {}, "status": False,
            "config": {"villages": {}}, "gather": {"enabled": 0, "total": 0},
            "bot": {"100": {"public": {"name": "BBM 100"}, "resources": {"wood": 1},
                            "last_run": int(time.time())}}}
    cases = {
        "incoming": dict(base, missing_snapshot=["200"],
                         pulse={"available": True, "incomings": 3, "supports": 0,
                                "at": time.time() - 120, "age_seconds": 120}),
        "unknown": dict(base, missing_snapshot=[], pulse={"available": False}),
    }
    with srv.app.test_request_context("/"):
        html = srv.render_template("bot.html", data=cases["incoming"])
        check("3 ataque(s) chegando, segundo o jogo" in html, "/ nao mostra o contador do jogo")
        check("Risco observado" in html, "/ com ataque chegando nao sai como risco")
        check("Aldeia 200" in html and "ainda sem snapshot" in html,
              "/ nao lista a gerenciada sem snapshot")
        html = srv.render_template("bot.html", data=cases["unknown"])
        check("Não lido" in html, "/ sem pulso deveria dizer 'Não lido', nao 0")
        check("chegando, segundo o jogo" not in html, "/ sem pulso nao inventa ataque")
        html = srv.render_template("villages.html", data=cases["incoming"])
        check("Ataques chegando (jogo)" in html, "/villages sem o item do pulso")
        check("1 gerenciada(s) sem snapshot" in html, "/villages nao conta a sem snapshot")


def test_sync_counts_config_village_without_snapshot():
    srv = _client()
    orig_grab, orig_cfg = srv.DataReader.cache_grab, srv.DataReader.config_grab
    try:
        srv.DataReader.cache_grab = staticmethod(
            lambda kind: {"100": {}} if kind == "managed" else {})
        srv.DataReader.config_grab = staticmethod(lambda: {"villages": {
            "100": {"managed": True}, "200": {"managed": True}, "300": {"managed": False}}})
        out = srv.sync()
        check(out["missing_snapshot"] == ["200"],
              "so a gerenciada sem snapshot: %r" % out["missing_snapshot"])
        check("pulse" in out, "sync sem pulse")
        # Sem config.json, config_grab devolve None: o sync que toda pagina usa
        # nao pode passar a cair por causa da contagem nova.
        srv.DataReader.config_grab = staticmethod(lambda: None)
        check(srv.sync()["missing_snapshot"] == [], "sync sem config.json")
    finally:
        srv.DataReader.cache_grab, srv.DataReader.config_grab = orig_grab, orig_cfg


# ---------------------------------------------------------------- W6

def test_conquest_attention_reason():
    from webmanager.utils import ConquestReader as CR
    now = 1790000000
    grace = CR.OVERDUE_GRACE_SEC

    def t(**kw):
        base = {"status": "train_sent", "reserved_by": "74689", "last_hit_ts": now + 3600,
                "scheduled_arrival": None}
        base.update(kw)
        return base

    check(CR.attention_reason(t(), now=now) is None, "trem no ar nao pede atencao")
    check(CR.attention_reason(t(last_hit_ts=now - grace + 60), now=now) is None,
          "dentro da folga do relatorio nao pede atencao")
    r = CR.attention_reason(t(last_hit_ts=now - 9480), now=now)
    check(r and "2h38min" in r and "#74689" in r,
          "o caso real da auditoria (vencido ha 2h38) pede atencao: %r" % r)
    check(CR.attention_reason(t(status="extra_pending", last_hit_ts=now - 99999), now=now) is None,
          "extra_pending com pouso no passado e o normal dele")
    r = CR.attention_reason(t(status="train_scheduled", last_hit_ts=0,
                              scheduled_arrival=now - 3600), now=now)
    check(r and "agendado" in r, "trem agendado com chegada vencida: %r" % r)
    check(CR.attention_reason(t(status="train_scheduled", last_hit_ts=0,
                                scheduled_arrival=now + 3600), now=now) is None,
          "trem agendado no futuro nao pede atencao (a copia da lista marcava)")
    check("contrato" in CR.attention_reason(t(status="xyz"), now=now), "status desconhecido")
    check(CR.attention_reason(t(reserved_by="—"), now=now).startswith("Operação ativa sem"),
          "ativa sem origem")
    check(CR.attention_reason(t(status="conquered"), now=now) is None, "conquistada nao pede")


def test_conquest_page_counter_matches_list():
    srv = _client()
    from webmanager.utils import ConquestReader as CR
    now = time.time()
    targets = []
    for i, (status, last_hit, sched) in enumerate([
            ("train_scheduled", 0, now + 3600),       # nao pede (a lista antiga marcava)
            ("train_sent", now - 9480, None),         # pede: vencido
            ("conquered", now - 99999, None),         # nao pede
            ("lost", now - 99999, None)]):            # pede
        t = {"target_id": str(1000 + i), "target_name": "Bárbara %d" % i, "status": status,
             "reserved_by": "74689", "last_hit_ts": last_hit, "last_hit_fmt": "—",
             "scheduled_arrival": sched, "scheduled_arrival_fmt": "—", "sources": {},
             "hits_done": 0, "hits_needed": 4, "hits_pct": 0, "location_str": "1|1",
             "loyalty_now": 100, "loyalty_color": "success", "loyalty_source": "estimate",
             "status_label": status, "status_color": "info", "queued_at_fmt": "—"}
        t["attention_reason"] = CR.attention_reason(t)
        targets.append(t)
    area = {"enabled": False, "usable": False}
    with srv.app.test_request_context("/conquest"):
        html = srv.render_template("conquest.html", data={}, targets=targets, error=None,
                                   conquest_enabled=True, area=area)
    check("2 para revisar" in html, "contador deveria ser 2")
    check(html.count('class="twb-exception-item"') == 2,
          "lista deveria ter 2 itens, tem %d" % html.count('class="twb-exception-item"'))
    check("deveria ter pousado há 2h38min" in html, "motivo do vencido na lista")


# ---------------------------------------------------------------- W10

def test_farmscores_separates_own_and_player():
    from webmanager.utils import FarmScoreReader
    tmp = tempfile.mkdtemp()
    orig = FarmScoreReader.ATTACKS_DIR
    try:
        FarmScoreReader.ATTACKS_DIR = tmp
        rows = {
            "44167": {"farm_score": 3664, "safe": True},   # virou BBM 031
            "11111": {"farm_score": 1200, "safe": True},   # barbara
            "22222": {"farm_score": 1600, "safe": True},   # de jogador, sem additional_farms
            "33333": {"farm_score": 900, "safe": True},    # de jogador, em additional_farms
            "55555": {"farm_score": 50, "safe": True},     # managed-own pelo label
            "61947": {"farm_score": 3272, "safe": True},   # alvo da conquista ativa
        }
        for vid, data in rows.items():
            with open(os.path.join(tmp, vid + ".json"), "w") as fh:
                json.dump(data, fh)
        labels = {
            "44167": {"label": "Bárbara (557|293)", "own": False, "owner": "0"},
            "11111": {"label": "Bárbara (1|1)", "own": False, "owner": "0"},
            "22222": {"label": "FireHouse 23 (579|325)", "own": False, "owner": "920023448"},
            "33333": {"label": "Alvo (2|2)", "own": False, "owner": "920023448"},
            "55555": {"label": "BBM 016 (576|316)", "own": True, "owner": None},
            "61947": {"label": "Bárbara (583|285)", "own": False, "owner": "0"},
        }
        farms, _, own, player, unreadable = FarmScoreReader.load(
            own_ids={"44167"}, labels=labels, extra_farm_ids={"33333"},
            conquest_blocked={"61947": "conquista barbara, status extra_pending"})
        check(unreadable is False, "lista de conquista lida")
        ids = [f["target_id"] for f in farms]
        check("44167" not in ids and "55555" not in ids, "aldeia propria no ranking: %r" % ids)
        check(sorted(f["target_id"] for f in own) == ["44167", "55555"], "own: %r" % own)
        check([f["target_id"] for f in player] == ["22222"], "player fora do ranking: %r" % player)
        check(ids[0] == "11111", "1o lugar e a barbara: %r" % ids)
        extra = next(f for f in farms if f["target_id"] == "33333")
        check(extra["player_owned"] and extra["status_key"] == "player" and ids[-2] == "33333",
              "jogador em additional_farms fica no ranking, marcado e no fim: %r" % ids)
        conq = next(f for f in farms if f["target_id"] == "61947")
        check(conq["status_key"] == "conquest" and ids[-1] == "61947" and conq["conquest_block"],
              "alvo de conquista (o caso real da 61947, 2o do ranking) marcado e por ultimo")
        _, _, _, _, unreadable = FarmScoreReader.load(
            own_ids=set(), labels=labels, extra_farm_ids=set(), conquest_blocked=None)
        check(unreadable is True, "lista ilegivel e dita, nao vira 'nenhum bloqueado'")
        check(farms[0]["target_label"] == "Bárbara (1|1)", "nome em vez de id")
    finally:
        FarmScoreReader.ATTACKS_DIR = orig
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- W11

def test_hunter_expired_pending_is_not_active():
    srv = _client()
    from webmanager.utils import HunterReader
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "schedules.json")
    orig = HunterReader._cache_path
    now = time.time()
    try:
        HunterReader._cache_path = staticmethod(lambda: path)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({
                "a": {"target_id": "1", "arrival_time": now - 7200, "status": "pending",
                      "attacks": [{"source_village_id": "9", "troops": {"axe": 1},
                                   "status": "pending", "send_time": now - 9000}]},
                "b": {"target_id": "2", "arrival_time": now + 7200, "status": "pending",
                      "attacks": [{"source_village_id": "9", "troops": {"axe": 1},
                                   "status": "pending", "send_time": now + 3600}]},
                "c": {"target_id": "3", "arrival_time": now - 99999, "status": "complete",
                      "attacks": [{"source_village_id": "9", "troops": {"axe": 1},
                                   "status": "sent"}]},
            }, fh)
        sched = {s["sched_key"]: s for s in HunterReader.load()}
        check(sched["a"]["expired"] and not sched["b"]["expired"] and not sched["c"]["expired"],
              "expired: %r" % {k: v["expired"] for k, v in sched.items()})
        html = srv.app.test_client().get("/hunter").get_data(as_text=True)
        check("1 agendadas · 1 vencidas · 1 terminais" in html,
              "cabecalho deveria separar vencida de agendada")
        check("Chegada vencida sem fechamento" in html, "vencida nao pede atencao")
        check("Pendente com chegada vencida" in html, "vencida nao vai para o historico")
        active = html.split('id="titulo-agendamentos-hunter"')[1].split('id="novo-agendamento"')[0]
        check("Alvo #2" in active and "Alvo #1" not in active,
              "a tabela de ativos deveria ter so o #2")
    finally:
        HunterReader._cache_path = orig
        shutil.rmtree(tmp, ignore_errors=True)


for fn in [
    test_extract_verbatim_and_failure_is_not_zero,
    test_unarmed_never_writes_armed_writes_on_change,
    test_read_absent_bad_and_age,
    test_pages_show_pulse_and_missing_snapshot,
    test_sync_counts_config_village_without_snapshot,
    test_conquest_attention_reason,
    test_conquest_page_counter_matches_list,
    test_farmscores_separates_own_and_player,
    test_hunter_expired_pending_is_not_active,
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
print("OK: auditoria de campo do painel (W1/W4, W6, W10, W11)")
