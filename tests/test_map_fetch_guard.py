"""
Testes da guarda de rede de `Map.get_map()`.

MOTIVACAO (incidente real, nao suposto). Em 2026-09-20 as 12:15 uma falha de
DNS transitoria derrubou o processo inteiro do bot. Recorte verbatim de
cache/logs/session_latest.log:

    12:15:47 - Requests - WARNING - GET .../game.php?village=37318&screen=map:
        ... NameResolutionError(... [Errno 11001] getaddrinfo failed)
    I crashed :(   'NoneType' object has no attribute 'text'
      File "game/village.py", line 950, in ensure_map_loaded
        self.area.get_map()
      File "game/map.py", line 53, in get_map
        game_state = Extractor.game_state(res)
      File "core/extractors.py", line 144, in game_state
        res = res.text
    AttributeError: 'NoneType' object has no attribute 'text'
    12:16:01 - Requests - DEBUG - GET .../game.php?screen=overview [200]

A rede voltou **14 segundos depois** (12:16:01 respondeu 200). O custo desses
14 segundos foi o ciclo inteiro das 28 aldeias e, com ele, o
`BarbarianTrainPlanner` -- que roda por ultimo, depois do laco de aldeias. E
por isso que o gate de reservas (docs/backend.md 8.7) e os pools novos de
conquista (8.6) seguiam sem uma unica observacao em campo: o planejador nunca
era alcancado.

Segundo padrao do CLAUDE.md: `WebWrapper.get_url()` devolve None em QUALQUER
excecao, e por tabela `get_action` tambem.

A SEGUNDA METADE, que e a que se escreveria errado. `Map.fetch_delay` e 8h e a
instancia de Map **sobrevive entre ciclos** (village.py:945), enquanto
`last_fetch` era estampado ANTES de saber o resultado da requisicao. Uma guarda
ingenua (`if res is None: return False`) trocaria o crash por um apagao
silencioso de 8 horas: o bot seguiria vivo, sem mapa, e portanto sem farm e sem
eleicao de alvo -- e nada no log diria isso depois da primeira linha. Por isso a
janela so se fecha com leitura bem-sucedida, e o teste que importa aqui e o
`test_failure_does_not_burn_the_8h_window`.

Rodar: python tests/test_map_fetch_guard.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game.map import Map

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


# ---------------------------------------------------------------- fixtures

# Recorte VERBATIM da tela game.php?screen=map do br143 (setor 560|300, uma
# aldeia real), no formato que `Extractor.map_data` e `Extractor.game_state`
# consomem de fato -- os dois leem `res.text` com regex, entao a fixture precisa
# ser o texto da pagina, nao um dict ja parseado.
SECTOR = [
    {
        "x": 560,
        "y": 300,
        "tiles": None,
        "data": {
            "x": 560,
            "y": 300,
            "villages": {
                "17": {
                    "6": ["41123", 21, "BBM 001", "9.876", "5955651", 42,
                          None, "0", 4, None, "standard", "494", 21]
                }
            },
            "players": {},
            "allies": {},
        },
    }
]

GAME_STATE = {"village": {"x": 577, "y": 306, "id": 41123}, "locale": "pt_BR"}

MAP_PAGE = (
    "<html><script>\n"
    "TribalWars.updateGameData(%s);\n"
    "TWMap.sectorPrefech = %s;\n"
    "</script></html>"
) % (json.dumps(GAME_STATE), json.dumps(SECTOR))

# 200 que NAO e a tela de mapa: o que o servidor devolve com a sessao expirada
# ou em bot protection. Os dois regex falham, entao game_state vem None.
LOGIN_PAGE = "<html><body>Login</body></html>"


class FakeResponse:
    def __init__(self, text):
        self.text = text


class FakeWrapper:
    """Conta as requisicoes em vez de ir a rede."""

    headers = {"user-agent": "x", "Referer": "y"}

    def __init__(self, responses):
        # Lista de respostas, consumida em ordem; a ultima se repete.
        self.responses = list(responses)
        self.calls = 0

    def get_action(self, village_id=None, action=None):
        self.calls += 1
        idx = min(self.calls - 1, len(self.responses) - 1)
        page = self.responses[idx]
        return None if page is None else FakeResponse(page)

    def get_url(self, url, headers=None):
        # sector_radius fica em 0 nestes testes, entao fetch_sectors nem chega
        # aqui; presente so para a instancia ser utilizavel.
        return None


def new_map(responses):
    return Map(wrapper=FakeWrapper(responses), village_id="41123", sector_radius=0)


# ---------------------------------------------------------------- a guarda

def test_network_failure_does_not_raise():
    """O crash de 2026-09-20: res=None chegava cru em Extractor.game_state."""
    area = new_map([None])
    try:
        result = area.get_map()
    except AttributeError as exc:
        failures.append(
            "res=None deveria degradar, mas levantou AttributeError: %s" % exc
        )
        return
    check(result is False,
          "falha de rede deveria devolver False, devolveu %r" % (result,))


def test_failure_keeps_the_previous_map():
    """
    Degradar nao pode significar esquecer. O farm itera sobre `map.villages` e
    o planejador de conquista usa `my_location`; um ciclo com rede ruim deve
    seguir com o mapa do ciclo anterior, nao com um mapa vazio.
    """
    area = new_map([MAP_PAGE, None])
    check(area.get_map() is True, "a primeira leitura deveria ter funcionado")
    villages_before = dict(area.villages)
    location_before = list(area.my_location)
    check(len(villages_before) == 1,
          "a fixture deveria render 1 aldeia, rendeu %d" % len(villages_before))

    # Forca a janela a vencer para a segunda chamada ir a rede.
    area.last_fetch = 0
    area.get_map()
    check(area.villages == villages_before,
          "a falha de rede apagou o mapa anterior: %r" % (area.villages,))
    check(area.my_location == location_before,
          "a falha de rede apagou my_location: %r" % (area.my_location,))


def test_failure_does_not_burn_the_8h_window():
    """
    O teste que importa. `fetch_delay` e 8h e a instancia sobrevive entre
    ciclos, entao estampar `last_fetch` antes de saber o resultado faria 14
    segundos de DNS ruim custarem 8 horas de mapa -- em silencio.
    """
    area = new_map([None, MAP_PAGE])
    area.get_map()
    check(area.wrapper.calls == 1,
          "esperava 1 requisicao, houve %d" % area.wrapper.calls)

    # Proximo ciclo, sem mexer em last_fetch: tem que tentar de novo.
    result = area.get_map()
    check(area.wrapper.calls == 2,
          "apos falha o ciclo seguinte deveria tentar de novo, mas get_map() "
          "voltou pela janela de 8h (requisicoes: %d)" % area.wrapper.calls)
    check(result is True,
          "a releitura deveria ter funcionado, devolveu %r" % (result,))
    check(len(area.villages) == 1,
          "a releitura deveria popular o mapa, tem %d aldeias" % len(area.villages))


def test_success_does_close_the_window():
    """
    O contrapeso do teste acima: sem isto, 'restaurar last_fetch' poderia ter
    sido escrito frouxo demais e o bot pediria a tela de mapa todo ciclo, que e
    justamente o custo que `fetch_delay` existe para evitar.
    """
    area = new_map([MAP_PAGE])
    check(area.get_map() is True, "a leitura deveria ter funcionado")
    check(area.wrapper.calls == 1, "esperava 1 requisicao")
    area.get_map()
    check(area.wrapper.calls == 1,
          "leitura bem-sucedida deveria fechar a janela de 8h, mas houve %d "
          "requisicoes" % area.wrapper.calls)


# ------------------------------------------------- 200 que nao e a tela de mapa

def test_page_without_game_state_does_not_raise():
    """
    Sessao expirada/bot protection: 200 com markup de login. `game_state`
    devolve None implicitamente e `_fallback_location` nao pode indexar isso.
    """
    area = new_map([LOGIN_PAGE])
    try:
        result = area.get_map()
    except (TypeError, KeyError) as exc:
        failures.append("200 sem game_state levantou %s: %s"
                        % (type(exc).__name__, exc))
        return
    check(result is False,
          "pagina sem mapa deveria devolver False, devolveu %r" % (result,))
    check(area.my_location is None,
          "sem game_state, my_location deveria ficar None, ficou %r"
          % (area.my_location,))


def test_page_without_game_state_does_not_burn_the_window():
    area = new_map([LOGIN_PAGE, MAP_PAGE])
    area.get_map()
    area.get_map()
    check(area.wrapper.calls == 2,
          "leitura falha (200 sem mapa) nao deveria fechar a janela de 8h "
          "(requisicoes: %d)" % area.wrapper.calls)
    check(len(area.villages) == 1, "a releitura deveria popular o mapa")


def test_fallback_location_tolerates_junk():
    """
    `_fallback_location` e chamada com o que quer que `Extractor.game_state`
    tenha devolvido, e esse valor nao e validado em lugar nenhum.
    """
    area = new_map([MAP_PAGE])
    for junk in (None, {}, {"village": None}, {"village": {}}, "texto", []):
        try:
            got = area._fallback_location(junk)
        except Exception as exc:
            failures.append("_fallback_location(%r) levantou %s: %s"
                            % (junk, type(exc).__name__, exc))
            continue
        check(got is None,
              "_fallback_location(%r) deveria dar None, deu %r" % (junk, got))
    check(area._fallback_location(GAME_STATE) == [577, 306],
          "game_state valido deveria dar [577, 306], deu %r"
          % (area._fallback_location(GAME_STATE),))


# ---------------------------------------------------------------- runner

if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            # Uma excecao inesperada e o sintoma central deste arquivo (o bug
            # original era um AttributeError cru), entao ela vira falha
            # registrada em vez de abortar a bateria e esconder as demais.
            try:
                fn()
            except Exception as exc:
                failures.append("%s levantou %s: %s"
                                % (name, type(exc).__name__, exc))
    if failures:
        print("FAIL (%d)" % len(failures))
        for f in failures:
            print("  - %s" % f)
        sys.exit(1)
    print("OK - guarda de rede de Map.get_map()")
