"""
Attack manager
Sounds dangerous but it just sends farms
"""

from core.extractors import Extractor
import logging
import math
import time
from datetime import datetime
from datetime import timedelta

from core.filemanager import FileManager
from core.templates import UNIT_CARRY, UNIT_POP
from core.world_config import WorldConfig
from game.reservations import manual_exclusion

# Trechos do error_box que significam "o pacote nao cabe no que ha em casa".
# So esta causa pode marcar o pacote como indisponivel no ciclo; qualquer
# outra recusa e problema do alvo, e blacklistar o pacote por causa dela
# pararia o farm da aldeia inteira.
#
# Verificado ao vivo no br143 em 2026-08-19, postando 9999 lanceiros de uma
# aldeia que tem zero na etapa `try=confirm` (que valida e nao envia):
#
#     Nao existem unidades suficientes
#
# So ha a variante pt-BR porque e a unica que eu li de um servidor. Mundo em
# outro idioma cai no caminho generico (segue para o proximo alvo, como antes)
# e loga a mensagem em WARNING -- e de la que sai o texto para acrescentar
# aqui, em vez de adivinhar traducoes.
INSUFFICIENT_UNITS_MESSAGES = (
    "unidades suficientes",
)

# Trechos do error_box do limite de ataque falso. Tambem e problema do PACOTE
# e nao do alvo -- o pacote e pequeno demais para os pontos desta aldeia, e
# sera recusado em todo alvo igualmente. Mensagem real do br143, 2026-08-19:
#
#     A forca de ataque precisa do minimo de 73 habitantes.
#     Voce esta tentando enviar 60 fazendeiros.
#
# O bot passou a evitar esta recusa em vez de so reagir a ela (ver
# _ordered_templates), mas o padrao fica como rede: os pontos usados no
# calculo sao lidos uma vez por ciclo e podem envelhecer dentro do ciclo.
FAKE_LIMIT_MESSAGES = (
    "precisa do mínimo de",
    "precisa do minimo de",
)


def field_distance(a, b):
    """
    Distancia em campos entre duas coordenadas (x, y).

    Mesma conta do `Map.get_dist`, mas entre dois pontos quaisquer em vez de
    "daqui ate la" -- o trem multi-origem precisa medir de varias origens e
    nenhuma delas e necessariamente a aldeia do Map em maos.
    """
    return math.sqrt(((a[0] - b[0]) ** 2) + ((a[1] - b[1]) ** 2))


