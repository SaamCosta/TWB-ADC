"""
Moedas por aldeia (§8.85): o registro que faltava para a bandeira de moeda
(tipo 7) ter valor no plano por valor (`core/flag_planner`). Lógica pura.

Até 04/11 o bot cunhava sem contar: o `SnobManager.coin_item` (1 moeda por
POST), o hub (`MintManager._mint_max` e a sessão automática de 8 h) e a
cunhagem diária, nenhum deixava linha. Agora cada um deixa `TWB_MINT` no
reporter, e o que entra é o que o SERVIDOR contou, não o que o bot mandou
(13º padrão):

- `src: "post"`: a cunhagem por POST, com o contador da conta na academia
  ANTES (a tela que o bot acabou de ler) e DEPOIS (a resposta). Só entra com
  depois > antes; sem contador nos dois lados não há linha.
- `src: "auto"`: a sessão automática, pelo "O que já foi coletado até agora"
  da academia do hub, com o fim da sessão. Vale o maior número lido por
  sessão (aldeia, fim). Desde §8.88 a sessão deixa uma linha também no
  início (moedas 0), e assim o registro sabe que ela está em andamento.
- `src: "total"`: só o contador da conta, numa leitura sem cunhagem.

O contador da conta (`pages.academy.coin_total`) é o que separa "a aldeia não
cunhou" de "a aldeia cunhou sem o bot ver" (9º padrão: à mão, ou numa sessão
automática que o bot não acompanha). Se a conta ganhou mais moedas do que o
registro explica, aldeia sem registro fica DESCONHECIDA, não zero.
"""
import json

# Custo base da moeda no br143 (`game/mint_planner.BASE_COIN_COST`, captura de
# 04/10): é o que a bandeira desconta, então o valor dela é moedas/h x isto x %.
COIN_BASE_TOTAL = 28000 + 30000 + 25000
MINT_WINDOW = 7 * 86400
MINT_MIN_SPAN = 24 * 3600
# Folga para a moeda de fora do registro: abaixo disto é arredondamento das
# leituras (a sessão do hub é lida até ~10 min antes do fim).
UNSEEN_MIN = 3
UNSEEN_FRAC = 0.05
# Sessão automática do hub (`mint_manager.AUTO_MINT_SECONDS`): o início sai do
# fim lido na tela, que vem segundos depois do clique (§8.86: 15 s), daí a folga.
SESSION_SECONDS = 8 * 3600
SESSION_START_SLACK = 5 * 60
# Leitura que fecha a sessão: o hub relê 10 min antes do fim
# (`mint_manager.AUTO_MINT_FINAL_READ`), mais folga para o tick atrasar.
SESSION_FINAL_READ = 15 * 60


def mint_event(src, coins=None, before=None, after=None, end=None, total=None):
    """Mensagem `TWB_MINT` (JSON numa linha) ou None se não há o que registrar."""
    if src == "post":
        if before is None or after is None or after <= before:
            return None
        payload = {"src": "post", "coins": after - before, "before": before, "after": after}
    elif src == "auto":
        if coins is None:
            return None
        payload = {"src": "auto", "coins": int(coins), "end": end, "total": total}
    elif src == "total":
        if total is None:
            return None
        payload = {"src": "total", "total": int(total)}
    else:
        return None
    return json.dumps(payload, sort_keys=True)


def account_totals(events):
    """[(ts, total)] do contador da conta, de todas as linhas que o trazem."""
    out = []
    for ts, _, ev in events or []:
        for key in ("before", "after", "total"):
            if ev.get(key) is not None:
                out.append((ts, int(ev[key])))
    return sorted(out)


def hub_sessions(events):
    """
    Sessões automáticas lidas: [{"vid", "end", "coins", "last_ts", "closed"}].
    Leituras da mesma aldeia com fins a até `SESSION_START_SLACK` são a mesma
    sessão: o início (§8.88) e a leitura final leem o "Fim" da mesma tela.
    Vale o maior número lido. Fechada = lida perto do fim (`SESSION_FINAL_READ`)
    ou sem fim conhecido (o registro antigo, que contava inteira).
    """
    out = []
    for ts, vid, ev in sorted(events or [], key=lambda e: (str(e[1]), e[2].get("end") or 0, e[0])):
        if ev.get("src") != "auto":
            continue
        end = ev.get("end")
        last = out[-1] if out else None
        if (last and last["vid"] == str(vid) and end and last["end"]
                and abs(end - last["end"]) <= SESSION_START_SLACK):
            last["coins"] = max(last["coins"], int(ev.get("coins") or 0))
            last["last_ts"] = max(last["last_ts"], ts)
        else:
            out.append({"vid": str(vid), "end": end, "coins": int(ev.get("coins") or 0),
                        "last_ts": ts})
    for s in out:
        s["closed"] = not s["end"] or s["last_ts"] >= s["end"] - SESSION_FINAL_READ
    return out


