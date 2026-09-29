"""
Pedido de apoio de membros da tribo: leitura do tópico do fórum, do BBCode ou
de texto colado, e o saldo que ainda falta em cada aldeia (docs/backend.md
§8.39).

Formato de referência: o tópico "BLINDAGEM FIXA - APOIO" do fórum Defesa da
tribo 987 no br143 (forum_id=2513, thread_id=1639), capturado em 2026-09-29.
O organizador mantém no PRIMEIRO post uma tabela `bbcodetable` com uma aldeia
por linha e as tropas pedidas por coluna, e a EDITA para refletir o que ainda
falta ("ATUALIZADO 19:34"). Quem envia responde com uma linha por aldeia no
formato `Número/Lança/Espada/Explorador/Cavalaria Pesada`.

Regra da falta, decidida pelo usuário em 2026-09-29: a tabela já é o saldo na
hora da última edição, então só se descontam as respostas postadas DEPOIS
dela. Resposta no mesmo minuto da edição é ambígua (o fórum só mostra
minutos): conta como ainda não descontada e sai marcada `ambiguous`.

Tudo aqui é puro: sem rede, sem disco. Quem busca o tópico é o webmanager.
"""
import html as html_lib
import re
import unicodedata
from datetime import datetime, timedelta

# Ordem das colunas quando o texto colado não traz cabeçalho: a mesma do
# formato de resposta do tópico de referência.
DEFAULT_UNIT_ORDER = ["spear", "sword", "spy", "heavy"]

# Unidades que fazem sentido como apoio. Ofensivas ficam de fora de propósito:
# ninguém pede machado de apoio, e aceitar a coluna abriria a porta para um
# envio de tropa de ataque para a aldeia de um companheiro.
SUPPORT_UNITS = ["spear", "sword", "archer", "spy", "heavy", "knight"]

# Nome normalizado (sem acento, minúsculo, sem pontuação) -> unidade. A ordem
# importa: "arqueiro a cavalo" antes de "arqueiro", "cav pesada" antes de
# qualquer coisa que case "cav".
_UNIT_NAMES = [
    ("arqueiro a cavalo", "marcher"),
    ("cavalaria pesada", "heavy"),
    ("cav pesada", "heavy"),
    ("pesada", "heavy"),
    ("cavalaria leve", "light"),
    ("cav leve", "light"),
    ("lanca", "spear"),
    ("lanceiro", "spear"),
    ("espada", "sword"),
    ("espadachim", "sword"),
    ("machado", "axe"),
    ("barbaro", "axe"),
    ("arqueiro", "archer"),
    ("explorador", "spy"),
    ("batedor", "spy"),
    ("paladino", "knight"),
    ("ariete", "ram"),
    ("catapulta", "catapult"),
    ("nobre", "snob"),
    ("cp", "heavy"),
]

COORD_RE = re.compile(r"(?<!\d)(\d{1,3})\|(\d{1,3})(?!\d)")


def _norm(text):
    text = unicodedata.normalize("NFKD", html_lib.unescape(text or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9 ]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def unit_from_label(label):
    """Unidade de um rótulo de coluna/token em português, ou None."""
    n = _norm(label)
    if not n:
        return None
    for name, unit in _UNIT_NAMES:
        if n == name or n.startswith(name + " ") or n.startswith(name + "s") \
                or (" " + name + " ") in (" " + n + " "):
            return unit
    return None


def _strip_tags(fragment):
    text = re.sub(r"<br\s*/?>", "\n", fragment or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return html_lib.unescape(text)


def _int(text):
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else None


# -- datas do fórum -----------------------------------------------------------

_DATE_ABS = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})\s+às\s+(\d{1,2}):(\d{2})")
_DATE_REL = re.compile(r"(hoje|ontem)\s+às\s+(\d{1,2}):(\d{2})")


def parse_forum_date(text, today):
    """
    "em 17.08.2026 às 16:59" / "hoje às 19:35" / "ontem às 08:10" -> datetime
    no fuso do servidor. `today` é a data do servidor (a página traz em
    `id="serverDate"`). None quando não casa -- data desconhecida não pode
    virar "agora", senão toda resposta pareceria posterior à edição.
    """
    text = html_lib.unescape(text or "")
    m = _DATE_ABS.search(text)
    if m:
        d, mo, y, h, mi = (int(g) for g in m.groups())
        return datetime(y, mo, d, h, mi)
    m = _DATE_REL.search(text)
    if m and today is not None:
        base = today if m.group(1) == "hoje" else today - timedelta(days=1)
        return datetime(base.year, base.month, base.day, int(m.group(2)), int(m.group(3)))
    return None


