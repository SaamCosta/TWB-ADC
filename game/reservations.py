"""
Feature 35 / Fase 1 -- leitura do quadro OFICIAL de reservas da tribo.

Contexto: docs/backend.md 8.7. Em 2026-09-20 o usuario relatou que o bot nobrou
uma barbara que outro jogador do SQUAD 02 tinha reservado. O bot nao tinha o
conceito de reserva: `find_target()` filtrava por dono, raio, pontuacao e area
de interesse, e nenhum desses sabe que alguem pediu aquela aldeia.

VOCABULARIO -- LEIA ANTES DE MEXER
----------------------------------
Neste projeto "reserva" ja significava TROPA (`conquest_reserve`,
`_reserve`/`_release` em game/conquest_planner.py: nobres e escolta prometidos
a um trem). Aqui significa ALVO, e o dono do dado e OUTRA PESSOA. Sao coisas
diferentes com o mesmo nome, e foi assim que a 8.2 comecou -- por isso tudo
neste modulo diz "claim"/"quadro"/"reservado por", e nada aqui chama `_reserve`.

DUAS METADES, E SO A PRIMEIRA E INOFENSIVA
------------------------------------------
`ReservationBoard` LE o quadro (Fase 1, 2026-09-20). `ReservationWriter`
ESCREVE nele (Fase 2, 2026-09-21), e escrever publica intencao num quadro
compartilhado com a alianca inteira -- sentar em reserva que nunca vira
conquista e tao mal visto quanto furar reserva alheia. Por isso a escrita tem
gate proprio (`conquest.reserve_targets`, default off), teto de vagas e
confirmacao pelo estado do quadro, nunca por mensagem de sucesso.

(Ate 2026-09-21 este docstring dizia "nada neste modulo faz POST". Passou a
ser mentira no momento em que a Fase 2 entrou, e ficou corrigido no mesmo
passo -- 16o padrao do CLAUDE.md.)

O PORQUE DO `None`
------------------
`claims()` devolve `None` quando NAO conseguiu ler, e `{}` quando leu e nao ha
nada. Todo consumidor precisa tratar os dois diferente: sem leitura o bot nao
sabe o que e de quem, e o custo de errar e assimetrico -- um falso negativo
custa uma barbara entre dezenas, um falso positivo custa capital social, e
irreversivel, e ja gastou 4 nobres e uma moeda. Na duvida, pular.
"""
import logging
import time

from core.extractors import Extractor


