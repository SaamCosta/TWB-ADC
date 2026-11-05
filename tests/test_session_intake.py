"""
Entrada da sessao pela extensao do navegador (docs/backend.md §8.87).

O testador loga no jogo e a extensao `browser_extension/` posta os cookies em
`POST /api/session` do painel. O endpoint recebe credencial, entao o que este
arquivo prova e a porta estreita e o "so grava depois de provar":

 - `world_from_url`         mundo e endpoint de qualquer mercado, sem br143 fixo;
                            portal (`www.`), http e host de fora ficam fora;
 - `request_refusal`        so loopback, so a origem da extensao, so JSON;
 - `parse_payload`          sem `sid` nao passa, e lixo em cookie nao passa;
 - `world_mismatch`         config de outro mundo recusa; sem config aceita;
 - `accept`                 grava so com `_session_works` verde (wrapper falso);
 - manifest                 o id fixo bate com a `key`, e as permissoes cobrem
                            todo mercado de `TW_DOMAINS`;
 - rota                     origem de pagina, sem origem e Host de fora levam
                            403 antes de qualquer requisicao ao jogo.

Sem rede e sem escrever em `cache/` (o `save_json_file` da rota e trocado).

Rodar: python tests/test_session_intake.py
"""
import base64
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import session_intake as si  # noqa: E402

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


ORIGIN = si.ALLOWED_ORIGINS[0]
GOOD = {
    "url": "https://br143.tribalwars.com.br/game.php?village=1&screen=overview",
    "cookies": {"sid": "0:abc", "cid": "9", "global_village_id": "1"},
    "user_agent": "Mozilla/5.0 Teste",
    "flags": {"sid": {"httpOnly": True, "secure": True, "hostOnly": True,
                      "domain": "br143.tribalwars.com.br", "value": "nao-copiar"}},
}


def test_world_from_url_mercados():
    w = si.world_from_url(GOOD["url"])
    check(w == {"server": "br143", "endpoint": "https://br143.tribalwars.com.br/game.php",
                "host": "br143.tribalwars.com.br"}, "br143: %r" % (w,))
    for url, server in (("https://en153.tribalwars.net/game.php", "en153"),
                        ("https://nlc1.tribalwars.nl/game.php?x=1", "nlc1"),
                        ("https://de250.die-staemme.de/game.php", "de250"),
                        ("https://no50.tribalwars.com/game.php", "no50"),
                        ("https://uk80.tribalwars.co.uk/game.php", "uk80")):
        got = si.world_from_url(url)
        check(got and got["server"] == server, "%s -> %r" % (url, got))


def test_world_from_url_recusa():
    for url in ("http://br143.tribalwars.com.br/game.php",      # sem TLS
                "https://www.tribalwars.com.br/",                # portal
                "https://br143.tribalwars.com.br.evil.com/game.php",
                "https://x.br143.tribalwars.com.br/game.php",
                "https://br143.tribalwars.com.br:8443/game.php",
                "https://evil.com/br143.tribalwars.com.br",
                "javascript:alert(1)", "", None, 42):
        check(si.world_from_url(url) is None, "devia recusar %r" % (url,))


def test_request_refusal():
    ok = si.request_refusal(ORIGIN, "127.0.0.1:5000", "application/json")
    check(ok is None, "requisicao boa recusada: %r" % ok)
    check(si.request_refusal(ORIGIN, "localhost:5000", "application/json; charset=utf-8") is None,
          "localhost com charset recusado")
    check(si.request_refusal(ORIGIN, "[::1]:5000", "application/json") is None, "[::1] recusado")
    # DNS rebinding: a pagina chega no 127.0.0.1 com o Host dela.
    check(si.request_refusal(ORIGIN, "evil.com:5000", "application/json"),
          "Host de fora passou")
    check(si.request_refusal("https://evil.com", "127.0.0.1:5000", "application/json"),
          "origem de pagina passou")
    check(si.request_refusal("chrome-extension://outraextensaoqualquer", "127.0.0.1:5000",
                             "application/json"), "outra extensao passou")
    check(si.request_refusal(None, "127.0.0.1:5000", "application/json"),
          "sem Origin passou (aqui nao ha cliente legitimo sem navegador)")
    # Formulario HTML so manda form-urlencoded/multipart/text sem preflight.
    check(si.request_refusal(ORIGIN, "127.0.0.1:5000", "text/plain"), "text/plain passou")