def _server_today(page):
    m = re.search(r'id="serverDate">(\d{2})/(\d{2})/(\d{4})', page)
    if not m:
        return None
    d, mo, y = (int(g) for g in m.groups())
    return datetime(y, mo, d)


# -- tabela -------------------------------------------------------------------

def _cells(row_html):
    # O markup real mistura <td> e <th> e fecha errado
    # (`<td><b>Número</b></th>`), então corta por abertura de célula em vez de
    # casar pares.
    parts = re.split(r"<t[dh][^>]*>", row_html)[1:]
    return [re.sub(r"</t[dh]>\s*$", "", p.strip()) for p in parts]


def _parse_table(table_html):
    """[linhas de pedido], unit_order -- de uma `bbcodetable` do fórum."""
    rows = re.findall(r"(?s)<tr[^>]*>(.*?)</tr>", table_html)
    if not rows:
        return [], []
    header = [_strip_tags(c).strip() for c in _cells(rows[0])]
    col_units = [unit_from_label(h) for h in header]
    unit_order = [u for u in col_units if u]
    requests = []
    for row in rows[1:]:
        cells = _cells(row)
        anchor_idx = next((i for i, c in enumerate(cells) if "village_anchor" in c
                           or COORD_RE.search(_strip_tags(c))), None)
        if anchor_idx is None:
            continue
        cell = cells[anchor_idx]
        text = _strip_tags(cell).strip()
        coord = COORD_RE.search(text)
        if not coord:
            continue
        vid = re.search(r'data-id="(\d+)"', cell)
        player = re.search(r'data-player="(\d+)"', cell)
        num = None
        for c in cells[:anchor_idx]:
            num = _int(_strip_tags(c))
            if num is not None:
                break
        need = {}
        for i, c in enumerate(cells):
            unit = col_units[i] if i < len(col_units) else None
            if unit:
                need[unit] = _int(_strip_tags(c)) or 0
        requests.append({
            "num": num,
            "name": re.sub(r"\s+", " ", text),
            "x": int(coord.group(1)),
            "y": int(coord.group(2)),
            "village_id": vid.group(1) if vid else None,
            "player_id": player.group(1) if player else None,
            "need": need,
        })
    return requests, unit_order


# -- respostas ----------------------------------------------------------------

_REPLY_LINE = re.compile(r"^\s*(\d{1,4})\s*((?:/\s*\d+\s*)+)$")


def parse_reply_lines(text, unit_order):
    """
    Linhas `NN/lança/espada/exp/pesada` de uma resposta -> [(num, {unit: qtd})].
    Linha que não segue o formato é ignorada (conversa, "enviado!", etc.).
    """
    out = []
    for line in (text or "").splitlines():
        m = _REPLY_LINE.match(line.strip())
        if not m:
            continue
        values = [int(v) for v in re.findall(r"\d+", m.group(2))]
        units = {}
        for unit, value in zip(unit_order, values):
            if value:
                units[unit] = value
        out.append((int(m.group(1)), units))
    return out


def _posts(page):
    body = page
    start = body.find('id="forum_post_list"')
    if start >= 0:
        body = body[start:]
        end = body.find("</form>")
        if end >= 0:
            body = body[:end]
    return re.findall(r'(?s)<div class="post">(.*?)(?=<div class="post">|$)', body)


def _post_meta(post, today):
    author = re.search(r'screen=info_player&amp;id=(\d+)"[^>]*>\s*([^<]+?)\s*</a>', post)
    date = re.search(r'<span class="igmline-date">([^<]+)</span>', post)
    edited = re.search(r"Editado por\s+(.+?)\s+((?:em\s+\d{2}\.\d{2}\.\d{4}|hoje|ontem)\s+às\s+\d{1,2}:\d{2})",
                       _strip_tags(post))
    text = re.search(r'(?s)<div class="text">(.*)', post)
    return {
        "author_id": author.group(1) if author else None,
        "author": author.group(2) if author else None,
        "posted_at": parse_forum_date(date.group(1), today) if date else None,
        "edited_at": parse_forum_date(edited.group(2), today) if edited else None,
        "text": _strip_tags(text.group(1)) if text else "",
        "html": post,
    }


