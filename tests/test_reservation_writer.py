"""
Fase 2 do quadro de reservas: criar, remover e o teto de vagas.

  ReservationWriter.claim_target()    -- criar, e a confirmacao pelo quadro
  ReservationWriter.release_claim()   -- remover, e a guarda de procedencia
  ReservationWriter.bot_slot_usage()  -- as 5 vagas da alianca

PROCEDENCIA DAS FIXTURES
------------------------
Todas as linhas sao VERBATIM de `screen=ally&mode=reservations&page=all` do
br143, capturadas em 2026-09-21 com o WebWrapper do proprio bot (7o padrao).
O quadro tinha 441 reservas, 3 delas desta conta.

  #79340  bárbara reservada por MIM, SEM comentario. E a do canario manual de
          21/09 -- a que prova que a linha propria traz link de apagar e
          `show_comment_disabled.png`.
  #77075  reservada por terceiro, COM comentario de verdade
          (`show_comment.png`). Entrou para o flag ter os dois lados.
  #75920  bárbara reservada por terceiro, sem comentario.

O contrato do `ajax=load_comment` NAO foi deduzido de HTML: saiu do
`ReservationManager.js` que a tela carrega, buscado do CDN estatico
`dsbr.innogamescdn.com` (sem sessao, logo sem gastar o limite de taxa da
conta). O `success` do jQuery le `{code, id, comment, rights}` e so aceita a
resposta quando `code` e truthy.

O QUE NAO TEM FIXTURE, E POR QUE ISSO DEIXOU DE IMPORTAR
--------------------------------------------------------
A resposta de recusa para alvo reservado por companheiro da PROPRIA tribo
nunca foi capturada (o canario de 21/09 so viu a de aliado: "Um aliado ja
reservou ..."). Isso era um buraco enquanto o desenho previa ler a mensagem de
sucesso/erro do POST. Nao e mais: `claim_target()` confirma pelo ESTADO DO
QUADRO relido, nunca pelo texto da resposta. Um parser ancorado numa frase
acertaria o caso de aliado e erraria calado o de companheiro de tribo -- e o
15o padrao ao contrario, um detector que nunca dispara. `test_criar_falha_
quando_o_quadro_nao_confirma` e o teste que cobre isso sem precisar da frase.

Rodar: python tests/test_reservation_writer.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.extractors import Extractor
from game.reservations import ReservationBoard, ReservationWriter


MY_ID = "5955651"
CSRF = "32afa79e"
STAMP = "Conquista em andamento -- trem a caminho"

GAME_STATE = (
    'TribalWars.updateGameData({"player":{"id":5955651,"name":"sccj",'
    '"ally":"987","villages":"30"},"village":{"id":32056}});'
)

# O formulario de criar, de onde sai o token `h`. Recorte verbatim.
CREATE_FORM = (
    '<form action="/game.php?village=32056&amp;screen=ally&amp;'
    'mode=reservations&amp;action=new_reservation&amp;group_id=all&amp;'
    'filter=&amp;h=32afa79e" method="post">'
    '<input type="hidden" name="x[]" id="inputx">'
    '<input type="hidden" name="y[]" id="inputy">'
    '<input type="radio" name="target_type" value="coord" checked="checked">'
    '<input class="comment_input" type="text" name="comment[]" '
    'placeholder="Comentário"/></form>'
)

# ---- linhas verbatim -------------------------------------------------------
MINHA = '''<tr id="reservation_79340">
    <td>
                <input type="checkbox" name="ids[]" value="79340"/>

                <span class="village_anchor" data-player="0" data-id="51540"><a href="/game.php?village=32056&amp;screen=info_village&amp;id=51540" >Aldeia-bonus (582|289) K25</a></span>
            </td>
    <td>1007</td>
    <td>---</td>
    <td>
                <a href="/game.php?village=32056&amp;screen=info_player&amp;id=5955651"  title="Os Randolinhos">sccj</a>
    </td>
    <td>em 24.09. às 07:49</td>
    <td style="white-space:nowrap;">
        <img id="img_load_79340" src="/graphic/throbber18.gif" style="display:none;" alt="carregando..." />
        <a id="show_reservation_comment_79340" href="#" onclick="ReservationManager.toggleComment(79340);return false;">            <img src="/graphic/show_comment_disabled.png" alt="Nenhum comentário disponível" title="Nenhum comentário disponível" />
        </a>        <a href="/game.php?village=32056&amp;screen=map&amp;x=582&amp;y=289&amp;beacon"><img src="/graphic/map_center.png" alt="Centralizar mapa" title="Centralizar mapa" /></a>
                    <a href="/game.php?village=32056&amp;screen=ally&amp;action=delete_reservations&amp;id=79340&amp;page=&amp;group_id=all&amp;sort=expires_at&amp;order=ASC&amp;filter=&amp;h=32afa79e"><img src="/graphic/delete.png" alt="Apagar" title="Apagar" /></a>
            </td>
</tr>'''

DE_TERCEIRO_COM_COMENTARIO = '''<tr id="reservation_77075">
    <td>
                <input type="checkbox" name="ids[]" value="77075"/>

                <span class="village_anchor" data-player="5706293" data-id="47894"><a href="/game.php?village=32056&amp;screen=info_village&amp;id=47894" >C1 bigodeland | 014 (558|305) K35</a></span>
            </td>
    <td>5198</td>
    <td><a href="/game.php?village=32056&amp;screen=info_player&amp;id=5706293"  title="Os Randolinhos">lukasvictor</a></td>
    <td>
                <a href="/game.php?village=32056&amp;screen=info_player&amp;id=920052056"  title="Os Randolinhos">Haivar O sem osso</a>
    </td>
    <td>amanhã às 09:15</td>
    <td style="white-space:nowrap;">
        <img id="img_load_77075" src="/graphic/throbber18.gif" style="display:none;" alt="carregando..." />
        <a id="show_reservation_comment_77075" href="#" onclick="ReservationManager.toggleComment(77075);return false;">            <img src="/graphic/show_comment.png" alt="Mostrar comentários" title="Mostrar comentários" />
        </a>        <a href="/game.php?village=32056&amp;screen=map&amp;x=558&amp;y=305&amp;beacon"><img src="/graphic/map_center.png" alt="Centralizar mapa" title="Centralizar mapa" /></a>
            </td>
</tr>'''

DE_TERCEIRO = '''<tr id="reservation_75920">
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
</tr>'''

# A reserva do bot: a #79340 com o carimbo, que e como ela sairia do jogo se o
# bot a tivesse criado. So o flag da imagem muda -- e o flag e o que o parser
# le. Derivada de proposito e SO nisto: nenhuma outra parte da linha depende
# de quem criou (a propria captura prova, comparando #79340 com #77075).
DO_BOT = MINHA.replace("show_comment_disabled.png", "show_comment.png")


def page(*rows):
    return (GAME_STATE
            + '<a href="/game.php?screen=ally&amp;mode=reservations">x</a>'
            + CREATE_FORM + "".join(rows))


# --------------------------------------------------------------------------
# Dublês
# --------------------------------------------------------------------------

class FakeResponse:
    def __init__(self, text="", payload=None):
        self.text = text
        self.status_code = 200
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class FakeWrapper:
    """
    Registra toda requisicao. `pages` e a sequencia de HTMLs que os GETs da
    tela devolvem, para o teste controlar o que o quadro mostra ANTES e DEPOIS
    de uma escrita.
    """

    def __init__(self, pages=None, comments=None):
        self.pages = list(pages or [])
        self.comments = comments or {}
        self.gets = []
        self.posts = []

    def get_url(self, url, headers=None):
        self.gets.append(url)
        if "mode=reservations" in url and "action=" not in url:
            html = self.pages.pop(0) if len(self.pages) > 1 else self.pages[0]
            return FakeResponse(text=html)
        return FakeResponse(text="ok")

    def post_url(self, url, data, headers=None):
        self.posts.append((url, data))
        if "ajax=load_comment" in url:
            rid = str(data["reservation_id"])
            if rid not in self.comments:
                return FakeResponse(payload={"code": 0})
            return FakeResponse(payload={
                "code": 1, "id": rid, "comment": self.comments[rid],
                "rights": "write",
            })
        return FakeResponse(text="ok")


def build(pages, comments=None, **cfg):
    conquest = {"respect_tribe_reservations": True, "reserve_targets": True}
    conquest.update(cfg)
    config = {"conquest": conquest}
    wrapper = FakeWrapper(pages=pages, comments=comments)
    board = ReservationBoard(wrapper=wrapper, config=config)
    board.refresh("32056")
    writer = ReservationWriter(wrapper=wrapper, config=config, board=board)
    writer.begin_cycle()
    return wrapper, board, writer


# --------------------------------------------------------------------------
# Gate
# --------------------------------------------------------------------------

def test_gate_nasce_desligado():
    """
    `reserve_targets` e separado de `respect_tribe_reservations` de proposito:
    ler o quadro nao tem efeito social e nasce ligado; escrever nele publica
    intencao para a alianca inteira e nasce desligado.
    """
    wrapper = FakeWrapper(pages=[page(DE_TERCEIRO)])
    config = {"conquest": {"respect_tribe_reservations": True}}
    board = ReservationBoard(wrapper=wrapper, config=config)
    board.refresh("32056")
    writer = ReservationWriter(wrapper=wrapper, config=config, board=board)
    assert writer.enabled is False
    assert writer.claim_target("40808", (531, 289)) is None
    assert wrapper.posts == [], "gate desligado nao pode tocar na rede"


def test_sem_leitura_do_quadro_nao_escreve():
    """
    Escrever sem saber o que ja esta no quadro e como o bot furaria reserva
    alheia. A Fase 1 ja tratava `None` como "nao sei"; aqui isso vira recusa
    de escrever, nao um POST as cegas.
    """
    wrapper = FakeWrapper(pages=["<html>login</html>"])
    config = {"conquest": {"reserve_targets": True}}
    board = ReservationBoard(wrapper=wrapper, config=config)
    board.refresh("32056")
    writer = ReservationWriter(wrapper=wrapper, config=config, board=board)
    writer.begin_cycle()
    assert board.is_readable() is False
    assert writer.claim_target("40808", (531, 289)) is None
    assert wrapper.posts == []


def test_sem_csrf_nao_escreve():
    """
    Sem o `h` do formulario o POST seria recusado, e um 200 de recusa lido
    como sucesso e exatamente o que esta cadeia nao pode fazer. A ausencia do
    formulario tambem e o sinal de "conta sem direito de reservar".
    """
    sem_form = (GAME_STATE
                + '<a href="/game.php?screen=ally&amp;mode=reservations">x</a>'
                + DE_TERCEIRO)
    wrapper, board, writer = build([sem_form])
    assert board.is_readable() is True, "a LEITURA nao depende do formulario"
    assert board.csrf is None
    assert writer.claim_target("40808", (531, 289)) is None
    assert wrapper.posts == []


def test_orcamento_de_uma_escrita_por_ciclo():
    """
    O limite de taxa e da CONTA: cada POST daqui disputa requisicao com o
    farm. Uma escrita por ciclo tambem transforma qualquer laco com bug em,
    no maximo, uma acao por ciclo.
    """
    wrapper, board, writer = build([page(DE_TERCEIRO), page(DE_TERCEIRO, DO_BOT)])
    assert writer.claim_target("51540", (582, 289)) is not None
    antes = len(wrapper.posts)
    assert writer.claim_target("40808", (531, 289)) is None
    assert len(wrapper.posts) == antes, "a segunda escrita nao pode sair"
    writer.begin_cycle()
    assert writer._writes_this_cycle == 0


# --------------------------------------------------------------------------
# Criar
# --------------------------------------------------------------------------

def test_criar_manda_coordenada_em_x_e_y():
    """
    O destino e COORDENADA em campos separados, nao `village_id`. Supor
    `target_village` custou uma reescrita inteira no envio de recursos da
    Feature 9, e o formulario desta tela tem a mesma forma.
    """
    wrapper, board, writer = build([page(DE_TERCEIRO), page(DE_TERCEIRO, DO_BOT)])
    claim = writer.claim_target("51540", (582, 289))
    assert claim is not None

    url, data = wrapper.posts[0]
    assert "action=new_reservation" in url
    assert "h=%s" % CSRF in url, "o `h` sai da MESMA leitura que produziu a lista"
    assert data["x[]"] == "582" and data["y[]"] == "289"
    assert data["target_type"] == "coord"
    assert "village_id" not in data and "target_village" not in data
    assert data["comment[]"] == STAMP, "toda reserva do bot nasce carimbada"


def test_criar_confirma_pelo_quadro_e_nao_pela_mensagem():
    """
    A confirmacao rele o quadro e exige o alvo aparecer como reserva desta
    conta. Duas razoes medidas: a redacao da recusa muda conforme quem reservou
    (aliado x companheiro de tribo, e so a primeira foi observada), e a
    resposta do POST vem na paginacao default de 10 linhas ordenada por
    validade -- a reserva recem-criada cai na ULTIMA pagina e nao apareceria
    nela de qualquer jeito (26o padrao).
    """
    wrapper, board, writer = build([page(DE_TERCEIRO), page(DE_TERCEIRO, DO_BOT)])
    claim = writer.claim_target("51540", (582, 289))
    assert claim is not None
    assert claim["reservation_id"] == "79340"
    # releu o quadro depois de postar
    assert len([u for u in wrapper.gets if "mode=reservations" in u]) == 2


def test_criar_falha_quando_o_quadro_nao_confirma():
    """
    Falha de POST NUNCA vira sucesso presumido. Aqui o servidor respondeu 200
    (recusa de alvo ja reservado responde 200 com uma frase) e o quadro relido
    continua sem a reserva -- o alvo nao conta como reservado.

    E o caso que substitui a fixture de recusa que nao foi capturada: nao
    importa qual frase o jogo escolheu, porque nada aqui le a frase.
    """
    wrapper, board, writer = build([page(DE_TERCEIRO)])
    assert writer.claim_target("51540", (582, 289)) is None
    assert len(wrapper.posts) == 1, "o POST saiu"
    assert board.claimed_by_me("51540", (582, 289)) is None


def test_criar_exige_coordenada():
    """
    Sem coordenada nao ha o que postar -- o formulario nao aceita id. Recusa
    antes de gastar requisicao em vez de mandar x/y vazios.
    """
    wrapper, board, writer = build([page(DE_TERCEIRO)])
    assert writer.claim_target("51540", None) is None
    assert wrapper.posts == []


# --------------------------------------------------------------------------
# Teto de vagas
# --------------------------------------------------------------------------

def test_teto_de_vagas_default_e_uma():
    """
    A alianca da 5 vagas por jogador e no dia da medicao o usuario ja ocupava
    2 a mao. Como o planejador mantem UM trem barbaro por vez no imperio
    inteiro, uma vaga basta. Sem teto o bot encheria o quadro e o dono da
    conta nao conseguiria reservar nada -- sem erro, so recusa.
    """
    wrapper, board, writer = build(
        [page(DE_TERCEIRO, DO_BOT)], comments={"79340": STAMP}
    )
    assert writer._max_slots() == 1
    assert writer.bot_slot_usage() == 1
    assert writer.claim_target("40808", (531, 289)) is None
    assert wrapper.posts == [
        p for p in wrapper.posts if "ajax=load_comment" in p[0]
    ], "so pode ter havido leitura de comentario, nenhuma escrita"


def test_teto_nunca_passa_do_limite_da_alianca():
    """
    `reservation_limit` e config DA ALIANCA e nunca se escreve daqui (21o
    padrao). O teto proprio so pode ser menor ou igual a ele.
    """
    _, _, writer = build([page(DE_TERCEIRO)], reserve_max_slots=99)
    assert writer._max_slots() == ReservationWriter.ALLIANCE_SLOT_LIMIT == 5
    _, _, writer = build([page(DE_TERCEIRO)], reserve_max_slots="lixo")
    assert writer._max_slots() == 1


def test_reserva_manual_do_usuario_nao_conta_como_do_bot():
    """
    A #79340 e da conta e NAO tem comentario -- e uma reserva feita a mao.
    `reserved_by_id == own` responde "e da conta", nao "e do bot".

    Zero requisicao para decidir isso: sem comentario, nao e do bot, e o bot
    sempre carimba.
    """
    wrapper, board, writer = build([page(DE_TERCEIRO, MINHA)])
    assert len(board.my_claims()) == 1
    assert writer.bot_slot_usage() == 0, "manual nao ocupa vaga DO BOT"
    assert wrapper.posts == [], "reserva sem comentario nao custa requisicao"


def test_procedencia_desconhecida_conta_para_o_teto():
    """
    Comentario ilegivel = `None` = "nao sei". Os dois lados erram para a
    inacao: conta como vaga usada (o bot cria menos, custo de uma barbara
    entre dezenas) e nunca e removida.
    """
    wrapper, board, writer = build([page(DO_BOT)], comments={})
    assert writer._stamped_by_bot(board.my_claims()[0]) is None
    assert writer.bot_slot_usage() == 1


# --------------------------------------------------------------------------
# Remover
# --------------------------------------------------------------------------

def test_remover_usa_o_href_do_proprio_jogo():
    """
    A remocao usa o link que o jogo renderizou na linha, com `h`, `page`,
    `sort` e `filter` da mesma leitura. O `id` dele e o da RESERVA (79340),
    nao o da aldeia (51540).
    """
    wrapper, board, writer = build(
        [page(DE_TERCEIRO, DO_BOT), page(DE_TERCEIRO)], comments={"79340": STAMP}
    )
    claim = board.my_claims()[0]
    assert writer.release_claim(claim, reason="conquista resolvida") is True

    apagou = [u for u in wrapper.gets if "action=delete_reservations" in u]
    assert len(apagou) == 1
    assert "id=79340" in apagou[0]
    assert "id=51540" not in apagou[0]
    assert "h=%s" % CSRF in apagou[0]


def test_NUNCA_remove_reserva_manual_do_usuario():
    """
    O teste que nao pode falhar nunca: remover reserva feita a mao pelo
    usuario e o incidente da 8.7 ao contrario.

    A #79340 aqui e a real, da conta e SEM carimbo. Ela tem link de apagar --
    ou seja, o bot CONSEGUIRIA remove-la -- e mesmo assim nao remove.
    """
    wrapper, board, writer = build([page(DE_TERCEIRO, MINHA)])
    claim = board.my_claims()[0]
    assert claim["delete_href"], "a reserva propria tem link, logo da para remover"
    assert writer.release_claim(claim, reason="qualquer") is False
    assert [u for u in wrapper.gets if "action=delete_reservations" in u] == []


def test_nao_remove_quando_o_comentario_nao_pode_ser_lido():
    """
    `None` de procedencia nao pode ser lido como False por quem remove: as
    duas respostas tem custo oposto e so uma e irreversivel. A reserva fica
    onde esta e expira sozinha em ate 3 dias.
    """
    wrapper, board, writer = build([page(DO_BOT)], comments={})
    claim = board.my_claims()[0]
    assert writer.release_claim(claim) is False
    assert [u for u in wrapper.gets if "action=delete_reservations" in u] == []


def test_nao_remove_reserva_de_terceiro():
    """
    Reserva de outro jogador nao tem link de apagar -- o jogo nem oferece a
    acao. A guarda existe mesmo assim, porque ela e mais barata que descobrir
    do lado do servidor que era proibido.
    """
    wrapper, board, writer = build(
        [page(DE_TERCEIRO_COM_COMENTARIO)], comments={"77075": STAMP}
    )
    claim = Extractor.tribe_reservations(page(DE_TERCEIRO_COM_COMENTARIO))[0]
    assert claim["reserved_by_id"] != MY_ID
    assert claim["delete_href"] is None
    assert writer.release_claim(claim) is False
    assert [u for u in wrapper.gets if "action=delete_reservations" in u] == []


def test_remocao_nao_confirmada_nao_conta_como_removida():
    """
    O espelho de `test_criar_falha_quando_o_quadro_nao_confirma`: se a reserva
    continua no quadro depois do GET, nada foi removido.
    """
    wrapper, board, writer = build(
        [page(DE_TERCEIRO, DO_BOT)], comments={"79340": STAMP}
    )
    claim = board.my_claims()[0]
    assert writer.release_claim(claim) is False


def test_carimbo_diferente_nao_e_do_bot():
    """
    A comparacao e do texto exato. Comentario de outra pessoa que por acaso
    esteja numa reserva da conta nao autoriza remocao.
    """
    wrapper, board, writer = build(
        [page(DO_BOT)], comments={"79340": "minha reserva, nao mexe"}
    )
    claim = board.my_claims()[0]
    assert writer._stamped_by_bot(claim) is False
    assert writer.release_claim(claim) is False


# --------------------------------------------------------------------------
# A varredura do planejador
# --------------------------------------------------------------------------

def _planner(writer, board, active):
    """
    `BarbarianTrainPlanner` sem `__init__` e com o `ConquestCache` trocado --
    a varredura le `cache/conquest`, que e ESTADO DE PRODUCAO. Um teste que
    escrevesse (ou lesse e decidisse) sobre o diretorio real cairia no 21o
    padrao: a guarda mexendo no artefato que ela protege.
    """
    import game.conquest_planner as planner_mod

    class _Cache:
        @staticmethod
        def active_conquests():
            return dict(active)

    planner_mod.ConquestCache = _Cache
    p = planner_mod.BarbarianTrainPlanner.__new__(
        planner_mod.BarbarianTrainPlanner
    )
    p.logger = writer.logger
    p.config = writer.config
    p.reservation_board = board
    p.reservation_writer = writer
    return p


def test_varredura_libera_quando_a_conquista_acabou():
    """
    O gatilho e `active_conquests()` -- o MESMO conjunto que ja governa a
    invariante de um trem por vez. Alvo que saiu dali resolveu (conquistado,
    perdido, bloqueado, cancelado) e a reserva nao tem mais o que defender.
    """
    wrapper, board, writer = build(
        [page(DE_TERCEIRO, DO_BOT), page(DE_TERCEIRO)], comments={"79340": STAMP}
    )
    _planner(writer, board, active={})._release_finished_target_claims()
    assert [u for u in wrapper.gets if "action=delete_reservations" in u]


def test_varredura_nao_toca_em_conquista_em_andamento():
    """
    O alvo 51540 ainda esta em `train_scheduled`: soltar a reserva agora
    devolveria o alvo para a tribo enquanto quatro nobres do bot voam para la.
    """
    wrapper, board, writer = build(
        [page(DE_TERCEIRO, DO_BOT)], comments={"79340": STAMP}
    )
    planner = _planner(writer, board, active={"51540": {"status": "train_scheduled"}})
    planner._release_finished_target_claims()
    assert [u for u in wrapper.gets if "action=delete_reservations" in u] == []


def test_varredura_ignora_reserva_manual_sem_gastar_requisicao():
    """
    Reserva sem comentario e descartada antes de qualquer POST: zero custo por
    ciclo no caso normal, que e o quadro so ter reservas manuais do usuario.
    """
    wrapper, board, writer = build([page(DE_TERCEIRO, MINHA)])
    _planner(writer, board, active={})._release_finished_target_claims()
    assert wrapper.posts == []
    assert [u for u in wrapper.gets if "action=delete_reservations" in u] == []


def test_varredura_nao_faz_nada_com_o_gate_desligado():
    wrapper = FakeWrapper(pages=[page(DE_TERCEIRO, DO_BOT)])
    config = {"conquest": {"respect_tribe_reservations": True}}
    board = ReservationBoard(wrapper=wrapper, config=config)
    board.refresh("32056")
    writer = ReservationWriter(wrapper=wrapper, config=config, board=board)
    writer.begin_cycle()
    _planner(writer, board, active={})._release_finished_target_claims()
    assert wrapper.posts == []


# --------------------------------------------------------------------------
# Contrato do load_comment
# --------------------------------------------------------------------------

def test_load_comment_exige_code_truthy():
    """
    A guarda e a MESMA que o proprio jogo usa: o `success` do
    ReservationManager.js faz `e.code||alert(...)`. Sem `code`, nao ha
    resposta boa -- e nao uma resposta com comentario vazio.
    """
    assert Extractor.reservation_comment(None) is None
    assert Extractor.reservation_comment({"code": 0, "comment": "x"}) is None
    assert Extractor.reservation_comment({"comment": "x"}) is None
    ok = Extractor.reservation_comment(
        {"code": 1, "id": "79340", "comment": STAMP, "rights": "write"}
    )
    assert ok["comment"] == STAMP


def test_load_comment_posta_o_id_da_reserva():
    wrapper, board, writer = build([page(DO_BOT)], comments={"79340": STAMP})
    writer._stamped_by_bot(board.my_claims()[0])
    url, data = [p for p in wrapper.posts if "ajax=load_comment" in p[0]][0]
    assert data == {"reservation_id": "79340"}


def test_comentario_e_lido_uma_vez_por_ciclo():
    """
    O cache existe para a varredura por ciclo nao repetir o mesmo POST: o
    limite de taxa e da conta.
    """
    wrapper, board, writer = build([page(DO_BOT)], comments={"79340": STAMP})
    claim = board.my_claims()[0]
    writer._stamped_by_bot(claim)
    writer._stamped_by_bot(claim)
    assert len([p for p in wrapper.posts if "ajax=load_comment" in p[0]]) == 1
    writer.begin_cycle()
    writer._stamped_by_bot(claim)
    assert len([p for p in wrapper.posts if "ajax=load_comment" in p[0]]) == 2


# --------------------------------------------------------------------------

if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(list(globals().items())):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print("ok   %s" % name)
        except AssertionError as exc:
            failed += 1
            print("FALHA %s: %r" % (name, exc))
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print("ERRO  %s: %r" % (name, exc))
    print("\n%s" % ("TUDO VERDE" if not failed else "%d falha(s)" % failed))
    sys.exit(1 if failed else 0)
