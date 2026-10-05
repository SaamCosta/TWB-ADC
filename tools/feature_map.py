"""
Mapeamento de funcionalidades da conta: o que o jogo mostra com premium,
gerente de conta e assistente de saque, e o que mostra sem eles.

Por que existe: o bot e feito para conta gratuita, com uma camada ativavel
quando o recurso pago for detectado (memoria `bot-alvo-conta-gratuita`). Para
desenhar as duas camadas e preciso saber, tela por tela, o que e pago. A KB
oficial so lista as vantagens por alto, e a §8.25 de `docs/backend.md` ficou
com varios "premium? (a confirmar)". A resposta certa vem de medir a MESMA
lista de telas, com o MESMO instrumento, nas duas situacoes, e comparar:

    python tools/feature_map.py capture --label premium      # com tudo ativo
    python tools/feature_map.py capture --label premium      # 2a vez: piso de ruido
    python tools/feature_map.py capture --label free         # depois que vencer
    python tools/feature_map.py compare <dirA> <dirB>        # o que mudou

A segunda captura com premium nao e redundancia: ela mede o que muda entre
dois dias sem mudar a conta (ordens do gerente, relatorios novos, comandos no
ar). Sem esse piso, qualquer diferenca premium x gratis seria ambigua
(decimo primeiro padrao do CLAUDE.md: saber se o conjunto e um conjunto).

Regras de seguranca, todas impostas no codigo e nao so aqui:
- **so GET**, e nenhuma URL com `action=`, `ajaxaction=` ou `h=` (as tres
  marcam acao que muda estado no jogo);
- o cliente e o `WebWrapper` do bot, com os mesmos cabecalhos (setimo padrao);
- uma requisicao a cada `--interval` segundos (padrao 60) e **parada** no
  primeiro `data-bot-protect` diferente de vazio: o limite de taxa e da conta
  e soma todos os clientes (memoria `nunca-usar-priority-mode-ao-sondar`).
  Rodar com o bot dormindo (fora de `active_hours`) e sem navegar no jogo;
- nao troca grupo de aldeias (nenhum `group=` na URL); a visao geral que o
  jogo lembra por aba ja e tratada pelo bot com `mode=prod` explicito (§8.37);
- HTML bruto e resumo vao para `cache/feature_map/` (fora do git): as paginas
  tem token de sessao e nome de jogador, e o repositorio e publico.
"""
import argparse
import gzip
import json
import os
import random
import re
import sys
import time
from html import unescape
from urllib.parse import parse_qsl, urlsplit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

OUT_DIR = os.path.join("cache", "feature_map")

# Aldeia de referencia: a de mais edificios construidos (BBM 003, 16 de 17 --
# so falta a torre). A torre e lida na BBM 002, que tem torre nivel 8.
DEFAULT_VILLAGE = "44683"
DEFAULT_TOWER_VILLAGE = "38409"

