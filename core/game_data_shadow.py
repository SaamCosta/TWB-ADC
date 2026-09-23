"""
P-OVERVIEW-SOMBRA (docs/backend.md §9, item 20a): modo sombra das releituras
da visao geral da aldeia.

O bot le `game.php?village=N&screen=overview` ~3x por aldeia por ciclo (inicio,
antes de recrutar, depois do mercado). Cada releitura existe para atualizar o
`game_data` (recursos, fazenda) depois de acoes que gastaram recurso. Mas toda
tela HTML do jogo traz `TribalWars.updateGameData(...)`, e as respostas AJAX
com `TribalWars-Ajax: 1` trazem `game_data` no topo (setimo padrao) -- entao o
dado fresco provavelmente ja chegou na ultima resposta.

Este modulo NAO corta nada. O wrapper guarda o ultimo `game_data` visto por
aldeia (`remember`), e nas releituras o bot continua fazendo o GET e so compara
o que ja tinha com o que a releitura trouxe (`record_reread`). Uma linha de log
e uma linha em `cache/shadow/overview.jsonl` por comparacao. A decisao de cortar
sai da leitura dessas linhas depois de ao menos um ciclo diurno completo.

Tudo aqui e observabilidade: nenhuma funcao levanta para o chamador, e wrapper
sem suporte (mock de teste) vira no-op.
"""
import json
import logging
import os
import re
import time

logger = logging.getLogger("OverviewShadow")

RESOURCES = ("wood", "stone", "iron")
SHADOW_FILE = os.path.join("cache", "shadow", "overview.jsonl")
# Arredondamento: `*_float` e o valor exato do servidor, mas uma resposta sem
# ele cai no inteiro, que difere do float em ate 1. Acima disso e diferenca real.
TOLERANCE = 1.5

_GAME_DATA_RE = re.compile(r'TribalWars\.updateGameData\((.+?)\);')


def extract_game_data(text):
    """`game_data` de uma resposta do jogo, HTML ou JSON; None se nao houver.

    HTML: o mesmo regex de `Extractor.game_state`. JSON: com `TribalWars-Ajax`
    o jogo embrulha em `{"response": ..., "game_data": ...}`; sem o cabecalho
    pode vir sem `game_data`, e ai nao ha o que guardar."""
    if not text:
        return None
    stripped = text.lstrip()
    if stripped.startswith("{"):
        try:
            payload = json.loads(stripped, strict=False)
        except ValueError:
            return None
        gd = payload.get("game_data") if isinstance(payload, dict) else None
        return gd if isinstance(gd, dict) else None
    match = _GAME_DATA_RE.search(text)
    if not match:
        return None
    try:
        gd = json.loads(match.group(1), strict=False)
    except ValueError:
        return None
    return gd if isinstance(gd, dict) else None


def snapshot(game_data, source_url=None, ajax=False, received_at=None):
    """Recorte do `game_data` que interessa a comparacao, ou None.

    `at` e o `time_generated` do servidor (ms -> s) quando existe: a producao
    entre duas leituras se mede no relogio de quem produz, nao no nosso."""
    try:
        village = game_data.get("village") or {}
        vid = village.get("id")
        if vid is None:
            return None
        generated = game_data.get("time_generated")
        at = float(generated) / 1000.0 if generated else (received_at or time.time())
        snap = {
            "village_id": str(vid),
            "at": at,
            "screen": game_data.get("screen"),
            "mode": game_data.get("mode"),
            "ajax": bool(ajax),
            "url": source_url,
        }
        for res in RESOURCES:
            value = village.get("%s_float" % res, village.get(res))
            if value is None:
                return None
            snap[res] = float(value)
            snap["%s_prod" % res] = float(village.get("%s_prod" % res) or 0.0)
        for key in ("pop", "pop_max", "storage_max", "trader_away"):
            if village.get(key) is not None:
                snap[key] = int(village.get(key))
        return snap
    except (AttributeError, TypeError, ValueError):
        return None


def compare(previous, fresh):
    """Compara o que o bot ja tinha (`previous`) com a releitura (`fresh`).

    Para cada recurso: `expected` = anterior + producao do intervalo, limitado
    ao armazem; `residual` = lido - esperado. Residual ~0 significa que a
    releitura nao trouxe nada que o bot nao pudesse calcular. Residual negativo
    e gasto que a resposta anterior nao refletia; positivo e chegada de recurso
    (transporte, saque) ou armazem que mudou.

    Devolve None quando nao ha anterior ou as aldeias nao batem."""
    if not previous or not fresh:
        return None
    if previous.get("village_id") != fresh.get("village_id"):
        return None
    age = max(0.0, fresh["at"] - previous["at"])
    cap = fresh.get("storage_max") or previous.get("storage_max")
    resources = {}
    worst = 0.0
    for res in RESOURCES:
        expected = previous[res] + previous.get("%s_prod" % res, 0.0) * age
        if cap:
            expected = min(expected, float(cap))
        residual = fresh[res] - expected
        resources[res] = {
            "before": round(previous[res], 1),
            "read": round(fresh[res], 1),
            "diff": round(fresh[res] - previous[res], 1),
            "residual": round(residual, 1),
        }
        worst = max(worst, abs(residual))
    other = {}
    for key in ("pop", "pop_max", "storage_max", "trader_away"):
        if previous.get(key) != fresh.get(key):
            other[key] = [previous.get(key), fresh.get(key)]
    if worst <= TOLERANCE and not other:
        verdict = "igual" if all(
            abs(r["diff"]) <= TOLERANCE for r in resources.values()) else "producao"
    else:
        verdict = "diverge"
    return {
        "village_id": fresh["village_id"],
        "age_sec": round(age, 1),
        "source_screen": previous.get("screen"),
        "source_mode": previous.get("mode"),
        "source_ajax": previous.get("ajax", False),
        "source_url": previous.get("url"),
        "resources": resources,
        "other": other,
        "verdict": verdict,
    }