def parse_forum_thread(page):
    """
    Tópico de pedido de apoio -> dict com `requests` (a tabela), as respostas
    e o saldo. None quando a página não é um tópico do fórum (sessão
    expirada, bot protection) -- distinto de um tópico sem tabela, que volta
    com `requests` vazio e `error` preenchido.
    """
    if not page or 'id="forum_post_list"' not in page:
        return None
    today = _server_today(page)
    title = re.search(r"<h2>(?:<strong>[^<]*</strong>:\s*)?([^<]+)</h2>", page)
    posts = [_post_meta(p, today) for p in _posts(page)]
    table_idx = None
    for i, p in enumerate(posts):
        if "bbcodetable" in p["html"] and ("village_anchor" in p["html"]
                                           or COORD_RE.search(p["text"])):
            table_idx = i
            break
    result = {
        "title": html_lib.unescape(title.group(1)).strip() if title else None,
        "server_date": today.strftime("%Y-%m-%d") if today else None,
        "is_last_page": "Forum.is_last_page = true" in page,
        "requests": [],
        "unit_order": [],
        "table_author": None,
        "table_updated_at": None,
        "replies": [],
        "error": None,
    }
    if table_idx is None:
        result["error"] = "nenhuma tabela de aldeias encontrada no tópico"
        return result
    table_post = posts[table_idx]
    table = re.search(r'(?s)<table class="vis bbcodetable">.*?</table>', table_post["html"])
    requests, unit_order = _parse_table(table.group(0) if table else "")
    updated = table_post["edited_at"] or table_post["posted_at"]
    # O organizador também marca a atualização num post seguinte ("ATUALIZADO
    # 19:34", editado na mesma hora). A edição da tabela é o que vale.
    result.update({
        "requests": requests,
        "unit_order": unit_order or list(DEFAULT_UNIT_ORDER),
        "table_author": table_post["author"],
        "table_updated_at": updated.isoformat() if updated else None,
    })
    for p in posts[table_idx + 1:]:
        lines = parse_reply_lines(p["text"], result["unit_order"])
        if not lines:
            continue
        posted = p["posted_at"]
        if updated is None or posted is None:
            after, ambiguous = True, True
        else:
            after = posted >= updated
            ambiguous = posted == updated
        result["replies"].append({
            "author": p["author"],
            "author_id": p["author_id"],
            "posted_at": posted.isoformat() if posted else None,
            "after_update": after,
            "ambiguous": ambiguous,
            "lines": [{"num": n, "units": u} for n, u in lines],
        })
    return result


def remaining(parsed):
    """
    Saldo por pedido: tabela menos as respostas postadas depois da última
    edição dela. Devolve a lista de pedidos com `delivered` e `missing`,
    nunca negativo -- quem manda a mais não cria crédito para a próxima linha.
    """
    delivered = {}
    for reply in parsed.get("replies") or []:
        if not reply.get("after_update"):
            continue
        for line in reply["lines"]:
            acc = delivered.setdefault(line["num"], {})
            for unit, qty in line["units"].items():
                acc[unit] = acc.get(unit, 0) + int(qty)
    out = []
    for req in parsed.get("requests") or []:
        got = delivered.get(req.get("num"), {})
        missing = {u: max(0, int(q) - int(got.get(u, 0))) for u, q in req["need"].items()}
        out.append(dict(req, delivered=dict(got), missing=missing))
    return out


# -- texto colado -------------------------------------------------------------

_BB_HEADER = re.compile(r"(?s)\[\*\*\](.*?)\[/\*\*\]")
_LABELED = re.compile(
    r"(\d[\d.]*)\s*(?:x\s*)?([a-zA-ZÀ-ÿ][a-zA-ZÀ-ÿ. ]{0,20})"
    r"|([a-zA-ZÀ-ÿ][a-zA-ZÀ-ÿ. ]{0,20}?)\s*[:=]\s*(\d[\d.]*)"
)


def _labeled_units(text):
    units = {}
    for m in _LABELED.finditer(text):
        if m.group(1):
            qty, label = m.group(1), m.group(2)
        else:
            label, qty = m.group(3), m.group(4)
        unit = unit_from_label(label.split()[0] if label.split() else label) \
            or unit_from_label(label)
        if unit in SUPPORT_UNITS:
            units[unit] = units.get(unit, 0) + (_int(qty) or 0)
    return units