def test_parse_payload():
    data, err = si.parse_payload(GOOD)
    check(err is None, "payload bom recusado: %r" % err)
    check(data and data["server"] == "br143" and data["cookies"]["sid"] == "0:abc",
          "payload mal lido: %r" % (data,))
    check(data and "value" not in data["flags"]["sid"],
          "flags levou campo fora da lista (valor de cookie no log?)")
    no_sid = dict(GOOD, cookies={"cid": "9"})
    check(si.parse_payload(no_sid)[1], "sem sid passou")
    bad_value = dict(GOOD, cookies={"sid": "a\r\nSet-Cookie: x=1"})
    check(si.parse_payload(bad_value)[1], "quebra de linha em valor passou")
    bad_name = dict(GOOD, cookies={"sid": "a", "x y": "1"})
    check(si.parse_payload(bad_name)[1], "nome com espaco passou")
    many = dict(GOOD, cookies={"c%d" % i: "1" for i in range(si.MAX_COOKIES + 1)})
    check(si.parse_payload(many)[1], "cookies demais passou")
    check(si.parse_payload([1, 2])[1], "lista passou")
    check(si.parse_payload(dict(GOOD, url="https://www.tribalwars.com.br/"))[1],
          "url do portal passou")
    ua = si.parse_payload(dict(GOOD, user_agent="x\ny"))[0]
    check(ua and ua["user_agent"] is None, "user-agent com quebra de linha ficou")


def test_world_mismatch():
    check(si.world_mismatch(None, "br143") is None, "sem config devia aceitar")
    check(si.world_mismatch({"server": {"server": "br143"}}, "br143") is None,
          "mesmo mundo recusado")
    msg = si.world_mismatch({"server": {"server": "BR142"}}, "br143")
    check(msg and "br142" in msg and "br143" in msg, "outro mundo: %r" % msg)


class FakeWrapper:
    instances = []

    def __init__(self, url, server=None, endpoint=None, works=True, text=""):
        self.args = (url, server, endpoint)
        self.headers = {"user-agent": "padrao"}
        self.delay = 1.0
        self.session_extra = {}
        self.tested = None
        self.works = works
        self.last_response = type("R", (), {"text": text})()
        FakeWrapper.instances.append(self)

    def _session_works(self, cookies):
        self.tested = dict(cookies)
        return self.works


def factory(works=True, text=""):
    def make(url, server=None, endpoint=None):
        return FakeWrapper(url, server=server, endpoint=endpoint, works=works, text=text)
    return make


def test_accept():
    data, _ = si.parse_payload(GOOD)
    ok, msg = si.accept(data, None, wrapper_factory=factory())
    w = FakeWrapper.instances[-1]
    check(ok, "sessao boa recusada: %s" % msg)
    check(w.args == ("https://br143.tribalwars.com.br/game.php", "br143",
                     "https://br143.tribalwars.com.br/game.php"), "wrapper errado: %r" % (w.args,))
    check(w.tested == data["cookies"], "provou outros cookies")
    check(w.delay == 0, "a prova devia ser sem o sono de 3-7 s")
    check(w.headers["user-agent"] == "Mozilla/5.0 Teste",
          "sem config, o user-agent devia ser o do navegador")
    check(w.session_extra.get("browser_user_agent") == "Mozilla/5.0 Teste",
          "session.json nao vai guardar o user-agent do navegador")

    cfg = {"server": {"server": "br143"}, "bot": {"user_agent": "UA do config"}}
    si.accept(data, cfg, wrapper_factory=factory())
    check(FakeWrapper.instances[-1].headers["user-agent"] == "UA do config",
          "com config, o user-agent devia ser o do config (o que o bot usa)")

    before = len(FakeWrapper.instances)
    ok, msg = si.accept(data, {"server": {"server": "br142"}}, wrapper_factory=factory())
    check(not ok and len(FakeWrapper.instances) == before,
          "mundo errado devia recusar sem requisicao ao jogo")

    ok, msg = si.accept(data, None, wrapper_factory=factory(works=False))
    check(not ok and "nao aceitou" in msg, "sessao vencida: %r" % msg)
    ok, msg = si.accept(data, None, wrapper_factory=factory(works=False, text=si.BOT_PROTECT_MARKER))
    check(not ok and "captcha" in msg, "captcha devia ser dito: %r" % msg)


