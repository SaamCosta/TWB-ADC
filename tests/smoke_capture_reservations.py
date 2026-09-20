"""
CAPTURA SO-LEITURA da tela oficial de reservas da tribo.

Fora do glob `test_*.py` de proposito: vai a REDE com a sessao do bot.

    python tests/smoke_capture_reservations.py

Grava o HTML cru em cache/debug/ para recortar fixture verbatim. E GET puro,
nao muda nada no jogo e nao atrapalha o bot rodando.

Setimo padrao do CLAUDE.md: usa o proprio `WebWrapper` do bot (e busca as duas
formas, com e sem `TribalWars-Ajax: 1`), porque o mesmo endpoint ja devolveu
envelopes diferentes dependendo dos cabecalhos.
"""
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

# Cookie fresco por variavel de ambiente (TWB_COOKIE="k=v; k2=v2"), para quando
# o cache/session.json esta expirado. NAO reescreve o session.json de
# proposito: aquele arquivo e do bot, e sobrescrever estado de producao para
# conseguir uma leitura e o vigesimo primeiro padrao do CLAUDE.md.
_override = os.environ.get("TWB_COOKIE", "").strip()
if _override:
    jar = {}
    for part in _override.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        jar[k.strip()] = v
    session = {"cookies": jar}
    print("usando TWB_COOKIE (%d cookies), session.json intocado" % len(jar))

wrapper = WebWrapper(config["server"]["endpoint"], server=config["server"]["server"],
                     endpoint=config["server"]["endpoint"])
wrapper.headers["user-agent"] = config["bot"]["user_agent"]
wrapper.web.cookies.update(session["cookies"])
wrapper.priority_mode = True

vid = sorted(config["villages"].keys())[0]
os.makedirs("cache/debug", exist_ok=True)


def dump(name, text):
    path = "cache/debug/%s" % name
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    print("   -> %s (%d bytes)" % (path, len(text)))


# 1) A tela, pelo caminho normal do bot (get_url monta os cabecalhos padrao).
url = "game.php?village=%s&screen=ally&mode=reservations" % vid
print("\n== GET %s" % url)
res = wrapper.get_url(url)
if res is None:
    print("   get_url devolveu None")
    raise SystemExit(1)
print("   status=%s url_final=%s len=%d" % (res.status_code, res.url, len(res.text)))
dump("reservations_plain.html", res.text)

# Onde esta o miolo: procura a tabela/linha que fala de reserva.
for pat in ("reserva", "Reserva", "reservation", "mode=reservations"):
    hits = [m.start() for m in re.finditer(pat, res.text)]
    print("   '%s': %d ocorrencias" % (pat, len(hits)))

# 2) A mesma tela com os cabecalhos de AJAX, que e a outra forma que o wrapper
#    usa em outros caminhos. Nao passa por get_api_data porque ali screen=api.
custom = dict(wrapper.headers)
custom["accept"] = "application/json, text/javascript, */*; q=0.01"
custom["x-requested-with"] = "XMLHttpRequest"
custom["tribalwars-ajax"] = "1"
print("\n== GET (mesmo url, com tribalwars-ajax: 1)")
res2 = wrapper.get_url(url, headers=custom)
if res2 is None:
    print("   get_url devolveu None")
else:
    print("   status=%s len=%d" % (res2.status_code, len(res2.text)))
    dump("reservations_ajax.html", res2.text)
    print("   mesma resposta do caminho normal? %s" % (res2.text == res.text))

# 3) A tela de visao geral da tribo, para saber se o link de reservas aparece
#    (isso responde se a conta tem o direito na tribo).
print("\n== GET screen=ally (indice, para achar o link/permissao)")
res3 = wrapper.get_url("game.php?village=%s&screen=ally" % vid)
if res3 is not None:
    dump("ally_index.html", res3.text)
    print("   modes vistos: %s" % sorted(set(re.findall(r'mode=([a-z_]+)', res3.text))))

# 4) A identidade da conta, para separar "reservado por mim" de "reservado por
#    outro". Por decisao do usuario isso sai do jogo, nao de config nova --
#    entao a captura tem que provar ONDE o dado aparece. Tres candidatos, e o
#    que importa e qual deles casa com o nome que a lista de reservas mostra.
print("\n== identidade da conta")
for label, pat in (
    ("game_state player.name", r'"player"\s*:\s*\{[^}]*?"name"\s*:\s*"(.*?)"'),
    ("game_state player.id", r'"player"\s*:\s*\{[^}]*?"id"\s*:\s*"?(\d+)'),
    ("link screen=info_player&id=", r'screen=info_player&(?:amp;)?id=(\d+)'),
    ("menu_row nome", r'id="menu_row2_village"[^>]*>(.*?)<'),
):
    for src_name, src in (("reservations", res.text), ("ally", res3.text if res3 else "")):
        found = re.findall(pat, src)
        if found:
            print("   [%s] %s -> %s" % (src_name, label, sorted(set(found))[:5]))

