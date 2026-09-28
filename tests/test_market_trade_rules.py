"""
A26-06 e A26-07 (`docs/backend.md` §8.32): as duas regras do mercado.

A26-06 -- `market.trade_max_per_hour` era lido como HORAS ENTRE TROCAS
(`last_trade + 3600 * valor`), o contrario do nome e do helpfile. Com o default
1 as duas leituras coincidem, e foi isso que escondeu o bug. Os testes usam
valores diferentes de 1 de proposito (17o padrao do CLAUDE.md).

A26-07 -- `check_other_offers()` aceitava qualquer oferta que entregasse o
recurso que falta e cobrasse ate todo o excedente: 1.000 de ferro por 20.000 de
madeira passava. Agora a proporcao nao pode passar de `trade_bias`.

So logica pura: nenhum teste faz requisicao.

Rodar: python tests/test_market_trade_rules.py
"""
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game.resources import ResourceManager


def _man(**attrs):
    man = ResourceManager.__new__(ResourceManager)
    man.logger = logging.getLogger("test_market")
    for key, value in attrs.items():
        setattr(man, key, value)
    return man


# --------------------------------------------------------------------------
# A26-06
# --------------------------------------------------------------------------

def test_valor_e_trocas_por_hora_nao_horas_entre_trocas():
    assert _man(trade_max_per_hour=12).trade_interval_seconds() == 300.0
    assert _man(trade_max_per_hour=0.5).trade_interval_seconds() == 7200.0
    # o unico valor em que as duas leituras concordam
    assert _man(trade_max_per_hour=1).trade_interval_seconds() == 3600.0


def test_zero_ou_negativo_desliga_em_vez_de_dividir_por_zero():
    assert _man(trade_max_per_hour=0).trade_interval_seconds() is None
    assert _man(trade_max_per_hour=-1).trade_interval_seconds() is None


def test_valor_ilegivel_cai_no_default_de_uma_por_hora():
    assert _man(trade_max_per_hour="abc").trade_interval_seconds() == 3600.0
    assert _man(trade_max_per_hour=None).trade_interval_seconds() == 3600.0


def test_manage_market_respeita_o_intervalo_novo():
    """
    Ponta a ponta no portao de manage_market: com 12/h e a ultima troca ha 10
    min, o bot pode trocar de novo. Na leitura antiga (12 h entre trocas) ele
    pararia no portao.
    """
    passed = []
    man = _man(trade_max_per_hour=12, last_trade=int(time.time()) - 600)
    # Tudo depois do portao e substituido: o teste so quer saber se passou.
    man.drop_existing_trades = lambda: passed.append(True)
    man.get_plenty_off = lambda: None
    orig_localtime = time.localtime
    # meio-dia: fora da janela 23h-6h em que manage_market nao troca
    time.localtime = lambda *_a: time.struct_time((2026, 9, 27, 12, 0, 0, 6, 270, 0))
    try:
        man.manage_market(drop_existing=True)
    finally:
        time.localtime = orig_localtime
    assert passed == [True], "o portao de intervalo barrou uma troca permitida"

    blocked = []
    man = _man(trade_max_per_hour=12, last_trade=int(time.time()) - 60)
    man.drop_existing_trades = lambda: blocked.append(True)
    man.manage_market(drop_existing=True)
    assert blocked == [], "trocou antes de 5 min com 12 por hora"


# --------------------------------------------------------------------------
# A26-07
# --------------------------------------------------------------------------

def _offer(offer_amount, wanted_amount, offered="iron", wanted="wood"):
    return {"id": "1", "offered": offered, "offer_amount": offer_amount,
            "wanted": wanted, "wanted_amount": wanted_amount}


def test_oferta_abusiva_e_recusada():
    """O exemplo da auditoria: 1.000 de ferro por 20.000 de madeira."""
    man = _man(trade_bias=1.0)
    assert not man.offer_is_acceptable(
        _offer(1000, 20000), "iron", 1000, "wood", willing_to_sell=30000)


def test_oferta_justa_ou_melhor_e_aceita():
    man = _man(trade_bias=1.0)
    assert man.offer_is_acceptable(_offer(1000, 1000), "iron", 1000, "wood", 30000)
    assert man.offer_is_acceptable(_offer(1200, 1000), "iron", 1000, "wood", 30000)


def test_teto_segue_o_trade_multiplier_value():
    # 1.000 por 1.100: passa com bias 1.2, nao passa com 1.0.
    assert _man(trade_bias=1.2).offer_is_acceptable(
        _offer(1000, 1100), "iron", 1000, "wood", 30000)
    assert not _man(trade_bias=1.0).offer_is_acceptable(
        _offer(1000, 1100), "iron", 1000, "wood", 30000)


def test_regras_antigas_continuam():
    man = _man(trade_bias=1.0)
    # recurso errado nos dois lados
    assert not man.offer_is_acceptable(_offer(1000, 900, offered="stone"), "iron", 1000, "wood", 30000)
    assert not man.offer_is_acceptable(_offer(1000, 900, wanted="stone"), "iron", 1000, "wood", 30000)
    # entrega menos do que falta
    assert not man.offer_is_acceptable(_offer(500, 400), "iron", 1000, "wood", 30000)
    # cobra mais do que temos sobrando
    assert not man.offer_is_acceptable(_offer(1000, 900), "iron", 1000, "wood", 800)


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok   %s" % name)
            except Exception as exc:
                failures += 1
                print("FALHA %s: %r" % (name, exc))
    sys.exit(1 if failures else 0)