class AttackManager:
    """
    Attackmanager class
    """
    map = None
    village_id = None
    troopmanager = None
    wrapper = None
    targets = {}
    logger = logging.getLogger("Attacks")
    max_farms = 15
    # Pontos desta aldeia e populacao minima que o mundo exige por ataque
    # (fake_limit% dos pontos). Ambos reatribuidos por village.py a cada ciclo;
    # zero significa "sem limite conhecido" e desliga a checagem.
    village_points = 0
    min_attack_pop = 0
    template = {}
    extra_farm = []
    repman = None
    target_high_points = False
    farm_radius = 50
    farm_minpoints = 0
    farm_maxpoints = 1000
    ignored = []

    # Configures the amount of spies used to detect if villages are safe to farm
    scout_farm_amount = 5

    forced_peace_time = None
    # True enquanto a janela de paz forcada esta ativa agora (distinto de
    # forced_peace_time, que e o teto de *chegada* da proxima janela).
    in_forced_peace = False

    # blocks villages which cannot be attacked at the moment (too low points, beginners protection etc..)
    _unknown_ignored = []

    # Don't mess with these they are in the config file
    farm_high_prio_wait = 1200
    farm_default_wait = 3600
    farm_low_prio_wait = 7200

    def __init__(self, wrapper=None, village_id=None, troopmanager=None, map=None):
        """
        Create the attack manager
        """
        self.wrapper = wrapper
        self.village_id = village_id
        self.troopmanager = troopmanager
        self.map = map
        # P3: mutaveis por instancia (ver CLAUDE.md). `ignored` e
        # `_unknown_ignored` sao mutados in-place (.append/.remove) e nunca
        # reatribuidos, entao como atributos de classe eram compartilhados
        # por todas as aldeias -- um alvo fora do farm_radius de uma aldeia
        # ficava ignorado para todas, mesmo estando perto de outra.
        # `targets` e `extra_farm` sao reatribuidos, mas declarar aqui evita
        # a mesma armadilha se algum caminho falhar antes da atribuicao.
        self.ignored = []
        self._unknown_ignored = []
        self.targets = {}
        self.extra_farm = []
        # Duracao (segundos) do ultimo attack() confirmado pelo servidor, ou
        # None se o ultimo attack() falhou/nao foi enviado. Existe para o
        # ConquestManager saber *quando o nobre pousa*, sem recalcular
        # distancia x velocidade por conta propria (o jogo ja devolve o numero
        # na tela de confirmacao, e e ele que manda). Ver
        # ConquestManager._arrival_from_last_attack().
        self.last_attack_duration = None
        # Texto do error_box da ultima recusa do jogo, ou None. E atributo em
        # vez de valor de retorno de propositio: attack() ja devolve a string
        # "forced_peace" como sentinel, e string e truthy -- scout() faz
        # `if self.attack(...)` e trataria o sentinel como sucesso. Mais um
        # sentinel string pioraria isso; o atributo mantem attack() devolvendo
        # falsy em toda recusa.
        self.last_refusal = None
        # Set by TWB/Village. It gives long farm loops a cooperative checkpoint
        # where Hunter can take priority without a second thread touching the
        # shared HTTP session concurrently.
        self.hunter_service_callback = None

    def _refused_for_pack_reason(self):
        """
        A ultima recusa do jogo foi problema do PACOTE, e nao do alvo?

        Duas causas caem aqui, e ambas se repetiriam identicas em todo alvo:
        falta de tropa em casa, e pacote abaixo do limite de ataque falso do
        mundo. Qualquer outra causa e problema do alvo e o pacote continua
        valido para os demais -- tratar as duas igual e o que fazia o bot
        repetir a mesma tentativa dezenas de vezes por ciclo.

        Mensagem desconhecida devolve False de proposito: seguir para o
        proximo alvo e o degradar seguro, e o texto vai ao log em WARNING
        justamente para poder ser acrescentado a uma das listas depois de lido
        de um servidor real. Foi assim que o limite de ataque falso apareceu:
        ele nao estava mapeado, caiu no caminho generico e se identificou pelo
        log.
        """
        reason = (self.last_refusal or "").lower()
        return any(
            frag in reason
            for frag in INSUFFICIENT_UNITS_MESSAGES + FAKE_LIMIT_MESSAGES
        )

    def enough_in_village(self, units):
        """
        Checks if there are enough troops in a village,
        respecting the conquest_reserve set by ConquestManager /
        PvpConquestManager.
        """
        farmable = self._get_farmable_troops()
        for unit in units:
            available = int(farmable.get(unit, 0))
            if units[unit] > available:
                return f"{unit} ({available}/{units[unit]})"
        return False

    def _get_farmable_troops(self):
        """
        Feature 8 / Feature 13: Returns available troops minus every active
        conquest_reserve (summed across owners -- barbarian noble train
        escort, PvP conquest clear/escort, etc. -- see
        TroopManager.total_conquest_reserve()). Ensures troops earmarked for
        any pending conquest are never consumed by farm attacks while
        waiting for that attack to actually fire.
        """
        reserve = self.troopmanager.total_conquest_reserve() if hasattr(
            self.troopmanager, "total_conquest_reserve"
        ) else {}
        farmable = {}
        for unit, qty in self.troopmanager.troops.items():
            reserved = reserve.get(unit, 0)
            farmable[unit] = str(max(0, int(qty) - reserved))
        return farmable

    def run(self):
        """
        Run the farming logic
        """
        if not self.troopmanager.can_attack or self.troopmanager.troops == {}:
            # Disable farming is disabled in config or no troops available
            return False
        self.get_targets()
        ignored = []
        # Limits the amount of villages that are farmed from the current village
        for target in self.targets[0: self.max_farms]:
            if callable(self.hunter_service_callback):
                self.hunter_service_callback()
            village, *_ = target
            packs = self._ordered_templates(village["id"])
            sent = False
            for template in packs:
                if template in ignored:
                    continue
                out_res = self.send_farm(target, template)
                if out_res == 1:
                    sent = True
                    break
                if out_res == -1:
                    ignored.append(template)
            # Se nem o menor pacote cabe no que sobrou em casa, os proximos
            # alvos tambem nao vao caber -- encerra o ciclo em vez de repetir
            # a mesma checagem para cada um. Preserva o `break` que o caminho
            # de template unico ja tinha.
            if not sent and packs and packs[-1] in ignored:
                break

    def _pack_capacity(self, template):
        """
        Capacidade de saque de um pacote de farm.
        """
        return sum(UNIT_CARRY.get(unit, 0) * int(qty) for unit, qty in template.items())

    def _pack_population(self, template):
        """
        Populacao (fazendeiros) que um pacote ocupa -- a unidade em que o
        limite de ataque falso e expresso.
        """
        return sum(UNIT_POP.get(unit, 0) * int(qty) for unit, qty in template.items())

    def _legalize(self, template):
        """
        Devolve o pacote crescido o suficiente para respeitar o limite de
        ataque falso desta aldeia, ou o proprio pacote se ele ja respeita.

        Crescer e melhor do que descartar: o pacote pequeno existe para nao
        desperdicar tropa em alvo pobre, e o piso do mundo nao muda essa
        intencao, so o minimo. Descartar deixaria a aldeia grande sem opcao
        pequena nenhuma e todo alvo pobre receberia o pacote medio.

        O piso sobe junto com os pontos da aldeia, entao um pacote escrito no
        template deixa de ser legal sozinho, sem nada no bot mudar -- a BBM
        001 cruzou 6.000 pontos e os 60 de populacao do menor pacote viraram
        ilegais. Por isso o ajuste e aqui, em runtime, e nao um numero fixo no
        arquivo.
        """
        if not self.min_attack_pop:
            return template
        pop = self._pack_population(template)
        if pop >= self.min_attack_pop or pop <= 0:
            return template
        # Cresce proporcionalmente, arredondando para cima, para preservar a
        # proporcao entre unidades quando o pacote tem mais de uma.
        factor = self.min_attack_pop / pop
        grown = {
            unit: max(1, math.ceil(int(qty) * factor)) for unit, qty in template.items()
        }
        self.logger.debug(
            "Pacote %s tem %d de populacao, abaixo do minimo %d desta aldeia (%d pontos); "
            "crescido para %s", str(template), pop, self.min_attack_pop,
            self.village_points, str(grown)
        )
        return grown

    def _expected_loot(self, vid):
        """
        Quanto este alvo deve render agora. Duas fontes, a maior vence:

        - `farm_score`: media longa do que nos saqueamos. E **capada pelo
          pacote que mandamos** -- medido em 2026-08-17, dos envios com
          capacidade 8.000, 46% voltaram exatamente com 8.000, ou seja o valor
          real era desconhecido acima disso.
        - `ReportManager.last_seen_value()`: a observacao mais recente sobre o
          alvo -- estoque visto pelo explorador, ou o saque do ultimo ataque.
          E o dado fresco, e o que corrige um `farm_score` velho ou ausente.

        Zero significa "sem dado nenhum", e nao "alvo pobre" -- ver
        _ordered_templates.

        Este metodo consultava `has_resources_left()`, que olha **so o
        relatorio mais novo** e devolve False quando ele nao e de exploracao.
        Como depois do primeiro farm o mais novo passa a ser sempre um
        relatorio de ataque, o caminho desligava de vez: em 2026-08-19, ao
        vivo, 11 dos 119 alvos ficavam com expected=0 e levavam o menor pacote
        da escada -- um deles com 10.292 vistos pelo explorador recebendo 640
        de capacidade.
        """
        entry = AttackCache.get_cache(vid) or {}
        expected = int(entry.get("farm_score") or 0)
        if self.repman:
            expected = max(expected, int(self.repman.last_seen_value(vid) or 0))
        return expected

    def _ordered_templates(self, vid):
        """
        Escolhe com qual pacote de farm comecar neste alvo, casando capacidade
        com o saque esperado, e devolve o escolhido mais os menores.

        A cauda importa: a queda para pacote menor por falta de tropa em casa
        ja existia em run() e continua valendo. O que muda e o ponto de
        partida, que antes era sempre o primeiro item do template -- ou seja,
        aldeia cheia mandava o maior pacote em todo alvo, e aldeia vazia sempre
        o menor, independente do que o alvo tinha.

        A ordenacao e recalculada por capacidade em vez de confiar na ordem do
        arquivo, para que um template escrito fora de ordem nao inverta a
        escada em silencio.

        Todo pacote passa por _legalize() antes: o mundo exige um minimo de
        populacao por ataque que cresce com os pontos da aldeia, e um pacote
        escrito no template deixa de ser legal sozinho conforme ela cresce.
        Crescer o pacote e feito ANTES da ordenacao porque muda a capacidade e
        pode reordenar a escada -- dois pacotes distintos no arquivo podem
        virar o mesmo depois do piso, e a deduplicacao evita tentar duas vezes
        exatamente o mesmo envio.
        """
        templates = self.template if isinstance(self.template, list) else [self.template]
        legalizados = []
        for pack in templates:
            legal = self._legalize(pack)
            if legal not in legalizados:
                legalizados.append(legal)
        packs = sorted(legalizados, key=self._pack_capacity, reverse=True)
        if len(packs) < 2:
            return packs

        expected = self._expected_loot(vid)
        if not expected:
            # Nenhuma observacao: sonda com o menor em vez de comprometer o
            # maior num alvo que pode nao render nada.
            return packs[-1:]

        # Menor pacote que ainda cobre o esperado; se nenhum cobre, o maior.
        #
        # A comparacao e ESTRITA de proposito. `expected` vem em boa parte de
        # valores que sao o proprio teto do pacote anterior -- saque igual a
        # capacidade nao e uma medicao, e uma observacao censurada: significa
        # "tinha isso ou mais". Com `>=`, um alvo que volta lotado fixa o score
        # na capacidade e escolhe para sempre o mesmo pacote que o censurou.
        # Havia 18 alvos com farm_score exatamente 1.600 no cache de
        # 2026-08-19, todos capados pelo pacote antigo de 20 cavalarias, para
        # ilustrar que o caso e comum e nao teorico. Com `>`, esse alvo sobe um
        # degrau, descobre o valor real e assenta onde deve.
        for index in range(len(packs) - 1, -1, -1):
            if self._pack_capacity(packs[index]) > expected:
                return packs[index:]
        return packs

    def send_farm(self, target, template):
        """
        Send a farming run
        """
        target, *_ = target  # unpack village dict; ignore distance and sort_key
        missing = self.enough_in_village(template)
        if not missing:
            cached = self.can_attack(vid=target["id"], clear=False)
            if cached:
                attack_result = self.attack(target["id"], troops=template)
                if attack_result == "forced_peace":
                    return 0
                # O log e o reporter ficam DENTRO do if: antes eles anunciavam
                # o ataque antes de saber se o servidor aceitou, entao contavam
                # tentativa como envio. Medido em 2026-08-19: num ciclo com 28
                # tentativas da BBM 001, apenas 5 viraram POST de confirmacao e
                # 23 foram recusadas -- e as 23 apareciam no log como
                # "Attacking ...". Toda analise de campo feita por contagem de
                # linha (volume de farm, capacidade enviada, /farmscores) saia
                # inflada, e foi assim que a validacao desta feature comecou
                # com numeros errados.
                if attack_result:
                    self.logger.info(
                        "Attacking %s -> %s (%s)", self.village_id, target["id"], str(template)
                    )
                    self.wrapper.reporter.report(
                        self.village_id,
                        "TWB_FARM",
                        "Attacking %s -> %s (%s)"
                        % (self.village_id, target["id"], str(template)),
                    )
                    for u in template:
                        self.troopmanager.troops[u] = str(
                            int(self.troopmanager.troops[u]) - template[u]
                        )
                    self.attacked(
                        target["id"],
                        scout=True,
                        safe=True,
                        high_profile=cached["high_profile"]
                        if type(cached) == dict
                        else False,
                        low_profile=cached["low_profile"]
                        if type(cached) == dict and "low_profile" in cached
                        else False,
                    )
                    return 1
                elif self._refused_for_pack_reason():
                    # Recusa que se repetiria identica em todo alvo -- ou nao
                    # ha tropa em casa, ou o pacote e menor que o limite de
                    # ataque falso desta aldeia. O contador local so decrementa
                    # em caso de sucesso, entao sem isto enough_in_village()
                    # aprovaria de novo e o bot tentaria o mesmo pacote no
                    # proximo alvo: foram 23 tentativas recusadas seguidas na
                    # BBM 001 em 2026-08-19, cada uma com um GET e um POST.
                    # -1 poe o pacote na lista de ignorados do ciclo, o mesmo
                    # tratamento da falta de tropa detectada localmente.
                    self.logger.info(
                        "Pacote %s recusado por %s (%s), nao sera tentado de novo neste ciclo",
                        str(template), self.village_id, self.last_refusal
                    )
                    return -1
                else:
                    self.logger.debug(
                        "Ignoring target %s because unable to attack (server refused, not blocking future attempts)", target["id"]
                    )
        else:
            self.logger.debug(
                "Not sending additional farm because not enough units: %s", missing
            )
            return -1
        return 0

    def get_targets(self):
        """
        Gets all possible farming targets based on distance and loot efficiency.
        Sorts by: distance / farm_score (lower = more efficient).
        Falls back to distance-only for farms with no report history.
        """
        output = []
        # Feature 5: load all cached farm scores for efficiency sorting
        farm_scores = AttackCache.cache_grab()
        # Unknown farms get high priority so they are visited first to build history.
        # Once farm_manager runs and scores them, they settle into their real position.
        default_score = 9999

        my_village = (
            self.map.villages[self.village_id]
            if self.village_id in self.map.villages
            else None
        )
        for vid in self.map.villages:
            village = self.map.villages[vid]
            if village["owner"] != "0" and vid not in self.extra_farm:
                if vid not in self.ignored:
                    self.logger.debug(
                        "Ignoring village %s because player owned, add to additional_farms to auto attack", vid
                    )
                    self.ignored.append(vid)
                continue
            if my_village and "points" in my_village and "points" in village:
                if village["points"] >= self.farm_maxpoints:
                    if vid not in self.ignored:
                        self.logger.debug(
                            "Ignoring village %s because points %d exceeds limit %d",
                            vid, village["points"], self.farm_maxpoints
                        )
                        self.ignored.append(vid)
                    continue
                if village["points"] <= self.farm_minpoints:
                    if vid not in self.ignored:
                        self.logger.debug(
                            "Ignoring village %s because points %d below limit %d",
                            vid, village["points"], self.farm_minpoints
                        )
                        self.ignored.append(vid)
                    continue
                if (
                        village["points"] >= my_village["points"]
                        and not self.target_high_points
                ):
                    if vid not in self.ignored:
                        self.logger.debug(
                            "Ignoring village %s because of higher points %d -> %d",
                            vid, my_village["points"], village["points"]
                        )
                        self.ignored.append(vid)
                    continue
                if vid in self._unknown_ignored:
                    continue
            if village["owner"] != "0":
                get_h = time.localtime().tm_hour
                if get_h in range(0, 8) or get_h == 23:
                    self.logger.debug(
                        "Village %s will be ignored because it is player owned and attack between 23h-8h", vid
                    )
                    continue
            distance = self.map.get_dist(village["location"])
            if distance > self.farm_radius:
                if vid not in self.ignored:
                    self.logger.debug(
                        "Village %s will be ignored because it is too far away: distance is %f, max is %d",
                        vid, distance, self.farm_radius
                    )
                    self.ignored.append(vid)
                continue
            if vid in self.ignored:
                self.logger.debug("Removed %s from farm ignore list", vid)
                self.ignored.remove(vid)

            # `or default_score` trataria um score 0 (farm que nao rende nada)
            # como "sem historico" e o colocaria no topo da fila. Enquanto o
            # farm_score nunca era gravado (P1-8) isso era inofensivo; agora
            # que o farm_manager grava de verdade, precisa distinguir
            # "ainda nao pontuado" (None) de "pontuado como ruim" (0).
            score = farm_scores.get(vid, {}).get("farm_score")
            if score is None:
                score = default_score
            output.append([village, distance, distance / max(score, 1)])
        self.logger.info(
            "Farm targets: %d Ignored targets: %d", len(output), len(self.ignored)
        )
        self.targets = sorted(output, key=lambda x: x[2])

    def attacked(self, vid, scout=False, high_profile=False, safe=True, low_profile=False):
        """
        The farm was sent and this is a callback on what happened.
        Merges with existing cache to preserve farm_score and attack_count.
        """
        existing = AttackCache.get_cache(vid) or {}
        cache_entry = {
            "scout": scout,
            "safe": safe,
            "high_profile": high_profile,
            "low_profile": low_profile,
            "last_attack": int(time.time()),
            # preserve score fields calculated by farm_manager
            "farm_score": existing.get("farm_score", None),
            "attack_count": existing.get("attack_count", 0),
        }
        AttackCache.set_cache(vid, cache_entry)

    def scout(self, vid):
        """
        Attempt to send scouts to a farm
        """
        if "spy" not in self.troopmanager.troops or int(self.troopmanager.troops["spy"]) < self.scout_farm_amount:
            self.logger.debug(
                "Cannot scout %s at the moment because insufficient unit: spy", vid
            )
            return False
        troops = {"spy": self.scout_farm_amount}
        # P2-37: nao retornava nada em caso de sucesso, entao o guard do
        # chamador (`if self.scout(vid): return False`) nunca era verdadeiro --
        # o bot mandava o espiao E o farm no mesmo ciclo, contra o proprio
        # objetivo de "espiar antes de atacar".
        #
        # O `!= "forced_peace"` e o mesmo guard que os outros quatro
        # chamadores de attack() ja tinham (ConquestManager duas vezes,
        # Hunter, PvpConquest); este era o unico fora do padrao. Sem ele,
        # durante a paz forcada o sentinel -- que e string, logo truthy --
        # passava como sucesso e attacked() gravava last_attack=agora para um
        # explorador que nunca saiu, adiando a proxima espionagem real.
        result = self.attack(vid, troops=troops)
        if result and result != "forced_peace":
            self.attacked(vid, scout=True, safe=False)
            return True
        return False

    def can_attack(self, vid, clear=False):
        """
        Checks if it is safe en engage
        If not an amount of 5 scouts will be sent
        """
        cache_entry = AttackCache.get_cache(vid)

        if cache_entry and cache_entry["last_attack"]:
            last_attack = datetime.fromtimestamp(cache_entry["last_attack"])
            now = datetime.now()
            # 2026-08-17: era 12h. Medido no cache atual, a idade dos alvos e
            # bimodal -- mediana de ~11h (os que o bot farma de fato) e uma
            # cauda de ~31 alvos com mais de 72h. Entre 12h e 48h praticamente
            # nao ha alvo, entao subir o limiar quase nao muda a demanda de
            # explorador (45 -> 42 alvos); serve para parar de re-espiar alvo
            # recem-farmado por causa de um atraso de ciclo.
            if last_attack < now - timedelta(hours=48):
                self.logger.debug(f"Attacked long ago %s, trying scout attack", {last_attack})
                if self.scout(vid):
                    return False

        if not cache_entry:
            status = self.repman.safe_to_engage(vid)
            if status == 1:
                return True

            if self.troopmanager.can_scout:
                self.scout(vid)
                return False
            self.logger.warning(
                "%s will be attacked but scouting is not possible (yet), going in blind!", vid
            )
            return True

        if not cache_entry["safe"] or clear:
            if cache_entry["scout"] and self.repman:
                status = self.repman.safe_to_engage(vid)
                if status == -1:
                    self.logger.info(
                        "Checking %s: scout report not yet available", vid
                    )
                    return False
                if status == 0:
                    # Relatório velho = último contato há MAIS de
                    # farm_low_prio_wait*2. Estava invertido: re-espiava alvo
                    # recém-espiado e descartava para sempre o que precisava
                    # ser reavaliado (P1-10).
                    if int(time.time()) - cache_entry["last_attack"] > self.farm_low_prio_wait * 2:
                        self.logger.info(f"{vid}: Old scout report found ({cache_entry['last_attack']}), re-scouting")
                        self.scout(vid)
                        return False
                    else:
                        self.logger.info(
                            "%s: scout report noted enemy units, ignoring", vid
                        )
                        return False
                self.logger.info(
                    "%s: scout report noted no enemy units, attacking", vid
                )
                return True

            self.logger.debug(
                "%s will be ignored for attack because unsafe, set safe:true to override", vid
            )
            return False

        if not cache_entry["scout"] and self.troopmanager.can_scout:
            self.scout(vid)
            return False
        min_time = self.farm_default_wait
        if cache_entry["high_profile"]:
            min_time = self.farm_high_prio_wait
        if "low_profile" in cache_entry and cache_entry["low_profile"]:
            min_time = self.farm_low_prio_wait

        if cache_entry and self.repman:
            res_left, res = self.repman.has_resources_left(vid)
            total_loot = 0
            for x in res:
                total_loot += int(res[x])

            if res_left and total_loot > 100:
                self.logger.debug(f"Draining farm of resources! Sending attack to get {res}.")
                min_time = int(self.farm_high_prio_wait / 2)

        if cache_entry["last_attack"] + min_time > int(time.time()):
            self.logger.debug(
                "%s will be ignored because of previous attack (%d sec delay between attacks)",
                vid, min_time
            )
            return False
        return cache_entry

    def has_troops_available(self, troops):
        for t in troops:
            if (
                    t not in self.troopmanager.troops
                    or int(self.troopmanager.troops[t]) < troops[t]
            ):
                return False
        return True

    def _resolve_position(self, vid):
        """
        Coordenada (x, y) do alvo, ou None quando nao da para saber onde ele
        fica -- unico caso em que o ataque nao pode sequer ser tentado.

        Duas fontes, nesta ordem:

        1. `self.map.map_pos`, o scan de mapa DESTA aldeia neste ciclo. E o que
           o farm usa, e para o farm basta: ele so itera sobre `map.villages`,
           entao o alvo sempre veio dali.
        2. `cache/villages/{vid}.json`, o snapshot COMPARTILHADO que qualquer
           aldeia gerenciada alimenta (game/map.py::Map.build_cache_entry).

        A fonte 2 existe por causa da conquista: `ConquestManager.find_target()`
        devolve alvo manual ignorando raio de proposito, e `_get_village_meta()`
        ja consultava esse mesmo snapshot para nome/pontos. So a COORDENADA
        continuava saindo apenas do `map_pos` local -- entao um alvo legitimo,
        validado pelo webmanager contra `cache/villages`, era recusado aqui em
        silencio se por acaso nao estivesse no prefetch de mapa da aldeia que o
        reivindicou. Com `farms.map_sector_radius = 0` (o default, e o valor em
        campo) esse prefetch e pequeno e erratico -- ver o comentario em
        map.py:56 --, entao o caso era comum, e o unico sinal era um
        `attack N/4 failed` sem motivo.

        O gate do P2-38 continua valendo: sem coordenada em NENHUMA das duas
        fontes, devolve None antes do GET da praca (que custa o sleep de
        delay_factor). O que muda e que agora isso e logado -- "recusei" sem
        dizer por que foi metade do custo do bug original.
        """
        position = self.map.map_pos.get(vid)
        if position:
            return position

        cached = FileManager.load_json_file(f"cache/villages/{vid}.json") or {}
        location = cached.get("location")
        if location and len(location) == 2:
            self.logger.debug(
                "[Attack] %s -> %s: coordenada %s|%s veio do cache compartilhado "
                "(alvo fora do scan de mapa desta aldeia)",
                self.village_id, vid, location[0], location[1]
            )
            return int(location[0]), int(location[1])

        self.logger.warning(
            "[Attack] %s -> %s: sem coordenada no scan desta aldeia nem em "
            "cache/villages/%s.json -- nao da para montar o ataque",
            self.village_id, vid, vid
        )
        return None

    def attack(self, vid, troops=None, additional_attacks=None):
        """
        Send one TW attack, optionally with more attacks in the same request.

        ``additional_attacks`` is the native rally-point train: the primary
        attack keeps the ordinary unit fields and every extra command is sent
        as ``train[2][unit]``, ``train[3][unit]``, ... .  The numbering was
        captured and validated live on br143 on 2026-09-04; attack #1 is the
        unprefixed command, so the first additional row really starts at 2.

        The batch uses the form's normal ``action=command`` endpoint.  That is
        the exact endpoint used by the game's own "Adicionar ataque adicional"
        form and was validated with two real commands landing 115 ms apart.
        Single attacks deliberately keep the long-standing
        ``ajaxaction=popup_command`` path.
        """
        # P1-17: o AttackManager passou a ser criado sempre (village.py::
        # ensure_attack_manager), inclusive durante paz forcada. Antes o
        # bloqueio vinha de o objeto simplesmente nao existir; agora precisa
        # ser explicito, senao Hunter/PvP atacariam dentro da janela de paz.
        # Zerado a cada tentativa para que um caller nunca leia a duracao de um
        # ataque anterior como se fosse a deste (ver last_attack_duration).
        self.last_attack_duration = None
        self.last_refusal = None
        additional_attacks = [dict(atk) for atk in (additional_attacks or [])]

        if self.in_forced_peace:
            self.logger.info("[Attack] %s -> %s: forced peace active, not sending", self.village_id, vid)
            return "forced_peace"

        # P2-38: validar a posicao antes do GET da praca -- a requisicao
        # (com o sleep de delay_factor) era desperdicada quando o alvo nao
        # estava no mapa.
        position = self._resolve_position(vid)
        if position is None:
            return False

        url = f"game.php?village={self.village_id}&screen=place&target={vid}"
        pre_attack = self.wrapper.get_url(url)
        if pre_attack is None:
            self.logger.warning("[Attack] %s -> %s: request timed out, aborting", self.village_id, vid)
            return False
        pre_data = {}
        for u in Extractor.attack_form(pre_attack):
            k, v = u
            pre_data[k] = v
        if troops:
            pre_data.update(troops)
        else:
            pre_data.update(self.troopmanager.troops)

        x, y = position
        post_data = {"x": x, "y": y, "target_type": "coord", "attack": "Aanvallen"}
        pre_data.update(post_data)

        confirm_url = f"game.php?village={self.village_id}&screen=place&try=confirm"
        conf = self.wrapper.post_url(url=confirm_url, data=pre_data)
        if conf is None:
            self.logger.warning("[Attack] %s -> %s: confirm request timed out, aborting", self.village_id, vid)
            return False
        if '<div class="error_box">' in conf.text:
            # O motivo importa: "falta unidade" pede parar de tentar este
            # pacote no ciclo, "aldeia nao existe" pede tirar o alvo da lista,
            # e ate 2026-08-19 as duas viravam o mesmo False silencioso -- o
            # chamador logava "server refused" sem dizer o que o jogo falou.
            self.last_refusal = Extractor.error_box_text(conf)
            self.logger.warning(
                "[Attack] %s -> %s recusado pelo jogo: %s",
                self.village_id, vid, self.last_refusal
            )
            return False
        duration = Extractor.attack_duration(conf)
        if self.forced_peace_time:
            now = datetime.now()
            if now + timedelta(seconds=duration) > self.forced_peace_time:
                self.logger.info("Attack would arrive after the forced peace timer, not sending attack!")
                return "forced_peace"

        self.logger.info(
            "[Attack] %s -> %s duration %f.1 h", self.village_id, vid, duration / 3600
        )
        self.last_attack_duration = duration

        confirm_data = {}
        for u in Extractor.attack_form(conf):
            k, v = u
            if k == "support":
                continue
            confirm_data[k] = v
        new_data = {"building": "main", "h": self.wrapper.last_h}
        confirm_data.update(new_data)
        # The extractor doesn't like the empty cb value, and mistakes its value for x. So I add it here.
        if "x" not in confirm_data:
            confirm_data["x"] = x

        if additional_attacks:
            primary_troops = troops or self.troopmanager.troops
            batch = [primary_troops] + additional_attacks
            requested = {}
            for attack_troops in batch:
                for unit, qty in attack_troops.items():
                    requested[unit] = requested.get(unit, 0) + int(qty)

            if not self.has_troops_available(requested):
                self.last_refusal = "batch requires more units than are available"
                self.logger.warning(
                    "[Attack] %s -> %s: %s",
                    self.village_id, vid, self.last_refusal
                )
                return False

            # The native form posts every enabled unit for every added row,
            # including zeroes.  Use the troop manager as the world-specific
            # unit list (it includes archer/marcher only on worlds that have
            # them), plus any explicit keys so tests and callers stay robust.
            unit_names = set(self.troopmanager.troops)
            for attack_troops in batch:
                unit_names.update(attack_troops)

            for train_index, attack_troops in enumerate(additional_attacks, start=2):
                for unit in sorted(unit_names):
                    confirm_data[f"train[{train_index}][{unit}]"] = int(
                        attack_troops.get(unit, 0)
                    )

            batch_url = (
                f"game.php?village={self.village_id}"
                "&screen=place&action=command"
            )
            result = self.wrapper.post_url(url=batch_url, data=confirm_data)
            if result is None:
                self.logger.warning(
                    "[Attack] %s -> %s: batch request timed out, aborting",
                    self.village_id, vid
                )
                return False
            if getattr(result, "status_code", 200) != 200:
                self.last_refusal = "batch request returned HTTP %s" % getattr(
                    result, "status_code", "unknown"
                )
                self.logger.warning(
                    "[Attack] batch %s -> %s failed: %s",
                    self.village_id, vid, self.last_refusal
                )
                return False
            if '<div class="error_box">' in result.text:
                self.last_refusal = Extractor.error_box_text(result)
                self.logger.warning(
                    "[Attack] batch %s -> %s refused by game: %s",
                    self.village_id, vid, self.last_refusal
                )
                return False
        else:
            result = self.wrapper.get_api_action(
                village_id=self.village_id,
                action="popup_command",
                params={"screen": "place"},
                data=confirm_data,
            )

        return result