class ReservationBoard:
    """
    Quadro de reservas da tribo, cacheado por TTL curto e compartilhado por
    todas as aldeias do ciclo.

    Compartilhado de proposito: a lista e global (nao ha recorte por aldeia) e
    a resposta mede ~707 KB. Uma instancia por aldeia faria 30 requisicoes
    dessas por ciclo para obter exatamente o mesmo conteudo.
    """

    # `page=all` devolve a lista inteira numa requisicao. Medido em 2026-09-20:
    # 489 reservas, 707 KB -- contra 49 paginas de 10 no default do jogo. O
    # tamanho de pagina tambem e configuravel na tela, mas por POST e a
    # configuracao e COMPARTILHADA com a tribo inteira: mexer nela mudaria a
    # interface de outras pessoas para conseguir uma leitura, o que e o
    # vigesimo primeiro padrao do CLAUDE.md. `page=all` nao escreve nada.
    URL = "game.php?village=%s&screen=ally&mode=reservations&page=all"

    DEFAULT_TTL = 600

    def __init__(self, wrapper, config):
        self.wrapper = wrapper
        self.config = config
        self.logger = logging.getLogger("Reservations")
        # Mutaveis em __init__, nao no corpo da classe (1o padrao do CLAUDE.md).
        self._by_village = {}
        self._by_location = {}
        self._own_player_id = None
        self._fetched_at = 0.0
        self._read_ok = False
        # Fase 2: token CSRF e a aldeia pela qual a tela foi lida. Ficam aqui
        # porque sao propriedades DA LEITURA, nao do escritor -- o `h` e o
        # `village=` do formulario vem da mesma resposta que produziu a lista,
        # e usar um `h` de outra leitura seria decidir com token velho.
        self._csrf = None
        self._read_village_id = None

    # ------------------------------------------------------------------
    # Leitura
    # ------------------------------------------------------------------

    @property
    def enabled(self):
        return self.config.get("conquest", {}).get("respect_tribe_reservations", True)

    def _ttl(self):
        return self.config.get("conquest", {}).get(
            "reservation_cache_seconds", self.DEFAULT_TTL
        )

    def refresh(self, village_id, force=False):
        """
        Rele o quadro se o cache expirou. Devolve True se ha leitura valida.

        TTL curto de proposito: reserva de terceiro nasce a qualquer momento e
        o custo de reler e uma requisicao, enquanto o custo de agir sobre um
        quadro velho e o incidente que esta feature existe para impedir.
        """
        if not force and self._read_ok and (time.time() - self._fetched_at) < self._ttl():
            return True

        res = self.wrapper.get_url(self.URL % village_id)
        # `get_url` devolve None em QUALQUER excecao (2o padrao do CLAUDE.md),
        # e `tribe_reservations` devolve None quando a resposta e 200 mas nao e
        # a tela de reservas -- sessao expirada virando login e o caso real,
        # medido em 2026-09-20.
        claims = Extractor.tribe_reservations(res)
        if claims is None:
            # NAO zera o cache anterior: uma leitura velha e melhor que
            # nenhuma, e o `_read_ok` abaixo so cai se nunca houve leitura.
            self.logger.warning(
                "Reservations: nao consegui ler screen=ally&mode=reservations "
                "pela aldeia %s (sessao expirada ou markup novo). Conquista "
                "NOVA fica bloqueada ate a proxima leitura boa; o que ja esta "
                "em andamento segue.", village_id
            )
            return self._read_ok and (time.time() - self._fetched_at) < self._stale_grace()

        own = Extractor.own_player_id(res)
        if not own:
            self.logger.warning(
                "Reservations: li %d reservas mas nao achei o id do proprio "
                "jogador no game_state -- sem ele nao da para separar reserva "
                "minha de reserva alheia, entao a leitura nao vale", len(claims)
            )
            return False

        self._own_player_id = own
        # Pode vir None numa tela em que o formulario de criar nao renderiza
        # (conta sem direito de reservar). Nao invalida a LEITURA -- a Fase 1
        # foi escrita para nao depender do formulario --, so desliga a escrita.
        self._csrf = Extractor.reservation_csrf(res)
        self._read_village_id = village_id
        self._by_village = {}
        self._by_location = {}
        for claim in claims:
            self._by_village[str(claim["village_id"])] = claim
            if claim.get("location"):
                self._by_location[tuple(claim["location"])] = claim
        self._fetched_at = time.time()
        self._read_ok = True

        mine = sum(1 for c in claims if c.get("reserved_by_id") == own)
        self.logger.info(
            "Reservations: %d reservas no quadro da tribo (%d minhas, %d de "
            "terceiros)", len(claims), mine, len(claims) - mine
        )
        return True

    def _stale_grace(self):
        """
        Por quanto tempo uma leitura velha ainda vale quando a nova falhou.

        Existe para nao transformar um soluco de rede em bloqueio total da
        conquista: o quadro muda em escala de horas (o limite de tempo da
        tribo e de 3 dias, lido da propria tela em 2026-09-20), entao servir
        dados de alguns TTLs atras e muito mais seguro do que ficar cego. Mas
        e limitado: passado isso, o bot volta a assumir que nao sabe.
        """
        return self._ttl() * 6

    # ------------------------------------------------------------------
    # Consulta
    # ------------------------------------------------------------------

    def claimed_by_other(self, target_id, location=None):
        """
        Dict da reserva quando `target_id` esta reservado por OUTRA pessoa.
        `None` quando esta livre, quando a reserva e minha, ou quando a
        feature esta desligada.

        NAO confundir com `is_readable()`: esta funcao devolve None tanto para
        "olhei e esta livre" quanto para "nao tenho leitura". Quem decide
        iniciar conquista precisa checar `is_readable()` separadamente -- e o
        que o teste `test_blocked_when_board_unreadable` cobre.

        Aceita coordenada alem do id porque o quadro identifica a aldeia pelos
        dois (`data-id` e o "(x|y)" do nome), e as duas chaves existem no
        cache local em momentos diferentes: um alvo manual digitado por
        coordenada pode nao ter id resolvido ainda.
        """
        if not self.enabled:
            return None
        claim = self._by_village.get(str(target_id))
        if not claim and location:
            claim = self._by_location.get(tuple(location))
        if not claim:
            return None
        if claim.get("reserved_by_id") == self._own_player_id:
            return None
        return claim

    def is_readable(self):
        """True quando ha leitura valida do quadro (fresca ou dentro da graca)."""
        if not self.enabled:
            return True
        if not self._read_ok:
            return False
        return (time.time() - self._fetched_at) < self._stale_grace()

    # ------------------------------------------------------------------
    # Consulta usada pela ESCRITA (Fase 2)
    # ------------------------------------------------------------------

    def my_claims(self):
        """
        As reservas criadas por ESTA CONTA, como lista.

        Note o "conta", nao "bot": inclui as que o usuario fez a mao no jogo.
        Separar as duas e problema de PROCEDENCIA e nao de leitura -- o quadro
        nao tem esse campo, e nenhuma leitura daqui responde essa pergunta.
        Quem responde e `ReservationWriter._stamped_by_bot()`.

        Medido em 2026-09-20: 1 de 480 linhas era da conta. Ou seja, esta
        lista e curta por construcao -- o limite da alianca e de 5.
        """
        if not self._read_ok or not self._own_player_id:
            return []
        return [
            claim for claim in self._by_village.values()
            if claim.get("reserved_by_id") == self._own_player_id
        ]

    def claimed_by_me(self, target_id, location=None):
        """
        A reserva de `target_id` quando ela e DESTA CONTA. O espelho de
        `claimed_by_other()`, e existe para confirmar uma criacao: depois do
        POST o alvo tem que aparecer aqui, senao nada foi reservado.
        """
        if not self._read_ok or not self._own_player_id:
            return None
        claim = self._by_village.get(str(target_id))
        if not claim and location:
            claim = self._by_location.get(tuple(location))
        if not claim:
            return None
        return claim if claim.get("reserved_by_id") == self._own_player_id else None

    @property
    def fetched_at(self):
        """Epoch da ultima leitura boa. A validade no quadro e relativa a ele."""
        return self._fetched_at

    @property
    def csrf(self):
        return self._csrf

    @property
    def read_village_id(self):
        return self._read_village_id



