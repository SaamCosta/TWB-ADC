"""
Testes da venda na bolsa premium (Feature 34, game/resources.py).

Os numeros da bolsa abaixo sao LEITURA REAL do br143 em 2026-08-20, tirados de
game.php?screen=market&mode=exchange com a sessao do bot (aldeia 41123, K35).
Nao sao inventados: a versao anterior desta funcao nunca vendeu nada
justamente por ter sido escrita contra um numero que ninguem conferiu contra o
servidor.

O estado medido e o de bolsa 100% CHEIA -- stock == capacity nos tres
recursos, que e o que bloqueia a venda no K35 hoje. O caso de bolsa vazia e
construido a partir das MESMAS constantes reais, mudando so o estoque; isso e
legitimo porque a formula de preco marginal e a do proprio jogo
(calculate_marginal_price, portada do JS e conferida contra o servidor), e nao
uma suposicao sobre formato de resposta.

Rodar: python tests/test_premium_exchange.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game.resources import MERCHANT_CAPACITY, PremiumExchange, ResourceManager

# interface.php nao publica isto; veio do PremiumExchange.receiveData({...})
# embutido na tela da bolsa, verbatim.
CONSTANTS = {
    "resource_base_price": 0.015,
    "resource_price_elasticity": 0.0148,
    "stock_size_modifier": 20000,
}
TAX = {"buy": 0.03, "sell": 0}
CAPACITY = {"wood": 257683, "stone": 267540, "iron": 249405}

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


def make_data(stock, merchants=40):
    return {
        "stock": dict(stock),
        "capacity": dict(CAPACITY),
        "tax": dict(TAX),
        "constants": dict(CONSTANTS),
        "duration": 7200,
        "merchants": merchants,
        "rates": {},
    }


def make_exchange(data):
    return PremiumExchange(
        wrapper=None,
        stock=data["stock"],
        capacity=data["capacity"],
        tax=data["tax"],
        constants=data["constants"],
        duration=data["duration"],
        merchants=data["merchants"],
    )


def make_manager(actual=None, requested=None, **cfg):
    rm = ResourceManager(wrapper=None, village_id="41123")
    rm.actual = actual if actual is not None else {"wood": 50000, "stone": 50000, "iron": 50000}
    rm.requested = requested or {}
    rm.do_premium_trade = True
    for key, value in cfg.items():
        setattr(rm, key, value)
    return rm


def test_full_bag_sells_nothing():
    """
    Estado real do K35 hoje: stock == capacity nos tres recursos. O jogo recusa
    venda nessa situacao ("quando o estoque de uma troca esta cheio, nenhum
    recurso desse tipo pode mais ser vendido para ela"), entao o bot nao pode
    nem tentar.
    """
    data = make_data(dict(CAPACITY))
    rm = make_manager(premium_max_rate=100000)  # limiar absurdo de proposito
    offer = rm._premium_pick_offer(data, make_exchange(data))
    check(offer is None,
          f"bolsa cheia deveria bloquear a venda, mas escolheu {offer}")


def test_empty_bag_sells_at_the_floor_rate():
    """
    Com estoque zero o preco marginal e o base_price puro: 1/0.015 = 66,7
    recursos por PP. E a janela que faz a estrategia valer a pena.
    """
    data = make_data({"wood": 0, "stone": 0, "iron": 0})
    exchange = make_exchange(data)
    rate = exchange.calculate_rate_for_one_point("wood")
    check(60 <= rate <= 67,
          f"taxa de bolsa vazia fora do esperado (~66): {rate}")

    rm = make_manager(premium_max_rate=90, premium_batch=1000)
    offer = rm._premium_pick_offer(data, exchange)
    check(offer is not None, "bolsa vazia com taxa 66 deveria vender")
    if offer:
        resource, amount, offered_rate = offer
        check(amount == 1000, f"deveria vender o lote de 1000, veio {amount}")
        check(offered_rate <= 90, f"vendeu acima do limiar: {offered_rate}")


def test_rate_threshold_blocks_expensive_sales():
    """
    A regra central da estrategia: esperar a taxa cair em vez de despejar.
    Com a bolsa pela metade a taxa sobe muito acima de 90.
    """
    half = {r: CAPACITY[r] // 2 for r in CAPACITY}
    data = make_data(half)
    exchange = make_exchange(data)
    rate = exchange.calculate_rate_for_one_point("wood")
    check(rate > 90, f"esperava taxa alta com bolsa pela metade, veio {rate}")

    rm = make_manager(premium_max_rate=90)
    check(rm._premium_pick_offer(data, exchange) is None,
          "taxa acima do limiar deveria bloquear a venda")

    # Mesmo estado, limiar frouxo: agora vende.
    rm_loose = make_manager(premium_max_rate=rate + 1)
    check(rm_loose._premium_pick_offer(data, exchange) is not None,
          "com limiar acima da taxa a venda deveria acontecer")


def test_reserved_resources_are_never_sold():
    """
    `requested` e o que construcao/recrutamento ja prometeram gastar. Vender
    isso desfaz o trabalho do ciclo.
    """
    data = make_data({"wood": 0, "stone": 0, "iron": 0})
    rm = make_manager(
        actual={"wood": 1200, "stone": 0, "iron": 0},
        requested={"building": {"wood": 1000}},
        premium_max_rate=90,
        premium_batch=1000,
    )
    check(rm._premium_sellable("wood") == 200,
          f"sobra vendavel errada: {rm._premium_sellable('wood')}")

    # A primeira versao deste teste exigia que NENHUMA oferta de madeira
    # saisse. Estava errada: a reserva foi respeitada -- o codigo ofereceu 200
    # dos 1200, nao os 1200. O invariante certo e "nunca acima da sobra".
    offer = rm._premium_pick_offer(data, make_exchange(data))
    if offer and offer[0] == "wood":
        check(offer[1] <= 200,
              f"ofereceu {offer[1]} de madeira com so 200 livres: {offer}")

    # Com o piso de lote em 1000 (padrao), 200 nao enche um mercador e a venda
    # espera. Foi esta rodada de teste que motivou o piso existir.
    rm.premium_min_batch = 1000
    check(rm._premium_pick_offer(data, make_exchange(data)) is None,
          "200 de sobra nao deveria virar viagem de mercador com piso 1000")

    # E com o piso relaxado a venda parcial volta a acontecer, provando que o
    # bloqueio acima vem do piso e nao da reserva.
    rm.premium_min_batch = 100
    partial = rm._premium_pick_offer(data, make_exchange(data))
    check(partial is not None and partial[1] == 200,
          f"com piso 100 deveria vender os 200 livres, veio {partial}")


def test_keep_floor_is_honoured():
    data = make_data({"wood": 0, "stone": 0, "iron": 0})
    rm = make_manager(
        actual={"wood": 1500, "stone": 0, "iron": 0},
        premium_max_rate=90,
        premium_batch=1000,
    )
    rm.premium_keep = {"wood": 1400, "stone": 0, "iron": 0}
    check(rm._premium_sellable("wood") == 100,
          f"piso ignorado: sobra {rm._premium_sellable('wood')}")


def test_premium_keep_is_per_instance():
    """
    Primeiro padrao recorrente do projeto: dict mutavel como atributo de classe
    vira estado compartilhado entre aldeias. Existe um ResourceManager por
    aldeia.
    """
    a = ResourceManager(wrapper=None, village_id="1")
    b = ResourceManager(wrapper=None, village_id="2")
    a.premium_keep["wood"] = 5000
    check(b.premium_keep["wood"] == 0,
          "premium_keep esta compartilhado entre instancias (atributo de classe)")


def test_rate_hash_extraction_survives_every_return_shape():
    """
    get_api_action() devolve TRES coisas: o JSON, o objeto Response cru quando
    o corpo nao e JSON, ou None em falha de rede. A versao anterior fazia
    result["response"][0]["rate_hash"] direto, o que era TypeError em dois dos
    tres casos.

    ⚠️ O formato com rate_hash NAO foi validado em pt-BR -- e suposicao herdada
    do upstream, e a bolsa cheia do br143 impede exercitar isso antes do mundo
    novo. Estes casos travam o COMPORTAMENTO do parser (nunca estourar, sempre
    devolver None quando nao ha hash), nao a forma correta da resposta.
    """
    rm = make_manager()

    class FakeResponse:
        text = "<html>nao sou json</html>"

    cases = [
        (None, None, "falha de rede"),
        (FakeResponse(), None, "resposta nao-JSON"),
        ({}, None, "dict vazio"),
        ({"response": []}, None, "lista vazia"),
        ({"response": [{"nada": 1}]}, None, "sem rate_hash"),
        ({"response": [{"rate_hash": "abc"}]}, "abc", "lista com hash"),
        ({"response": {"rate_hash": "def"}}, "def", "dict com hash"),
        ({"rate_hash": "ghi"}, "ghi", "hash na raiz"),
    ]
    for payload, expected, label in cases:
        try:
            got = rm._premium_extract_rate_hash(payload, "wood", 1000)
        except Exception as exc:
            failures.append(f"_premium_extract_rate_hash estourou em {label}: {exc!r}")
            continue
        check(got == expected,
              f"_premium_extract_rate_hash({label}) devolveu {got!r}, esperava {expected!r}")


def test_disabled_manager_does_nothing():
    """Sem o gate ligado a funcao nao pode nem tocar a rede (wrapper e None)."""
    rm = make_manager()
    rm.do_premium_trade = False
    try:
        rm.do_premium_stuff()
    except Exception as exc:
        failures.append(f"do_premium_stuff desligado deveria retornar, estourou: {exc!r}")


def test_merchant_capacity_matches_optimize_n_assumption():
    """
    optimize_n() ja assumia 1000 via `size=1000`. A constante existe para o
    numero ter nome; se alguem mudar um dos dois, isto quebra.
    """
    check(MERCHANT_CAPACITY == 1000,
          f"MERCHANT_CAPACITY mudou para {MERCHANT_CAPACITY} -- conferir optimize_n(size=)")


for fn in [
    test_full_bag_sells_nothing,
    test_empty_bag_sells_at_the_floor_rate,
    test_rate_threshold_blocks_expensive_sales,
    test_reserved_resources_are_never_sold,
    test_keep_floor_is_honoured,
    test_premium_keep_is_per_instance,
    test_rate_hash_extraction_survives_every_return_shape,
    test_disabled_manager_does_nothing,
    test_merchant_capacity_matches_optimize_n_assumption,
]:
    fn()

if failures:
    print(f"FALHOU ({len(failures)} problema(s)):")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("OK: venda na bolsa premium")