# A lista fixa. Cada item: (chave, querystring sem `village=`, aldeia).
# "v" = aldeia de referencia, "t" = aldeia com torre. A ordem e a de captura:
# primeiro o que o bot consome (e o que pode quebrar no dia em que o premium
# vencer), depois o que a §8.25 deixou "a confirmar", depois o resto.
SCREENS = [
    # --- consumidas pelo bot hoje -----------------------------------------
    ("overview", "screen=overview", "v"),
    ("overview_villages", "screen=overview_villages", "v"),
    ("overview_villages/prod", "screen=overview_villages&mode=prod", "v"),
    ("overview_villages/commands", "screen=overview_villages&mode=commands&page=-1", "v"),
    ("main", "screen=main", "v"),
    ("barracks", "screen=barracks", "v"),
    ("stable", "screen=stable", "v"),
    ("garage", "screen=garage", "v"),
    ("snob", "screen=snob", "v"),
    ("smith", "screen=smith", "v"),
    ("statue", "screen=statue", "v"),
    ("statue/overview", "screen=statue&mode=overview", "v"),
    ("watchtower", "screen=watchtower", "t"),
    ("place", "screen=place", "v"),
    ("place/units", "screen=place&mode=units", "v"),
    ("place/scavenge", "screen=place&mode=scavenge", "v"),
    ("market", "screen=market", "v"),
    ("market/send", "screen=market&mode=send", "v"),
    ("market/other_offer", "screen=market&mode=other_offer", "v"),
    ("market/own_offer", "screen=market&mode=own_offer", "v"),
    ("market/all_own_offer", "screen=market&mode=all_own_offer", "v"),
    ("market/exchange", "screen=market&mode=exchange", "v"),
    ("flags", "screen=flags", "v"),
    ("inventory", "screen=inventory", "v"),
    ("report/all", "screen=report&mode=all", "v"),
    ("map", "screen=map", "v"),
    ("info_player", "screen=info_player", "v"),
    ("info_player/stats_own", "screen=info_player&mode=stats_own", "v"),
    ("ally", "screen=ally", "v"),
    ("ally/reservations", "screen=ally&mode=reservations", "v"),
    # --- §8.25: "premium? (a confirmar)" ----------------------------------
    ("overview_villages/combined", "screen=overview_villages&mode=combined", "v"),
    ("overview_villages/trader", "screen=overview_villages&mode=trader", "v"),
    ("overview_villages/units", "screen=overview_villages&mode=units", "v"),
    ("overview_villages/buildings", "screen=overview_villages&mode=buildings", "v"),
    ("overview_villages/tech", "screen=overview_villages&mode=tech", "v"),
    ("overview_villages/groups", "screen=overview_villages&mode=groups", "v"),
    ("overview_villages/incomings", "screen=overview_villages&mode=incomings", "v"),
    ("train", "screen=train", "v"),
    ("train/mass", "screen=train&mode=mass", "v"),
    ("place/scavenge_mass", "screen=place&mode=scavenge_mass", "v"),
    ("place/call", "screen=place&mode=call", "v"),
    ("market/call", "screen=market&mode=call", "v"),
    ("report/filter", "screen=report&mode=filter", "v"),
    ("snob/coin", "screen=snob&mode=coin", "v"),
    # --- gerente de conta e assistente de saque ---------------------------
    ("am_farm", "screen=am_farm", "v"),
    ("am_village", "screen=am_village", "v"),
    ("am_troops", "screen=am_troops", "v"),
    ("am_research", "screen=am_research", "v"),
    ("am_warehouse", "screen=am_warehouse", "v"),
    ("am_market", "screen=am_market", "v"),
    ("am_notify", "screen=am_notify", "v"),
    # --- premium: o proprio jogo diz o que vende e quando vence ----------
    ("premium", "screen=premium", "v"),
    ("premium/use", "screen=premium&mode=use", "v"),
    ("premium/feature_log", "screen=premium&mode=feature_log", "v"),
    # "Vantagens" de cada produto: a lista oficial, dentro do jogo, do que
    # cada um da (a KB manda ver aqui). A descoberta agrupa por tela/modo e
    # so pegou uma das tres na captura 1 -- por isso estao na lista fixa.
    ("premium/help/Premium", "screen=premium&mode=help&feature=Premium", "v"),
    ("premium/help/AccountManager", "screen=premium&mode=help&feature=AccountManager", "v"),
    ("premium/help/FarmAssistent", "screen=premium&mode=help&feature=FarmAssistent", "v"),
    # --- o resto da interface ---------------------------------------------
    ("place/templates", "screen=place&mode=templates", "v"),
    ("place/neighbor", "screen=place&mode=neighbor", "v"),
    ("place/sim", "screen=place&mode=sim", "v"),
    ("market/traders", "screen=market&mode=traders", "v"),
    ("market/transports", "screen=market&mode=transports", "v"),
    ("wall", "screen=wall", "v"),
    ("farm", "screen=farm", "v"),
    ("storage", "screen=storage", "v"),
    ("hide", "screen=hide", "v"),
    ("wood", "screen=wood", "v"),
    ("stone", "screen=stone", "v"),
    ("iron", "screen=iron", "v"),
    ("report", "screen=report", "v"),
    ("info_player/daily_bonus", "screen=info_player&mode=daily_bonus", "v"),
    ("relic_system", "screen=relic_system", "v"),
    ("memo", "screen=memo", "v"),
    ("settings/settings", "screen=settings&mode=settings", "v"),
    ("settings/quickbar", "screen=settings&mode=quickbar", "v"),
]

