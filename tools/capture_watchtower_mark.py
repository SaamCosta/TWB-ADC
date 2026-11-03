"""
Captura da marca que a torre de vigia poe num ataque recebido (§9, item 30).

Por que existe (2026-11-03): o bot nao le a marca da torre (tamanho do
exercito e nobre), e a §6.2 tem a pendencia "falta capturar o markup" desde
que a BBM 002 tinha torre nivel 8. A dificuldade nunca foi a tela, foi saber
QUANDO olhar: a marca so aparece quando o ataque entra no alcance de uma torre.
O ataque 1460840129 contra a BBM 064 (88035) resolve isso, porque a hora de
entrada e calculavel: aríete/catapulta saindo de (510|571) as 12:52:34 de
03/11, rota a 3,15 campos da BBM 002 (nivel 20, alcance 15), entrada por volta
de 08/11 22:48:43 e chegada 10/11 11:02:12.

A mesma tela antes e depois da entrada e o par que serve de fixture (e de
guarda provada: o parser tem que achar a marca no `depois` e NAO achar no
`antes` -- decimo quinto padrao do CLAUDE.md):

    python tools/capture_watchtower_mark.py --label antes
    python tools/capture_watchtower_mark.py --label depois --at "2026-11-08 23:00"
    python tools/capture_watchtower_mark.py --compare antes depois

`--village` e `--command` servem para repetir com outro ataque.

Duas telas, um GET cada, `--interval` (padrao 90 s) entre elas:
  - `overview` da aldeia atacada: o widget de comandos que o
    `Extractor.incoming_commands` ja le. E aqui que a torre aparece: na
    captura `antes` (03/11) a linha ja trazia, ANTES da deteccao,
      <span class="commandicon-wt tooltip" data-command-id="1460840129"
            title="Ataque (será detectado por uma torre de vigia)">
    ou seja, o jogo avisa de antemao QUE vai detectar, nao QUANDO;
  - `info_command` do ataque. No `antes` nao tinha marca nenhuma; fica para
    ver se a deteccao acrescenta algo.
A lista de chegadas (`overview_villages&mode=incomings`) foi tirada depois da
primeira captura: numa conta sem premium o jogo devolve a visao de producao
com `mode: incomings` no `game_data`, sem linha de comando nenhuma.

Seguranca, reaproveitada do `tools/feature_map.py`: so GET com URL sem
`action`/`ajaxaction`/`h`, o `WebWrapper` do bot com os mesmos cabecalhos,
captcha aborta em vez de esperar, e qualquer `data-bot-protect` nao vazio
para tudo (memoria nunca-usar-priority-mode-ao-sondar). HTML bruto e resumo
vao para `cache/watchtower_mark/<label>/`, fora do git: as paginas tem token
de sessao e o nome do jogador atacante, e o repositorio e publico.
"""
import argparse
import datetime
import json
import os
import re
import sys
import time
from html import unescape
from urllib.parse import urlsplit

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.feature_map import (  # noqa: E402
    BOT_PROTECT_RE, extract_game_data, is_safe_query, session_lost, _wrapper,
)

OUT_ROOT = os.path.join("cache", "watchtower_mark")

SCREENS = [
    ("overview", "screen=overview"),
    ("info_command", "screen=info_command&id={command}&type=other"),
]

ATTR_RE = re.compile(r'\b(src|title|data-title|data-icon-hint|data-command-type|class)="([^"]*)"')


def command_blocks(html, command_id):
    """Os trechos da pagina que falam do comando: a `<tr>` que contem o id,
    ou, fora de tabela, 1.500 caracteres em volta. Um por ocorrencia, sem
    repetir trecho."""
    blocks = []
    for m in re.finditer(re.escape(str(command_id)), html):
        start = html.rfind("<tr", 0, m.start())
        end = html.find("</tr>", m.end())
        if start == -1 or end == -1 or m.start() - start > 4000:
            start, end = max(0, m.start() - 750), m.end() + 750
        else:
            end += len("</tr>")
        block = html[start:end]
        if block not in blocks:
            blocks.append(block)
    return blocks


