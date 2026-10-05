"""
Leitura da academia (`screen=snob`) e da bandeira atual (`screen=flags`) para
a cunhagem (§8.55). Só parse: quem faz a requisição é o `MintManager`.

Markup conferido na captura de 04/10/2026 (`cache/feature_map/
premium_20261004_2305/pages/snob.html.gz`, BBM 003):

    train.storage_item = {"wood":23520,"stone":25200,"iron":21000,"id":"coin"};
    <a href="#" id="coin_mint_fill_max">(1)</a>
    <form action="/game.php?village=44683&amp;screen=snob&amp;action=coin&amp;h=…">
        <input type="text" id="coin_mint_count" name="count" …>
    <form action="/game.php?village=44683&amp;screen=snob&amp;action=start_auto_minting_session&amp;h=…">

⚠️ O markup da academia COM a cunhagem automática em andamento nunca foi
capturado. `auto_minting_state()` só afirma o que viu: o botão de ativar está
lá ("can_start") ou a tabela está lá sem ele ("no_start_button", que é
provavelmente "em andamento", e por isso não é tratado como sucesso
confirmado). O `MintManager` salva a primeira resposta de cada tipo em
`cache/mint/samples/` para virar fixture.
"""
import json
import re

STORAGE_ITEM_RE = re.compile(r"train\.storage_item\s*=\s*(\{.+?\})")
FILL_MAX_RE = re.compile(r'id="coin_mint_fill_max"[^>]*>\s*\((\d+)\)')
START_AUTO_RE = re.compile(r"screen=snob&(?:amp;)?action=start_auto_minting_session")
AUTO_TABLE_RE = re.compile(r'class="vis auto-minting"')

# Mesmo regex de DefenceManager._read_flags_page (game/defence_manager.py),
# que é o que está validado em campo desde 2026-08-07.
CURRENT_FLAG_RE = re.compile(
    r'(?s)<div id="current_flag".+?/(\d+)_(\d+)\.\w+.+?<p>(.+?)</p>.+?</div>'
)
CURRENT_FLAG_HIDDEN = '<div id="current_flag" style="margin-top: 10px; display: none">'


def coin_cost(html):
    """{'wood','stone','iron'} da moeda nesta aldeia, com bônus aplicados; ou None."""
    match = STORAGE_ITEM_RE.search(html or "")
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
    except ValueError:
        return None
    if data.get("id") != "coin":
        # Mundo sem moeda: storage_item é o pacote de nobre guardado.
        return None
    try:
        return {r: int(data[r]) for r in ("wood", "stone", "iron")}
    except (KeyError, TypeError, ValueError):
        return None


def max_mintable(html):
    """Quantas moedas a aldeia cunha agora (o "(N)" ao lado do campo), ou None."""
    match = FILL_MAX_RE.search(html or "")
    return int(match.group(1)) if match else None


def auto_minting_state(html):
    """'can_start', 'no_start_button' ou None (tabela ausente: tela errada)."""
    html = html or ""
    if START_AUTO_RE.search(html):
        return "can_start"
    if AUTO_TABLE_RE.search(html):
        return "no_start_button"
    return None


def current_flag(html):
    """
    (tipo, nível) da bandeira equipada; () se a aldeia está sem bandeira; None
    se a tela não é a de bandeiras (sessão, captcha, markup novo).
    """
    html = html or ""
    if "FlagsScreen.setFlagCounts" not in html:
        return None
    if CURRENT_FLAG_HIDDEN in html:
        return ()
    match = CURRENT_FLAG_RE.search(html)
    if not match:
        return ()
    return int(match.group(1)), int(match.group(2))