def mint_inputs(vids, events, now, window=MINT_WINDOW, min_span=MINT_MIN_SPAN):
    """
    {vid: {"coin_h": moedas/h ou None, "coin_why": motivo}} a partir das
    `TWB_MINT` = [(ts, vid, dict)] dentro de `window`.
    """
    events = [(ts, str(vid), ev) for ts, vid, ev in (events or [])
              if now - window <= ts <= now]
    out = {}
    if not events:
        for vid in vids:
            out[str(vid)] = {"coin_h": None, "coin_why": "cunhagem: nenhum registro de moeda (TWB_MINT) ainda"}
        return out
    since = min(ts for ts, _, _ in events)
    span = now - since
    coins = {}
    for ts, vid, ev in events:
        if ev.get("src") == "post":
            coins[vid] = coins.get(vid, 0) + int(ev.get("coins") or 0)
    sessions = hub_sessions(events)
    for s in sessions:
        coins[s["vid"]] = coins.get(s["vid"], 0) + s["coins"]
    totals = account_totals(events)
    # Sessão que começou antes da primeira leitura do contador tem moedas de
    # antes dela: contá-la inteira faria a "moeda fora do registro" negativa e
    # esconderia a cunhagem à mão (§8.86: 33 da sessão, 31 delas antes da
    # primeira leitura). A conferência começa depois do fim da última dessas.
    if totals:
        early = [s["end"] for s in sessions
                 if s["end"] and s["end"] - SESSION_SECONDS < totals[0][0] - SESSION_START_SLACK]
        if early:
            cut = max(early)
            totals = [(ts, total) for ts, total in totals if ts >= cut]
    # Sessão aberta (em andamento, ou cuja leitura final não houve) cunha sem
    # o bot saber quanto: o contador sobe e nada no registro explica. Contada,
    # a sessão em andamento punha as aldeias sem registro em "desconhecido"
    # durante quase toda sessão de 8 h (§8.88). A janela dela fica fora da
    # conferência, nos dois lados: o crescimento e o registrado.
    opaque = [(s["end"] - SESSION_SECONDS - SESSION_START_SLACK, s["end"] + SESSION_START_SLACK)
              for s in sessions if not s["closed"]]

    def hidden(a, b):
        return any(a < hi and b > lo for lo, hi in opaque)

    pairs = [(a, b) for a, b in zip(totals, totals[1:]) if not hidden(a[0], b[0])]
    growth = sum(b[1] - a[1] for a, b in pairs) if pairs else None
    # Moedas registradas dentro do intervalo coberto pelo contador. A sessão
    # automática fechada que começou nele conta inteira (a leitura do fim cai
    # dentro).
    if growth is not None:
        t0, t1 = totals[0][0], totals[-1][0]
        # `<=` no começo: a primeira leitura costuma ser o "antes" do próprio
        # POST, e a moeda dele já está no crescimento.
        inside = sum(int(ev.get("coins") or 0) for ts, _, ev in events
                     if ev.get("src") == "post" and t0 <= ts <= t1 and not hidden(ts, ts))
        inside += sum(s["coins"] for s in sessions if s["closed"] and (
            not s["end"] or s["end"] - SESSION_SECONDS >= t0 - SESSION_START_SLACK))
        unseen = growth - inside
    else:
        unseen = None
    hours = span / 3600.0
    for vid in vids:
        vid = str(vid)
        n = coins.get(vid, 0)
        if span < min_span:
            entry = {"coin_h": None, "coin_why": "cunhagem: %.0f h de registro, o piso é %d h" % (
                hours, min_span // 3600)}
        elif n:
            entry = {"coin_h": n / hours, "coin_why": None}
        elif unseen is None:
            entry = {"coin_h": None, "coin_why": "cunhagem: sem duas leituras do contador da conta, "
                                                  "zero aqui não é medido"}
        elif unseen > max(UNSEEN_MIN, UNSEEN_FRAC * growth):
            entry = {"coin_h": None, "coin_why": "cunhagem: a conta ganhou %d moeda(s) que o bot não "
                                                  "registrou (à mão?), zero aqui não é medido" % unseen}
        else:
            entry = {"coin_h": 0.0, "coin_why": "o bot não cunhou nesta aldeia em %.0f h, e a conta "
                                                 "não ganhou moeda fora do registro" % hours}
        entry["coins"] = n
        out[vid] = entry
    return out
