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

A config nova HERDA a config viva (2026-11-24, troca br143 -> br147): as
preferencias do jogador (farm, conquista, Hunter, defesa, bandeiras, Telegram)
nao sao estado do mundo, e partir do template jogava fora ~50 ajustes. O que e
do mundo e zerado em `build_new_config()`: servidor, aldeias, area de
interesse (coordenada do mundo velho), deteccoes automaticas (`world.*` em
`None` para o bot redetectar) e as receitas de tropa dos perfis, que voltam
ao nome generico do template ("off"/"def"), resolvido por arqueiro em
`core/templates.py`. Um "off_no_archer" literal herdado num mundo com arqueiro
nunca recruta arqueiro, em silencio. `--from-template` volta ao comportamento
antigo (so `bot`, `reporting` e `notifications` sobrevivem).

Uso:
    python new_world_setup.py --world br147 \
        --endpoint https://br147.tribalwars.com.br/game.php
    python new_world_setup.py --world br147 --endpoint ... --apply

O arquivo `arquivo_<mundo>_<data>/` fica na raiz e esta no `.gitignore`: tem a
config inteira (sessao, token do Telegram).

Depois de rodar, ainda falta (nao da para automatizar):
    1. Painel no ar e o jogo aberto no mundo novo no Chrome: a extensao manda
       o `sid` para `POST /api/session` e `cache/session.json` nasce dali.
    2. Conferir a config gerada antes de soltar o bot.