def test_marcador_igual_ao_do_request():
    from core.request import BOT_PROTECT_MARKER
    check(si.BOT_PROTECT_MARKER == BOT_PROTECT_MARKER,
          "marcador de captcha divergiu de core/request.py")


def test_manifest():
    path = os.path.join(ROOT, "browser_extension", "manifest.json")
    manifest = json.load(open(path, encoding="utf-8"))
    der = base64.b64decode(manifest["key"])
    ext_id = "".join(chr(ord("a") + int(c, 16)) for c in hashlib.sha256(der).hexdigest()[:32])
    check(ext_id == si.EXTENSION_ID,
          "id da extensao (%s) nao bate com a key do manifest" % ext_id)
    hosts = set(manifest["host_permissions"])
    for domain in si.TW_DOMAINS:
        check("https://*.%s/*" % domain in hosts, "manifest sem permissao para %s" % domain)
    extra = {h for h in hosts if h.startswith("https://")} - {
        "https://*.%s/*" % d for d in si.TW_DOMAINS}
    check(not extra, "manifest pede host fora dos mercados: %r" % extra)
    local = {h for h in hosts if h.startswith("http://")}
    check(local == {"http://127.0.0.1/*", "http://localhost/*"},
          "destino http fora do loopback: %r" % local)
    check(set(manifest["permissions"]) == {"cookies", "storage", "alarms"},
          "permissoes mudaram: %r" % manifest["permissions"])
    js = open(os.path.join(ROOT, "browser_extension", "background.js"), encoding="utf-8").read()
    check("http://127.0.0.1:" in js and "fetch(" in js, "background.js sem o destino local")
    check(js.count("fetch(") == 1, "background.js ganhou outro fetch: conferir o destino")


def test_rota_recusa_antes_do_jogo():
    import webmanager.server as srv
    from core.filemanager import FileManager

    calls = []
    real_accept, real_save = si.accept, FileManager.save_json_file
    si.accept = lambda data, config: calls.append(data) or (True, "ok")
    FileManager.save_json_file = staticmethod(lambda data, path, **kw: calls.append(path))
    try:
        client = srv.app.test_client()
        body = json.dumps(GOOD)
        r = client.post("/api/session", data=body, content_type="application/json",
                        headers={"Origin": "https://evil.com"})
        check(r.status_code == 403, "origem de pagina: %d" % r.status_code)
        r = client.post("/api/session", data=body, content_type="application/json")
        check(r.status_code == 403, "sem origem: %d" % r.status_code)
        r = client.post("/api/session", data=body, content_type="application/json",
                        headers={"Origin": ORIGIN, "Host": "evil.com"})
        check(r.status_code == 403, "Host de fora: %d" % r.status_code)
        check(calls == [], "recusa chegou a provar/gravar: %r" % calls)

        r = client.post("/api/session", data=json.dumps(dict(GOOD, cookies={"cid": "1"})),
                        content_type="application/json", headers={"Origin": ORIGIN})
        check(r.status_code == 400 and calls == [], "sem sid: %d %r" % (r.status_code, calls))

        r = client.post("/api/session", data=body, content_type="application/json",
                        headers={"Origin": ORIGIN})
        out = r.get_json() or {}
        check(r.status_code == 200 and out.get("ok"), "aceite: %d %r" % (r.status_code, out))
        check("0:abc" not in r.get_data(as_text=True), "a resposta devolveu valor de cookie")
        check("sid(HttpOnly,Secure,host)" in (out.get("flags") or ""),
              "flags do sid fora da resposta: %r" % out.get("flags"))
        check("cache/session_intake.json" in calls, "resultado nao registrado")

        # O resto do painel segue com a checagem de sempre.
        r = client.post("/bot/stop", headers={"Origin": ORIGIN})
        check(r.status_code == 403, "a excecao vazou para outra rota: %d" % r.status_code)
    finally:
        si.accept, FileManager.save_json_file = real_accept, real_save


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except Exception as exc:
                import traceback
                traceback.print_exc()
                failures.append("%s levantou %s: %s" % (name, type(exc).__name__, exc))
    if failures:
        print("FAIL (%d)" % len(failures))
        for f in failures:
            print("  - %s" % f)
        sys.exit(1)
    print("OK test_session_intake")
