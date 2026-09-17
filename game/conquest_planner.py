"""
Planejador de trem de nobres barbaro, multi-origem (Feature 8, fase 2).

O QUE MUDA EM RELACAO AO MODELO ANTERIOR
----------------------------------------
Ate aqui `ConquestManager` era instanciado uma vez POR ALDEIA e exigia os 4
nobres do trem na MESMA aldeia (`attack.py`, `run()` -> `_available_nobles() <
TRAIN_SIZE`). Medido na conta em 16/09/2026: 5 nobres no imperio, distribuidos
3 na BBM 001 e 2 na BBM 011, e ZERO aldeias com 4 -- ou seja, nobres suficientes
para um trem inteiro e nenhum trem possivel. O modelo antigo fazia o imperio
esperar uma aldeia poupar 4 enquanto as outras seguravam nobre parado.

Este planejador roda UMA VEZ POR CICLO, enxerga todas as aldeias gerenciadas e
monta o trem com os nobres onde eles estiverem.

POR QUE A SINCRONIZACAO NAO E OPCIONAL
--------------------------------------
Nobres de aldeias diferentes estao a distancias diferentes do alvo, entao
despachar todos "agora" faz cada um pousar numa hora. No br143 a lealdade
regenera 1/hora (valor publicado em /page/settings, ver CLAUDE.md), entao um
trem esparramado em 3h devolve parte do que derrubou. Pior: cada nobre isolado
pode ser o ultimo a bater, deixando a barbara viva com lealdade baixa -- que e
um presente para quem estiver por perto.

A alternativa seria mandar todos juntos e aceitar um limiar de "chegam perto o
bastante". Limiar inventado neste repositorio ja custou caro (decimo oitavo
padrao do CLAUDE.md: reusar 30 min de evacuacao para apoio que leva horas
viajando). Aqui nao ha constante para calibrar: o Hunter ja resolve isso
perguntando ao PROPRIO SERVIDOR quanto dura cada viagem e recuando o horario de
saida a partir de uma chegada comum.

O BATCH SAI DE GRACA
--------------------
`Hunter.run()` agrupa comandos de mesma origem, mesmo alvo e mesmo `send_time`
num unico POST usando a forma nativa `train[2..N]` do jogo (hunter.py, Feature
26 -- dois comandos reais medidos pousando com 115 ms de diferenca). Como todos
os nobres de uma mesma aldeia aqui tem composicao e chegada identicas, eles
recebem o mesmo `send_time` e o Hunter os funde sozinho. Nao ha nada a fazer
neste modulo para obter o batch alem de nao estragar essa igualdade.

DIVISAO DE RESPONSABILIDADE
---------------------------
Este modulo so MONTA E DESPACHA. Todo o acompanhamento depois do envio --
lealdade real do relatorio, nobre extra, confirmacao de posse, alvo perdido
para outro jogador -- continua em `ConquestManager._handle_existing()`, que ja
funciona e nao tem por que ser reescrito. A fronteira entre os dois e o arquivo
`cache/conquest/{target}.json`.
"""

import datetime
import logging
import time

from core.filemanager import FileManager
from game.attack import ConquestCache, ConquestManager
from game.hunter import Hunter

logger = logging.getLogger("ConquestPlanner")

DATETIME_FMT = "%Y-%m-%d %H:%M:%S"


