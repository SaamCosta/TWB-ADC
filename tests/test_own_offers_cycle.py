"""
"Todas as suas ofertas" do mercado lida uma vez por ciclo (docs/backend.md
§8.63).

`drop_existing_trades()` baixava `screen=market&mode=all_own_offer` em toda
aldeia, todo ciclo (~50 GETs), e filtrava por `data-village`. A tela e da
CONTA: em 2026-10-17 uma oferta criada na BBM 001 (41123) foi listada lendo a
tela da BBM 002 (38409), e o POST de apagar do bot funcionou. A linha abaixo e
recorte verbatim daquela leitura, com o token `h` redigido.

So logica pura: nenhum teste faz requisicao.

Rodar: python tests/test_own_offers_cycle.py
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game.resources import ResourceManager

ROW_41123 = '''	<tr class="offer_container " id="offer_428353" data-id="428353" data-count="1" data-village="41123"
        data-wanted_wood="0" data-wanted_stone="100" data-wanted_iron="0">
		<td><input name="id_428353" type="checkbox" onkeydown="return no_enter(event)" /></td>

							        <td rowspan="1" id="village_41123" data-offer-count="1">
                    <a href="/game.php?village=41123&amp;screen=market&amp;mode=own_offer">BBM 001</a>
                </td>
							<td style="white-space:nowrap;"><span class="nowrap"><span class="icon header wood" title="Madeira"> </span>100</span> </td>
		<td style="white-space:nowrap;"><span class="nowrap"><span class="icon header stone" title="Argila"> </span>100</span> </td>
		<td id="offer_count_428353">1</td>
		<td>
                            <td style="min-width:140px;">
                                                            <a href="#" class="market_accept_offer btn float_right" data-id="428353" style="vertical-align:middle;">
                            Aceitar oferta
                        </a>
        	</tr>
'''
# Segunda linha sintetica de outra aldeia, no mesmo formato.
ROW_38409 = ROW_41123.replace("428353", "428360").replace("41123", "38409")
EMPTY = "Todas as suas ofertas Você não tem nada a oferecer atualmente."


# Toda tela de jogo traz isto; login e captcha nao (Extractor.game_state).
GAME = 'TribalWars.updateGameData({"village": {"id": 1}});'


class _Resp:
    def __init__(self, text):
        self.text = GAME + text


class _Meter:
    def __init__(self, started_at):
        self.started_at = started_at


class _Wrapper:
    def __init__(self, page, started_at=1000):
        self.page = page
        self.meter = _Meter(started_at)
        self.own_offers_cycle = None
        self.gets = []
        self.posts = []
        self.last_h = "h"

    def get_url(self, url):
        self.gets.append(url)
        return None if self.page is None else _Resp(self.page)

    def post_url(self, url, data):
        self.posts.append((url, data))
        return _Resp("")


def _man(wrapper, vid):
    man = ResourceManager.__new__(ResourceManager)
    man.logger = logging.getLogger("test_own_offers")
    man.wrapper = wrapper
    man.village_id = vid
    return man


def test_regex_do_bot_le_a_linha_verbatim():
    rows = _man(_Wrapper(ROW_41123), "41123").own_offers_this_cycle()
    # o link "Aceitar oferta" repete data-id, mas sem data-village depois
    assert rows == [("428353", "41123")], rows


def test_uma_leitura_por_ciclo_para_todas_as_aldeias():
    w = _Wrapper(ROW_41123 + ROW_38409)
    for vid in ("41123", "38409", "44683"):
        _man(w, vid).drop_existing_trades()
    assert len(w.gets) == 1, w.gets
    # cada aldeia apagou a sua, e so a sua
    assert [(u.split("village=")[1].split("&")[0], list(d)[0]) for u, d in w.posts] == [
        ("41123", "id_428353"), ("38409", "id_428360")], w.posts


def test_ciclo_novo_le_de_novo():
    w = _Wrapper(EMPTY)
    _man(w, "41123").drop_existing_trades()
    w.meter.started_at = 2000
    _man(w, "41123").drop_existing_trades()
    assert len(w.gets) == 2


def test_mesma_oferta_nao_e_apagada_duas_vezes():
    """A26-16: run_quest_actions() roda a aldeia de novo no mesmo ciclo."""
    w = _Wrapper(ROW_41123)
    _man(w, "41123").drop_existing_trades()
    _man(w, "41123").drop_existing_trades()
    assert len(w.posts) == 1, w.posts


def test_sem_medidor_le_por_chamada():
    w = _Wrapper(EMPTY, started_at=None)
    _man(w, "41123").drop_existing_trades()
    _man(w, "38409").drop_existing_trades()
    assert len(w.gets) == 2


def test_leitura_falha_nao_vira_lista_vazia_do_ciclo():
    w = _Wrapper(None)
    _man(w, "41123").drop_existing_trades()
    assert w.own_offers_cycle is None
    w.page = ROW_41123
    _man(w, "41123").drop_existing_trades()
    assert len(w.gets) == 2 and len(w.posts) == 1


def test_pagina_que_nao_e_do_jogo_nao_vale_pelo_ciclo():
    """Sessao vencida na 1a aldeia: zero linhas, mas nao "nenhuma oferta"."""
    w = _Wrapper("<html>login</html>")
    w.get_url = lambda url: (w.gets.append(url), type("R", (), {"text": "<html>login</html>"})())[1]
    _man(w, "41123").drop_existing_trades()
    assert w.own_offers_cycle is None
    _man(w, "38409").drop_existing_trades()
    assert len(w.gets) == 2


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