class AttackCache:
    @staticmethod
    def get_cache(village_id):
        return FileManager.load_json_file(f"cache/attacks/{village_id}.json")

    @staticmethod
    def set_cache(village_id, entry):
        return FileManager.save_json_file(entry, f"cache/attacks/{village_id}.json")

    @staticmethod
    def cache_grab():
        output = {}

        for existing in FileManager.list_directory("cache/attacks", ends_with=".json"):
            output[existing.replace(".json", "")] = FileManager.load_json_file(f"cache/attacks/{existing}")
        return output


class ConquestCache:
    """
    Feature 8: Persists conquest state per target village.
    Cache path: cache/conquest/{target_id}.json
    """
    @staticmethod
    def get(target_id):
        return FileManager.load_json_file(f"cache/conquest/{target_id}.json")

    @staticmethod
    def set(target_id, entry):
        FileManager.save_json_file(entry, f"cache/conquest/{target_id}.json")

    # Status que significam "este alvo ja e de alguem, nao reeleja".
    #
    # `train_scheduled` entrou com o planejador multi-origem
    # (game/conquest_planner.py): entre agendar no Hunter e o Hunter disparar
    # passam-se minutos ou horas, e nessa janela nao ha nobre no ar nem
    # registro "train_sent" -- ou seja, nenhum dos dois filtros antigos
    # cobria o alvo e find_target() o reelegeria como se estivesse livre. E o
    # mesmo buraco do incidente de 2026-08-12 (registro fora de all_reserved
    # com quatro nobres voando), so que do outro lado da linha do tempo.
    ACTIVE_STATUSES = ("train_scheduled", "train_sent", "extra_pending")

    @staticmethod
    def all_reserved():
        """Returns set of target_ids currently reserved by any village."""
        reserved = set()
        for fname in FileManager.list_directory("cache/conquest", ends_with=".json"):
            data = FileManager.load_json_file(f"cache/conquest/{fname}")
            if data and data.get("status") in ConquestCache.ACTIVE_STATUSES:
                reserved.add(fname.replace(".json", ""))
        return reserved

    @staticmethod
    def active_conquests():
        """
        {target_id: data} de toda conquista barbara em andamento, de qualquer
        aldeia -- agendada, em voo ou aguardando nobre extra.

        O planejador usa isto para manter a invariante de UM trem barbaro por
        vez no imperio. Ela ja existia de fato no modelo por aldeia, so que
        por acidente: cada ConquestManager so via a propria aldeia e precisava
        de 4 nobres proprios, entao dois trens simultaneos eram raros. Com o
        planejador juntando nobres do imperio inteiro, nada garantiria isso --
        e dois trens concorrentes disputariam os mesmos nobres.
        """
        active = {}
        for fname in FileManager.list_directory("cache/conquest", ends_with=".json"):
            data = FileManager.load_json_file(f"cache/conquest/{fname}")
            if not data:
                continue
            target_id = fname.replace(".json", "")
            if data.get("status") in ConquestCache.ACTIVE_STATUSES:
                active[target_id] = data
            elif ConquestCache.nobles_in_flight(data):
                # Status pode estar errado -- foi o que aconteceu em
                # 2026-08-12 ("complete" com quatro nobres no ar). A chegada
                # nao mente, entao ela tem a ultima palavra.
                active[target_id] = data
        return active

    @staticmethod
    def nobles_in_flight(data, now=None):
        """
        Devolve os timestamps de chegada, ainda no futuro, dos nobres ja
        enviados contra este alvo -- ou seja, os que estao voando agora.

        Incidente de 2026-08-12 (Barbara #40314) que motivou o campo: um trem
        de 4 nobres saiu as 11:54 e pousou as 15:37 deixando a lealdade em 11.
        O bot estimava 0 e marcou o alvo como resolvido; depois, sem nenhuma
        nocao de que ainda havia nobre a caminho, mandou um segundo trem e um
        nobre extra. Resultado: o nobre das 23:28 conquistou a aldeia e sua
        escolta virou guarnicao dela; o nobre das 00:00 chegou 32 minutos
        depois, autoconquistou a aldeia (queimando uma moeda) e matou os 421
        homens da propria guarnicao, perdendo mais 106 no combate.

        Repare que isto NAO olha `status`. A trava anterior dependia de o
        status estar correto, e o status era justamente o que estava errado --
        o alvo estava marcado "complete" com nobre no ar. Chegada e um fato
        temporal: ou o nobre pousou ou nao pousou.

        Um `null` na lista significa "nobre enviado, chegada desconhecida":
        Extractor.attack_duration() devolve 0 quando o regex nao casa (markup
        novo, resposta truncada), e somar 0 a hora de envio faria o nobre
        nascer "ja pousado" -- justamente o estado que causou o incidente.
        Nesse caso o nobre conta como em voo indefinidamente (inf), e so a
        confirmacao de posse (_target_is_mine, avaliada *antes* desta trava em
        _handle_existing justamente por isso) ou uma limpeza manual pelo
        dashboard (ConquestReader.force_clear) liberam o alvo. Travar e a
        direcao segura: o custo de nao mandar nobre e esperar, o custo de
        mandar em cima de outro ja foi medido em 527 tropas.
        """
        if not data:
            return []
        if now is None:
            now = time.time()
        pending = []
        for ts in data.get("noble_arrivals", []):
            if ts is None:
                pending.append(float("inf"))
            elif ts > now:
                pending.append(ts)
        return sorted(pending)

    @staticmethod
    def targets_with_nobles_in_flight(now=None):
        """
        Conjunto de target_ids com pelo menos um nobre ainda no ar, de
        qualquer aldeia. Usado por find_target() para nunca eleger um alvo que
        ja tem nobre a caminho, mesmo que o registro dele diga "complete".
        """
        in_flight = set()
        for fname in FileManager.list_directory("cache/conquest", ends_with=".json"):
            data = FileManager.load_json_file(f"cache/conquest/{fname}")
            if ConquestCache.nobles_in_flight(data, now=now):
                in_flight.add(fname.replace(".json", ""))
        return in_flight