class ReservationWriter:
    """
    Fase 2: cria e remove reservas de ALVO em nome da conta.

    Tres coisas que NAO sao escolha de estilo, e sim medicao (docs/backend.md
    8.7, sessao de 2026-09-21):

    1. **Momento.** A reserva nasce quando o trem e AGENDADO, nao quando o
       alvo entra na fila. `ConquestPlanner.run()` so elege alvo depois de o
       imperio ter os 4 nobres, entao a janela medida entre agendar e
       conquistar foi de 7,21 h e 10,68 h (os dois unicos registros de
       `cache/conquest` que tem os dois timestamps) contra os 3 DIAS de
       validade da alianca. Folga de 6,7x -- por isso nao existe renovacao
       aqui, e nao por otimismo: renovar exigiria remover e recriar, e entre
       os dois POSTs o alvo fica livre para outra pessoa pegar.

    2. **Teto.** A alianca da 5 vagas por jogador (lido de
       `reservation_limit`, que e config DA ALIANCA e nunca se mexe daqui).
       No dia da medicao o usuario ja ocupava 2 delas a mao. Como
       `ConquestPlanner` mantem UM trem barbaro por vez no imperio inteiro,
       uma vaga basta -- e e esse o default. Sem teto o bot encheria o quadro
       e o dono da conta nao conseguiria reservar nada, sem erro nenhum: so
       recusa.

    3. **Remover vale a pena, e isso e numero.** A reserva sobrevive a
       conquista por ~60 h, e o intervalo mediano entre duas conquistas
       medido nos 23 registros foi de ~37 h. Deixar expirar sozinha faria o
       bot segurar ~2 das 5 vagas em regime permanente, cobrindo quase duas
       conquistas com uma reserva morta.

    PROCEDENCIA -- o bot so mexe no que o bot criou
    -----------------------------------------------
    `reserved_by_id == own_player_id` responde "e da conta", nao "e do bot":
    as reservas manuais do usuario tambem sao da conta. O que separa as duas e
    o COMENTARIO, e ele foi escolhido por sobreviver ao que o cache local nao
    sobrevive -- restart, cache apagado, ou o usuario mexendo no jogo pela mao
    (9o padrao: o log registra o que o bot fez, nao o estado do mundo).

    O comentario nao vem na linha da lista; a linha traz so um flag binario, e
    o texto sai de um POST em `ajax=load_comment` por reserva. O flag e o que
    torna isso barato: reserva sem comentario nenhum definitivamente nao e do
    bot (o bot sempre carimba), entao nem chega a custar requisicao.

    Na duvida, NAO remove. Se o comentario nao puder ser lido, a reserva fica
    onde esta e expira sozinha em no maximo 3 dias -- o custo e uma vaga presa
    por alguns dias, contra remover reserva de um companheiro de alianca, que
    e o incidente da 8.7 ao contrario.
    """

    # Os dois formularios saem verbatim do HTML da propria tela (8.7). O
    # destino e COORDENADA em campos separados, nao `village_id`: e a mesma
    # forma que o envio de recursos da Feature 9 exigia, e supor
    # `target_village` la custou uma reescrita inteira.
    CREATE_URL = ("game.php?village=%s&screen=ally&mode=reservations"
                  "&action=new_reservation&group_id=all&filter=&h=%s")
    # Nao ha DELETE_URL: a remocao usa o `delete_href` que o jogo renderizou na
    # propria linha (`action=delete_reservations&id=N&...&h=...`). Ele so
    # aparece nas reservas desta conta -- medido em 2026-09-21, 3 linhas em 441
    # --, entao usar o href do jogo em vez de montar um e ao mesmo tempo a
    # forma mais simples e uma guarda: sem href, nao ha o que remover. O POST
    # em lote (`action=submit` + `ids[]` + `delete_claims`) que a 8.7 tinha
    # capturado ficou de fora de proposito: ele aceita varios ids de uma vez,
    # e nada aqui precisa disso -- so amplia o estrago de um bug.
    # Sem `mode=reservations` de proposito: e o valor literal do
    # `#reservation_ajax_link_load_comment` da tela.
    COMMENT_URL = "game.php?village=%s&screen=ally&&ajax=load_comment"

    # Texto neutro, escolhido pelo usuario em 2026-09-21. Ele e VISIVEL para a
    # alianca inteira ("Os Randola, Inquisition"), entao e interface social
    # antes de ser carimbo: diz a um humano por que a aldeia esta reservada,
    # sem anunciar que a conta e automatizada.
    DEFAULT_COMMENT = "Conquista em andamento -- trem a caminho"

    # Config DA ALIANCA, lida da tela em 2026-09-20. Esta aqui para o teto
    # proprio nunca ser maior que ela -- e NAO para ser escrita: mexer em
    # `reservation_limit` mudaria a regra para todos os outros jogadores
    # (21o padrao).
    ALLIANCE_SLOT_LIMIT = 5
    DEFAULT_MAX_SLOTS = 1

    # O limite de taxa e da CONTA: cada POST daqui disputa requisicao com o
    # farm. Uma escrita por ciclo e folgado para uma conquista a cada ~37 h, e
    # transforma qualquer laco com bug em, no maximo, uma acao por ciclo.
    MAX_WRITES_PER_CYCLE = 1

    def __init__(self, wrapper, config, board):
        self.wrapper = wrapper
        self.config = config
        self.board = board
        self.logger = logging.getLogger("Reservations")
        # Mutaveis em __init__ (1o padrao do CLAUDE.md).
        self._writes_this_cycle = 0
        self._comment_cache = {}

    # ------------------------------------------------------------------
    # Gates
    # ------------------------------------------------------------------

    @property
    def enabled(self):
        """
        Gate proprio, default OFF. Separado de `respect_tribe_reservations`
        de proposito: ler o quadro nao tem efeito social nenhum e por isso
        nasceu ligado; escrever nele tem, e por isso nasce desligado.
        """
        return bool(
            self.config.get("conquest", {}).get("reserve_targets", False)
        )

    def _comment(self):
        text = self.config.get("conquest", {}).get("reserve_comment")
        return (text or self.DEFAULT_COMMENT).strip()

    def _max_slots(self):
        raw = self.config.get("conquest", {}).get(
            "reserve_max_slots", self.DEFAULT_MAX_SLOTS
        )
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = self.DEFAULT_MAX_SLOTS
        return max(0, min(value, self.ALLIANCE_SLOT_LIMIT))

    def begin_cycle(self):
        """Zera o orcamento de escrita. Chamado uma vez por ciclo."""
        self._writes_this_cycle = 0
        self._comment_cache = {}

    def _may_write(self, what, needs_csrf=True, budget_exempt=False):
        """
        `needs_csrf=False` na remocao: ela usa o `delete_href` que o jogo
        renderizou, e esse href ja carrega o proprio `h`. O token do
        formulario de CRIAR e outro assunto -- acoplar os dois faria a
        remocao parar de funcionar por causa de um formulario que ela nao usa.

        `budget_exempt=True` e do timer de reserva (game/reservation_sniper.py):
        ele dispara num minuto marcado, e perder o minuto porque o planejador
        ja escreveu uma vez no ciclo seria perder a aldeia. O laco dele tem
        teto proprio (`MAX_ATTEMPTS`, uma por minuto), que e o que este
        orcamento existe para garantir.
        """
        if not self.enabled:
            return False
        if not budget_exempt and self._writes_this_cycle >= self.MAX_WRITES_PER_CYCLE:
            self.logger.info(
                "Reservations: %s adiado -- ja houve %d escrita(s) neste ciclo "
                "e o limite de taxa e da conta inteira", what,
                self._writes_this_cycle
            )
            return False
        if not self.board or not self.board.is_readable():
            self.logger.warning(
                "Reservations: %s cancelado -- sem leitura valida do quadro. "
                "Escrever sem saber o que ja esta la e como o bot furaria "
                "reserva alheia", what
            )
            return False
        if needs_csrf and not self.board.csrf:
            self.logger.warning(
                "Reservations: %s cancelado -- a tela nao trouxe o token `h` "
                "do formulario de criar reserva (conta sem direito de "
                "reservar, ou markup novo)", what
            )
            return False
        return True

    # ------------------------------------------------------------------
    # Procedencia
    # ------------------------------------------------------------------

    def _stamped_by_bot(self, claim):
        """
        True/False/None para "esta reserva foi criada pelo bot?".

        `None` significa "nao consegui saber" e NUNCA pode ser lido como
        False por quem remove -- as duas respostas tem custos opostos e so uma
        delas e irreversivel.

        Reserva sem comentario nenhum e False de graca, sem requisicao: o bot
        sempre carimba ao criar, e a confirmacao apos o POST verifica isso.
        """
        if not claim.get("has_comment"):
            return False

        reservation_id = str(claim.get("reservation_id") or "")
        if reservation_id in self._comment_cache:
            payload = self._comment_cache[reservation_id]
        else:
            village_id = self.board.read_village_id
            res = self.wrapper.post_url(
                self.COMMENT_URL % village_id,
                data={"reservation_id": reservation_id},
            )
            payload = Extractor.reservation_comment(res)
            self._comment_cache[reservation_id] = payload

        if payload is None:
            self.logger.warning(
                "Reservations: nao consegui ler o comentario da reserva %s "
                "(alvo %s) -- tratando como NAO sendo do bot, que e o lado "
                "seguro do erro", reservation_id, claim.get("village_id")
            )
            return None
        return (payload.get("comment") or "").strip() == self._comment()

    def bot_slot_usage(self):
        """
        Quantas das 5 vagas o BOT esta ocupando agora.

        Reserva cuja procedencia nao deu para apurar conta COMO SENDO do bot
        aqui, e nao conta na hora de remover. Os dois lados erram para a
        inacao de proposito: contar a mais faz o bot deixar de criar (custo:
        uma barbara entre dezenas), contar a menos faria ele estourar o teto e
        competir por vaga com o dono da conta.
        """
        used = 0
        for claim in self.board.my_claims():
            if self._stamped_by_bot(claim) is not False:
                used += 1
        return used

    def bot_claim_for(self, target_id, location=None):
        """A reserva DO BOT para este alvo, ou None."""
        claim = self.board.claimed_by_me(target_id, location)
        if not claim:
            return None
        return claim if self._stamped_by_bot(claim) is True else None

    # ------------------------------------------------------------------
    # Escrita
    # ------------------------------------------------------------------

    def claim_target(self, target_id, location, budget_exempt=False):
        """
        Reserva `location` em nome da conta. Devolve o dict da reserva
        confirmada, ou None.

        A confirmacao NAO le a mensagem de sucesso da resposta: rele o quadro
        e exige o alvo aparecer la como reserva desta conta. Dois motivos, os
        dois medidos. O canario de 2026-09-21 mostrou que o servidor recusa
        alvo ja reservado com uma frase especifica ("Um aliado ja reservou
        ..."), e a propria 8.7 anota que a redacao para companheiro da PROPRIA
        tribo pode ser outra -- um parser ancorado numa frase seria um detector
        que nunca dispara no outro caso (15o padrao ao contrario). E a resposta
        do POST vem na paginacao default de 10 linhas, ordenada por validade,
        entao a reserva recem-criada cai na ULTIMA pagina e nao apareceria nela
        de qualquer jeito (26o padrao).
        """
        if not location or len(location) != 2:
            self.logger.warning(
                "Reservations: alvo %s sem coordenada conhecida -- o formulario "
                "enderecca por x/y e nao por id, entao nao da para reservar",
                target_id
            )
            return None
        if not self._may_write("reservar %s" % target_id,
                               budget_exempt=budget_exempt):
            return None

        existing = self.board.claimed_by_me(target_id, location)
        if existing:
            return existing if self._stamped_by_bot(existing) is True else None

        used = self.bot_slot_usage()
        limit = self._max_slots()
        if used >= limit:
            self.logger.info(
                "Reservations: nao vou reservar %s -- o bot ja ocupa %d de %d "
                "vagas proprias (a alianca da %d por jogador, e as outras sao "
                "do usuario)", target_id, used, limit, self.ALLIANCE_SLOT_LIMIT
            )
            return None

        village_id = self.board.read_village_id
        if not budget_exempt:
            self._writes_this_cycle += 1
        self.wrapper.post_url(
            self.CREATE_URL % (village_id, self.board.csrf),
            data={
                "x[]": str(location[0]),
                "y[]": str(location[1]),
                "target_type": "coord",
                "input": "",
                "comment[]": self._comment(),
            },
        )

        self.board.refresh(village_id, force=True)
        claim = self.board.claimed_by_me(target_id, location)
        if not claim:
            self.logger.warning(
                "Reservations: o POST de reserva de %s (%s|%s) nao virou "
                "reserva no quadro -- alvo pode ja estar reservado por outro, "
                "ou as 5 vagas da conta estao cheias. O alvo NAO conta como "
                "reservado", target_id, location[0], location[1]
            )
            return None
        if not claim.get("has_comment"):
            self.logger.warning(
                "Reservations: reserva %s de %s criada SEM comentario -- o "
                "carimbo de procedencia nao pegou, entao o bot nao vai "
                "conseguir remove-la depois e ela vai expirar sozinha em 3 dias",
                claim.get("reservation_id"), target_id
            )
        self.logger.info(
            "Reservations: alvo %s (%s|%s) reservado no quadro da alianca "
            "(reserva %s) -- %d de %d vagas proprias em uso",
            target_id, location[0], location[1], claim.get("reservation_id"),
            self.bot_slot_usage(), self._max_slots()
        )
        return claim

    def release_claim(self, claim, reason=""):
        """
        Remove uma reserva -- e SO se ela for comprovadamente do bot.

        A checagem de procedencia fica aqui dentro, e nao no chamador, de
        proposito: e a unica funcao do modulo que pode causar o dano, entao e
        ela que tem que se recusar. Um chamador novo, escrito daqui a meses,
        nao precisa saber da regra para nao quebra-la.
        """
        if not claim:
            return False
        target_id = claim.get("village_id")
        if not self._may_write("liberar %s" % target_id, needs_csrf=False):
            return False
        if not claim.get("delete_href"):
            self.logger.warning(
                "Reservations: nao vou remover a reserva %s -- a linha nao "
                "trouxe link de apagar, e o jogo so renderiza esse link nas "
                "reservas da propria conta. Sem ele, ou a reserva nao e minha "
                "ou o markup mudou", claim.get("reservation_id")
            )
            return False

        if self._stamped_by_bot(claim) is not True:
            self.logger.warning(
                "Reservations: NAO vou remover a reserva %s (alvo %s) -- ela e "
                "da conta mas nao carrega o carimbo do bot, entao e do usuario "
                "ou de procedencia desconhecida. Expira sozinha em ate 3 dias",
                claim.get("reservation_id"), target_id
            )
            return False

        village_id = self.board.read_village_id
        self._writes_this_cycle += 1
        # O href ja carrega `id=<id da RESERVA>` (nao o da aldeia -- confundir
        # os dois removeria a reserva errada, 8.7) e o `h` da mesma leitura.
        self.wrapper.get_url(claim["delete_href"])

        self.board.refresh(village_id, force=True)
        still_there = self.board.claimed_by_me(target_id, claim.get("location"))
        if still_there:
            self.logger.warning(
                "Reservations: a reserva %s de %s continua no quadro depois do "
                "POST de remocao -- nao conto como removida",
                claim.get("reservation_id"), target_id
            )
            return False
        self.logger.info(
            "Reservations: reserva %s de %s liberada no quadro da alianca (%s)",
            claim.get("reservation_id"), target_id, reason or "alvo resolvido"
        )
        return True


def manual_exclusion(config, target_id, location=None):
    """
    Valvula de escape manual: `conquest.excluded_targets`.

    Aceita id de aldeia ("40808") ou coordenada ("531|289") na mesma lista,
    porque o usuario tem as duas a mao dependendo de onde viu o alvo -- o
    painel mostra id, o jogo mostra coordenada.

    Isto NAO e a solucao do problema, e o override: com a leitura oficial
    funcionando a lista tende a ficar vazia. Serve para reserva combinada fora
    do jogo (forum, Discord) e para alvo que o usuario quer barrar por
    qualquer outro motivo.

    Devolve a string que casou (para virar motivo no log/cache) ou None.
    """
    excluded = config.get("conquest", {}).get("excluded_targets", []) or []
    target_id = str(target_id)
    coord = "%s|%s" % tuple(location) if location else None
    for entry in excluded:
        entry = str(entry).strip()
        if not entry:
            continue
        if entry == target_id or (coord and entry.replace(" ", "") == coord):
            return entry
    return None