# Parametros que tornam uma URL uma acao, e nao uma leitura.
FORBIDDEN_PARAMS = ("action", "ajaxaction", "h")

# Na descoberta (segunda passada), telas que nao se abrem: privadas sem valor
# para o mapeamento (correio, forum, conta), compra/transferencia de pontos
# premium, e listas enormes sem relacao com recurso pago.
DISCOVERY_DENY_SCREENS = {
    "mail", "forum", "ranking", "buddies", "info_command", "info_village",
    "info_ally", "api", "logout", "help", "unit_info", "redir",
    # redireciona para forum.tribalwars.com.br (outro host); lido na captura 1
    "extforum",
}
DISCOVERY_DENY_PAIRS = {
    ("premium", "transfer"), ("premium", "premium"), ("premium", "cosmetics"),
    ("settings", "account"), ("settings", "email"), ("settings", "change_passwd"),
    ("settings", "delete"), ("settings", "sitter"), ("settings", "vacation"),
    ("settings", "ref"), ("settings", "push"), ("settings", "share"),
}

# Parametros que entram na chave normalizada de um link. Ids, paginas,
# coordenadas e tokens ficam de fora: mudam todo dia e nao dizem nada sobre
# o que a conta pode acessar.
LINK_KEEP = ("screen", "mode", "type", "subtype", "feature", "ajax", "ajaxaction", "action", "try")

BOT_PROTECT_RE = re.compile(r'data-bot-protect="(\w*)"')
HREF_RE = re.compile(r'(?:href|action|data-url|data-href)="([^"]*game\.php\?[^"]*)"')
FORM_RE = re.compile(r'<form\b[^>]*>', re.I)
INPUT_RE = re.compile(r'<(?:input|select|textarea|button)\b[^>]*\bname="([^"]+)"', re.I)
JS_MODULE_RE = re.compile(r'\b([A-Z][A-Za-z0-9_]{2,})\.(init[A-Za-z]*|setup|start)\(')
TABLE_ID_RE = re.compile(r'<table\b[^>]*\bid="([^"]+)"', re.I)
HEADING_RE = re.compile(r'<h([1-4])\b[^>]*>(.*?)</h\1>', re.I | re.S)
TAG_RE = re.compile(r'<[^>]+>')
ERROR_BOX_RE = re.compile(r'<div class="(error_box|info_box)"[^>]*>(.*?)</div>', re.S)
PREMIUM_CLASS_RE = re.compile(r'class="([^"]*(?:premium|locked|inactive|disabled)[^"]*)"', re.I)
# O jogo decide parte do que e premium no CLIENTE: `<body class="... has-pa">`
# na conta com premium, e o CSS esconde o aviso `premium_account_hint` e
# libera o bloco `premium-required`. O aviso vem no HTML nas duas situacoes
# (captura 1, coleta em massa), entao o texto dele e a classe do body sao os
# sinais -- sem eles, uma tela que so muda por CSS sairia "igual".
BODY_CLASS_RE = re.compile(r'<body\b[^>]*\bclass="([^"]*)"', re.I)
HINT_RE = re.compile(r'class="premium_account_hint"[^>]*>(.*?)</div>\s*</div>', re.S)
DATA_FEATURE_RE = re.compile(r'data-feature="([A-Za-z]+)"')
DIGITS_RE = re.compile(r'\d+')


class CaptchaHit(Exception):
    pass


# ---------------------------------------------------------------------------
# Logica pura (testada em tests/test_feature_map.py)
# ---------------------------------------------------------------------------

def is_safe_query(query):
    """True se a querystring so le. Recusa `action`, `ajaxaction` e `h`."""
    params = dict(parse_qsl(query, keep_blank_values=True))
    return not any(p in params for p in FORBIDDEN_PARAMS)


