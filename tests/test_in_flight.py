"""
Testes de game/in_flight.py (Feature 38) e de webmanager/utils.py::InFlightReader.

Sem rede e sem tocar no `cache/` real: o wrapper e de mentira e o CACHE_PATH
dos dois lados e trocado por arquivo temporario. Isso nao e detalhe de
higiene -- `cache/` e estado de producao nao regeneravel, e um teste que
escreve no artefato que ele vigia ja abriu buraco de bytes NUL no log de
sessao com o bot rodando (21o padrao do CLAUDE.md).

O que e verificado, e por que cada coisa importa:

  - `page=-1` NA URL. Sem ele a tela devolve 25 de 65 comandos e o cabecalho
    diz 25, entao a perda e invisivel. E o unico parametro cuja ausencia
    quebraria a feature sem quebrar nenhum teste de parser -- por isso a
    asercao e sobre a URL pedida, nao sobre o resultado.
  - LEITURA RUIM NUNCA APAGA LEITURA BOA. Igual a PlayerStats/WorldVillages:
    um soluco do servidor nao pode fazer o painel regredir de "tenho dado"
    para "nada no ar", que e uma afirmacao falsa e tranquilizadora.
  - O BALDE `landed`. Comando cuja chegada ja passou vai para um balde
    proprio: nem somado aos que voam (mentira por afirmacao), nem escondido
    (mentira por omissao).

Rodar: python tests/test_in_flight.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game.in_flight import InFlight
from webmanager.utils import InFlightReader

_checks = 0
_failures = []


def _check(label, got, want):
    global _checks
    _checks += 1
    if got != want:
        _failures.append("%s: esperado %r, veio %r" % (label, want, got))
        print("  FALHOU %s: esperado %r, veio %r" % (label, want, got))
    else:
        print("  ok %s" % label)


def _check_true(label, got):
    _check(label, bool(got), True)


SERVER_CLOCK = ('<span id="serverTime">16:14:06</span>'
                '<span id="serverDate">22/09/2026</span>')

HEADER = (
    '<table id="commands_table"><tr><th>Comando (@COUNT@)</th>'
    '<th><a href="?order=start_name">Origem</a></th>'
    '<th><a href="?order=command_date_arrival">Chegada</a></th>'
    + "".join(
        '<th><a href="?order=%s"><img src="https://x/graphic/unit/unit_%s.webp" /></a></th>'
        % (u, u)
        for u in ("spear", "sword", "axe", "spy", "light", "heavy", "ram",
                  "catapult", "knight", "snob")
    )
    + "</tr>"
)


def _row(cid, ctype, arrival, units, label="Ataque a Aldeia de barbaros (598|315) K35",
         origin_id="40374", origin="BBM 024 (588|314) K35", snob_icon=False):
    order = ("spear", "sword", "axe", "spy", "light", "heavy", "ram",
             "catapult", "knight", "snob")
    cells = "".join("<td class='unit-item'>%d</td>" % units.get(u, 0) for u in order)
    icon = ('<span class="own_command" data-icon-hint="Com nobre " '
            'data-command-type="%s" data-command-id="%s">'
            '<img src="https://x/graphic/command/snob.webp" /></span>' % (ctype, cid)
            ) if snob_icon else ""
    return (
        '<tr class="nowrap row_ax"><td>'
        '<span class="own_command" data-icon-hint="Ataque pequeno (1-1000 tropas) " '
        'data-command-type="%s" data-command-id="%s">'
        '<img src="https://x/graphic/command/attack_small.webp" /></span>%s'
        '<span class="quickedit-label">%s</span></td>'
        '<td><a href="/game.php?screen=info_village&amp;id=%s">%s</a></td>'
        '<td>%s:<span class="grey small">000</span></td>%s</tr>'
        % (ctype, cid, icon, label, origin_id, origin, arrival, cells)
    )


def _page(rows, count=None):
    return (SERVER_CLOCK
            + HEADER.replace("@COUNT@", str(len(rows) if count is None else count))
            + "".join(rows) + "</table>")


class FakeResponse:
    def __init__(self, text):
        self.text = text


class FakeWrapper:
    """Wrapper de mentira: registra as URLs pedidas e devolve o que mandarem."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []

    def get_url(self, url):
        self.urls.append(url)
        item = self.responses.pop(0) if self.responses else None
        return FakeResponse(item) if isinstance(item, str) else item