class ConquestManager:
    """
    Feature 8: Noble train manager for barbarian conquest.
    Handles target selection, escort calculation and attack sequencing.
    One ConquestManager instance per offensive village per cycle.
    """
    TRAIN_SIZE = 4
    MAX_RADIUS = 100
    # Quantas reivindicacoes sem envio um alvo manual aguenta antes de sair da
    # fila. Ver _note_failed_claim() para por que a fila precisa de uma saida.
    MANUAL_CLAIM_ATTEMPTS = 3
    # Units never used as escort filler.
    # knight (Paladino): there is only ever one per village and it must never
    # leave on its own -- same rule already enforced for the PvP conquest in
    # 2026-08-07 (see docs/backend.md). Without it here, the barbarian
    # train could ship the Paladino out as escort filler.
    # snob: it is the train's payload, not escort -- _send_train sets
    # troops["snob"] = 1 explicitly per attack, overwriting whatever the
    # escort calculation produced. Leaving snob in the escort pool only
    # inflated total_per_attack against min_escort_total, so a train could be
    # judged "escorted enough" on the back of nobles that were never actually
    # sent as escort. Noble availability is gated separately, by
    # _available_nobles().
    EXCLUDED_UNITS = {"spy", "knight", "snob"}

    # Default de classe porque varios chamadores (e os testes) constroem o
    # manager por `__new__`, sem passar pelo __init__. E imutavel, entao nao
    # cai no 1o padrao do CLAUDE.md -- o perigo la e list/dict mutados
    # in-place, compartilhados entre as instancias de todas as aldeias.
    reservation_board = None
    # Feature 36: lista de aldeias do mundo (map/village.txt). Mesmo motivo de
    # ser default de classe, e tambem imutavel do ponto de vista do 1o padrao
    # -- a instancia guarda estado, mas o default aqui e None.
    world_villages = None

    def __init__(self, wrapper, village_id, troopmanager, map_obj, config, repman=None,
                 reservation_board=None, world_villages=None):
        self.wrapper = wrapper
        self.village_id = village_id
        self.troopmanager = troopmanager
        self.map = map_obj
        self.config = config
        self.repman = repman  # ReportManager — used for real loyalty extraction
        # Feature 35 / Fase 1: quadro oficial de reservas da tribo (ALVO, nao
        # tropa -- ver o aviso de vocabulario em game/reservations.py). Opcional
        # de proposito: injetado por twb.py, ausente nos testes e nas chamadas
        # antigas. Quando e None a conquista se comporta como antes.
        self.reservation_board = reservation_board
        # Feature 36: piso de descoberta de alvo (docs/backend.md 8.6). Opcional
        # pelo mesmo motivo do quadro de reservas: injetado por twb.py, ausente
        # nos testes antigos, e quando e None o pool se comporta como antes.
        self.world_villages = world_villages
        self.logger = logging.getLogger(f"Conquest:{self.village_id}")
        self._attack_manager = AttackManager(
            wrapper=wrapper,
            village_id=village_id,
            troopmanager=troopmanager,
            map=map_obj,
        )
        # Faixa real de queda de lealdade por nobre, do <mood> do mundo.
        # WorldConfig.get() serve do cache em disco e so vai a rede a cada
        # CACHE_TTL, entao chamar por instancia/ciclo e barato.
        server_cfg = (config or {}).get("server", {})
        self._drop_min, self._drop_max = WorldConfig.loyalty_drop_range(
            WorldConfig.get(
                server=server_cfg.get("server"),
                endpoint=server_cfg.get("endpoint"),
            ),
            fallback=(config or {}).get("conquest", {}).get("loyalty_drop_per_noble", 25),
        )

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self):
        """
        Main entry point called from village.run_conquest().
        Returns True if something was dispatched, False otherwise.

        Desde a fase 2 (game/conquest_planner.py) este metodo NAO monta mais
        trem novo. Ele cuida da conquista que esta em andamento: lealdade real
        do relatorio, nobre extra quando faltou pouco, confirmacao de posse e
        alvo perdido para outro jogador. Quem escolhe alvo e despacha trem e o
        `BarbarianTrainPlanner`, que roda uma vez por ciclo e enxerga o
        imperio inteiro.

        A montagem saiu daqui inteira, e nao ficou como plano B, de proposito.
        Dois sistemas capazes de comprometer nobre para o mesmo alvo e o bug
        de double-booking que a Feature 27 existe para matar -- e a janela
        entre o planejador agendar (`train_scheduled`) e o Hunter disparar dura
        horas, que e tempo de sobra para uma aldeia com 4 nobres proprios
        montar um segundo trem contra o mesmo alvo sem saber do primeiro.
        Nobre e a unidade mais cara do jogo e ja custou 527 tropas e uma moeda
        neste projeto (2026-08-12).
        """
        cfg = self.config.get("conquest", {})
        if not cfg.get("enabled", False):
            return False

        # P1-9: a conquista em andamento e checada ANTES do guard de trem
        # completo. _handle_existing() trata o estado extra_pending, que
        # precisa de 1 noble, nao de TRAIN_SIZE. Com a ordem antiga, logo apos
        # disparar um trem a aldeia ficava com 0 nobles e todo run() saia no
        # primeiro return False -- a regen de lealdade, a leitura de lealdade
        # real e o envio do noble extra so voltavam a ser avaliados quando a
        # aldeia acumulasse 4 nobles novos, o que pode levar dias. Nesse meio
        # tempo a lealdade do alvo regenerava e o progresso se perdia.
        existing = self._get_my_conquest()
        if existing:
            return self._handle_existing(existing, cfg)

        # Sem conquista em andamento nesta aldeia nao ha nada a fazer aqui: a
        # montagem do trem e do planejador global. A reserva de escolta que o
        # caminho antigo mantinha tambem sai, senao ela ficaria presa para
        # sempre -- era o `run()` seguinte que a soltava, e ele nao existe
        # mais (P2-22 por outra porta).
        self.troopmanager.conquest_reserve.pop("barbarian_conquest", None)
        return False


    # ------------------------------------------------------------------
    # Target selection
    # ------------------------------------------------------------------

    def find_target(self, cfg, reach_from=None):
        """
        Scans the map for barbarian villages within radius, scores them
        and returns the best unreserved target_id.

        Feature 15: a manually queued target (set via webmanager /conquest)
        always takes priority over automatic scoring, bypassing the
        radius/points filters below (deliberate user choice).

        `reach_from` e a lista de coordenadas (x, y) das aldeias que podem de
        fato despachar nobre -- o trem multi-origem do BarbarianTrainPlanner.
        Quando ela vem:

          - o filtro de raio passa a usar a MENOR distancia ate qualquer uma
            dessas origens, em vez da distancia ate esta aldeia;
          - o pool de candidatos deixa de ser so o scan de mapa desta aldeia
            (ver _candidate_pool).

        A PONTUACAO continua medindo a partir desta aldeia (a ancora), de
        proposito: a ancora e quem manda mais nobres, entao a viagem dela e a
        que costuma definir a chegada comum de todo mundo. O que a ancora nao
        pode mais fazer e decidir QUEM ENTRA na lista -- era esse o defeito
        (docs/backend.md 8.6): o conjunto de alvos visiveis dependia de onde os
        nobres se acumularam, que e circunstancia e nao geografia.

        Sem `reach_from` o comportamento e o historico, byte por byte: uma
        aldeia so, vendo so o proprio scan.
        """
        # Feature 35: sem leitura do quadro de reservas nao se INICIA conquista
        # nenhuma -- nem automatica, nem manual. Antes de tudo de proposito:
        # e a fila manual que tem prioridade absoluta logo abaixo, entao uma
        # guarda colocada depois dela deixaria justamente o caminho manual
        # passando as cegas.
        if not self._may_start_new_conquest():
            return None

        manual_target = self._get_manual_target()
        if manual_target:
            self.logger.info(
                "Conquest: using manually queued target %s (overrides automatic selection)",
                manual_target
            )
            return manual_target

        max_radius = self._effective_radius(cfg)
        min_pts = cfg.get("min_points", 100)
        max_pts = cfg.get("max_points", 3000)
        # `all_reserved` filtra por status; `targets_with_nobles_in_flight`
        # filtra por chegada. Precisamos dos dois porque foi exatamente a
        # divergencia entre eles que causou o incidente de 2026-08-12: o
        # registro de 40314 estava "complete" (logo, fora de all_reserved) com
        # quatro nobres no ar, e find_target() reelegeu o mesmo alvo como se
        # fosse novo, disparando um segundo trem inteiro.
        reserved = ConquestCache.all_reserved() | ConquestCache.targets_with_nobles_in_flight()

        # Collect managed village locations for gap-filling score
        my_locations = self._get_managed_locations()

        origins = [tuple(loc) for loc in (reach_from or []) if loc and len(loc) == 2]
        if not origins:
            # Sem origens explicitas, a unica referencia e esta aldeia -- e ela
            # so tem coordenada depois de um scan de mapa bem-sucedido. Segundo
            # padrao do CLAUDE.md: `get_map()` devolve False em resposta que
            # nao e a tela de mapa, e ai `my_location` continua None.
            if not self.map.my_location:
                self.logger.warning(
                    "Conquest: aldeia %s ainda sem coordenada propria (scan de "
                    "mapa nao veio) -- sem ela nao da para medir raio nenhum",
                    self.village_id
                )
                return None
            origins = [tuple(self.map.my_location)]

        # `max_radius` viaja junto porque e ele que define a caixa de recorte
        # da lista do mundo -- ver _world_box(). Sem reach_from o pool continua
        # sendo so o scan desta aldeia, byte por byte como antes.
        pool = self._candidate_pool(reach_from, max_radius=max_radius)

        candidates = []
        for vid, village in pool.items():
            if str(village.get("owner", "0")) != "0":
                continue  # not barbarian
            if vid in reserved:
                continue  # already targeted
            if vid == self.village_id:
                continue

            pts = village.get("points", 0)
            if pts < min_pts or pts > max_pts:
                continue

            location = village.get("location")
            # O pool compartilhado e disco, nao o scan em memoria: uma entrada
            # truncada ou de formato antigo chegaria aqui sem coordenada, e o
            # `get_dist` abaixo estouraria o ciclo inteiro do planejador.
            if not location or len(location) != 2:
                continue

            # Alcance: a menor viagem entre as origens que podem mandar nobre.
            if min(field_distance(location, origin) for origin in origins) > max_radius:
                continue

            # Reserva de ALVO (tribo). Exclusao dura, depois do filtro de raio
            # so para nao consultar o quadro para alvo que ja saiu por outro
            # motivo -- a ordem nao muda o resultado.
            blocked = self._claim_block_reason(vid, location)
            if blocked:
                self.logger.info(
                    "Conquest: alvo %s descartado da selecao automatica (%s: %s)",
                    vid, blocked[0],
                    blocked[1].get("reserved_by_name") or blocked[1].get("matched")
                )
                continue

            dist = self.map.get_dist(location)
            score = self._score_target(village, dist, my_locations, cfg)
            candidates.append((vid, score, location))

        if not candidates:
            return None

        # Area de interesse: dentro dela primeiro, fora so quando nao sobrou
        # nada dentro. Ver _prefer_area_of_interest().
        candidates = self._prefer_area_of_interest(candidates, cfg)

        # Lower score = better target
        candidates.sort(key=lambda x: x[1])
        return candidates[0][0]

    # ------------------------------------------------------------------
    # Feature 35 / Fase 1 -- reserva de ALVO (tribo), nao reserva de tropa
    # ------------------------------------------------------------------

    def _claim_block_reason(self, target_id, location=None):
        """
        Motivo pelo qual este alvo NAO pode ser conquistado por nos, ou None.

        Devolve `(motivo_curto, detalhe_dict)` para o chamador logar e gravar
        em cache/conquest -- sem isso, daqui a um mes ninguem sabe se a
        exclusao ainda vale (docs/backend.md 8.7).

        Duas fontes, nesta ordem:
          1. `conquest.excluded_targets` -- valvula de escape manual, para
             reserva combinada fora do jogo (forum, Discord).
          2. O quadro oficial da tribo, quando reservado por OUTRA pessoa.

        Isto e exclusao DURA, ao contrario de `_prefer_area_of_interest()`, que
        e preferencia. A assimetria e deliberada: pular um alvo livre custa uma
        barbara entre dezenas; nobrar reserva alheia custa capital social, e
        irreversivel, e ja gastou 4 nobres e uma moeda.
        """
        manual = manual_exclusion(self.config, target_id, location)
        if manual:
            return "excluded_targets", {"blocked_by": "config", "matched": manual}

        board = self.reservation_board
        if not board:
            return None
        claim = board.claimed_by_other(target_id, location)
        if claim:
            return "tribe_reservation", {
                "blocked_by": "tribe_reservation",
                "reserved_by_id": claim.get("reserved_by_id"),
                "reserved_by_name": claim.get("reserved_by_name"),
                "reserved_by_tribe": claim.get("reserved_by_tribe"),
                "reservation_expires": claim.get("expires_text"),
            }
        return None

    def _may_start_new_conquest(self):
        """
        False quando o bot nao tem leitura confiavel do quadro de reservas.

        Ler isto como "na duvida, pule" e nao como "na duvida, siga" e o ponto
        inteiro da feature: sem a leitura o bot nao sabe o que e de quem. Vale
        SO para conquista nova -- `_handle_existing()` nao consulta isto de
        proposito, porque abortar um trem por falha de leitura joga fora tropa
        real que ja esta voando.
        """
        board = self.reservation_board
        if not board or board.is_readable():
            return True
        self.logger.warning(
            "Conquest: sem leitura do quadro de reservas da tribo -- nenhuma "
            "conquista NOVA sera iniciada neste ciclo. Um alvo livre a mais "
            "custa uma barbara; nobrar reserva alheia custa capital social."
        )
        return False

    def _prefer_area_of_interest(self, candidates, cfg):
        """
        Filtra os candidatos para a caixa de coordenadas de
        `conquest.area_of_interest`, DEVOLVENDO A LISTA ORIGINAL quando nao
        sobra ninguem dentro dela.

        `candidates` e a lista de `(vid, score, location)` montada por
        find_target(); a coordenada viaja na tupla em vez de ser reconsultada
        aqui, para nao criar uma segunda fonte de verdade para a posicao do
        mesmo alvo dentro da mesma decisao.

        Preferencia, nao restricao, e isso e de proposito. A formulacao no
        forum da tribo (SQUAD 02, br143) e "nao quero jogador crescendo para
        fora da regiao ENQUANTO AINDA TIVERMOS BBs e alvos disponiveis dentro
        da nossa area" -- ou seja, a area esgotada libera o resto, e um filtro
        duro deixaria o bot parado em vez de expandir.

        Por que nao virou peso no _score_target: o score e uma mistura de
        centralidade, distancia e pontos, e qualquer peso finito pode ser
        vencido por uma combinacao boa o bastante fora da area. "Dentro ganha
        de fora, ponto" e a regra que o texto descreve, e particao expressa
        isso sem precisar calibrar constante nenhuma.

        Dentro da area o ranking nao muda: continua o `fill_gaps`, que por
        medir distancia media ao imperio inteiro elege naturalmente a borda
        mais proxima do cluster -- que e o "expandir gradativamente" do mesmo
        post. E o `fill_gaps` sozinho que NAO serve aqui: com o centroide das
        28 aldeias em ~(577|308), um alvo na fronteira norte (572|295) tem
        distancia media ~13 contra ~5 de um alvo no miolo, e com 60% de peso em
        centralidade a fronteira nunca ganha. O `fill_gaps` foi escrito para
        adensar o miolo; a area de interesse e o que diz para qual lado crescer.
        """
        area = cfg.get("area_of_interest") or {}
        if not area.get("enabled", False) or not candidates:
            return candidates

        try:
            x_min, x_max = int(area["x_min"]), int(area["x_max"])
            y_min, y_max = int(area["y_min"]), int(area["y_max"])
        except (KeyError, TypeError, ValueError):
            self.logger.warning(
                "Conquest: area_of_interest ligada mas sem x_min/x_max/y_min/"
                "y_max utilizaveis (%s) -- ignorando a area neste ciclo", area
            )
            return candidates

        inside = []
        for candidate in candidates:
            loc = candidate[2]
            if not loc or len(loc) != 2:
                continue
            x, y = int(loc[0]), int(loc[1])
            if x_min <= x <= x_max and y_min <= y <= y_max:
                inside.append(candidate)

        if not inside:
            self.logger.info(
                "Conquest: nenhuma barbara elegivel dentro de %d-%d|%d-%d neste "
                "ciclo -- avaliando os %d candidatos de fora da area",
                x_min, x_max, y_min, y_max, len(candidates)
            )
            return candidates

        self.logger.info(
            "Conquest: %d de %d candidatos estao na area de interesse "
            "(%d-%d|%d-%d) -- os de fora ficam para quando ela esgotar",
            len(inside), len(candidates), x_min, x_max, y_min, y_max
        )
        return inside

    def _effective_radius(self, cfg):
        """
        Raio de busca em campos, limitado pelo que o NOBRE realmente alcanca
        neste mundo (`<snob><max_dist>`, br143 = 70).

        `MAX_RADIUS = 100` e um teto chumbado do bot base e nao corresponde a
        regra de mundo nenhuma. Sem esta trava, `conquest.max_radius: 100`
        elegeria alvos que o jogo recusa no envio -- e a recusa vem no FIM do
        caminho, depois de escolher alvo, montar escolta, sondar duracao e
        agendar no Hunter. O alvo ficaria reservado, o trem nao sairia, e o
        unico sinal seria uma recusa generica.

        O limite do mundo e servido do cache em disco (TTL de 6h), entao isto
        nao vai a rede por ciclo. Mundo que nao publica a tag, ou publica 0
        (sem limite), cai no teto antigo -- e a configuracao do usuario segue
        valendo quando for menor, porque ela e uma escolha e nao um limite.
        """
        configured = cfg.get("max_radius", 20)
        server_cfg = (self.config or {}).get("server", {})
        world_limit = WorldConfig.noble_max_distance(
            WorldConfig.get(
                server=server_cfg.get("server"),
                endpoint=server_cfg.get("endpoint"),
            )
        )
        ceiling = world_limit if world_limit else self.MAX_RADIUS
        if configured > ceiling:
            self.logger.warning(
                "Conquest: max_radius %s excede o alcance do nobre neste mundo "
                "(%s campos) -- usando %s. Alvo alem disso seria recusado pelo "
                "jogo so na hora do envio",
                configured, ceiling, ceiling
            )
        return min(configured, ceiling)

    def _score_target(self, village, dist, my_locations, cfg):
        """
        Scoring for fill_gaps priority (default):
        Combines distance from attacker and centrality to empire.
        Lower = more desirable.

        Bugfix (2026-08-07): the 60/30/10 weights below used to apply
        directly to raw values -- distance in tiles (0..max_radius, so 0..20
        by default) and points (0..max_points, so 0..1100 by default).
        Those two ranges differ by ~2 orders of magnitude, so the "10%
        points" term (pts * 0.1, up to 110) completely swamped the "60%
        centrality" + "30% distance" terms (up to ~18 combined) -- in
        practice this always picked the highest-points barbarian in range,
        basically ignoring distance/gap-filling entirely (confirmed live:
        picked a target 11.2 tiles away over one 1.4 tiles away purely
        because it had ~3x the points). Fixed by normalizing distance and
        points to comparable 0..1 scales (relative to max_radius/max_points)
        before applying the weights, so the stated 60/30/10 split actually
        holds regardless of the configured radius/points range.
        """
        priority = cfg.get("priority", "fill_gaps")
        pts = village.get("points", 1)
        loc = village["location"]

        # Mesmo raio do filtro em find_target(), nao o cru da config: e por ele
        # que a distancia e normalizada, e usar dois numeros diferentes faria a
        # pontuacao referir-se a um raio que a selecao nao usa.
        max_radius = max(1, self._effective_radius(cfg))
        max_pts = max(1, cfg.get("max_points", 3000))
        # Higher points = more desirable, so this is subtracted below;
        # capped at 1.0 in case a village exceeds max_points somehow.
        pts_factor = min(1.0, pts / max_pts)
        dist_norm = min(1.0, dist / max_radius)

        if priority == "fill_gaps" and my_locations:
            # Average distance from ALL managed villages → lower means more central
            avg_dist_to_empire = sum(
                ((loc[0] - lx) ** 2 + (loc[1] - ly) ** 2) ** 0.5
                for lx, ly in my_locations
            ) / len(my_locations)
            avg_dist_norm = min(1.0, avg_dist_to_empire / max_radius)
            # Blend: centrality 60%, attacker distance 30%, inverse points 10%
            score = (avg_dist_norm * 0.6) + (dist_norm * 0.3) - (pts_factor * 0.1)
        else:
            # Simple: closer and higher points wins
            score = dist_norm - (pts_factor * 0.1)

        return score

    def _candidate_pool(self, reach_from=None, max_radius=None):
        """
        {village_id: dados} sobre o qual a selecao automatica varre.

        Sem `reach_from` (caminho historico, uma aldeia decidindo sozinha) e
        so o scan de mapa DESTA aldeia. Com ele, o snapshot compartilhado
        `cache/villages` -- alimentado por todas as aldeias gerenciadas -- com
        o scan vivo desta aldeia por cima.

        POR QUE O SCAN LOCAL NAO BASTA
        ------------------------------
        Com `farms.map_sector_radius = 0` (o default, e o valor em campo) o
        `TWMap.sectorPrefech` traz poucos setores e nao centrados na aldeia
        (ver o comentario em map.py:56). Medido ao vivo em 19/09/2026, com as
        39 barbaras elegiveis que o imperio conhece no K25:

            BBM 001 (a ancora de hoje) enxergava 23
            BBM 011 (a outra aldeia com nobre) enxergava as mesmas 23
            BBM 023 enxergava 30
            cache/villages tinha as 39

        Como o laco de find_target() so via esse funil, o conjunto de alvos
        dependia de qual aldeia acumulou nobre. Subir `max_radius` NAO corrige
        isso -- o raio filtra o que ja esta na lista; 16 alvos nunca chegavam a
        ser filtrados. O painel ja contava pelo snapshot compartilhado
        (ConquestReader.area_of_interest), entao ele e o bot vinham dando
        numeros diferentes para a mesma pergunta.

        O QUE ESTA FONTE TEM DE PIOR, E POR QUE AINDA ASSIM SERVE
        --------------------------------------------------------
        O snapshot e disco: dono e pontos sao do ultimo scan que passou por
        ali, entao uma barbara conquistada por um jogador pode continuar
        registrada como barbara ate alguem reescanear. O scan vivo desta
        aldeia entra por cima justamente por isso -- onde as duas fontes
        falam, a fresca vence. E o que escapar disso ainda encontra a
        revalidacao de posse em `_handle_existing()` (que le a mesma
        cache/villages e encerra o alvo como "lost"), a mesma rede que ja
        segurava o alvo manual em `_get_manual_target()`.

        Custo: uma varredura de diretorio por chamada. Isto roda UMA VEZ POR
        CICLO (o planejador global), nao por aldeia -- medido em 19/09/2026,
        851 arquivos em 0,13 s com o cache de disco do SO quente (a frio nao
        medi). Se o numero de aldeias conhecidas crescer muito, e um candidato
        ao indice descrito em docs/backend.md 6.5.

        A TERCEIRA FONTE (Feature 36, 2026-09-20)
        -----------------------------------------
        As duas fontes acima tem o MESMO limite, e o conserto de 19/09 nao o
        tocou: as duas so contem o que alguma aldeia nossa ja escaneou algum
        dia. Medido em 20/09: o mundo tem 130.909 aldeias e `cache/villages`
        tinha 851 -- cobertura de 0,65%. `map/village.txt` entra como PISO de
        descoberta, recortado pela caixa de coordenadas que o raio permite
        (ver `max_radius` abaixo).

        PRECEDENCIA -- e ela NAO e a mesma para as duas perguntas que este
        pool responde. Para DESCOBERTA (quem existe e onde) as tres fontes
        somam. Para POSSE vale scan vivo > village.txt > cache/villages,
        porque o cruzamento das 851 entradas em 20/09 deu 38 aldeias que o
        cache jurava barbaras e o mundo dava como de jogador, contra ZERO no
        sentido inverso -- barbara virar aldeia de jogador e o que conquista
        faz, e o cache local nao fica sabendo. Deixar o cache ganhar em posse
        manteria 38 barbaras fantasma elegiveis, que e o incidente da 8.7
        entrando por outra porta e com nobre de verdade. O racional completo
        esta no topo de game/world_villages.py.
        """
        if not reach_from:
            return self.map.villages

        pool = {}

        # 1. Piso de descoberta: o mundo inteiro, recortado pelo alcance.
        world = self._world_box(reach_from, max_radius)
        pool.update(world)

        # 2. cache/villages por cima -- mais campos (tribo, scout, buildings) e
        #    normalmente mais recente em pontos.
        for fname in FileManager.list_directory("cache/villages", ends_with=".json"):
            data = FileManager.load_json_file(f"cache/villages/{fname}")
            if not data:
                continue
            vid = fname.replace(".json", "")
            known = world.get(vid)
            if known and str(data.get("owner", "0")) == "0" and str(known["owner"]) != "0":
                # O cache apodreceu: esta aldeia tem dono. 38 a 0 na medicao,
                # entao isto nao e empate a desempatar, e uma fonte errada.
                data = dict(data)
                data["owner"] = known["owner"]
                data["points"] = known["points"]
            pool[vid] = data

        # 3. Scan vivo desta aldeia por ultimo: e a unica fonte deste ciclo, e
        #    pode legitimamente contradizer as duas de cima nos dois sentidos.
        pool.update(self.map.villages)
        return pool

    def _world_box(self, reach_from, max_radius):
        """
        As aldeias do mundo dentro do alcance de alguma origem, ou {}.

        RECORTE ANTES DA PONTUACAO, e esse e o ponto. O laco de find_target()
        passaria de ~851 para ~130.909 iteracoes por ciclo se o mundo entrasse
        inteiro; a caixa de coordenadas derivada de `max_radius` devolve so a
        vizinhanca util. A caixa e o retangulo que circunscreve os circulos de
        raio `max_radius` em volta das origens -- ela admite os cantos, que
        estao fora do alcance, mas isso nao muda o resultado: o filtro de raio
        real, por distancia de campo, roda logo depois no proprio laco.

        Sem `max_radius` nao ha recorte seguro a fazer, entao a fonte fica de
        fora em vez de entrar inteira.
        """
        if not self.world_villages or not max_radius:
            return {}
        origins = [tuple(loc) for loc in (reach_from or []) if loc and len(loc) == 2]
        if not origins:
            return {}
        try:
            radius = int(max_radius)
        except (TypeError, ValueError):
            return {}
        xs = [int(o[0]) for o in origins]
        ys = [int(o[1]) for o in origins]
        return self.world_villages.in_box(
            min(xs) - radius, max(xs) + radius,
            min(ys) - radius, max(ys) + radius,
        )

    def _get_managed_locations(self):
        """Returns list of (x, y) for all managed villages with cached coords."""
        locations = []
        for fname in FileManager.list_directory("cache/managed", ends_with=".json"):
            data = FileManager.load_json_file(f"cache/managed/{fname}")
            if data and data.get("x") and data.get("y"):
                locations.append((data["x"], data["y"]))
        return locations

    def _get_manual_target(self):
        """
        Feature 15: checks cache/conquest/*.json for a target queued manually
        via the webmanager (/conquest), status == "manual". Processed
        oldest-first (FIFO, by "queued_at"). Any village whose noble train
        becomes ready will pick up the oldest pending manual target here,
        before find_target() ever runs its automatic scoring loop.

        Re-validates barbarian ownership against the shared cache/villages/
        snapshot (populated by any managed village's map fetch) before
        handing the target out -- if it's no longer a barbarian (someone
        else conquered it, or it was never barbarian to begin with, e.g. a
        bad manual entry), the queue entry is marked "invalid" instead of
        being retried forever.

        Returns target_id or None.
        """
        pending = []
        for fname in FileManager.list_directory("cache/conquest", ends_with=".json"):
            data = FileManager.load_json_file(f"cache/conquest/{fname}")
            if data and data.get("status") == "manual":
                target_id = fname.replace(".json", "")
                pending.append((data.get("queued_at", 0), target_id, data))

        pending.sort(key=lambda item: item[0])

        for _, target_id, data in pending:
            village_data = FileManager.load_json_file(f"cache/villages/{target_id}.json")

            # Feature 35: o alvo pode ter sido reservado por outra pessoa
            # DEPOIS de entrar na fila -- a fila e um estado parado e o quadro
            # da tribo nao e. E o 6o padrao do CLAUDE.md: reconferir a premissa
            # no momento de agir, nao no de decidir.
            #
            # Vira "blocked" e nao "invalid" porque a causa e externa e
            # reversivel (a reserva expira em 3 dias no br143, e pode ser
            # solta antes): "invalid" e para alvo que nunca vai servir.
            blocked = self._claim_block_reason(
                target_id, (village_data or {}).get("location")
            )
            if blocked:
                reason, detail = blocked
                who = detail.get("reserved_by_name") or detail.get("matched")
                self.logger.warning(
                    "Conquest: alvo manual %s esta reservado (%s: %s) -- "
                    "tirando da fila sem enviar nada", target_id, reason, who
                )
                ConquestCache.set(target_id, {
                    **data, **detail,
                    "status": "blocked",
                    "blocked_reason": reason,
                    "blocked_at": int(time.time()),
                })
                continue

            if village_data and str(village_data.get("owner", "0")) != "0":
                self.logger.warning(
                    "Conquest: manual target %s is no longer a barbarian village "
                    "(owner=%s) -- cancelling manual queue entry",
                    target_id, village_data.get("owner")
                )
                ConquestCache.set(target_id, {
                    **data,
                    "status": "invalid",
                    "invalid_reason": "Não é mais uma aldeia bárbara",
                })
                continue
            return target_id
        return None

    def _note_failed_claim(self, target_id):
        """
        Registra que uma aldeia reivindicou um alvo MANUAL e nao conseguiu
        despachar o trem. Depois de MANUAL_CLAIM_ATTEMPTS tentativas o registro
        vira "invalid" e sai da fila.

        Isto existe por causa de como `find_target()` trata alvo manual: ele e
        devolvido antes de tudo e sem condicao nenhuma, entao enquanto houver um
        unico registro "manual" na fila NENHUMA aldeia da conta faz selecao
        automatica. Um alvo que nunca consegue ser atacado -- coordenada
        irrecuperavel, o jogo recusando o envio, a aldeia que o pegou nao
        alcancando -- congelava a Feature 8 inteira, e o unico sinal era um
        `attack 1/4 failed` por ciclo. Sem contador nao ha saida desse estado a
        nao ser alguem abrir o dashboard e perceber.

        Falha aqui NAO e a mesma coisa que "escolta insuficiente": o chamador so
        conta o que passou pelo gate de escolta e chegou a tentar enviar. E
        nobre em voo tambem nao conta -- `_send_train` devolve False quando o
        `_noble_flight_guard` segura o envio, e isso e o sistema funcionando,
        nao o alvo sendo ruim. Confundir os dois invalidaria justamente o alvo
        que esta dando certo.
        """
        data = ConquestCache.get(target_id)
        if not data or data.get("status") != "manual":
            return
        if ConquestCache.nobles_in_flight(data):
            return

        attempts = int(data.get("failed_claims", 0)) + 1
        data["failed_claims"] = attempts
        data["last_failed_claim_by"] = self.village_id
        if attempts >= self.MANUAL_CLAIM_ATTEMPTS:
            data["status"] = "invalid"
            data["invalid_reason"] = (
                "O trem nao saiu em %d tentativas (ultima pela aldeia %s). "
                "Alvo tirado da fila para nao travar a conquista automatica."
                % (attempts, self.village_id)
            )
            self.logger.warning(
                "Conquest: alvo manual %s invalidado apos %d tentativas sem "
                "envio -- a selecao automatica volta a rodar",
                target_id, attempts
            )
        else:
            self.logger.warning(
                "Conquest: alvo manual %s continua na fila, mas o envio falhou "
                "%d/%d vezes", target_id, attempts, self.MANUAL_CLAIM_ATTEMPTS
            )
        ConquestCache.set(target_id, data)

    def _get_village_meta(self, target_id):
        """
        Returns village metadata dict (name/points/location/owner) for
        target_id, preferring this village's own live map scan
        (self.map.villages) and falling back to the shared cache/villages/
        snapshot. The fallback matters for Feature 15: a manually queued
        target may lie outside the map region this particular village
        fetched this cycle, but another managed village may have already
        cached it.
        """
        village = self.map.villages.get(target_id)
        if village:
            return village
        return FileManager.load_json_file(f"cache/villages/{target_id}.json") or {}

    # ------------------------------------------------------------------
    # Train dispatch
    # ------------------------------------------------------------------

    def _arrival_of_last_attack(self):
        """
        Timestamp de chegada do ataque que o AttackManager acabou de enviar,
        derivado da duracao que o proprio jogo devolveu na tela de
        confirmacao. None quando essa duracao nao veio -- ver
        ConquestCache.nobles_in_flight() para o que um None significa.

        Nao recalculamos distancia x velocidade aqui de proposito: o servidor
        ja aplica velocidade de mundo, bonus e arredondamento, e duplicar essa
        conta seria uma segunda fonte de verdade para divergir da primeira.
        """
        duration = getattr(self._attack_manager, "last_attack_duration", None)
        if not duration:
            self.logger.warning(
                "Conquest: o jogo nao devolveu a duracao do ataque -- registro "
                "o nobre como em voo por tempo indeterminado"
            )
            return None
        return int(time.time() + duration)

    def _noble_flight_guard(self, target_id, conquest_data=None):
        """
        True se ja existe nobre nosso a caminho de target_id -- nesse caso
        nenhum outro nobre pode sair para la, ponto.

        A regra e por alvo e independe de o trem anterior ter dado certo. Se
        deu errado, so o relatorio dira quanta lealdade sobrou, e ele so
        existe depois do pouso. Se deu certo, a escolta do nobre vencedor vira
        guarnicao da aldeia nova, e o nobre seguinte entra matando os
        proprios companheiros (2026-08-12: 421 defensores e 106 atacantes
        mortos, todos nossos, alem da moeda da autoconquista).
        """
        if conquest_data is None:
            conquest_data = ConquestCache.get(target_id)
        pending = ConquestCache.nobles_in_flight(conquest_data)
        if not pending:
            return False

        first = pending[0]
        if first == float("inf"):
            self.logger.info(
                "Conquest: %d nobre(s) a caminho de %s com chegada desconhecida "
                "-- nao envio mais nenhum ate confirmar a posse da aldeia "
                "(limpe pelo dashboard se souber que nao ha nada voando)",
                len(pending), target_id
            )
        else:
            self.logger.info(
                "Conquest: %d nobre(s) ja a caminho de %s, proximo pouso em "
                "%.1f min -- nao envio mais nenhum antes disso",
                len(pending), target_id, (first - time.time()) / 60
            )
        return True


    def _available_troops(self):
        """
        Feature 27: troops in this village genuinely free for the barbarian
        conquest -- total, minus EXCLUDED_UNITS, minus every reservation owned
        by *another* system (today: the PvP conquest's "pvp:{target_id}" keys,
        set by PvpConquestManager._reserve_troops).

        Before this, _build_escort/_calculate_needed_escort read
        troopmanager.troops raw, so the barbarian train could commit troops the
        PvP conquest had already earmarked for a scheduled clear or noble
        escort -- the same double-booking class of bug as the 38409 incident
        (docs/backend.md, 2026-08-07), but across two systems instead of
        within one.

        Our own "barbarian_conquest" key is deliberately NOT subtracted. run()
        sets it while the escort is still too small, precisely to stop
        farm/gather from spending the troops being accumulated. Subtracting it
        here would make this manager block itself: reserve set -> next cycle
        sees less available -> escort still looks insufficient -> reserve never
        released, even once the real troop count would suffice.
        """
        reserve = self.troopmanager.total_conquest_reserve(
            exclude_owner="barbarian_conquest"
        ) if hasattr(self.troopmanager, "total_conquest_reserve") else {}

        available = {}
        for unit, qty in self.troopmanager.troops.items():
            if unit in self.EXCLUDED_UNITS:
                continue
            free = int(qty) - reserve.get(unit, 0)
            if free > 0:
                available[unit] = free
        return available

    def _available_nobles(self):
        """
        Feature 27: nobles in this village not already committed to another
        conquest system. PvpConquestManager reserves one snob per scheduled
        noble attack (game/pvp_conquest.py, troops["snob"] = 1 -> reserved
        under "pvp:{target_id}"), and those nobles may sit at home for hours
        while Hunter waits to synchronise arrival times.

        Reading troops["snob"] raw counted them as available, so the barbarian
        conquest could decide it had a full train and fire, consuming nobles a
        scheduled PvP train was relying on. Nobles are the most expensive unit
        in the game, which makes this the costliest instance of the
        double-booking bug this feature exists to fix.
        """
        reserve = self.troopmanager.total_conquest_reserve(
            exclude_owner="barbarian_conquest"
        ) if hasattr(self.troopmanager, "total_conquest_reserve") else {}
        total = int(self.troopmanager.troops.get("snob", 0))
        return max(0, total - reserve.get("snob", 0))

    def _calculate_needed_escort(self, cfg):
        """
        Feature 8: Calculates how many troops need to be kept home (reserved)
        so that when they accumulate, _build_escort() will pass.

        Target: min_escort_total troops per noble × TRAIN_SIZE nobles,
        divided by escort_ratio (since _build_escort commits ratio% of available).

        Example: min_escort_total=50, TRAIN_SIZE=4, escort_ratio=0.25
          → need 50 × 4 = 200 committed → need 200 / 0.25 = 800 total at home
          → spread evenly across available unit types

        Returns {unit: qty_to_reserve} or {} if no troops present at all, or
        if reserving would do more harm than good (see P2-22 below).

        P2-22: this used to reserve `min(per_unit, free)` per type, and the
        min() meant any type with fewer troops than the even split got 100%
        of it reserved. Since _get_farmable_troops() and do_gather() both
        subtract the reserve, that stopped farm and gather outright -- with
        no time limit, and the reserve lives in TroopManager, which persists
        across cycles, so it stayed stuck until the escort finally closed.
        Worse, it is self-defeating: farming is what funds the recruitment
        that would close the escort gap, so freezing the army to reach an
        escort target actively delays reaching it.

        Two gates now bound that:

        1. Only reserve once the goal is realistically in reach
           (escort_reserve_min_progress, default 0.5 = half of needed_total
           already home). Far from the target, the reserve buys nothing --
           it can't conjure troops, it only stops the farm income that pays
           for them -- so it's skipped entirely.
        2. Never reserve more than escort_reserve_max_pct (default 0.8) of
           any single type, so farm/gather always keep a working residual
           instead of being starved to zero on some unit the template needs.

        Together: small army -> no reserve at all (gate 1); large army ->
        the 20% left over is big enough in absolute terms to keep farming
        (gate 2). Both are opt-out-able via config for anyone who prefers
        the old all-in behaviour (max_pct 1.0, min_progress 0.0).
        """
        # Mesma fracao do _build_escort, senao a reserva mira um alvo que o
        # envio nao usa: reservar para 50% e mandar 15% prende tropa que nunca
        # vai sair, e reservar para 15% e exigir 50% nunca fecha a escolta.
        ratio = self._escort_ratio(cfg)
        min_total = cfg.get("min_escort_total", 50)
        max_pct = cfg.get("escort_reserve_max_pct", 0.8)
        min_progress = cfg.get("escort_reserve_min_progress", 0.5)

        # Total troops needed at home to satisfy escort after ratio+split
        # per_attack = (available × ratio) // TRAIN_SIZE ≥ min_total
        # → available × ratio ≥ min_total × TRAIN_SIZE
        # → available ≥ (min_total × TRAIN_SIZE) / ratio
        needed_total = math.ceil((min_total * self.TRAIN_SIZE) / ratio) if ratio > 0 else 0

        # Net of other systems' reservations (Feature 27): reserving troops the
        # PvP conquest already claimed would make the two reservations sum to
        # more than the village actually has, starving farm/gather of troops
        # that only exist on paper.
        available = self._available_troops()

        if not available:
            return {}

        # P2-22, gate 1: is the escort target even in reach?
        have_total = sum(available.values())
        if needed_total > 0 and have_total < needed_total * min_progress:
            self.logger.info(
                "Conquest: %d/%d troops toward escort target — too far off to "
                "reserve (below %.0f%%), leaving farm and gather free",
                have_total, needed_total, min_progress * 100
            )
            return {}

        # Distribute the needed total evenly across available unit types
        per_unit = math.ceil(needed_total / len(available))
        reserve = {}
        for unit, free in available.items():
            # P2-22, gate 2: cap per type so a residual always stays farmable.
            # Only reserve up to what's actually free (no phantom reserve).
            qty = min(per_unit, int(free * max_pct))
            if qty > 0:
                reserve[unit] = qty

        return reserve

    @staticmethod
    def _escort_ratio(cfg):
        """
        Fracao da tropa de casa que vai de escolta -- SO para barbaro.

        `conquest.escort_ratio` parece pertencer a este modulo pelo nome da
        secao, mas quem tambem o le e o PvpConquestManager
        (game/pvp_conquest.py:588 e :905, `config["conquest"]["escort_ratio"]`).
        As duas conquistas tem riscos opostos:

          - barbara nao tem defesa nem dono, entao escolta grande e quase toda
            desperdicio: a tropa fica fora de casa a viagem inteira, ida e
            volta, sem farmar;
          - contra JOGADOR a escolta e o que impede o defensor de snipar um
            comando isolado do trem. Afina-la e perder o nobre e a operacao.

        Baixar `escort_ratio` para economizar contra barbaro teria afinado o
        trem de PvP junto, em silencio. Por isso a chave nova
        `barbarian_escort_ratio` -- ausente, cai no valor antigo e nada muda
        para ninguem.
        """
        ratio = cfg.get("barbarian_escort_ratio")
        if ratio is None:
            ratio = cfg.get("escort_ratio", 0.5)
        return ratio

    def _build_escort(self, cfg):
        """
        Calculates per-attack escort by dividing available troops across
        TRAIN_SIZE attacks using barbarian_escort_ratio (see _escort_ratio).
        Returns dict of {unit: qty_per_attack} or None if below minimum.

        Accepts any combat troop type (spear, sword, archer, axe, light, heavy, ram).
        spy, knight and snob are excluded (see EXCLUDED_UNITS), as are troops
        reserved by another conquest system (see _available_troops).
        Works for both offensive and defensive village profiles.

        Minimum escort is validated two ways:
        - min_escort: per-unit minimums (optional, e.g. {"heavy": 20})
        - min_escort_total: minimum combined troops per noble attack (default: 50)
        """
        ratio = self._escort_ratio(cfg)
        min_escort = cfg.get("min_escort", {})
        min_escort_total = cfg.get("min_escort_total", 50)

        # Feature 27: net of troops another system already reserved, so the
        # barbarian train never commits troops a scheduled PvP clear/escort is
        # counting on.
        available = self._available_troops()

        # Total troops to commit across all 4 attacks
        committed = {
            unit: int(qty * ratio)
            for unit, qty in available.items()
        }

        # Per-attack share (floor division, remainder stays home)
        per_attack = {
            unit: qty // self.TRAIN_SIZE
            for unit, qty in committed.items()
            if qty // self.TRAIN_SIZE > 0
        }

        if not per_attack:
            self.logger.warning("Conquest: no troops available for escort after ratio split")
            return None

        # Validate per-unit minimums if configured
        for unit, min_qty in min_escort.items():
            if per_attack.get(unit, 0) < min_qty:
                self.logger.warning(
                    "Conquest: escort below minimum for %s (%d < %d)",
                    unit, per_attack.get(unit, 0), min_qty
                )
                return None

        # Validate total escort per noble attack regardless of troop type
        total_per_attack = sum(per_attack.values())
        if total_per_attack < min_escort_total:
            self.logger.warning(
                "Conquest: escort total %d below min_escort_total %d per noble — "
                "waiting for more troops before sending train",
                total_per_attack, min_escort_total
            )
            return None

        self.logger.info(
            "Conquest: escort per noble = %s (total: %d)",
            per_attack, total_per_attack
        )
        return per_attack

    # ------------------------------------------------------------------
    # Extra noble logic (loyalty regeneration)
    # ------------------------------------------------------------------

    def _target_is_mine(self, target_id):
        """
        Proof-of-conquest: checks if target_id now appears in cache/villages/
        with owner matching our player_id.
        Returns True if confirmed ours, False otherwise.

        Bugfix (2026-08-07): used to read self.wrapper.player_id /
        self.wrapper.game_state, but WebWrapper never actually sets either --
        those attributes only exist on per-village objects (Village.game_data,
        BuildingManager.game_state), never on the shared session wrapper. The
        hasattr() check was always False and the game_state fallback always
        raised AttributeError, so this always returned False, silently. Fixed
        by reading the owner id from cache/villages/{self.village_id}.json --
        self.village_id is always one of our own managed villages, so its
        cached "owner" field IS our player_id, no wrapper plumbing needed.
        Mirrors the equivalent fix in
        PvpConquestManager._own_player_id() (game/pvp_conquest.py).
        """
        data = FileManager.load_json_file(f"cache/villages/{target_id}.json")
        if not data:
            return False
        own_data = FileManager.load_json_file(f"cache/villages/{self.village_id}.json")
        if not own_data:
            return False
        player_id = str(own_data.get("owner", "0"))
        if player_id == "0":
            return False
        owner = str(data.get("owner", "0"))
        return owner == player_id and owner != "0"

    def _target_taken_by_other(self, target_id):
        """
        Id do jogador que conquistou o alvo, se ele deixou de ser barbaro e
        nao e nosso. None quando ainda e barbaro, quando e nosso, ou quando
        nao da para saber.

        Le a mesma fonte que _target_is_mine (cache/villages/, alimentado pelo
        scan de mapa de qualquer aldeia gerenciada). Ausencia de dado devolve
        None de proposito: sem informacao nao se encerra alvo nenhum.
        """
        data = FileManager.load_json_file(f"cache/villages/{target_id}.json")
        if not data:
            return None
        owner = str(data.get("owner", "0"))
        if owner == "0":
            return None  # ainda barbara
        own_data = FileManager.load_json_file(f"cache/villages/{self.village_id}.json")
        player_id = str(own_data.get("owner", "0")) if own_data else "0"
        if owner == player_id:
            return None  # e nossa -- _target_is_mine trata
        return owner

    def _get_real_loyalty(self, target_id):
        """
        Tries to extract real loyalty from the most recent noble attack report
        against target_id. Returns float loyalty value or None if not available.

        Reports with extra["loyalty_after"] are populated by reports.py
        when it processes noble (snob) attack reports.
        """
        if not self.repman:
            return None
        best_ts = 0
        best_loyalty = None
        for rep_id, entry in self.repman.last_reports.items():
            if str(entry.get("dest")) != str(target_id):
                continue
            extra = entry.get("extra", {})
            # Only consider reports that contain snob and have loyalty data
            if "loyalty_after" not in extra:
                continue
            units_sent = extra.get("units_sent", {})
            if "snob" not in units_sent:
                continue
            when = extra.get("when", 0)
            if when > best_ts:
                best_ts = when
                best_loyalty = float(extra["loyalty_after"])
        return best_loyalty

    def _handle_existing(self, conquest_data, cfg):
        """
        Called when this village already has a conquest in progress.

        Priority order for loyalty source:
        1. Village ownership check (cache/villages/) — definitive proof
        2. Alvo conquistado por outro jogador — encerra o alvo
        3. Nobre ainda no ar — nao se estima nada antes do pouso
        4. Real loyalty from noble attack report (reports.py extracts it)
        5. Mathematical estimate (fallback)
        """
        target_id = conquest_data["target_id"]
        regen = cfg.get("loyalty_regen_per_hour", 1)
        # Piso da faixa, mesma razao do _send_train: a estimativa vira um
        # limite superior da lealdade que sobrou, em vez de um numero que se
        # acredita exato.
        loyalty_drop = self._drop_min

        # --- Priority 1: ownership check (prova dos 9) ---
        # Precisa continuar sendo o primeiro, *antes* da trava de nobre em
        # voo: quando a chegada e desconhecida (ETA null) a trava e
        # permanente, e esta e a unica saida automatica dela. Com a ordem
        # invertida o alvo ficaria preso para sempre mesmo depois de
        # conquistado, e a unica saida seria limpar na mao pelo dashboard.
        if self._target_is_mine(target_id):
            self.logger.info(
                "Conquest: target %s confirmed as ours via village cache — marking conquered",
                target_id
            )
            ConquestCache.set(target_id, {
                **conquest_data,
                "status": "conquered",
                "confirmed_by": "village_cache",
            })
            self.wrapper.reporter.report(
                self.village_id, "TWB_CONQUEST",
                f"Conquest CONFIRMED: {target_id} is now ours."
            )
            return False

        # --- Priority 2: alguem se adiantou ---
        # A barbara pode ter sido conquistada por OUTRO jogador enquanto nosso
        # trem voava (~4h de voo numa barbara de 400-1000 pontos, que e alvo
        # cobicado por todo mundo). Dai em diante nada abaixo faz sentido:
        #
        #   - a lealdade dele reiniciou em 25 e sobe do zero da conquista; a
        #     nossa ultima leitura ("Descida 32 para 11") virou numero morto,
        #     sem relacao nenhuma com o estado atual da aldeia;
        #   - e continuar mandando nobre deixaria de ser limpeza de barbaro e
        #     viraria conquista de aldeia de jogador, sem passar por nada do
        #     PvpConquestManager (Feature 13), que existe para isso e e
        #     semi-manual de proposito -- com simulador e aprovacao do alvo.
        #     Declararia guerra a alguem como efeito colateral.
        #
        # find_target() ja filtra por dono na selecao e _get_manual_target()
        # revalida antes de entregar o alvo; era este terceiro caminho, o da
        # conquista ja em andamento, que nunca reconferia.
        #
        # Nao desfaz nada: nobre que ja saiu nao volta. So para de comprometer
        # nobres novos, e libera a aldeia para escolher outro alvo.
        taken_by = self._target_taken_by_other(target_id)
        if taken_by:
            self.logger.warning(
                "Conquest: alvo %s deixou de ser barbaro (conquistado pelo "
                "jogador %s) -- encerrando. Nobres ja em rota nao voltam.",
                target_id, taken_by
            )
            ConquestCache.set(target_id, {
                **conquest_data,
                "status": "lost",
                "lost_to_owner": taken_by,
            })
            self.wrapper.reporter.report(
                self.village_id, "TWB_CONQUEST",
                f"Alvo {target_id} perdido: conquistado pelo jogador {taken_by}"
            )
            return False

        # --- Priority 2.5: alguem da tribo reservou o alvo ---
        # Feature 35. O trem leva ~4h e a reserva pode nascer nesse intervalo:
        # reconferir no momento de agir, nao no de decidir (6o padrao).
        #
        # Deliberadamente NAO consulta `_may_start_new_conquest()`: falha de
        # LEITURA nao encerra conquista em andamento, porque abortar por nao
        # conseguir abrir uma pagina joga fora tropa real que ja esta voando.
        # So uma reserva efetivamente LIDA barra aqui.
        #
        # Nao desfaz nada -- nobre que ja saiu nao volta --, exatamente como a
        # Priority 2 acima. O efeito e parar de comprometer nobres novos e
        # liberar a aldeia. A tropa ainda reservada para este alvo e solta por
        # `BarbarianTrainPlanner._release_orphan_reserves()`, que varre toda
        # reserva `barb_train:*` cujo alvo saiu de "train_scheduled" -- e a
        # armadilha do P2-22, e o mecanismo que ja existe para ela.
        blocked = self._claim_block_reason(target_id, self._get_village_meta(target_id).get("location"))
        if blocked:
            reason, detail = blocked
            who = detail.get("reserved_by_name") or detail.get("matched")
            self.logger.warning(
                "Conquest: alvo %s em andamento foi reservado por %s (%s) -- "
                "encerrando. Nobres ja em rota nao voltam, mas nenhum novo sai.",
                target_id, who, reason
            )
            ConquestCache.set(target_id, {
                **conquest_data, **detail,
                "status": "blocked",
                "blocked_reason": reason,
                "blocked_at": int(time.time()),
            })
            self.wrapper.reporter.report(
                self.village_id, "TWB_CONQUEST",
                f"Alvo {target_id} abandonado: reservado por {who}"
            )
            return False

        # --- Priority 3: nobre em voo ---
        # A aldeia ainda nao e nossa e ha nobre a caminho: nao ha decisao a
        # tomar. Nem enviar outro (o que esta no ar pode resolver sozinho, e
        # se ele conquistar a escolta dele vira guarnicao — o proximo nobre
        # entraria matando os proprios), nem marcar "complete" (a conquista
        # ainda nao aconteceu). So esperar o pouso.
        if self._noble_flight_guard(target_id, conquest_data):
            return False

        # --- Priority 4: real loyalty from report ---
        real_loyalty = self._get_real_loyalty(target_id)
        last_hit = conquest_data.get("last_hit_timestamp", 0)

        if real_loyalty is not None and real_loyalty <= 0:
            # Lealdade <= 0 no relatorio significa que a aldeia MUDOU DE DONO
            # naquele ataque -- os relatorios reais trazem "Descida 18 para -7"
            # e "25 para -8". Aplicar regeneracao em cima disso e sem sentido:
            # a lealdade de uma aldeia recem-conquistada reinicia (25 no br143,
            # medido no relatorio das 00:00:59 de 2026-08-13) e pertence ao
            # novo dono; o numero negativo nao e um saldo que sobe com o tempo.
            # Sem esta saida, -7 mais algumas horas de regen viraria um valor
            # positivo e o bot mandaria nobre numa aldeia ja conquistada --
            # que, se a conquista foi nossa e o cache de aldeias estiver
            # atrasado, e exatamente a autoconquista de novo.
            # Isto tambem e prova, nao estimativa: _get_real_loyalty() so le
            # relatorios dos NOSSOS ataques (dest == alvo e snob entre as
            # unidades enviadas), e a Priority 2 acima ja teria encerrado o
            # alvo se outro jogador fosse o dono. Um relatorio nosso dizendo
            # que a lealdade foi a <= 0 significa que foi o nosso nobre que
            # conquistou -- so o cache de aldeias ainda nao refletiu.
            self.logger.info(
                "Conquest: target %s — nosso relatorio marca lealdade %.0f (<= 0): "
                "conquistada pelo nosso nobre, encerrando o alvo",
                target_id, real_loyalty
            )
            ConquestCache.set(target_id, {
                **conquest_data,
                "status": "conquered",
                "confirmed_by": "noble_report",
            })
            return False

        if real_loyalty is not None:
            # Apply regen since that report's timestamp
            hours_since_report = (time.time() - last_hit) / 3600
            current_loyalty = min(100.0, real_loyalty + (hours_since_report * regen))
            loyalty_source = "report"
            self.logger.info(
                "Conquest: target %s — real loyalty from report: %.1f, "
                "estimated now: %.1f (%.1fh regen)",
                target_id, real_loyalty, current_loyalty, hours_since_report
            )
        else:
            # --- Priority 5: mathematical estimate ---
            loyalty_after = conquest_data.get("loyalty_after_train", 0)
            hours_elapsed = (time.time() - last_hit) / 3600
            current_loyalty = min(100.0, loyalty_after + (hours_elapsed * regen))
            loyalty_source = "estimate"
            self.logger.info(
                "Conquest: target %s — no report data, using estimate: %.1f "
                "(%.1fh elapsed)",
                target_id, current_loyalty, hours_elapsed
            )

        if current_loyalty <= 0:
            # ATENCAO: isto NAO e prova de nada. As duas saidas acima
            # ("conquered") tem evidencia -- o cache de aldeias ou o nosso
            # proprio relatorio de nobre. Esta aqui e so aritmetica: lealdade
            # inicial presumida, menos 25 por nobre presumidos, mais regen. Foi
            # essa conta que disse "0" quando o servidor dizia 11 no incidente
            # da Barbara #40314, e foi o rotulo unico "complete" que pintou
            # aquilo de verde no dashboard como se fosse conquista consumada.
            #
            # O bot para de mandar nobre aqui de proposito: se a estimativa
            # estiver certa, mandar mais e autoconquista; se estiver errada,
            # quem decide o proximo passo e uma pessoa olhando a tela. Por isso
            # o status e visivelmente distinto e nao verde.
            self.logger.warning(
                "Conquest: target %s — estimativa (nao confirmada) chegou a %.1f. "
                "Encerrando SEM confirmacao de posse: verifique no jogo se a "
                "aldeia e sua. Nenhum relatorio de nobre com lealdade real foi "
                "encontrado para este alvo.",
                target_id, current_loyalty
            )
            ConquestCache.set(target_id, {
                **conquest_data,
                "status": "assumed_done",
                "assumed_reason": "estimativa de lealdade chegou a zero sem confirmacao",
            })
            return False

        self.logger.info(
            "Conquest: target %s loyalty = %.1f — sending extra noble(s)",
            target_id, current_loyalty
        )

        available_nobles = self._available_nobles()
        if available_nobles < 1:
            self.logger.info("Conquest: no noble available for extra hit, waiting")
            return False

        escort_per_attack = self._build_escort(cfg)
        if escort_per_attack is None:
            return False

        troops = dict(escort_per_attack)
        troops["snob"] = 1
        result = self._attack_manager.attack(target_id, troops=troops)

        if result and result != "forced_peace":
            new_loyalty = max(0.0, current_loyalty - loyalty_drop)
            arrival = self._arrival_of_last_attack()
            ConquestCache.set(target_id, {
                **conquest_data,
                # .get("hits", ...) e fallback p/ arquivos antigos gravados
                # antes da correção do mismatch de chave (ver _send_train).
                "hits_done": conquest_data.get("hits_done", conquest_data.get("hits", 0)) + 1,
                "hits_needed": conquest_data.get("hits_needed", self.TRAIN_SIZE),
                "loyalty_after_train": new_loyalty,
                "loyalty_source": loyalty_source,
                # Só este nobre: chegamos aqui através de _noble_flight_guard,
                # que garante que todos os anteriores já pousaram.
                "noble_arrivals": [arrival],
                "last_hit_timestamp": arrival or int(time.time()),
                # Mesmos parametros do _send_train, para o dashboard refazer a
                # conta identica em vez de cair nos defaults dele.
                "loyalty_drop_per_noble": self._drop_min,
                "loyalty_drop_range": [self._drop_min, self._drop_max],
                "loyalty_regen_per_hour": regen,
                # Nunca "complete" aqui. O nobre acabou de sair e leva horas
                # para pousar; marcar a conquista como resolvida no envio foi
                # o que pintou a aldeia de verde no dashboard às 20:19:37 de
                # 2026-08-12 com o nobre ainda no mapa, e o que fez o alvo
                # deixar de ser rastreado. Quem fecha é _target_is_mine() ou a
                # lealdade zerada *depois* do pouso, no topo deste método.
                "status": "extra_pending",
            })
            self.logger.info(
                "Conquest: extra noble sent to %s, estimated loyalty now %.1f "
                "(pouso em %s)",
                target_id, new_loyalty,
                datetime.fromtimestamp(arrival).strftime("%H:%M:%S")
                if arrival else "horário desconhecido"
            )
            return True

        return False

    def _get_my_conquest(self):
        """
        Returns active conquest data reserved by this village, or None.
        """
        for fname in FileManager.list_directory("cache/conquest", ends_with=".json"):
            target_id = fname.replace(".json", "")
            data = FileManager.load_json_file(f"cache/conquest/{fname}")
            if (
                data
                and data.get("reserved_by") == self.village_id
                and data.get("status") in ("train_sent", "extra_pending")
            ):
                data["target_id"] = target_id
                return data
        return None
