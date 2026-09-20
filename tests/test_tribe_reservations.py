"""
Parser do quadro oficial de reservas da tribo, e o quadro em si.

  Extractor.tribe_reservations()  -- o markup
  Extractor.own_player_id()       -- "minha" contra "de outro"
  ReservationBoard                -- TTL, graca e o contrato do None
  manual_exclusion()              -- a valvula de escape

PROCEDENCIA DA FIXTURE -- DUAS LINHAS REAIS E UMA DERIVADA
----------------------------------------------------------
Capturada de `game.php?screen=ally&mode=reservations` do br143 em 2026-09-20,
com o WebWrapper do proprio bot (7o padrao do CLAUDE.md: a resposta depende de
como se pergunta).

  #75920  VERBATIM. Barbara (data-player="0", Proprietario = "---"), reservada
          por terceiro COM tribo -> dois links na celula do reservante.
  #74922  VERBATIM. Aldeia de JOGADOR reservada por terceiro -> tem link
          `info_player` na celula do dono TAMBEM, que e a armadilha.
  #76156  ⚠️ NAO VERBATIM -- DERIVADA. Barbara reservada por MIM.

Sobre a #76156, para ninguem confiar nela mais do que ela merece: a captura da
linha real foi bloqueada no meio da sessao, entao esta linha foi montada a
partir da #75920 trocando o id do reservante pelo meu (5955651) e a tribo pela
minha ([SQUAD 02], ally 987 do game_state). O que E fato medido: o filtro
"[Sua]" da propria tela (`group_id=creator_id&filter=5955651`) devolveu
EXATAMENTE 1 linha, ou seja a conta tem uma reserva propria e o jogo a
identifica por esse id; e a estrutura da celula nao depende de quem reservou.
O que NAO foi observado: essa linha renderizada. Se o jogo marcar a reserva
propria de forma diferente (um botao de remover a mais, por exemplo), o parse
posicional continua valendo -- ele le `info_player` dentro da celula 3 -- mas
**trocar esta linha pela real na proxima captura e barato e deve ser feito**,
porque markup suposto e exatamente o que fez `loyalty_from_report()` falhar.

Rodar: python tests/test_tribe_reservations.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.extractors import Extractor
from game.reservations import ReservationBoard, manual_exclusion


MY_ID = "5955651"

# `TribalWars.updateGameData(...)` reduzido ao que o parser le -- o resto do
# game_state real tem ~40 chaves e nao muda nada aqui. Os valores de player
# sao os reais da conta.
GAME_STATE = (
    'TribalWars.updateGameData({"player":{"id":5955651,"name":"sccj",'
    '"ally":"987","villages":"30"},"village":{"id":32056}});'
)

# ---- recorte verbatim do servidor, tres linhas do <tbody> --------------------
ROWS = '''
<tr id="reservation_75920">
    <td>
                <input type="checkbox" name="ids[]" value="75920"/>

                <span class="village_anchor" data-player="0" data-id="40808"><a href="/game.php?village=32056&amp;screen=info_village&amp;id=40808" >Aldeia de bárbaros (531|289) K25</a></span>
            </td>
    <td>1012</td>
    <td>---</td>
    <td>
                    <a href="/game.php?village=32056&amp;screen=info_ally&amp;&amp;id=16">
                [RANDOW]
            </a>
                <a href="/game.php?village=32056&amp;screen=info_player&amp;id=919714218"  title="Os Randola">Conde Strahd von Zarovch</a>
    </td>
    <td>hoje às 07:45</td>
    <td style="white-space:nowrap;">
        <img id="img_load_75920" src="/graphic/throbber18.gif" style="display:none;" alt="carregando..." />
                    <img src="/graphic/show_comment_disabled.png" alt="Nenhum comentário disponível" title="Nenhum comentário disponível" />
                <a href="/game.php?village=32056&amp;screen=map&amp;x=531&amp;y=289&amp;beacon"><img src="/graphic/map_center.png" alt="Centralizar mapa" title="Centralizar mapa" /></a>
            </td>
</tr>

<tr id="reservation_74922">
    <td>
                <input type="checkbox" name="ids[]" value="74922"/>

                <span class="village_anchor" data-player="920036122" data-id="36455"><a href="/game.php?village=32056&amp;screen=info_village&amp;id=36455" >GoofyDark de aldeia (516|304) K35</a></span>
            </td>
    <td>9129</td>
    <td><a href="/game.php?village=32056&amp;screen=info_player&amp;id=920036122"  title="Huntrs">GoofyDark</a></td>
    <td>
                <a href="/game.php?village=32056&amp;screen=info_player&amp;id=492673"  title="Os Randolinhos">Gedoz</a>
    </td>
    <td>hoje às 08:38</td>
    <td style="white-space:nowrap;">
        <img id="img_load_74922" src="/graphic/throbber18.gif" style="display:none;" alt="carregando..." />
                    <img src="/graphic/show_comment_disabled.png" alt="Nenhum comentário disponível" title="Nenhum comentário disponível" />
                <a href="/game.php?village=32056&amp;screen=map&amp;x=516&amp;y=304&amp;beacon"><img src="/graphic/map_center.png" alt="Centralizar mapa" title="Centralizar mapa" /></a>
            </td>
</tr>

<tr id="reservation_76156">
    <td>
                <input type="checkbox" name="ids[]" value="76156"/>

                <span class="village_anchor" data-player="0" data-id="40314"><a href="/game.php?village=32056&amp;screen=info_village&amp;id=40314" >Aldeia de bárbaros (575|303) K35</a></span>
            </td>
    <td>1104</td>
    <td>---</td>
    <td>
                    <a href="/game.php?village=32056&amp;screen=info_ally&amp;&amp;id=987">
                [SQUAD 02]
            </a>
                <a href="/game.php?village=32056&amp;screen=info_player&amp;id=5955651"  title="SQUAD 02">sccj</a>
    </td>
    <td>hoje às 11:02</td>
    <td style="white-space:nowrap;">
        <img id="img_load_76156" src="/graphic/throbber18.gif" style="display:none;" alt="carregando..." />
                    <img src="/graphic/show_comment_disabled.png" alt="Nenhum comentário disponível" title="Nenhum comentário disponível" />
                <a href="/game.php?village=32056&amp;screen=map&amp;x=575&amp;y=303&amp;beacon"><img src="/graphic/map_center.png" alt="Centralizar mapa" title="Centralizar mapa" /></a>
            </td>
</tr>
'''

PAGE = GAME_STATE + '<a href="/game.php?screen=ally&amp;mode=reservations">x</a>' + ROWS

# A pagina de login que o jogo devolve quando a sessao expirou. Recorte do
# comeco da resposta REAL de 2026-09-20 (51.713 bytes, status 200): o ponto e
# que ela nao tem `mode=reservations` em lugar nenhum -- medido, 0 ocorrencias
# contra 122 na tela de verdade.
LOGIN_PAGE = (
    '<!DOCTYPE html><html><head><title>Tribal Wars - Browsergame medieval'
    '</title></head><body><div id="login_wrap">'
    '<form method="post" action="/index.php?action=login"></form></div></body></html>'
)


# --------------------------------------------------------------------------
# O markup
# --------------------------------------------------------------------------

def test_parseia_as_tres_linhas():
    claims = Extractor.tribe_reservations(PAGE)
    assert claims is not None
    assert len(claims) == 3, claims


def test_alvo_e_a_aldeia_e_nao_o_id_da_reserva():
    """
    O `<tr id="reservation_75920">` e o id da RESERVA; o alvo e o 40808 do
    `data-id`. Confundir os dois faria a exclusao nunca casar com nada em
    cache/conquest, e falhar em silencio -- o bot conquistaria igual.
    """
    claim = Extractor.tribe_reservations(PAGE)[0]
    assert claim["reservation_id"] == "75920"
    assert claim["village_id"] == "40808"
    assert claim["village_id"] != claim["reservation_id"]


def test_coordenada_e_dono_saem_da_linha():
    barbara, jogador, minha = Extractor.tribe_reservations(PAGE)
    assert barbara["location"] == (531, 289)
    assert barbara["owner"] == "0", "barbara tem data-player=0"
    assert jogador["location"] == (516, 304)
    assert jogador["owner"] == "920036122"
    assert minha["location"] == (575, 303)


def test_reservante_e_o_jogador_e_nao_a_tribo():
    """
    A celula do reservante tem DOIS links quando ele tem tribo, e o da tribo
    vem primeiro. Pegar "o primeiro id da celula" traria a tribo (16), que nao
    e jogador nenhum.
    """
    barbara, jogador, _ = Extractor.tribe_reservations(PAGE)
    assert barbara["reserved_by_id"] == "919714218"
    assert barbara["reserved_by_name"] == "Conde Strahd von Zarovch"
    assert barbara["reserved_by_tribe"] == "RANDOW"
    # Sem tribo na celula: nao pode vazar o "Huntrs" do dono (celula anterior).
    assert jogador["reserved_by_id"] == "492673"
    assert jogador["reserved_by_name"] == "Gedoz"


def test_nao_confunde_reservante_com_proprietario():
    """
    Na linha da aldeia de jogador, a celula 2 (Proprietario) tambem tem um
    link `info_player`. Um regex solto sobre a linha inteira pegaria o dono
    (920036122) em vez de quem reservou (492673) -- e o bot acharia que a
    reserva e de quem ja mora la.
    """
    jogador = Extractor.tribe_reservations(PAGE)[1]
    assert jogador["owner"] == "920036122"
    assert jogador["reserved_by_id"] == "492673"
    assert jogador["reserved_by_id"] != jogador["owner"]


def test_validade_fica_crua():
    """
    A coluna e "Data de validade" (o <th> ordena por `sort=expires_at`), e o
    texto e relativo e em portugues. A Fase 1 nao precisa do valor -- estar na
    lista ja significa reservada -- entao ele e guardado sem parse.
    """
    claim = Extractor.tribe_reservations(PAGE)[0]
    assert claim["expires_text"] == "hoje às 07:45"


def test_premissa_do_parse_por_celula():
    """
    O parse por celula so vale se nao houver `<td>` aninhado dentro da linha.
    Isso foi MEDIDO contra a captura real (6 celulas), nao suposto -- o
    corolario do 19o padrao: armadilha plausivel precisa ser medida antes de
    virar comentario no codigo.
    """
    import re
    row = re.search(r'<tr id="reservation_\d+">(.*?)</tr>', ROWS, re.S).group(1)
    assert len(re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)) == 6


# --------------------------------------------------------------------------
# A distincao que decide se barra ou nao
# --------------------------------------------------------------------------

def test_identidade_sai_do_game_state():
    assert Extractor.own_player_id(PAGE) == MY_ID


def test_pagina_de_login_nao_e_lista_vazia():
    """
    O CONTRATO desta feature. A resposta de sessao expirada e um 200 com HTML
    de login. Se o parser devolvesse [] o bot concluiria "nada reservado" e
    conquistaria livremente -- exatamente o incidente, so que agora com uma
    feature de seguranca dando a permissao.
    """
    assert Extractor.tribe_reservations(LOGIN_PAGE) is None
    assert Extractor.tribe_reservations(None) is None
    # E uma tela de reservas de verdade porem vazia continua sendo [].
    vazia = GAME_STATE + '<a href="/game.php?screen=ally&amp;mode=reservations">x</a>'
    assert Extractor.tribe_reservations(vazia) == []


# --------------------------------------------------------------------------
# O quadro
# --------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, text):
        self.text = text


class _FakeWrapper:
    def __init__(self, *pages):
        self.pages = list(pages)
        self.calls = []

    def get_url(self, url):
        self.calls.append(url)
        page = self.pages.pop(0) if len(self.pages) > 1 else self.pages[0]
        return None if page is None else _FakeResponse(page)


def _board(*pages, **cfg):
    conquest = {"respect_tribe_reservations": True}
    conquest.update(cfg)
    return ReservationBoard(_FakeWrapper(*pages), {"conquest": conquest})


def test_barra_reserva_de_terceiro_e_nao_a_minha():
    board = _board(PAGE)
    assert board.refresh("32056")
    assert board.is_readable()

    alheia = board.claimed_by_other("40808")
    assert alheia and alheia["reserved_by_name"] == "Conde Strahd von Zarovch"

    assert board.claimed_by_other("40314") is None, (
        "40314 esta reservada por mim (5955651) -- barrar aqui faria o bot "
        "recusar o proprio alvo"
    )
    assert board.claimed_by_other("99999") is None, "alvo livre nao e barrado"


def test_barra_por_coordenada_tambem():
    """
    Um alvo manual pode chegar como coordenada antes de ter id resolvido.
    """
    board = _board(PAGE)
    board.refresh("32056")
    assert board.claimed_by_other("99999", location=(531, 289))
    assert board.claimed_by_other("99999", location=(516, 304))
    assert board.claimed_by_other("99999", location=(575, 303)) is None  # minha


def test_blocked_when_board_unreadable():
    """
    Sem leitura, `is_readable()` e False e `claimed_by_other()` devolve None
    para tudo. Os dois juntos sao o contrato: quem for iniciar conquista tem
    que checar `is_readable()`, porque None aqui significa tanto "livre"
    quanto "nao sei".
    """
    board = _board(LOGIN_PAGE)
    assert board.refresh("32056") is False
    assert board.is_readable() is False
    assert board.claimed_by_other("40808") is None


def test_get_url_none_tambem_e_ilegivel():
    board = _board(None)
    assert board.refresh("32056") is False
    assert board.is_readable() is False


def test_leitura_boa_sobrevive_a_falha_seguinte():
    """
    Um soluco de rede nao pode zerar a conquista do imperio: o quadro muda em
    escala de dias (limite de 3 dias, lido da tela), entao servir a leitura
    anterior por algumas horas e mais seguro que ficar cego.
    """
    board = _board(PAGE, LOGIN_PAGE)
    assert board.refresh("32056")
    assert board.refresh("32056", force=True) is True, "caiu na graca"
    assert board.is_readable()
    assert board.claimed_by_other("40808"), "ainda sabe o que era de quem"


def test_ttl_evita_reler_no_mesmo_ciclo():
    board = _board(PAGE, PAGE)
    board.refresh("32056")
    board.refresh("32056")
    board.refresh("32056")
    assert len(board.wrapper.calls) == 1, "TTL nao segurou a releitura"
    assert "page=all" in board.wrapper.calls[0], (
        "sem page=all a lista vem paginada em 10 -- eram 49 paginas em "
        "2026-09-20, e o bot leria so a primeira"
    )


def test_desligado_nao_barra_nada():
    board = _board(PAGE, respect_tribe_reservations=False)
    board.refresh("32056")
    assert board.claimed_by_other("40808") is None
    assert board.is_readable() is True, (
        "com a feature off o bot nao fica 'cego' -- ele so nao consulta"
    )


# --------------------------------------------------------------------------
# A valvula de escape
# --------------------------------------------------------------------------

def test_exclusao_manual_por_id_e_por_coordenada():
    cfg = {"conquest": {"excluded_targets": ["40808", "516|304", " 600|400 "]}}
    assert manual_exclusion(cfg, "40808") == "40808"
    assert manual_exclusion(cfg, "99999", location=(516, 304)) == "516|304"
    assert manual_exclusion(cfg, "99999", location=(600, 400)) == " 600|400 ".strip()
    assert manual_exclusion(cfg, "99999", location=(1, 2)) is None
    assert manual_exclusion({}, "40808") is None


if __name__ == "__main__":
    falhas = 0
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok   %s" % nome)
            except Exception as exc:
                falhas += 1
                print("FALHA %s: %r" % (nome, exc))
    sys.exit(1 if falhas else 0)