# --------------------------------------------------------------------------
print("\n== a URL pede page=-1 (sem isso, 25 de 65 comandos, em silencio) ==")
tmpdir = tempfile.mkdtemp()
cache_file = os.path.join(tmpdir, "in_flight.json")
import game.in_flight as in_flight_mod
in_flight_mod.CACHE_PATH = cache_file

page = _page([_row("1", "attack", "hoje as 16:24:23", {"light": 8})])
wrapper = FakeWrapper([page])
flight = InFlight(wrapper=wrapper, config={})
_check("refresh aceito", flight.refresh("32056"), True)
_check("uma requisicao", len(wrapper.urls), 1)
_check_true("URL contem page=-1", "page=-1" in wrapper.urls[0])
_check_true("URL e a tela de comandos", "mode=commands" in wrapper.urls[0])
_check_true("URL usa a aldeia dada como endereco", "village=32056" in wrapper.urls[0])
_check("um comando lido", len(flight._commands), 1)


print("\n== TTL: nao rele dentro da janela, rele depois ==")
wrapper = FakeWrapper([page, page])
flight = InFlight(wrapper=wrapper, config={"in_flight": {"cache_seconds": 600}})
flight.refresh("32056")
_check("segunda chamada nao vai a rede", flight.refresh("32056"), False)
_check("continua uma requisicao", len(wrapper.urls), 1)
flight._fetched_at -= 601
_check("depois do TTL, rele", flight.refresh("32056"), True)
_check("duas requisicoes", len(wrapper.urls), 2)


print("\n== gate desligado e argumentos ausentes ==")
off = InFlight(wrapper=FakeWrapper([page]), config={"in_flight": {"enabled": False}})
_check("gate off nao le", off.refresh("32056"), False)
_check("sem wrapper nao le", InFlight(wrapper=None, config={}).refresh("32056"), False)
_check("sem aldeia nao le", InFlight(wrapper=FakeWrapper([page]), config={}).refresh(""), False)


print("\n== leitura ruim NUNCA apaga leitura boa ==")
bom = _page([_row("1", "attack", "hoje as 16:24:23", {"light": 8})])
wrapper = FakeWrapper([bom, None, "<html>login</html>"])
flight = InFlight(wrapper=wrapper, config={"in_flight": {"cache_seconds": 0}})
flight.refresh("32056")
_check("leitura boa guardada", len(flight._commands), 1)

_check("falha de rede rejeitada", flight.refresh("32056"), False)
_check("comandos preservados apos falha de rede", len(flight._commands), 1)
_check_true("motivo registrado", flight._last_error)

_check("markup irreconhecivel rejeitado", flight.refresh("32056"), False)
_check("comandos preservados apos markup ruim", len(flight._commands), 1)


print("\n== 'nada no ar' e uma leitura VALIDA, nao uma falha ==")
wrapper = FakeWrapper([_page([], count=0)])
flight = InFlight(wrapper=wrapper, config={})
_check("tabela vazia e aceita", flight.refresh("32056"), True)
_check("zero comandos", flight._commands, [])
_check_true("arquivo gravado", os.path.exists(cache_file))
saved = json.load(open(cache_file, encoding="utf-8"))
_check("cache reflete o vazio", saved["commands"], [])


print("\n== InFlightReader: flying x landed x unknown ==")
InFlightReader.CACHE_PATH = cache_file
NOW = 1790000000
payload = {
    "fetched_at": NOW - 300,
    "server_time": NOW - 300,
    "commands": [
        {"command_id": "a", "command_type": "attack", "arrival_ts": NOW + 3600,
         "arrival_text": "hoje as 17:00:00", "units": {"light": 50},
         "has_snob": False, "origin_label": "BBM 024 (588|314) K35",
         "label": "Ataque a X (598|315) K35", "target_coords": "598|315"},
        {"command_id": "b", "command_type": "attack", "arrival_ts": NOW + 60,
         "arrival_text": "hoje as 16:16:00", "units": {"snob": 1, "axe": 400},
         "has_snob": True, "origin_label": "BBM 011 (582|304) K35",
         "label": "Ataque a Y (582|289) K25", "target_coords": "582|289"},
        {"command_id": "c", "command_type": "return", "arrival_ts": NOW - 120,
         "arrival_text": "hoje as 16:13:00", "units": {"light": 8},
         "has_snob": False, "origin_label": "BBM 001 (570|300) K35",
         "label": "Retorno de Z (571|301) K35", "target_coords": "571|301"},
        {"command_id": "d", "command_type": "attack", "arrival_ts": None,
         "arrival_text": "quando der", "arrival_error": "formato nao reconhecido",
         "units": {}, "has_snob": False, "origin_label": "BBM 002 (572|302) K35",
         "label": "Ataque a W (573|303) K35", "target_coords": "573|303"},
    ],
}
with open(cache_file, "w", encoding="utf-8") as fh:
    json.dump(payload, fh)