def normalize_link(href):
    """`game.php?village=1&screen=x&mode=y&id=9&h=ab` -> `x&mode=y`.

    Devolve None para o que nao e link de tela do jogo."""
    href = unescape(href)
    query = urlsplit(href).query if "?" in href else ""
    params = dict(parse_qsl(query, keep_blank_values=True))
    screen = params.get("screen")
    if not screen:
        return None
    parts = [screen]
    for key in LINK_KEEP[1:]:
        if key in params:
            parts.append("%s=%s" % (key, params[key]))
    return "&".join(parts)


def _text(html_fragment):
    return re.sub(r"\s+", " ", unescape(TAG_RE.sub(" ", html_fragment))).strip()


def _redact_text(text):
    """Numeros viram `#`: contagens e horarios mudam todo dia, e a pergunta
    e se o bloco existe, nao quanto ele diz."""
    return DIGITS_RE.sub("#", text)[:200]


def extract_game_data(html):
    from core.game_data_shadow import extract_game_data as _extract
    try:
        return _extract(html) or {}
    except Exception:
        return {}


def fingerprint(html):
    """Resumo estrutural de uma pagina, estavel entre dias e sensivel ao que
    um recurso pago acrescenta ou tira: links, formularios, campos, endpoints
    de acao, modulos JS, tabelas, titulos, caixas de aviso e chamadas de
    compra. Nada de valor numerico de jogo."""
    gd = extract_game_data(html)
    links = set()
    endpoints = set()
    premium_links = set()
    for href in HREF_RE.findall(html):
        key = normalize_link(href)
        if not key:
            continue
        if "ajaxaction=" in key or "action=" in key:
            endpoints.add(key)
        else:
            links.add(key)
        if key.startswith("premium"):
            premium_links.add(key)
    forms = set()
    for tag in FORM_RE.findall(html):
        m = re.search(r'action="([^"]*)"', tag)
        if m:
            forms.add(normalize_link(m.group(1)) or "(externo)")
    inputs = sorted({DIGITS_RE.sub("#", n) for n in INPUT_RE.findall(html)})
    boxes = sorted({"%s: %s" % (cls, _redact_text(_text(body)))
                    for cls, body in ERROR_BOX_RE.findall(html) if _text(body)})
    headings = sorted({_redact_text(_text(body)) for _, body in HEADING_RE.findall(html)
                       if _text(body)})
    features = {}
    for name, info in (gd.get("features") or {}).items():
        if isinstance(info, dict):
            features[name] = {k: info.get(k) for k in ("possible", "active")}
    return {
        "screen": gd.get("screen"),
        "mode": gd.get("mode"),
        "features": features,
        "bot_protect": sorted(set(BOT_PROTECT_RE.findall(html))),
        "size": len(html),
        "links": sorted(links),
        "endpoints": sorted(endpoints),
        "premium_links": sorted(premium_links),
        "forms": sorted(forms),
        "inputs": inputs,
        "js_modules": sorted({"%s.%s" % m for m in JS_MODULE_RE.findall(html)}),
        "tables": sorted({DIGITS_RE.sub("#", t) for t in TABLE_ID_RE.findall(html)}),
        "headings": headings,
        "boxes": boxes,
        "premium_classes": sorted({c.strip() for c in PREMIUM_CLASS_RE.findall(html)}),
        "body_classes": sorted(set((BODY_CLASS_RE.search(html) or [None, ""])[1].split())),
        "premium_hints": sorted({_redact_text(_text(h)) for h in HINT_RE.findall(html)}),
        "data_features": sorted(set(DATA_FEATURE_RE.findall(html))),
    }


SET_FIELDS = ("links", "endpoints", "premium_links", "forms", "inputs",
              "js_modules", "tables", "headings", "boxes", "premium_classes",
              "body_classes", "premium_hints", "data_features")


