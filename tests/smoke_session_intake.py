"""
SMOKE (vai a rede com a conta; fora do glob da suite): o bot pegando a sessao
que a extensao mandou ao painel (§8.87).

Uso, depois de a extensao ter mandado a sessao e o painel ter gravado o
`cache/session.json`:

    python tests/smoke_session_intake.py [sessao_anterior.json]

1. Mostra o ultimo resultado do painel (`cache/session_intake.json`): mundo,
   mensagem e atributos de cada cookie (HttpOnly etc.), nunca valores.
2. Monta o `WebWrapper` como o `twb.py` monta (endpoint e user-agent do
   config). Com `sessao_anterior.json`, carrega o jar dele e chama
   `adopt_newer_session()` -- o caminho do bot rodando. Sem, chama `start()`
   -- o caminho do bot que sobe. Um ou dois GETs, pelo `get_url` do wrapper.

Imprime so hash curto de `sid`, para comparar sem expor.
"""
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.filemanager import FileManager  # noqa: E402
from core.request import WebWrapper  # noqa: E402


def short(value):
    return hashlib.sha256((value or "").encode()).hexdigest()[:8] if value else "-"


intake = FileManager.load_json_file("cache/session_intake.json") or {}
print("painel:", json.dumps({k: intake.get(k) for k in ("at", "server", "ok", "message")}))
for name, attrs in sorted((intake.get("flags") or {}).items()):
    print("   %-24s %s" % (name, attrs))

config = FileManager.load_json_file("config.json")
wrapper = WebWrapper(config["server"]["endpoint"], server=config["server"]["server"],
                     endpoint=config["server"]["endpoint"])
wrapper.headers["user-agent"] = config["bot"]["user_agent"]
current = (FileManager.load_json_file("cache/session.json") or {})
print("session.json: source=%s sid=%s" % (current.get("source"),
                                          short((current.get("cookies") or {}).get("sid"))))

if len(sys.argv) > 1:
    previous = json.load(open(sys.argv[1], encoding="utf-8-sig"))
    wrapper.web.cookies.update(previous["cookies"])
    print("jar anterior: sid=%s" % short(previous["cookies"].get("sid")))
    adopted = wrapper.adopt_newer_session()
    print("adopt_newer_session():", adopted)
    sids = sorted(c.value for c in wrapper.web.cookies if c.name == "sid")
    print("jar depois: sid=%s" % ",".join(short(s) for s in sids))
    res = wrapper.get_url("game.php?screen=overview")
    print("overview com o jar final: logado =", bool(res) and "game.php" in res.url)
else:
    print("start():", wrapper.start())
