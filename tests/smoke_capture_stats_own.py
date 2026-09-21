"""
CAPTURA SO-LEITURA da tela de estatisticas do jogador.

    game.php?village=<vid>&screen=info_player&mode=stats_own

Fora do glob `test_*.py` de proposito: vai a REDE com a sessao do bot. E GET
puro, nao muda nada no jogo e nao atrapalha o bot rodando.

    python tests/smoke_capture_stats_own.py

Grava o HTML cru em cache/debug/ e imprime o inventario das series encontradas,
para recortar fixture verbatim.

Setimo padrao do CLAUDE.md: usa o proprio `WebWrapper` do bot, porque o mesmo
endpoint ja devolveu envelopes diferentes dependendo dos cabecalhos.

NAO liga `priority_mode`. Pular o atraso do `get_url` com o bot rodando ja
provocou captcha por cima dele -- a sonda espera os mesmos 3-7x delay que o
bot espera.
"""
import json
import logging
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

from core.filemanager import FileManager
from core.request import WebWrapper

config = FileManager.load_json_file("config.json")
session = FileManager.load_json_file("cache/session.json")
if not config or not session:
    print("sem config.json ou cache/session.json -- nada a fazer")
    raise SystemExit(1)

wrapper = WebWrapper(config["server"]["endpoint"], server=config["server"]["server"],
                     endpoint=config["server"]["endpoint"])
wrapper.headers["user-agent"] = config["bot"]["user_agent"]
wrapper.web.cookies.update(session["cookies"])

vid = sorted(config["villages"].keys())[0]
os.makedirs("cache/debug", exist_ok=True)

url = "game.php?village=%s&screen=info_player&mode=stats_own" % vid
print("\n== GET %s" % url)
res = wrapper.get_url(url)
if res is None:
    print("   get_url devolveu None")
    raise SystemExit(1)
print("   status=%s len=%d" % (res.status_code, len(res.text)))

path = "cache/debug/stats_own.html"
with open(path, "w", encoding="utf-8") as fh:
    fh.write(res.text)
print("   -> %s" % path)

text = res.text

# 1) Series simples: InfoPlayer.Stats.createGraph('<id>', '<tipo>', [[ms, v]...])
print("\n== series simples (createGraph) ==")
for gid, kind, arr in re.findall(
    r"createGraph\('([^']+)',\s*'([^']+)',\s*(\[.*?\])\);", text, re.S
):
    pts = sorted(int(a) // 1000 for a, _ in re.findall(r'\["(\d+)","(-?\d+)"\]', arr))
    if not pts:
        print("   %-28s %-5s SEM PONTOS -- markup mudou?" % (gid, kind))
        continue
    step = (pts[-1] - pts[0]) / max(len(pts) - 1, 1) / 3600
    print("   %-28s %-5s n=%3d janela=%4.1fd passo=%4.1fh"
          % (gid, kind, len(pts), (pts[-1] - pts[0]) / 86400, step))

# 2) Series ricas: data.push({label: '<x>', ..., details: [{wood,stone,iron,total,percent}]})
#    Sao duas no mesmo HTML -- "Recursos saqueados" e "Recursos gastos" -- e a
#    unica coisa que as separa e a ORDEM. Nao ha id no bloco do push.
print("\n== series ricas (label + details) ==")
blocks = re.findall(r"label:\s*'([^']+)'.*?details:\s*(\[\{.*?\}\])", text, re.S)
for label, det in blocks:
    rows = json.loads(det)
    print("   %-22s n=%d  ultimo=%s" % (label, len(rows), rows[0].get("total")))

# 3) Guardas de semantica, medidas e nao supostas:
#    - total == wood+stone+iron
#    - percent == participacao daquela serie no total do DIA (nao no periodo)
print("\n== guardas de semantica ==")
for nome, grp in (("saqueado", blocks[:2]), ("gasto", blocks[2:])):
    series = {k: {r["time"]: r for r in json.loads(v)} for k, v in grp}
    if not series:
        print("   %s: nenhum bloco -- markup mudou?" % nome)
        continue
    soma_ok = pct_ok = True
    for stamp in {t for s in series.values() for t in s}:
        total_dia = sum(int(s[stamp]["total"]) for s in series.values() if stamp in s)
        for s in series.values():
            if stamp not in s:
                continue
            r = s[stamp]
            if int(r["wood"]) + int(r["stone"]) + int(r["iron"]) != int(r["total"]):
                soma_ok = False
            calc = 100 * int(r["total"]) / total_dia if total_dia else 0
            if abs(calc - r["percent"]) > 0.01:
                pct_ok = False
    print("   %s: total==w+s+i? %s | percent==participacao do dia? %s"
          % (nome, soma_ok, pct_ok))