def compare_fingerprints(a, b):
    """Diferenca entre duas capturas da mesma tela. `a`/`b` podem ser None
    (tela que so existe numa das capturas). Devolve dict vazio se igual."""
    if a is None or b is None:
        return {"presence": ("ausente" if a is None else "presente",
                             "ausente" if b is None else "presente")}
    diff = {}
    for field in ("status", "final", "screen", "mode", "bot_protect"):
        if a.get(field) != b.get(field):
            diff[field] = (a.get(field), b.get(field))
    if a.get("features") != b.get("features"):
        diff["features"] = (a.get("features"), b.get("features"))
    for field in SET_FIELDS:
        sa, sb = set(a.get(field) or ()), set(b.get(field) or ())
        if sa != sb:
            diff[field] = {"so_em_a": sorted(sa - sb), "so_em_b": sorted(sb - sa)}
    sa, sb = a.get("size") or 0, b.get("size") or 0
    if sa and sb and (max(sa, sb) / min(sa, sb)) > 1.5:
        diff["size"] = (sa, sb)
    return diff


def discover(fingerprints, captured_keys):
    """Telas linkadas a partir das capturadas e que ainda nao foram lidas,
    filtradas pelas listas de negacao. Devolve querystrings ordenadas."""
    seen = set()
    for fp in fingerprints.values():
        for link in fp.get("links") or ():
            seen.add(link)
    out = []
    for link in sorted(seen):
        parts = dict(p.split("=", 1) for p in link.split("&")[1:])
        screen = link.split("&")[0]
        mode = parts.get("mode")
        if screen in DISCOVERY_DENY_SCREENS or (screen, mode) in DISCOVERY_DENY_PAIRS:
            continue
        if any(k in parts for k in ("ajax", "ajaxaction", "action")):
            continue
        key = screen + ("/" + mode if mode else "")
        if key in captured_keys:
            continue
        query = "screen=" + screen + "".join("&%s=%s" % kv for kv in parts.items())
        if not is_safe_query(query):
            continue
        captured_keys = captured_keys | {key}
        out.append((key, query))
    return out


# ---------------------------------------------------------------------------
# Captura (rede)
# ---------------------------------------------------------------------------

def _wrapper():
    from core.filemanager import FileManager
    from core.request import WebWrapper

    class CaptureWrapper(WebWrapper):
        """O wrapper do bot, com uma diferenca: captcha nao espera, aborta.
        O do bot espera sem limite (§8.9), o que aqui deixaria a captura
        presa e somando reconferencias na taxa da conta."""
        captcha_hit = False

        def _await_captcha_clear(self, probe_url, headers=None):
            self.captcha_hit = True
            return None

    config = json.load(open("config.json", encoding="utf-8"))
    srv = config["server"]
    w = CaptureWrapper(url=srv["endpoint"], server=srv["server"],
                       endpoint=srv["endpoint"], reporter_enabled=False)
    session = FileManager.load_json_file("cache/session.json")
    if not session:
        raise SystemExit("sem cache/session.json")
    w.web.cookies.update(session["cookies"])
    if config.get("bot", {}).get("user_agent"):
        w.headers["user-agent"] = config["bot"]["user_agent"]
    w.priority_mode = False  # nunca: memoria nunca-usar-priority-mode-ao-sondar
    return w, config


def _active_hours(config):
    raw = (config.get("bot") or {}).get("active_hours") or "6-23"
    try:
        start, end = (int(x) for x in str(raw).split("-"))
        return start, end
    except ValueError:
        return 6, 23