class BarbarianTrainPlanner:
    """
    Um por ciclo, construido em twb.py depois do laco de aldeias.

    `villages` e o mesmo dict {village_id: Village} que PvpConquestManager e
    Hunter ja recebem.
    """

    # Chave de reserva deste sistema no TroopManager. Diferente da
    # "barbarian_conquest" usada pelo ConquestManager por aldeia de proposito:
    # sao dois donos distintos e o Feature 27 soma reservas por dono.
    RESERVE_PREFIX = "barb_train"

    # Margem sobre a viagem mais longa. A chegada comum e
    # `agora + maior_duracao + margem`: sem folga, a origem mais distante teria
    # send_time no passado no instante em que o plano e gravado e o Hunter
    # recusaria o comando (ele e estrito com departure vencida, e com razao).
    # 10 min cobre o intervalo entre o planejamento e o Hunter ser servido --
    # medido em campo: os ciclos ficam entre 10 e 35 min, e o twb.py encurta o
    # sono quando ha send_time proximo (`nearest_send_time`).
    ARRIVAL_MARGIN_SECONDS = 600

    def __init__(self, wrapper, villages, config, hunter=None):
        self.wrapper = wrapper
        self.villages = villages or {}
        self.config = config or {}
        self.logger = logger
        self._hunter = hunter

    # ------------------------------------------------------------------
    # Entrada
    # ------------------------------------------------------------------

    def run(self):
        """
        Monta e agenda no maximo um trem barbaro por ciclo.
        Devolve o target_id agendado, ou None.
        """
        cfg = self.config.get("conquest", {})
        if not cfg.get("enabled", False):
            return None

        # Antes do portao do Hunter de proposito: as duas rotinas abaixo so
        # LEEM o cache dele e desfazem estado pendente. Se ficassem depois,
        # desligar `hunter.enabled` com um trem ja agendado deixaria esse trem
        # em "train_scheduled" para sempre -- e, como esse status reserva o
        # alvo, a conquista do imperio inteiro travava junto, sem log.
        self._promote_scheduled_trains()
        self._release_orphan_reserves()

        if not self.config.get("hunter", {}).get("enabled", False):
            self.logger.warning(
                "Conquest: trem multi-origem exige hunter.enabled -- e o Hunter "
                "que sincroniza a chegada e funde os comandos de mesma origem. "
                "Sem ele o planejador nao agenda nada"
            )
            return None

        # Invariante: um trem barbaro por vez no imperio inteiro.
        active = ConquestCache.active_conquests()
        if active:
            self.logger.info(
                "Conquest: ja existe conquista barbara em andamento (%s) -- "
                "o planejador nao monta outra ate ela resolver",
                ", ".join(sorted(active))
            )
            return None

        sources = self._noble_sources()
        total = sum(qty for _vid, qty in sources)
        if total < ConquestManager.TRAIN_SIZE:
            self.logger.info(
                "Conquest: %d/%d nobres no imperio inteiro (%s) -- aguardando",
                total, ConquestManager.TRAIN_SIZE,
                ", ".join("%s:%d" % (vid, qty) for vid, qty in sources) or "nenhum"
            )
            return None

        target_id, target_meta = self._pick_target(cfg)
        if not target_id:
            self.logger.info("Conquest: nenhum alvo barbaro elegivel neste ciclo")
            return None

        plan = self._build_plan(target_id, sources, cfg)
        scheduled = self._schedule(target_id, target_meta, plan, cfg) if plan else None
        if not scheduled:
            # A fila manual tem prioridade absoluta em find_target(), entao um
            # alvo que nunca chega a ser agendado congelaria a selecao
            # automatica do imperio inteiro. O contador de tentativas e a saida
            # desse estado -- ver ConquestManager._note_failed_claim().
            #
            # Isto mora aqui e nao no ConquestManager porque a montagem do trem
            # mudou de dono: a chamada antiga estava no run() por aldeia, que
            # deixou de existir. Mover a decisao sem mover a guarda junto
            # deixaria a guarda viva nos testes e morta em campo.
            anchor = self._anchor_village()
            if anchor:
                self._manager_for(anchor)._note_failed_claim(target_id)
        return scheduled

    # ------------------------------------------------------------------
    # Nobres disponiveis no imperio
    # ------------------------------------------------------------------

    def _noble_sources(self):
        """
        [(village_id, nobres_livres)] ordenado por quantidade decrescente.

        "Livre" desconta o que outros sistemas ja reservaram (Feature 27 --
        PvpConquestManager reserva um snob por ataque agendado, e esses nobres
        podem ficar em casa por horas enquanto o Hunter espera a hora certa).
        Contar tropa reservada como disponivel foi exatamente o bug de
        double-booking que a Feature 27 existe para matar, e nobre e a unidade
        mais cara do jogo.
        """
        sources = []
        for vid, village in sorted(self.villages.items()):
            if not self._village_may_conquer(vid, village):
                continue
            units = getattr(village, "units", None)
            if not units or not units.troops:
                continue
            total = int(units.troops.get("snob", 0) or 0)
            reserved = 0
            if hasattr(units, "total_conquest_reserve"):
                reserved = int(units.total_conquest_reserve().get("snob", 0) or 0)
            free = max(0, total - reserved)
            if free > 0:
                sources.append((vid, free))
        sources.sort(key=lambda item: (-item[1], item[0]))
        return sources

    def _village_may_conquer(self, vid, village):
        """
        Mesmos portoes que Village.run_conquest() ja aplicava por aldeia -- o
        planejador nao pode ser uma porta dos fundos para eles.
        """
        village_cfg = self.config.get("villages", {}).get(vid, {})
        if not village_cfg.get("conquest_enabled", True):
            return False
        if not getattr(village, "area", None) or not getattr(village, "units", None):
            return False
        # Aldeia que e origem de clear/nobre de uma conquista PvP nao gasta
        # tropa com barbaro (game/village.py::_pvp_troop_spending_suspended).
        suspended = getattr(village, "_pvp_troop_spending_suspended", None)
        if callable(suspended) and suspended():
            return False
        return True

    # ------------------------------------------------------------------
    # Alvo
    # ------------------------------------------------------------------

    def _pick_target(self, cfg):
        """
        Reaproveita a selecao do ConquestManager, mas vista da aldeia com mais
        nobres -- e nao de uma aldeia arbitraria.

        Por que delegar em vez de reimplementar: `find_target()` carrega o
        alvo manual da fila, a area de interesse, o filtro de dono/pontos/raio
        e os dois filtros de alvo ja reservado. Reescrever tudo aqui criaria
        uma segunda politica de selecao para divergir da primeira em silencio.
        """
        anchor_id = self._anchor_village()
        if not anchor_id:
            return None, {}
        manager = self._manager_for(anchor_id)
        target_id = manager.find_target(cfg)
        if not target_id:
            return None, {}
        return target_id, manager._get_village_meta(target_id)

    def _manager_for(self, vid):
        """
        ConquestManager da aldeia `vid`, para reusar a politica que ja mora
        nele (selecao de alvo, escolta, fila manual) em vez de reescreve-la.

        Construir e barato: o unico custo real do __init__ e WorldConfig.get(),
        que serve do cache em disco e so vai a rede a cada CACHE_TTL.
        """
        village = self.villages[vid]
        return ConquestManager(
            wrapper=self.wrapper,
            village_id=vid,
            troopmanager=village.units,
            map_obj=village.area,
            config=self.config,
        )

    def _anchor_village(self):
        """
        Aldeia de referencia para a selecao: a que tem mais nobres.

        A escolha importa porque `find_target()` pontua por distancia ate a
        aldeia de referencia (`map.get_dist`) e filtra por `max_radius` sobre
        o scan de mapa dela. Ancorar em quem tem mais nobres aproxima o alvo
        de onde esta a maior parte do trem, o que encurta a viagem mais longa
        -- que e justamente a que define a chegada comum de todo mundo.
        """
        sources = self._noble_sources()
        return sources[0][0] if sources else None

    # ------------------------------------------------------------------
    # Plano
    # ------------------------------------------------------------------

    def _build_plan(self, target_id, sources, cfg):
        """
        [{source_village_id, troops}] com exatamente TRAIN_SIZE nobres, um por
        comando, cada um com sua escolta.

        Um nobre por comando e a regra do jogo, nao uma escolha: cada ataque
        derruba lealdade uma vez, entao quatro nobres num comando so seriam um
        unico golpe de lealdade com quatro nobres mortos junto.
        """
        plan = []
        remaining = ConquestManager.TRAIN_SIZE

        for vid, available in sources:
            if remaining <= 0:
                break
            take = min(available, remaining)
            escort = self._escort_for(vid, cfg, take)
            if escort is None:
                self.logger.info(
                    "Conquest: aldeia %s tem %d nobre(s) mas nao fecha a escolta "
                    "minima -- fica de fora deste trem", vid, available
                )
                self._reserve_toward_escort(vid, cfg)
                continue
            for _ in range(take):
                troops = dict(escort)
                troops["snob"] = 1
                plan.append({"source_village_id": vid, "troops": troops})
            remaining -= take

        if remaining > 0:
            self.logger.info(
                "Conquest: so %d/%d nobres tem escolta suficiente para sair -- "
                "nao agendo trem parcial",
                ConquestManager.TRAIN_SIZE - remaining, ConquestManager.TRAIN_SIZE
            )
            return None
        return plan

    def _reserve_toward_escort(self, vid, cfg):
        """
        Segura tropa em casa enquanto a escolta desta aldeia nao fecha.

        Comportamento que existia no `ConquestManager.run()` antigo e teria se
        perdido calado na mudanca de dono: sem ele, farm e gather gastam a
        tropa que a aldeia estava juntando e a escolta nunca fecha. O
        `_calculate_needed_escort()` ja tem os portoes que evitam o efeito
        contrario (P2-22: reservar cedo demais congela o farm que financia o
        recrutamento que fecharia a escolta), entao a chamada e direta.
        """
        manager = self._manager_for(vid)
        needed = manager._calculate_needed_escort(cfg)
        units = self.villages[vid].units
        if needed:
            units.conquest_reserve["barbarian_conquest"] = needed
            self.logger.info(
                "Conquest: aldeia %s reservando %s para fechar a escolta", vid, needed
            )
        elif units.conquest_reserve.pop("barbarian_conquest", None):
            self.logger.info(
                "Conquest: aldeia %s liberou a reserva de escolta -- farm e "
                "gather voltam a usar essa tropa", vid
            )

    def _escort_for(self, vid, cfg, noble_count):
        """
        Escolta POR COMANDO saindo desta aldeia, ou None se nao fecha o minimo.

        Delega o calculo ao ConquestManager da propria aldeia para nao criar
        uma segunda regra de escolta. A diferenca e que `_build_escort()`
        divide a tropa comprometida por TRAIN_SIZE (4), presumindo que os
        quatro nobres saem daqui; aqui pode sair menos, entao o excedente e
        redistribuido entre os comandos que esta aldeia realmente manda.
        """
        escort = self._manager_for(vid)._build_escort(cfg)
        if escort is None:
            return None
        if noble_count >= ConquestManager.TRAIN_SIZE:
            return escort
        factor = ConquestManager.TRAIN_SIZE / float(noble_count)
        return {unit: max(1, int(qty * factor)) for unit, qty in escort.items()}

    # ------------------------------------------------------------------
    # Agendamento
    # ------------------------------------------------------------------

    def _schedule(self, target_id, target_meta, plan, cfg):
        """
        Sonda a duracao de cada comando, escolhe a chegada comum e registra no
        Hunter.
        """
        hunter = self._get_hunter()
        durations = {}
        for atk in plan:
            source_id = atk["source_village_id"]
            key = (source_id, tuple(sorted(atk["troops"].items())))
            if key not in durations:
                durations[key] = hunter._probe_duration(
                    source_id, target_id, atk["troops"]
                )
            if not durations[key]:
                self.logger.warning(
                    "Conquest: nao consegui a duracao de %s -> %s pelo servidor "
                    "-- sem isso nao da para sincronizar a chegada, adiando",
                    source_id, target_id
                )
                return None
            atk["duration_seconds"] = float(durations[key])

        longest = max(atk["duration_seconds"] for atk in plan)
        arrival_ts = time.time() + longest + self.ARRIVAL_MARGIN_SECONDS
        arrival_str = datetime.datetime.fromtimestamp(arrival_ts).strftime(DATETIME_FMT)

        if not self._add_hunter_schedule(target_id, arrival_str, plan):
            return None

        self._reserve(target_id, plan)

        per_source = {}
        for atk in plan:
            per_source[atk["source_village_id"]] = per_source.get(
                atk["source_village_id"], 0
            ) + 1

        ConquestCache.set(target_id, {
            "status": "train_scheduled",
            # Quem "reserva" e o imperio, mas o campo e lido por
            # _get_my_conquest() para decidir qual aldeia acompanha a conquista
            # depois. A ancora e a que manda mais nobres.
            "reserved_by": max(per_source, key=lambda v: (per_source[v], v)),
            "scheduled_at": int(time.time()),
            "scheduled_arrival": int(arrival_ts),
            "hunter_schedule_key": self._sched_key(target_id, arrival_str),
            "sources": per_source,
            "hits_done": 0,
            "hits_needed": ConquestManager.TRAIN_SIZE,
            "target_name": target_meta.get("name") or ("Bárbara #%s" % target_id),
            "target_points": target_meta.get("points"),
            "target_location": target_meta.get("location"),
        })

        self.logger.info(
            "Conquest: trem de %d nobres agendado contra %s, chegada comum %s "
            "(origens: %s)",
            len(plan), target_id, arrival_str,
            ", ".join("%s x%d" % (v, n) for v, n in sorted(per_source.items()))
        )
        self.wrapper.reporter.report(
            max(per_source, key=lambda v: (per_source[v], v)),
            "TWB_CONQUEST",
            "Trem multi-origem agendado -> %s | chegada %s | origens %s"
            % (target_id, arrival_str, per_source),
        )
        return target_id

    @staticmethod
    def _sched_key(target_id, arrival_str):
        """Mesma regra de HunterReader.add_schedule, para achar o schedule depois."""
        return "%s_%s_barb" % (
            target_id, arrival_str.replace(" ", "T").replace(":", "-")
        )

    def _add_hunter_schedule(self, target_id, arrival_str, plan):
        try:
            from webmanager.utils import HunterReader
        except ImportError:
            try:
                from utils import HunterReader
            except ImportError:
                self.logger.error("Conquest: nao consegui importar HunterReader")
                return False

        return bool(HunterReader.add_schedule(
            target_id=target_id,
            arrival_str=arrival_str,
            attacks=[
                {
                    "source_village_id": atk["source_village_id"],
                    "troops": atk["troops"],
                    "is_fake": False,
                }
                for atk in plan
            ],
            label="barb",
        ))

    # ------------------------------------------------------------------
    # Reserva de tropa ate o Hunter disparar
    # ------------------------------------------------------------------

    def _reserve(self, target_id, plan):
        """
        Segura a tropa comprometida ate o Hunter mandar.

        Sem isto, farm e gather gastam entre o agendamento e o envio -- e como
        o `send_time` e recuado a partir da chegada, essa janela e de horas. O
        comando falharia no disparo, com o jogo recusando por falta de unidade,
        e a operacao inteira morreria em silencio. Mesmo motivo e mesma forma
        do `PvpConquestManager._reserve_troops`.
        """
        by_source = {}
        for atk in plan:
            acc = by_source.setdefault(atk["source_village_id"], {})
            for unit, qty in atk["troops"].items():
                acc[unit] = acc.get(unit, 0) + int(qty)

        key = "%s:%s" % (self.RESERVE_PREFIX, target_id)
        for vid, troops in by_source.items():
            village = self.villages.get(vid)
            if village and village.units is not None:
                village.units.conquest_reserve[key] = troops

    def _release(self, target_id):
        key = "%s:%s" % (self.RESERVE_PREFIX, target_id)
        for village in self.villages.values():
            units = getattr(village, "units", None)
            if units is not None:
                units.conquest_reserve.pop(key, None)

    def _release_orphan_reserves(self):
        """
        Solta reserva `barb_train:*` cujo alvo nao esta mais em
        `train_scheduled`.

        `_promote_scheduled_trains()` solta a reserva no caminho normal, mas
        ele depende de achar o registro e o schedule. Quem apagar qualquer um
        dos dois por fora -- o botao "limpar" do dashboard
        (ConquestReader.force_clear), uma limpeza de cache, o alvo virando
        "lost" por outro jogador ter conquistado -- deixa a tropa reservada sem
        nada para solta-la. Reserva presa nao da erro: ela so subtrai do farm e
        do gather, em silencio, para sempre. E o P2-22 de novo, e esta e a
        terceira porta pela qual ele tenta entrar neste projeto.

        Varrer e barato porque o dono esta no nome da chave: nao ha nada a
        cruzar com o disco alem dos registros que ja estao em memoria.
        """
        scheduled = {
            fname.replace(".json", "")
            for fname in FileManager.list_directory("cache/conquest", ends_with=".json")
            if (FileManager.load_json_file(f"cache/conquest/{fname}") or {}).get("status")
            == "train_scheduled"
        }
        prefix = "%s:" % self.RESERVE_PREFIX
        for vid, village in self.villages.items():
            units = getattr(village, "units", None)
            if units is None:
                continue
            for key in [k for k in units.conquest_reserve if k.startswith(prefix)]:
                if key[len(prefix):] not in scheduled:
                    units.conquest_reserve.pop(key, None)
                    self.logger.info(
                        "Conquest: soltando reserva orfa %s da aldeia %s -- o "
                        "trem correspondente nao existe mais", key, vid
                    )

    # ------------------------------------------------------------------
    # Transicao: agendado -> enviado
    # ------------------------------------------------------------------

    def _promote_scheduled_trains(self):
        """
        Converte `train_scheduled` em `train_sent` depois que o Hunter disparou,
        para o `ConquestManager._handle_existing()` assumir o acompanhamento.

        Quem sabe se o comando saiu e o Hunter, no proprio cache dele: cada
        ataque vira "sent" ou "failed" em `cache/hunter/schedules.json`. Esta e
        a costura entre os dois sistemas, e ela precisa existir porque o Hunter
        nao conhece conquista -- ele so manda ataque.

        A chegada gravada aqui e a `arrival_time` do schedule, nao uma conta
        local: o servidor calculou a duracao na sondagem e o Hunter dormiu ate
        o instante exato para honra-la. Recalcular daria um segundo numero para
        divergir do primeiro (ver _arrival_of_last_attack em attack.py).
        """
        schedules = FileManager.load_json_file(Hunter.SCHEDULE_CACHE) or {}
        for fname in FileManager.list_directory("cache/conquest", ends_with=".json"):
            data = FileManager.load_json_file(f"cache/conquest/{fname}")
            if not data or data.get("status") != "train_scheduled":
                continue
            target_id = fname.replace(".json", "")
            sched = schedules.get(data.get("hunter_schedule_key") or "")
            if not sched:
                continue

            attacks = sched.get("attacks", [])
            if any(atk.get("status") == "pending" for atk in attacks):
                continue  # ainda ha comando por sair

            sent = [atk for atk in attacks if atk.get("status") == "sent"]
            self._release(target_id)

            if not sent:
                self.logger.warning(
                    "Conquest: nenhum comando do trem contra %s chegou a sair "
                    "(Hunter marcou tudo como failed) -- alvo liberado",
                    target_id
                )
                ConquestCache.set(target_id, {
                    **data,
                    "status": "invalid",
                    "invalid_reason": "O Hunter nao conseguiu despachar nenhum "
                                      "nobre do trem agendado",
                })
                continue

            arrival = int(sched.get("arrival_time") or 0) or None
            drop_min = data.get("loyalty_drop_per_noble")
            if drop_min is None:
                drop_min = self.config.get("conquest", {}).get(
                    "loyalty_drop_per_noble", 25
                )
            ConquestCache.set(target_id, {
                **data,
                "status": "train_sent" if len(sent) == len(attacks) else "extra_pending",
                "hits_done": len(sent),
                # Mesmo pior caso do _send_train: o piso da faixa faz da
                # estimativa um limite SUPERIOR da lealdade que sobrou.
                "loyalty_after_train": max(0, 100 - (len(sent) * int(drop_min))),
                "loyalty_source": "estimate",
                "noble_arrivals": [arrival] * len(sent),
                "last_hit_timestamp": arrival or int(time.time()),
            })
            self.logger.info(
                "Conquest: %d/%d nobres do trem contra %s sairam pelo Hunter, "
                "pouso comum em %s",
                len(sent), len(attacks), target_id,
                datetime.datetime.fromtimestamp(arrival).strftime(DATETIME_FMT)
                if arrival else "horário desconhecido"
            )

    def _get_hunter(self):
        if self._hunter is None:
            self._hunter = Hunter(wrapper=self.wrapper)
        self._hunter.villages = self.villages
        return self._hunter