def marks(block):
    """Icones e dicas de um trecho: tudo que pode carregar a marca da torre
    (imagem de tamanho, icone de nobre, tooltip). Ordem estavel, sem repetir."""
    seen = []
    for attr, value in ATTR_RE.findall(block):
        value = unescape(value).strip()
        if attr == "class" and not re.search(r"(?i)icon|command|snob|noble|watch", value):
            continue
        if value and (attr, value) not in seen:
            seen.append((attr, value))
    return seen


def _wait_until(when):
    target = datetime.datetime.strptime(when, "%Y-%m-%d %H:%M")
    while True:
        left = (target - datetime.datetime.now()).total_seconds()
        if left <= 0:
            return
        print("esperando ate %s (%.0f min)" % (when, left / 60), flush=True)
        time.sleep(min(left, 1800))


def capture(args):
    if args.at:
        _wait_until(args.at)
    w, _config = _wrapper()
    out_dir = os.path.join(OUT_ROOT, args.label)
    os.makedirs(out_dir, exist_ok=True)
    summary = {"label": args.label, "village": args.village,
               "command": args.command, "screens": {}}
    last = 0.0
    for key, query in SCREENS:
        query = query.format(command=args.command)
        if not is_safe_query(query):
            raise SystemExit("URL com acao recusada: %s" % query)
        wait = args.interval - (time.time() - last)
        if last and wait > 0:
            time.sleep(wait)
        last = time.time()
        res = w.get_url("game.php?village=%s&%s" % (args.village, query))
        at = time.strftime("%Y-%m-%d %H:%M:%S")
        if w.captcha_hit:
            raise SystemExit("captcha em %s: parado (resolver no navegador)" % key)
        if res is None:
            summary["screens"][key] = {"at": at, "status": None}
            print(key, "sem resposta")
            continue
        html = res.text or ""
        game_host = urlsplit(getattr(w, "endpoint", None) or res.url).netloc
        if session_lost(res.url, extract_game_data(html), game_host):
            raise SystemExit("sessao perdida em %s -> %s" % (key, res.url))
        with open(os.path.join(out_dir, key + ".html"), "w", encoding="utf-8") as fh:
            fh.write(html)
        protect = sorted(set(BOT_PROTECT_RE.findall(html)))
        blocks = command_blocks(html, args.command)
        entry = {"at": at, "status": res.status_code, "bot_protect": protect,
                 "blocks": len(blocks),
                 "marks": [marks(b) for b in blocks]}
        summary["screens"][key] = entry
        print("%s [%s] %d trecho(s) com o comando" % (key, res.status_code, len(blocks)))
        for i, found in enumerate(entry["marks"]):
            for attr, value in found:
                print("   #%d %s=%s" % (i, attr, value[:160]))
        if any(protect):
            _save(out_dir, summary)
            raise SystemExit("data-bot-protect=%s em %s: parado" % (protect, key))
    _save(out_dir, summary)
    print("gravado em", out_dir)


def _save(out_dir, summary):
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=1)


def compare(a, b):
    def load(label):
        with open(os.path.join(OUT_ROOT, label, "summary.json"), encoding="utf-8") as fh:
            return json.load(fh)
    sa, sb = load(a), load(b)
    for key in sorted(set(sa["screens"]) | set(sb["screens"])):
        ma = {tuple(x) for blk in sa["screens"].get(key, {}).get("marks", []) for x in blk}
        mb = {tuple(x) for blk in sb["screens"].get(key, {}).get("marks", []) for x in blk}
        print("== %s: %d marca(s) em %s, %d em %s" % (key, len(ma), a, len(mb), b))
        for attr, value in sorted(mb - ma):
            print("   + %s=%s" % (attr, value[:160]))
        for attr, value in sorted(ma - mb):
            print("   - %s=%s" % (attr, value[:160]))


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--label", help="nome da captura (antes, depois, ...)")
    p.add_argument("--village", default="88035", help="aldeia atacada")
    p.add_argument("--command", default="1460840129", help="id do comando recebido")
    p.add_argument("--at", help='esperar ate "AAAA-MM-DD HH:MM" antes de capturar')
    p.add_argument("--interval", type=float, default=90.0, help="segundos entre GETs")
    p.add_argument("--compare", nargs=2, metavar=("A", "B"), help="comparar duas capturas")
    args = p.parse_args(argv)
    if args.compare:
        compare(*args.compare)
    elif args.label:
        capture(args)
    else:
        p.error("informe --label ou --compare")


if __name__ == "__main__":
    main()
