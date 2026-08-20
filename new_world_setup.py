"""
Arquiva o mundo atual e prepara a config para um mundo novo.

Existe porque a limpeza automatica do bot NAO serve para troca de mundo. O que
`TWB.get_overview()` faz (twb.py, por volta da linha 283) e apagar as entradas
de `cache/managed/` e as aldeias de `config["villages"]` que o servidor nao
devolve mais -- ou seja, ao apontar a config para outro mundo ele apaga
exatamente a configuracao que voce quer preservar, e MANTEM o resto do cache
(relatorios, mapa, zonas, sessao), que passa a servir dado de um mundo que nao
e mais o seu. `cache/villages/` e o pior: e dado de mapa por ID/coordenada.

Este script faz o inverso: guarda tudo do mundo velho num diretorio datado e
entrega um `cache/` limpo com uma `config.json` nova.

SEGURANCA: nao faz nada sem `--apply`. Sem a flag, so imprime o plano.

Uso:
    python new_world_setup.py --world br144 \
        --endpoint https://br144.tribalwars.com.br/game.php
    python new_world_setup.py --world br144 --endpoint ... --apply

Depois de rodar, ainda falta (nao da para automatizar):
    1. Logar no mundo novo no navegador e dar a string de cookie ao bot na
       primeira execucao -- `cache/session.json` nasce dali.
    2. Conferir a config gerada antes de soltar o bot.
"""
import argparse
import json
import os
import shutil
import sys
import time

# Diretorios de cache recriados vazios (mesma lista de twb.py::init).
CACHE_DIRS = [
    "cache/attacks", "cache/reports", "cache/villages", "cache/world",
    "cache/logs", "cache/managed", "cache/hunter", "cache/zones",
    "cache/pvp_conquest", "cache/resource_sharing", "cache/statue",
    "cache/inventory", "cache/premium",
]

# Secoes da config velha que sobrevivem a troca de mundo: sao preferencias da
# maquina/do jogador, nao estado do mundo.
KEEP_SECTIONS = ["bot", "reporting", "notifications"]

# Perfil de venda premium (docs/troca_premium.md). Aplicado so com --seller.
SELLER_OVERRIDES = {
    ("world", "trade_for_premium"): True,
    ("farms", "farm"): False,
    ("building", "default"): "premium_seller",
    ("units", "default"): "premium_seller",
    ("village_template", "trade_for_premium"): True,
    ("village_template", "gather_enabled"): True,
    ("village_template", "building"): "premium_seller",
    ("village_template", "units"): "premium_seller",
    ("village_template", "snobs"): 0,
    ("village_template", "conquest_enabled"): False,
    ("conquest", "enabled"): False,
    ("resource_sharing", "enabled"): False,
    ("zones", "enabled"): False,
}

root = os.path.dirname(os.path.abspath(__file__))


def p(path):
    return os.path.join(root, path)


