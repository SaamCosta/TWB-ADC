"""
SMOKE (fora do glob da suite): renderiza /village no webmanager real.

Fica fora de `tests/test_*.py` porque le o `cache/` e o `config.json` de
verdade -- e leitura, nao escrita, mas depende do estado da maquina e nao roda
em ambiente limpo. Serve para pegar erro de template (Jinja so falha em
runtime) sem subir o servidor.

Rodar: python tests/smoke_village_page.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "webmanager"))

from webmanager.server import app

managed = sorted(
    f[:-5] for f in os.listdir(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "cache", "managed"))
    if f.endswith(".json")
)

app.config["SERVER_NAME"] = "127.0.0.1:5000"
client = app.test_client()

falhas = 0
for vid in [None] + managed[:3]:
    url = "/village" if vid is None else "/village?id=%s" % vid
    resp = client.get(url, headers={"Host": "127.0.0.1:5000"})
    ok = resp.status_code == 200
    marker = b"Alvos de farm e o motivo de cada um" in resp.data
    print("%-28s status=%s painel_presente=%s" % (url, resp.status_code, marker))
    if not ok or (vid is not None and not marker):
        falhas += 1
        print(resp.data[-2000:].decode("utf-8", "replace"))

# O ramo populado do painel. Os dados sao sinteticos e ficam em memoria: nao
# se fabrica arquivo dentro de `cache/`, que e estado real do bot.
import time

import webmanager.server as srv

srv.FarmExclusionReader.load = staticmethod(lambda vid: {
    "available": True, "village_id": vid,
    "observed_at": int(time.time()) - 900, "observed_at_fmt": "22/09 10:00",
    "cycle_started_at": int(time.time()) - 1800,
    "truncated": True, "max_selecao": 400,
    "summary": [
        {"code": "longe_demais", "count": 612, "label": "Fora do raio de farm",
         "help": "ajuda", "knob": "farms.search_radius", "phase": "selecao"},
        {"code": "atacado", "count": 4, "label": "Atacado neste ciclo",
         "help": "ajuda", "knob": None, "phase": "tentativa"},
        {"code": "recusado_pelo_jogo", "count": 2, "label": "Recusado pelo jogo",
         "help": "ajuda", "knob": None, "phase": "tentativa"},
    ],
    "attempts": [
        {"target_id": "9", "target_label": "Bárbara (512|487)",
         "code": "recusado_pelo_jogo", "label": "Recusado pelo jogo",
         "help": "ajuda", "knob": None,
         "detail": "A força de ataque precisa do mínimo de 73 habitantes.",
         "observed_at": int(time.time()), "attacked": False},
        {"target_id": "10", "target_label": "Bárbara (513|487)",
         "code": "atacado", "label": "Atacado neste ciclo", "help": "ajuda",
         "knob": None, "detail": "pacote {'light': 15}",
         "observed_at": int(time.time()), "attacked": True},
    ],
    "selection_sample": [
        {"target_id": "11", "target_label": "Bárbara (600|600)",
         "code": "longe_demais", "label": "Fora do raio de farm",
         "help": "ajuda", "knob": "farms.search_radius",
         "detail": "80.0 campos, raio 50", "observed_at": int(time.time()),
         "attacked": False},
    ],
    "attacked_count": 4, "total": 618,
})

resp = client.get("/village?id=%s" % managed[0], headers={"Host": "127.0.0.1:5000"})
for esperado in (b"Recusado pelo jogo", b"Fora do raio de farm",
                 b"lista individual", b"farms.search_radius"):
    if esperado not in resp.data:
        falhas += 1
        print("FALTOU no ramo populado: %s" % esperado)
print("/village populado           status=%s" % resp.status_code)
if resp.status_code != 200:
    falhas += 1

sys.exit(1 if falhas else 0)