def _fetch(w, run_dir, key, query, village_id, interval, last_start):
    if not is_safe_query(query):
        raise ValueError("URL com acao recusada: %s" % query)
    wait = interval + random.uniform(-0.15, 0.15) * interval - (time.time() - last_start)
    if wait > 0:
        time.sleep(wait)
    started = time.time()
    url = "game.php?village=%s&%s" % (village_id, query)
    res = w.get_url(url)
    elapsed = time.time() - started
    if w.captcha_hit:
        raise CaptchaHit(key)
    record = {"key": key, "query": query, "village": village_id,
              "at": time.strftime("%Y-%m-%d %H:%M:%S"), "elapsed": round(elapsed, 1)}
    if res is None:
        record["status"] = None
        return record, started
    html = res.text or ""
    record["status"] = res.status_code
    final = normalize_link(res.url) or res.url.split("?")[0]
    record["final"] = final
    fp = fingerprint(html)
    record.update(fp)
    fname = key.replace("/", "__") + ".html.gz"
    with gzip.open(os.path.join(run_dir, "pages", fname), "wt", encoding="utf-8") as f:
        f.write(html)
    if any(v for v in fp["bot_protect"]):
        # `pending` antecede o `forced`: parar aqui e o que evita o captcha.
        raise CaptchaHit("%s (data-bot-protect=%s)" % (key, fp["bot_protect"]))
    return record, started


