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

ESTA FASE E SOMENTE LEITURA
---------------------------
Nada neste modulo faz POST. Criar reserva em nome da conta (Fase 2) publica
intencao num quadro compartilhado com outros humanos e tem custo social
proprio -- sentar em reserva que nunca vira conquista e tao mal visto quanto
furar reserva alheia. Fica para depois, com gate e canario proprios.

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