"""
import argparse
import copy
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
    "cache/inventory", "cache/premium", "cache/farm_exclusions",
    "cache/cycles",
]

# Arquivos de cache/ que sao da CONTA, nao do mundo: copiados para o cache
# novo (o original fica no arquivo). `export_identity.json` e o que a
# exportacao publica usa para anonimizar; o mundo novo entra nele como termo
# extra, porque o repo continua citando o mundo velho.
CARRY_FILES = ["export_identity.json"]

# Deteccoes automaticas do mundo: `None` faz o bot redetectar no primeiro
# ciclo (twb.py, check_and_set).
WORLD_AUTODETECT = ["knight_enabled", "flags_enabled", "quests_enabled",
                    "boosters_enabled"]

# Secoes da config velha que sobrevivem a troca de mundo: sao preferencias da
# maquina/do jogador, nao estado do mundo.
KEEP_SECTIONS = ["bot", "reporting", "notifications"]

# Perfil de venda premium (docs/backend.md). Aplicado so com --seller.
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


def _fill_missing(dst, tpl):
    """Acrescenta em `dst` as chaves do template que faltam (recursivo)."""
    for key, value in tpl.items():
        if key not in dst:
            dst[key] = copy.deepcopy(value)
        elif (isinstance(value, dict) and isinstance(dst[key], dict)
              and key != "villages"):
            _fill_missing(dst[key], value)


def build_new_config(old, template, world, endpoint, seller=False,
                     inherit=True):
    """
    Config do mundo novo. Pura: nao le nem grava arquivo.

    `inherit=True` parte da config viva e zera o que e do mundo; `False` parte
    do template e so preserva KEEP_SECTIONS.
    """
    if inherit:
        new = copy.deepcopy(old)
        _fill_missing(new, template)
        # Versao igual a do template: o merge do twb.py nao roda de novo.
        new["build"] = copy.deepcopy(template["build"])
        tpl_aoi = template.get("conquest", {}).get("area_of_interest")
        if tpl_aoi is not None and "conquest" in new:
            new["conquest"]["area_of_interest"] = copy.deepcopy(tpl_aoi)
        for key in WORLD_AUTODETECT:
            if key in new.get("world", {}):
                new["world"][key] = None
        for name, prof in new.get("profile_templates", {}).items():
            tpl_prof = template.get("profile_templates", {}).get(name)
            if tpl_prof and "units" in tpl_prof and isinstance(prof, dict):
                prof["units"] = tpl_prof["units"]
    else:
        new = copy.deepcopy(template)
        for section in KEEP_SECTIONS:
            if section in old and section in new:
                for key in new[section]:
                    if key in old[section]:
                        new[section][key] = old[section][key]
    new["server"]["server"] = world
    new["server"]["endpoint"] = endpoint
    # Mundo recem-aberto ainda nao esta no twstats; ligar depois a mao.
    new["server"]["server_on_twstats"] = False
    new["villages"] = {}

    if seller:
        for (section, key), value in SELLER_OVERRIDES.items():
            if section in new and key in new[section]:
                new[section][key] = value
            else:
                print(f"  AVISO: {section}.{key} nao existe no template, ignorado")
    return new


def _leaf_diff(a, b, path=""):
    """(caminho, antes, depois) de cada folha diferente entre dois dicts."""
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b), key=str):
            out += _leaf_diff(a.get(key), b.get(key), f"{path}{key}.")
    elif a != b:
        out.append((path[:-1], a, b))
    return out


def carry_identity(ident, new_world, public_world="br999"):
    """Acrescenta o mundo novo como termo extra da exportacao publica."""
    ident = copy.deepcopy(ident)
    terms = ident.setdefault("extra_terms", [])
    if new_world != ident.get("world") and not any(
            t.get("term") == new_world for t in terms):
        terms.append({"term": new_world, "replacement": public_world})
    return ident


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
    ap.add_argument("--from-template", action="store_true",
                    help="parte do template em vez de herdar a config viva")
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
    print(f"config nova : {'template' if args.from_template else 'herda a viva'}")

    template = json.load(open(p("config.example.json"), encoding="utf-8"))
    new = build_new_config(old, template, args.world, args.endpoint,
                           seller=args.seller, inherit=not args.from_template)
    for path, before, after in _leaf_diff(old, new):
        if path.split(".")[0] in ("villages", "notifications") or "token" in path:
            continue
        print(f"  muda: {path}: {json.dumps(before, ensure_ascii=False)[:50]}"
              f" -> {json.dumps(after, ensure_ascii=False)[:50]}")

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
        # os.rename, e nao shutil.move: no Windows, com algum arquivo aberto
        # (painel no ar), o shutil.move cai para copiar + apagar e pode parar
        # no meio do apagar, deixando o mundo em dois lugares pela metade.
        try:
            os.rename(p("cache"), os.path.join(p(archive), "cache"))
        except OSError as exc:
            os.rmdir(p(archive))
            sys.exit(f"ABORTADO: nao consegui mover cache/ ({exc}). Pare o "
                     "painel (webmanager) e o bot e rode de novo; nada mudou.")
        print(f"  cache/ -> {archive}/cache/")
    shutil.copy2(p("config.json"), os.path.join(p(archive), "config.json"))
    print(f"  config.json -> {archive}/config.json")
    if os.path.exists(p("config.bak")):
        shutil.copy2(p("config.bak"), os.path.join(p(archive), "config.bak"))

    for d in CACHE_DIRS:
        os.makedirs(p(d), exist_ok=True)
    print(f"  cache/ recriado vazio ({len(CACHE_DIRS)} diretorios)")

    for name in CARRY_FILES:
        src_file = os.path.join(p(archive), "cache", name)
        if not os.path.exists(src_file):
            continue
        data = json.load(open(src_file, encoding="utf-8"))
        if name == "export_identity.json":
            data = carry_identity(data, args.world)
        with open(p(f"cache/{name}"), "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        print(f"  cache/{name} levado para o cache novo")

    with open(p("config.json"), "w", encoding="utf-8") as fh:
        json.dump(new, fh, indent=2, ensure_ascii=False)
    print("  config.json nova gravada")

    print("\nFalta a mao:")
    print("  1. Painel no ar e o jogo aberto no mundo novo no Chrome: a extensao")
    print("     manda o sid e grava cache/session.json.")
    print("  2. Conferir a config antes de soltar o bot.")
    print(f"  3. O mundo velho continua inteiro em {archive}/ -- nada foi apagado.")


if __name__ == "__main__":
    main()
