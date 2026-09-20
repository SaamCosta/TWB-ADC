"""
CAPTURA SO-LEITURA da lista COMPLETA de reservas (`&page=all`) e da reserva
propria, para recortar fixture verbatim.

    python tests/smoke_capture_reservations_all.py

GET puro. Medido em 2026-09-20: `&page=all` traz as 489 reservas numa
requisicao (707 KB), contra 49 paginas de 10 no default.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.filemanager import FileManager
from core.request import WebWrapper

config = FileManager.load_json_file("config.json")
_raw = os.environ.get("TWB_COOKIE", "")
if not _raw and os.path.exists("cache/debug/cookie.txt"):
    with open("cache/debug/cookie.txt", encoding="utf-8") as fh:
        _raw = fh.read().strip()
jar = {}
for part in _raw.split(";"):
    part = part.strip()
    if "=" in part:
        k, v = part.split("=", 1)
        jar[k.strip()] = v
if not jar:
    jar = (FileManager.load_json_file("cache/session.json") or {}).get("cookies", {})

wrapper = WebWrapper(config["server"]["endpoint"], server=config["server"]["server"],
                     endpoint=config["server"]["endpoint"])
wrapper.headers["user-agent"] = config["bot"]["user_agent"]
wrapper.web.cookies.update(jar)
wrapper.priority_mode = True

vid = sorted(config["villages"].keys())[0]
BASE = "game.php?village=%s&screen=ally&mode=reservations" % vid
os.makedirs("cache/debug", exist_ok=True)

res = wrapper.get_url(BASE + "&page=all")
with open("cache/debug/reservations_all.html", "w", encoding="utf-8") as fh:
    fh.write(res.text)
rows = re.findall(r'<tr id="reservation_(\d+)">', res.text)
print("page=all: %d bytes, %d linhas" % (len(res.text), len(rows)))

res2 = wrapper.get_url(BASE + "&group_id=creator_id&filter=5955651")
with open("cache/debug/reservations_mine.html", "w", encoding="utf-8") as fh:
    fh.write(res2.text)
m = re.search(r'<tr id="reservation_\d+">.*?</tr>', res2.text, re.S)
print("\n=== MINHA reserva, verbatim ===")
print(m.group(0) if m else "(nenhuma)")