def _recent_log_write(seconds=2700):
    """
    Devolve o nome do arquivo de log escrito ha menos de `seconds`, ou None.
    Serve para detectar que o bot esta de pe sem inspecionar processo.

    ⚠️ A janela e DELIBERADAMENTE larga (45 min). A primeira versao usava 120s
    e nao detectava nada: o bot dorme entre ciclos e so escreve log na fase
    ativa -- num teste de 2026-08-20, com o bot claramente de pe, o log mais
    recente tinha 526s. E `bot.inactive_delay` chega a 2000s fora do horario
    ativo, entao ate 45 min e apertado.

    Errar para falso positivo e o lado certo: o custo e o usuario passar
    --force; o custo do falso negativo e mover cache/ no meio de uma gravacao
    do bot e corromper o arquivo do mundo inteiro.
    """
    logs = p("cache/logs")
    if not os.path.isdir(logs):
        return None
    now = time.time()
    for name in os.listdir(logs):
        full = os.path.join(logs, name)
        try:
            if now - os.path.getmtime(full) < seconds:
                return f"cache/logs/{name}"
        except OSError:
            continue
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", required=True, help="ex: br144")
    ap.add_argument("--endpoint", required=True,
                    help="ex: https://br144.tribalwars.com.br/game.php")
    ap.add_argument("--seller", action="store_true",
                    help="aplica o perfil de aldeia vendedora de PP")
    ap.add_argument("--apply", action="store_true",
                    help="sem isto, so imprime o plano")
    ap.add_argument("--force", action="store_true",
                    help="ignora a guarda de 'bot parece estar rodando'")
    args = ap.parse_args()

    if not os.path.exists(p("config.json")):
        sys.exit("config.json nao existe -- nada a arquivar, rode o bot uma vez")
    if not os.path.exists(p("config.example.json")):
        sys.exit("config.example.json nao existe")

    old = json.load(open(p("config.json"), encoding="utf-8"))
    old_world = old.get("server", {}).get("server", "desconhecido")
    stamp = time.strftime("%Y%m%d")
    archive = f"arquivo_{old_world}_{stamp}"

    print(f"mundo atual : {old_world}")
    print(f"mundo novo  : {args.world}")
    print(f"arquivo     : {archive}/")
    print(f"aldeias que saem da config: {len(old.get('villages', {}))}")
    if os.path.exists(p("cache")):
        total = sum(len(f) for _, _, f in os.walk(p("cache")))
        print(f"arquivos em cache/ a arquivar: {total}")
    print(f"perfil vendedor: {'SIM' if args.seller else 'nao'}")

    if not args.apply:
        print("\n[plano apenas] rode de novo com --apply para executar.")
        return

    if os.path.exists(p(archive)):
        sys.exit(f"{archive}/ ja existe -- mova ou apague antes")

    # O bot escreve em cache/ o tempo todo; mover o diretorio no meio de uma
    # gravacao corrompe o arquivo. Heuristica portavel: se algo em cache/logs/
    # mudou nos ultimos 2 minutos, ele esta de pe.
    busy = _recent_log_write()
    if busy and not args.force:
        sys.exit(
            f"ABORTADO: {busy} foi escrito nos ultimos 45 minutos -- o bot pode "
            "estar rodando.\n"
            "Pare o processo (twb.py), confirme com Get-Process python, e rode "
            "de novo.\n"
            "Se tiver certeza de que ele esta parado, use --force."
        )

    os.makedirs(p(archive))
    if os.path.exists(p("cache")):
        shutil.move(p("cache"), os.path.join(p(archive), "cache"))
        print(f"  cache/ -> {archive}/cache/")
    shutil.copy2(p("config.json"), os.path.join(p(archive), "config.json"))
    print(f"  config.json -> {archive}/config.json")
    if os.path.exists(p("config.bak")):
        shutil.copy2(p("config.bak"), os.path.join(p(archive), "config.bak"))

    for d in CACHE_DIRS:
        os.makedirs(p(d), exist_ok=True)
    print(f"  cache/ recriado vazio ({len(CACHE_DIRS)} diretorios)")

    # Config nova a partir do template, preservando o que e da maquina.
    new = json.load(open(p("config.example.json"), encoding="utf-8"))
    new["server"]["server"] = args.world
    new["server"]["endpoint"] = args.endpoint
    for section in KEEP_SECTIONS:
        if section in old and section in new:
            for key in new[section]:
                if key in old[section]:
                    new[section][key] = old[section][key]
    new["villages"] = {}

    if args.seller:
        for (section, key), value in SELLER_OVERRIDES.items():
            if section in new and key in new[section]:
                new[section][key] = value
            else:
                print(f"  AVISO: {section}.{key} nao existe no template, ignorado")
        print("  perfil vendedor aplicado")

    with open(p("config.json"), "w", encoding="utf-8") as fh:
        json.dump(new, fh, indent=2, ensure_ascii=False)
    print("  config.json nova gravada")

    print("\nFalta a mao:")
    print("  1. Logar no mundo novo no navegador; o bot pede a string de cookie")
    print("     na primeira execucao e grava cache/session.json.")
    print("  2. Conferir a config antes de soltar o bot.")
    print(f"  3. O mundo velho continua inteiro em {archive}/ -- nada foi apagado.")


if __name__ == "__main__":
    main()