def parse_pasted_text(text):
    """
    Pedido colado à mão: BBCode de tabela do fórum (`[table][**]...`), uma
    aldeia por linha com números na ordem do cabeçalho, ou texto livre com
    rótulo ("3000 pesada e 1000 lança em 776|536"). Toda linha precisa de uma
    coordenada `x|y`; sem ela não há destino.

    Devolve o mesmo formato de `parse_forum_thread` (sem respostas).
    """
    text = html_lib.unescape(text or "")
    unit_order = list(DEFAULT_UNIT_ORDER)
    header = _BB_HEADER.search(text)
    if header:
        labels = re.split(r"\[\|\|\]", header.group(1))
        found = [unit_from_label(re.sub(r"\[/?[a-z*]+\]", "", l)) for l in labels]
        if any(found):
            unit_order = [u for u in found if u]
        rows = re.split(r"\[\*\]", text[header.end():])
    else:
        rows = text.splitlines()
        # Cabeçalho em texto puro: a primeira linha sem coordenada que nomeia
        # duas ou mais unidades.
        for line in rows:
            if COORD_RE.search(line):
                break
            found = [unit_from_label(t) for t in re.split(r"[\t;/|,]+", line)]
            if sum(1 for f in found if f) >= 2:
                unit_order = [f for f in found if f]
                break
    requests = []
    for raw in rows:
        line = re.sub(r"\[/?(?:coord|village|player|ally|b|i|u|table|/?\|)\]", " ", raw)
        line = line.replace("[|]", " | ").replace("[/table]", " ")
        coord = COORD_RE.search(line)
        if not coord:
            continue
        before, after = line[:coord.start()], line[coord.end():]
        need = _labeled_units(after) or _labeled_units(before)
        if not need:
            numbers = [_int(n) for n in re.findall(r"\d[\d.]*", after)]
            # Descarta o "K57" do continente, que vem colado na coordenada.
            if re.match(r"\)?\s*K\d{2}", after.strip()):
                numbers = numbers[1:]
            need = {u: n for u, n in zip(unit_order, numbers) if n}
        # Só o inteiro que ABRE a linha é o número do pedido; "#06" no nome da
        # aldeia não é.
        lead = re.match(r"\s*(\d{1,4})(?=[\s|.)\-:]|$)", before)
        num = int(lead.group(1)) if lead else None
        name = before[lead.end():] if lead else before
        name = re.sub(r"\s+", " ", name.replace("|", " ")).strip(" -:()")
        requests.append({
            "num": num if num is not None else len(requests) + 1,
            "name": (name + " " if name else "") + "(%s|%s)" % coord.groups(),
            "x": int(coord.group(1)),
            "y": int(coord.group(2)),
            "village_id": None,
            "player_id": None,
            "need": need,
        })
    return {
        "title": None,
        "server_date": None,
        "is_last_page": True,
        "requests": requests,
        "unit_order": unit_order,
        "table_author": None,
        "table_updated_at": None,
        "replies": [],
        "error": None if requests else "nenhuma linha com coordenada x|y",
    }


def forum_link_ids(text):
    """(forum_id, thread_id) de um link de tópico colado, ou None."""
    text = html_lib.unescape(text or "")
    if "screen=forum" not in text:
        return None
    forum = re.search(r"[?&]forum_id=(\d+)", text)
    thread = re.search(r"[?&]thread_id=(\d+)", text)
    if not forum or not thread:
        return None
    return forum.group(1), thread.group(1)


def reply_text(lines, unit_order):
    """
    Texto de resposta para o tópico, no formato pedido pelo organizador:
    uma linha `NN/lança/espada/exp/pesada` por aldeia atendida.
    `lines`: [(num, {unit: qtd})]; números somados por aldeia.
    """
    by_num = {}
    for num, units in lines:
        acc = by_num.setdefault(num, {})
        for unit, qty in units.items():
            acc[unit] = acc.get(unit, 0) + int(qty)
    out = []
    for num in sorted(by_num, key=lambda n: (n is None, n)):
        values = [str(by_num[num].get(u, 0)) for u in unit_order]
        out.append("%02d/%s" % (num, "/".join(values)) if isinstance(num, int)
                   else "%s/%s" % (num, "/".join(values)))
    return "\n".join(out)
