"""
Testes do alcance do mapa: a grade de setores, o merge com o prefetch e a
degradacao de `Map.fetch_sectors()` quando a rede/parse falha.

MOTIVACAO (medida em 2026-08-31, nao suposta). `TWMap.sectorPrefech`, a unica
fonte de mapa que o bot tinha, traz so o que a tela de mapa desenha de cara:
**2 setores, e nao centrados na aldeia**. O efeito em campo, lido de
cache/logs/session_latest.log com as 18 aldeias todas dentro de um quadrado de
17 campos:

    BBM 007 (571|308)  ->  36 aldeias visiveis
    BBM 003 (579|304)  -> 220 aldeias visiveis

A diferenca nao e geografica, e sorteio de qual setor o prefetch incluiu. Para
a BBM 001 (577|306) o prefetch cobria y 300..319 -- ou seja **nada ao norte da
aldeia**, que esta a 6 campos da borda. E `search_radius` (100) nunca mordia:
no log inteiro nao ha uma unica linha "too far away".

Medido com a sessao real no mesmo dia, para a BBM 001:
    prefetch          :  2 setores,  94 aldeias
    map.php 3x3 (r=1) :  9 setores, 471 aldeias,  91.632 bytes
    map.php 3x3 (r=0) :  9 setores, 471 aldeias,  83.226 bytes

Por isso o bot pede r=0: os tiles de terreno nao sao usados em lugar nenhum.

Rodar: python tests/test_map_sectors.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game.map import Map, SECTOR_SIZE

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


# ---------------------------------------------------------------- fixtures

class FakeResponse:
    def __init__(self, payload=None, text=""):
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("nao e JSON")
        return self._payload


class FakeWrapper:
    """Registra a URL pedida em vez de ir a rede."""

    headers = {"user-agent": "x", "Referer": "y"}

    def __init__(self, response="default"):
        self.response = response
        self.urls = []
        self.headers_used = None

    def get_url(self, url, headers=None):
        self.urls.append(url)
        self.headers_used = headers
        if self.response == "default":
            return FakeResponse(payload=SECTOR_PAYLOAD)
        if self.response == "none":
            return None
        if self.response == "notjson":
            return FakeResponse(payload=None, text="<html>login</html>")
        if self.response == "dict":
            return FakeResponse(payload={"error": "nope"})
        return FakeResponse(payload=self.response)


# Recorte VERBATIM de map.php?v=2 do br143 em 2026-08-31 (setor 540|280), com
# uma aldeia real. A estrutura -- x, y, tiles, data{x,y,villages,players,
# allies} -- e IDENTICA a do sectorPrefech, que e o que permite os setores
# extras entrarem na mesma lista e serem lidos pelo mesmo parser.
SECTOR_PAYLOAD = [
    {
        "x": 540,
        "y": 280,
        "tiles": None,
        "data": {
            "x": 540,
            "y": 280,
            "villages": {
                "0": {
                    "1": ["54810", 21, "Mirmidão X", "1.173", "919932952", 42,
                          ["bonus de 10% na população", "bonus/farm.png"],
                          "0", 4, None, "standard", "494", 21]
                }
            },
            "players": {},
            "allies": {},
        },
    }
]

GAME_STATE = {"village": {"x": 577, "y": 306, "id": 41123}, "locale": "pt_BR"}


# ---------------------------------------------------------------- grade

def test_sector_grid_is_aligned_and_sized():
    grid = Map.sector_grid(577, 306, 1)
    check(len(grid) == 9, f"raio 1 deveria dar 9 setores, deu {len(grid)}")
    for sx, sy in grid:
        check(sx % SECTOR_SIZE == 0 and sy % SECTOR_SIZE == 0,
              f"setor ({sx},{sy}) nao esta alinhado em multiplo de {SECTOR_SIZE}")
    # 577 -> 560, 306 -> 300 (o proprio jogo faz `e - e % 20`)
    check((560, 300) in grid, "o setor da propria aldeia deveria estar na grade")
    check((540, 280) in grid and (580, 320) in grid,
          "a grade 3x3 deveria ir de (540,280) a (580,320)")

    grid2 = Map.sector_grid(577, 306, 2)
    check(len(grid2) == 25, f"raio 2 deveria dar 25 setores, deu {len(grid2)}")


def test_sector_grid_covers_the_village_on_every_side():
    """
    O bug original era assimetria: o prefetch cobria y 300..319 com a aldeia em
    306, deixando o norte inteiro invisivel. A grade tem que cobrir os dois
    lados em cada eixo.
    """
    x, y = 577, 306
    grid = Map.sector_grid(x, y, 1)
    xs = [sx for sx, _ in grid]
    ys = [sy for _, sy in grid]
    check(min(xs) < x < max(xs) + SECTOR_SIZE, "grade nao envolve a aldeia em x")
    check(min(ys) < y < max(ys) + SECTOR_SIZE, "grade nao envolve a aldeia em y")
    check(min(ys) <= y - SECTOR_SIZE,
          f"grade comeca em y={min(ys)}, nao cobre nada ao norte de {y}")


def test_sector_grid_drops_negative_coordinates():
    grid = Map.sector_grid(5, 5, 2)
    check(all(sx >= 0 and sy >= 0 for sx, sy in grid),
          "grade nao deveria conter coordenada negativa")
    check(len(grid) == 9, f"perto da borda 0|0 deveriam sobrar 9 setores, deu {len(grid)}")


# ---------------------------------------------------------------- merge

def test_merge_does_not_duplicate_prefetch_sectors():
    prefetch = [{"x": 560, "y": 300, "data": {}}, {"x": 580, "y": 300, "data": {}}]
    extra = [{"x": 560, "y": 300, "data": {}},   # ja veio no prefetch
             {"x": 540, "y": 280, "data": {}}]
    merged = Map.merge_sectors(prefetch, extra)
    check(len(merged) == 3, f"merge deveria dar 3 setores unicos, deu {len(merged)}")
    keys = [(s["x"], s["y"]) for s in merged]
    check(len(keys) == len(set(keys)), f"merge repetiu setor: {keys}")
    check(keys[0] == (560, 300), "merge deveria preservar a ordem do prefetch primeiro")


def test_merge_survives_junk_entries():
    merged = Map.merge_sectors([{"x": 1, "y": 2, "data": {}}], [None, "lixo", 42])
    check(len(merged) == 1, f"merge deveria descartar nao-dicts, deu {merged}")


def test_merge_with_empty_prefetch():
    """Prefetch vazio e um caso real: Extractor.map_data devolve None se o
    regex nao casar, e get_map passa [] adiante."""
    merged = Map.merge_sectors([], SECTOR_PAYLOAD)
    check(len(merged) == 1, f"merge com prefetch vazio deveria dar 1, deu {len(merged)}")


# ---------------------------------------------------------------- fetch

def test_fetch_is_off_by_default():
    """radius 0 = comportamento historico, e nenhuma requisicao a mais."""
    wrapper = FakeWrapper()
    m = Map(wrapper=wrapper, village_id="41123")
    check(m.sector_radius == 0, "o default de sector_radius deveria ser 0")
    check(m.fetch_sectors(GAME_STATE) == [], "radius 0 deveria devolver []")
    check(wrapper.urls == [], f"radius 0 nao deveria pedir nada, pediu {wrapper.urls}")


def test_fetch_builds_the_url_the_game_uses():
    wrapper = FakeWrapper()
    m = Map(wrapper=wrapper, village_id="41123", sector_radius=1)
    out = m.fetch_sectors(GAME_STATE)
    check(len(out) == 1, f"deveria devolver os setores do payload, deu {len(out)}")
    check(len(wrapper.urls) == 1, "deveria fazer exatamente uma requisicao")
    url = wrapper.urls[0]
    check(url.startswith("map.php?v=2"), f"URL errada: {url}")
    check("locale=pt_BR" in url, f"locale ausente na URL: {url}")
    # 9 setores, todos com r=0 (o bot nao usa os tiles de terreno)
    check(url.count("=0&") + url.count("=0") >= 9, f"deveria pedir 9 setores com r=0: {url}")
    check("560_300=0" in url, f"setor da propria aldeia ausente: {url}")
    check("540_280=0" in url and "580_320=0" in url, f"cantos ausentes: {url}")
    check("=1&" not in url.split("&e=")[1] if "&e=" in url else True,
          f"nenhum setor deveria pedir tiles (r=1): {url}")


def test_fetch_sends_xhr_headers_without_losing_wrapper_headers():
    wrapper = FakeWrapper()
    m = Map(wrapper=wrapper, village_id="41123", sector_radius=1)
    m.fetch_sectors(GAME_STATE)
    h = wrapper.headers_used or {}
    check(h.get("x-requested-with") == "XMLHttpRequest", f"faltou x-requested-with: {h}")
    check("json" in (h.get("accept") or ""), f"accept deveria pedir json: {h}")
    check(h.get("user-agent") == "x", "os headers do wrapper deveriam ser preservados")
    check(h is not wrapper.headers, "nao deveria mutar os headers do wrapper no lugar")


def test_fetch_parses_the_real_payload_into_the_shared_parser_shape():
    """
    O setor devolvido precisa ter a MESMA forma do prefetch, senao o laco de
    get_map() nao o consome. Este teste fixa a forma, com dado verbatim.
    """
    wrapper = FakeWrapper()
    m = Map(wrapper=wrapper, village_id="41123", sector_radius=1)
    out = m.fetch_sectors(GAME_STATE)
    sector = out[0]
    check("data" in sector, "setor sem chave 'data'")
    check("villages" in sector["data"], "setor sem data.villages")
    entry = sector["data"]["villages"]["0"]["1"]
    # Indices que build_cache_entry le: 0 id, 2 nome, 3 pontos, 4 dono,
    # 6 bonus, 11 tribo.
    check(entry[0] == "54810", f"id no indice 0: {entry[0]!r}")
    check(entry[2] == "Mirmidão X", f"nome no indice 2: {entry[2]!r}")
    check(int(entry[3].replace(".", "")) == 1173,
          f"pontos no indice 3 tem separador de milhar: {entry[3]!r}")
    check(entry[4] == "919932952", f"dono no indice 4: {entry[4]!r}")
    check(entry[11] == "494", f"tribo no indice 11: {entry[11]!r}")
    check(len(entry) == 13, f"entrada deveria ter 13 campos, tem {len(entry)}")


def test_fetch_degrades_to_empty_on_every_failure_mode():
    """
    Segundo padrao do CLAUDE.md: get_url devolve None em QUALQUER excecao, e
    uma resposta 200 pode nao ser a tela esperada. Nenhum desses casos pode
    levantar -- o farm segue com o prefetch.
    """
    for mode, label in [("none", "get_url devolveu None"),
                        ("notjson", "200 que nao e JSON (login/bot protect)"),
                        ("dict", "JSON que nao e lista")]:
        wrapper = FakeWrapper(response=mode)
        m = Map(wrapper=wrapper, village_id="41123", sector_radius=1)
        try:
            out = m.fetch_sectors(GAME_STATE)
        except Exception as exc:  # noqa: BLE001 - o teste existe para isto
            failures.append(f"{label}: levantou {type(exc).__name__}: {exc}")
            continue
        check(out == [], f"{label}: deveria devolver [], devolveu {out!r}")


def test_fetch_degrades_when_game_state_is_unusable():
    """
    game_state vem de um regex que devolve None quando a pagina nao e a
    esperada -- exatamente o caso da sessao expirada.
    """
    for gs, label in [(None, "game_state None"),
                      ({}, "game_state vazio"),
                      ({"village": {}}, "village sem coordenada"),
                      ({"village": {"x": "abc", "y": "9"}}, "coordenada nao numerica"),
                      ("<html>", "game_state que nem e dict")]:
        wrapper = FakeWrapper()
        m = Map(wrapper=wrapper, village_id="41123", sector_radius=1)
        try:
            out = m.fetch_sectors(gs)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{label}: levantou {type(exc).__name__}: {exc}")
            continue
        check(out == [], f"{label}: deveria devolver [], devolveu {out!r}")
        check(wrapper.urls == [], f"{label}: nao deveria ter pedido nada")


def test_coordinates_come_from_game_state_as_strings_too():
    """O jogo publica numero em algumas telas e string em outras (player.villages
    veio como "8" na Feature 24). int() tem que dar conta dos dois."""
    wrapper = FakeWrapper()
    m = Map(wrapper=wrapper, village_id="41123", sector_radius=1)
    out = m.fetch_sectors({"village": {"x": "577", "y": "306"}, "locale": "pt_BR"})
    check(len(out) == 1, "coordenada em string deveria funcionar")
    check("560_300=0" in wrapper.urls[0],
          f"setor errado a partir de coordenada string: {wrapper.urls[0]}")


for fn in [
    test_sector_grid_is_aligned_and_sized,
    test_sector_grid_covers_the_village_on_every_side,
    test_sector_grid_drops_negative_coordinates,
    test_merge_does_not_duplicate_prefetch_sectors,
    test_merge_survives_junk_entries,
    test_merge_with_empty_prefetch,
    test_fetch_is_off_by_default,
    test_fetch_builds_the_url_the_game_uses,
    test_fetch_sends_xhr_headers_without_losing_wrapper_headers,
    test_fetch_parses_the_real_payload_into_the_shared_parser_shape,
    test_fetch_degrades_to_empty_on_every_failure_mode,
    test_fetch_degrades_when_game_state_is_unusable,
    test_coordinates_come_from_game_state_as_strings_too,
]:
    fn()

if failures:
    print(f"FALHOU ({len(failures)} problema(s)):")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("OK: grade de setores, merge e degradacao do fetch de mapa")
