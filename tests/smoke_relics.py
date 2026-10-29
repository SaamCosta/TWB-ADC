"""
SMOKE (vai à rede, fora do glob da suíte): o `RelicManager` (§8.75) contra o
servidor, com o `WebWrapper` e a sessão do bot. Só GET, no máximo 3, com
`--interval` segundos entre eles (padrão 90: o bot roda na mesma conta, e a
taxa somada não pode passar de ~2 req/min). Nunca liga `priority_mode`.

O estado vai para `--out` (padrão: diretório temporário), nunca para o
`cache/relics.json` que o bot tem aberto (21º padrão).

    python tests/smoke_relics.py --village 41123
"""
import argparse
import json
import logging
import os
import re
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from core.filemanager import FileManager  # noqa: E402
from core.request import WebWrapper  # noqa: E402
from game import relic_manager as RM  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--village", default="41123")
ap.add_argument("--interval", type=int, default=90)
ap.add_argument("--out", default=os.path.join(tempfile.gettempdir(), "smoke_relics.json"))
args = ap.parse_args()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
config = FileManager.load_json_file("config.json")
wrapper = WebWrapper(config["server"]["endpoint"], server=config["server"]["server"],
                     endpoint=config["server"]["endpoint"])
wrapper.headers["user-agent"] = config["bot"]["user_agent"]
wrapper.web.cookies.update(FileManager.load_json_file("cache/session.json")["cookies"])

_get = wrapper.get_url
calls = []


def paced_get(url, headers=None):
    if "ajaxaction=" in url or "action=" in url.split("screen=")[-1]:
        raise SystemExit("recusado (acao): %s" % url)
    if calls:
        time.sleep(args.interval)
    calls.append(url)
    res = _get(url, headers)
    if res is not None and any(re.findall(r'data-bot-protect="(\w*)"', res.text)):
        raise SystemExit("PARADO: bot protection em %s" % url)
    return res


wrapper.get_url = paced_get
RM.CACHE_PATH = args.out
own_ids = sorted((config.get("villages") or {}).keys())
man = RM.RelicManager(wrapper=wrapper, config=config)
man.state = None
ok = man.run(args.village, own_ids=own_ids, reason="smoke")
print("run ->", ok, "GETs:", len(calls))
if ok:
    st = man.state
    print(json.dumps({"slots": st["slots"], "counts": st["counts"], "totals": st["totals"],
                      "coverage_check": st["coverage_check"],
                      "found": st["found"]}, ensure_ascii=False, indent=1))
    print("estado em", args.out)
