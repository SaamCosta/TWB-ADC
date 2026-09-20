"""
SONDAGEM SO-LEITURA: como pegar a lista de reservas inteira sem 49 requisicoes.

    python tests/smoke_probe_reservation_paging.py

GET puro, nada de POST -- nao muda a configuracao de `reservation_page_size` da
tribo (que e compartilhada com outras pessoas). Testa se a paginacao aceita
parametro por querystring e mede o encoding real da resposta.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.filemanager import FileManager
from core.request import WebWrapper

config = FileManager.load_json_file("config.json")
jar = {}
for part in os.environ.get("TWB_COOKIE", "").split(";"):
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

ROW = re.compile(r'<tr id="reservation_(\d+)">')


def probe(label, suffix):
    res = wrapper.get_url(BASE + suffix)
    if res is None:
        print("%-44s -> None" % label)
        return None
    rows = ROW.findall(res.text)
    pages = set(re.findall(r'&amp;page=(\d+)&amp;sort', res.text))
    print("%-44s -> %d linhas, len=%d, maior pagina vista=%s"
          % (label, len(rows), len(res.text),
             max((int(p) for p in pages), default="?")))
    return res


print("== encoding")
res = probe("baseline (sem parametro)", "")
print("   res.encoding=%s  apparent=%s" % (res.encoding, res.apparent_encoding))
print("   'barbaros' decodificado:",
      re.search(r'Aldeia de b.{1,3}rbaros', res.text).group(0).encode("unicode_escape"))

print("\n== tentativas de trazer tudo de uma vez")
for label, suffix in (
    ("page=-1", "&page=-1"),
    ("page=all", "&page=all"),
    ("reservation_page_size=1000", "&reservation_page_size=1000"),
    ("page_size=1000", "&page_size=1000"),
    ("page=-1&reservation_page_size=1000", "&page=-1&reservation_page_size=1000"),
):
    probe(label, suffix)

print("\n== filtros (reduzem o volume?)")
for label, suffix in (
    ("group_id=creator_id&filter=<eu>", "&group_id=creator_id&filter=5955651"),
    ("group_id=creator_ally_id&filter=987", "&group_id=creator_ally_id&filter=987"),
):
    probe(label, suffix)