def _save(run_dir, manifest, records):
    with open(os.path.join(run_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    with open(os.path.join(run_dir, "fingerprints.json"), "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=1)


def capture(args):
    w, config = _wrapper()
    start, end = _active_hours(config)
    hour = time.localtime().tm_hour
    if start <= hour < end and not args.force:
        raise SystemExit(
            "%02dh esta dentro de active_hours (%d-%d): o bot esta fazendo ~3,5 "
            "req/min e a captura somaria acima do limite da conta. Rodar fora "
            "da janela, ou --force sabendo disso." % (hour, start, end))
    stamp = time.strftime("%Y%m%d_%H%M")
    run_dir = os.path.join(OUT_DIR, "%s_%s" % (args.label, stamp))
    os.makedirs(os.path.join(run_dir, "pages"), exist_ok=True)
    villages = {"v": args.village, "t": args.tower}
    manifest = {"label": args.label, "started": time.strftime("%Y-%m-%d %H:%M:%S"),
                "village": args.village, "tower_village": args.tower,
                "interval": args.interval, "screens_fixed": len(SCREENS),
                "aborted": None}
    records = {}
    last = 0.0
    queue = [(k, q, villages[v]) for k, q, v in SCREENS]
    if args.only:
        wanted = set(args.only.split(","))
        queue = [item for item in queue if item[0] in wanted]
    discovered_pass = False
    try:
        while True:
            for i, (key, query, vid) in enumerate(queue, 1):
                rec, last = _fetch(w, run_dir, key, query, vid, args.interval, last)
                records[key] = rec
                print("[%s] %d/%d %-34s %s %s -> %s%s" % (
                    rec["at"][11:], i, len(queue), key, rec.get("status"),
                    rec.get("size"), rec.get("final"),
                    "  !! " + rec["boxes"][0] if rec.get("boxes") else ""), flush=True)
                _save(run_dir, manifest, records)
            if discovered_pass or not args.discover:
                break
            extra = discover(records, set(records))[:args.discover_max]
            manifest["discovered"] = [k for k, _ in extra]
            print("descoberta: %d tela(s) linkada(s) ainda nao lidas" % len(extra), flush=True)
            queue = [(k, q, args.village) for k, q in extra]
            discovered_pass = True
    except CaptchaHit as exc:
        manifest["aborted"] = "bot protection em %s" % exc
        print("PARADO: %s. Nada mais sera pedido." % manifest["aborted"], flush=True)
    except KeyboardInterrupt:
        manifest["aborted"] = "interrompido"
    manifest["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    manifest["captured"] = len(records)
    first = next((r for r in records.values() if r.get("features")), None)
    manifest["features"] = first.get("features") if first else None
    _save(run_dir, manifest, records)
    print("salvo em %s (%d telas)" % (run_dir, len(records)))


# ---------------------------------------------------------------------------
# Comparacao
# ---------------------------------------------------------------------------

def _load(run_dir):
    with open(os.path.join(run_dir, "fingerprints.json"), encoding="utf-8") as f:
        return json.load(f)


def refingerprint(args):
    """Recalcula o resumo de cada tela a partir do HTML salvo, mantendo os
    metadados da captura (status, url final, hora). Assim uma captura antiga
    e comparada com a mesma versao do resumo que uma nova -- o instrumento
    pode ganhar um campo sem invalidar o que ja foi medido."""
    records = _load(args.run)
    for key, rec in records.items():
        path = os.path.join(args.run, "pages", key.replace("/", "__") + ".html.gz")
        if not os.path.exists(path):
            continue
        with gzip.open(path, "rt", encoding="utf-8") as f:
            rec.update(fingerprint(f.read()))
    with open(os.path.join(args.run, "fingerprints.json"), "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=1)
    print("%d tela(s) recalculada(s) em %s" % (len(records), args.run))


def compare(args):
    a, b = _load(args.a), _load(args.b)
    noise = {}
    if args.noise:
        n1, n2 = _load(args.noise[0]), _load(args.noise[1])
        for key in set(n1) | set(n2):
            noise[key] = compare_fingerprints(n1.get(key), n2.get(key))
    def _features(run_dir):
        try:
            with open(os.path.join(run_dir, "manifest.json"), encoding="utf-8") as f:
                return json.load(f).get("features")
        except (OSError, ValueError):
            return None

    # As flags de `features` mudam em TODA tela quando o premium vence; uma
    # linha no topo, e nao repetida em cada secao.
    lines = ["# Comparacao de telas", "",
             "A = `%s` -- features: `%s`  " % (args.a, _features(args.a)),
             "B = `%s` -- features: `%s`" % (args.b, _features(args.b)), ""]
    if args.noise:
        lines.append("Ruido descontado: `%s` x `%s`\n" % tuple(args.noise))
    same = []
    for key in sorted(set(a) | set(b)):
        diff = compare_fingerprints(a.get(key), b.get(key))
        diff.pop("features", None)
        known = noise.get(key) or {}
        for field in list(diff):
            if field in SET_FIELDS and field in known:
                for side in ("so_em_a", "so_em_b"):
                    drop = set(known[field].get("so_em_a", ())) | set(known[field].get("so_em_b", ()))
                    diff[field][side] = [x for x in diff[field][side] if x not in drop]
                if not diff[field]["so_em_a"] and not diff[field]["so_em_b"]:
                    del diff[field]
            elif field == "size" and "size" in known:
                del diff[field]
        if not diff:
            same.append(key)
            continue
        lines.append("## %s" % key)
        for field, value in diff.items():
            if isinstance(value, dict):
                for side, label in (("so_em_a", "so em A"), ("so_em_b", "so em B")):
                    if value.get(side):
                        lines.append("- **%s** %s: %s" % (field, label,
                                     ", ".join("`%s`" % x for x in value[side])))
            else:
                lines.append("- **%s**: A=`%s` B=`%s`" % (field, value[0], value[1]))
        lines.append("")
    lines.append("## Sem diferenca estrutural (%d)" % len(same))
    lines.append(", ".join("`%s`" % k for k in same))
    text = "\n".join(lines) + "\n"
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print("escrito em %s" % args.out)
    else:
        sys.stdout.write(text)


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    os.chdir(ROOT)
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("capture")
    c.add_argument("--label", required=True, help="premium | free | ...")
    c.add_argument("--village", default=DEFAULT_VILLAGE)
    c.add_argument("--tower", default=DEFAULT_TOWER_VILLAGE)
    c.add_argument("--interval", type=float, default=60.0)
    c.add_argument("--discover", action="store_true",
                   help="segunda passada pelas telas linkadas e nao listadas")
    c.add_argument("--discover-max", type=int, default=40)
    c.add_argument("--only", help="chaves separadas por virgula (teste)")
    c.add_argument("--force", action="store_true")
    k = sub.add_parser("compare")
    k.add_argument("a")
    k.add_argument("b")
    k.add_argument("--noise", nargs=2, metavar=("RUN1", "RUN2"),
                   help="duas capturas na mesma situacao: o que muda entre "
                        "elas e descontado")
    k.add_argument("--out")
    r = sub.add_parser("refingerprint")
    r.add_argument("run")
    args = p.parse_args(argv)
    {"capture": capture, "compare": compare, "refingerprint": refingerprint}[args.cmd](args)


if __name__ == "__main__":
    main()
