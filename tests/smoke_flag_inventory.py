"""
Sonda o inventario REAL de bandeiras da conta (somente leitura).

Fora do glob `test_*.py` de proposito: vai a rede com a sessao do bot.
Rodar na mao: python tests/smoke_flag_inventory.py

Pergunta que ele responde (docs/backend.md 6.3): a politica de bandeira conta
a OFERTA? O codigo atual (`DefenceManager.manage_flags`) colapsa
`setFlagCounts` em {tipo: maior_nivel_com_amount>0} e DESCARTA a quantidade.
Este script imprime a quantidade que o servidor publica, que e o dado que a
decisao precisaria e nao tem.

Nao escreve nada em cache/ nem toca a sessao do bot.

Duas notas de procedencia:

- O cliente aqui e `requests` puro, nao o `WebWrapper` do bot (7o padrao do
  CLAUDE.md: a resposta depende de como se pergunta). O cruzamento que torna
  a leitura confiavel mesmo assim: o inventario colapsado que esta tela
  produz -- {3:7, 4:7, 5:7, 6:4, 8:7} -- bate exatamente com o
  `available_flags` que 28 das 30 aldeias tem em cache/managed, e ESSE foi
  escrito pelo wrapper do proprio bot. Se o envelope diferisse, os dois
  numeros divergiriam.
- Existia uma versao descartavel disto em `cache/_smoke_flag_inventory.py`,
  que e gitignored e portanto invisivel para quem le o repositorio (23o
  padrao). Esta e a versao versionada.
"""
import json
import os
import re
import sys

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as fh:
        config = json.load(fh)
    with open(os.path.join(ROOT, "cache", "session.json"), encoding="utf-8") as fh:
        session_cache = json.load(fh)

    session = requests.Session()
    session.cookies.update(session_cache["cookies"])
    session.headers.update({
        "user-agent": config["bot"]["user_agent"],
        "accept": "text/html,application/xhtml+xml",
    })

    village_id = sys.argv[1] if len(sys.argv) > 1 else "41123"
    url = "%s?village=%s&screen=flags" % (config["server"]["endpoint"], village_id)
    response = session.get(url, timeout=30)
    print("GET %s -> %s (%d bytes)" % (url, response.status_code, len(response.text)))

    match = re.search(r"FlagsScreen\.setFlagCounts\((.+?)\);", response.text)
    if not match:
        print("setFlagCounts NAO casou -- sessao vencida ou markup novo?")
        return 1

    raw = json.loads(match.group(1))
    print("\n--- setFlagCounts cru (tipo -> nivel -> amount) ---")
    print(json.dumps(raw, indent=1, sort_keys=True))

    print("\n--- o que o bot guarda hoje (quantidade descartada) ---")
    collapsed = {}
    for flag_type in raw:
        for level in raw[flag_type]:
            for amount in raw[flag_type][level]:
                if int(amount) > 0:
                    key = int(flag_type)
                    if key not in collapsed or collapsed[key] < int(level):
                        collapsed[key] = int(level)
    print(json.dumps(collapsed, indent=1, sort_keys=True))

    print("\n--- oferta por (tipo, nivel), que e o dado que falta ---")
    for flag_type in sorted(raw, key=int):
        for level in sorted(raw[flag_type], key=int):
            amounts = raw[flag_type][level]
            total = sum(int(a) for a in amounts)
            if total:
                print("  tipo %s nivel %s -> %d disponivel(is)" % (flag_type, level, total))

    current = re.search(
        r'(?s)<div id="current_flag".+?/(\d+)_(\d+)\.\w+.+?<p>(.+?)</p>.+?</div>',
        response.text,
    )
    if current:
        print("\nbandeira equipada nesta aldeia: tipo %s nivel %s (%s)" % (
            current.group(1), current.group(2), current.group(3).strip()
        ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