out = InFlightReader.load(now=NOW)
_check("disponivel", out["available"], True)
_check("dois no ar", len(out["flying"]), 2)
_check("um ja deveria ter chegado", len(out["landed"]), 1)
_check("um sem hora legivel", len(out["unknown"]), 1)
_check("o que venceu NAO esta em flying",
       [c["command_id"] for c in out["flying"]], ["b", "a"])
_check("landed identificado", out["landed"][0]["command_id"], "c")
_check("unknown identificado", out["unknown"][0]["command_id"], "d")
_check("motivo do unknown preservado",
       out["unknown"][0]["arrival_error"], "formato nao reconhecido")

print("\n  -- ordenacao e contas --")
_check("flying ordenado pela chegada mais proxima",
       out["flying"][0]["command_id"], "b")
_check("eta em segundos", out["flying"][0]["eta_seconds"], 60)
_check("eta formatado", out["flying"][0]["eta_fmt"], "1m 00s")
_check("eta de 1h", out["flying"][1]["eta_fmt"], "1h 00m")
_check("nobres no ar", out["nobles_flying"], 1)

print("\n  -- totais contam SO o que ainda voa --")
# O retorno de 8 leves ja venceu: soma-lo em "tropa no ar" seria contar tropa
# que provavelmente ja esta em casa.
_check("totais so do que voa",
       out["totals"], {"Bárbaro": 400, "Cavalaria leve": 50, "Nobre": 1})
_check("rotulo pt-BR por unidade",
       out["flying"][0]["units_fmt"], "400 Bárbaro, 1 Nobre")

print("\n  -- idade e procedencia da leitura --")
_check("idade em segundos", out["age_seconds"], 300)
_check("idade formatada", out["age_fmt"], "5m 00s")
_check("procedencia da hora e o overview, nunca estimativa",
       out["flying"][0]["source"], "overview")
_check("tipo rotulado", out["flying"][0]["type_label"], "Ataque")
_check("retorno rotulado diferente de ataque",
       out["landed"][0]["type_label"], "Retorno")
_check("ataque conta como saindo", out["flying"][0]["is_outbound"], True)
_check("retorno NAO conta como saindo", out["landed"][0]["is_outbound"], False)


print("\n== sem arquivo: 'nao li' e diferente de 'nada no ar' ==")
InFlightReader.CACHE_PATH = os.path.join(tmpdir, "nao_existe.json")
out = InFlightReader.load(now=NOW)
_check("indisponivel", out["available"], False)
_check("sem comandos", out["flying"], [])
_check("sem idade inventada", out["age_seconds"], None)

InFlightReader.CACHE_PATH = os.path.join(tmpdir, "quebrado.json")
with open(InFlightReader.CACHE_PATH, "w", encoding="utf-8") as fh:
    fh.write("{isto nao e json")
out = InFlightReader.load(now=NOW)
_check("json quebrado degrada para indisponivel", out["available"], False)

InFlightReader.CACHE_PATH = os.path.join(tmpdir, "vazio.json")
with open(InFlightReader.CACHE_PATH, "w", encoding="utf-8") as fh:
    json.dump({"fetched_at": NOW - 10, "commands": []}, fh)
out = InFlightReader.load(now=NOW)
_check("leitura boa e vazia -> available False, mas com idade",
       (out["available"], out["age_seconds"]), (False, 10))


print("\n" + "=" * 70)
if _failures:
    print("FALHAS (%d de %d):" % (len(_failures), _checks))
    for f in _failures:
        print("  - " + f)
    sys.exit(1)
print("OK - %d checagens de in_flight passaram" % _checks)