def format_line(point, result):
    source = result["source_screen"] or "?"
    if result["source_mode"]:
        source += "/%s" % result["source_mode"]
    if result["source_ajax"]:
        source += " (ajax)"
    parts = []
    for res in RESOURCES:
        r = result["resources"][res]
        parts.append("%s %d->%d (res %+d)" % (
            res, r["before"], r["read"], r["residual"]))
    extra = ""
    if result["other"]:
        extra = " | " + ", ".join(
            "%s %s->%s" % (k, v[0], v[1]) for k, v in sorted(result["other"].items()))
    return "Sombra %s aldeia %s: %s | anterior de %s ha %ds | %s%s" % (
        point, result["village_id"], result["verdict"], source,
        result["age_sec"], "; ".join(parts), extra)


def remember_full(wrapper, village_id, game_data, text):
    """Guarda o game_data COMPLETO desta resposta, so se ela for HTML.

    So HTML de proposito: e a mesma origem de `Extractor.game_state()`, que e o
    que os consumidores das releituras sempre receberam. O envelope JSON do
    `TribalWars-Ajax` traz um `game_data` que a sombra comparou certo nos
    recursos, mas ninguem conferiu se ele tem todas as chaves que
    `ResourceManager.update()` le -- e na duvida o GET continua."""
    try:
        if not isinstance(getattr(wrapper, "game_data_full", None), dict):
            return
        if (text or "").lstrip().startswith("{"):
            wrapper.game_data_full.pop(str(village_id), None)
            return
        wrapper.game_data_full[str(village_id)] = {
            "game_data": game_data, "received_at": time.time(),
        }
    except Exception:
        pass


def reuse(wrapper, village_id, point):
    """game_data completo e recente desta aldeia, ou None (faca o GET).

    Corte do §9 item 20a, decidido sobre o ciclo diurno de 2026-09-23: nas
    releituras `update_totals` e `market`, 67 de 67 comparacoes deram
    `producao` (nada alem da producao do intervalo), com o dado anterior
    tendo no maximo 34 s. Reaproveitar o que a ultima tela HTML trouxe da o
    mesmo resultado sem a requisicao. `max_age` (bot.reuse_game_data_max_age)
    limita isso ao caso medido; acima dele, ou sem dado, o GET volta.
    """
    try:
        max_age = float(getattr(wrapper, "reuse_game_data_max_age", 0) or 0)
        store = getattr(wrapper, "game_data_full", None)
        if max_age <= 0 or not isinstance(store, dict):
            return None
        entry = store.get(str(village_id))
        if not entry:
            return None
        age = time.time() - entry["received_at"]
        if age > max_age:
            return None
        gd = entry["game_data"]
        logger.debug(
            "Releitura %s aldeia %s: reaproveitado game_data de %s ha %.0fs "
            "(sem GET)", point, village_id, gd.get("screen"), age)
        return json.loads(json.dumps(gd))
    except Exception:
        return None


def before(wrapper, village_id):
    """O que o bot ja sabia desta aldeia, capturado ANTES do GET de releitura
    (o proprio GET sobrescreve o registro no `post_process`)."""
    seen = getattr(wrapper, "game_data_seen", None)
    if not isinstance(seen, dict):
        return None
    snap = seen.get(str(village_id))
    return dict(snap) if snap else None


def record_reread(wrapper, village_id, point, previous, path=SHADOW_FILE):
    """Depois do GET de releitura: compara, loga e anexa ao jsonl. Nunca levanta."""
    try:
        fresh = before(wrapper, village_id)
        if not fresh or fresh.get("screen") != "overview":
            return None
        result = compare(previous, fresh)
        if result is None:
            logger.debug("Sombra %s aldeia %s: sem leitura anterior", point, village_id)
            return None
        logger.info(format_line(point, result))
        entry = dict(result, point=point, logged_at=time.time())
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return result
    except Exception as e:
        logger.debug("Sombra %s aldeia %s falhou: %s", point, village_id, e)
        return None
