"""
Tick de eventos (§8.71, fase 2): o bot toma consciencia de um fato quando ele
acontece, nao quando o proximo ciclo comeca.

POR QUE EXISTE
--------------
Nas palavras do usuario (19/10): "e como se o bot so tomasse consciencia real
de cada informacao quando o ciclo comeca". O ciclo mede ~4 h com 30+ aldeias,
e o acompanhamento da conquista barbara (`ConquestManager._handle_existing`),
a promocao do trem depois que o Hunter manda
(`BarbarianTrainPlanner._promote_scheduled_trains`) e os avisos de Telegram
dos dois so rodavam no inicio do ciclo. Um nobre que pousava as 07:11 com a
lealdade em 45 esperava ate horas pelo extra -- e a lealdade regenera 1/h no
br143.

O QUE FAZ, E QUANDO
-------------------
Roda nos checkpoints que ja existem (o `service_callback` do Hunter, chamado
entre as fases e dentro do farm, onde ja rodam `OwnDefense.tick` e
`MintManager.tick`) e no sono entre ciclos. E barato quando nao ha nada: so
le `cache/conquest` e `cache/hunter/schedules.json` do disco.

1. Promocao: trem `train_scheduled` cujo schedule do Hunter nao tem mais
   comando por sair vira `train_sent`/`extra_pending` na hora, com o aviso
   "os N nobres sairam" ou "INCOMPLETA". Nenhuma requisicao.
2. Pouso: conquista `train_sent`/`extra_pending` cujos nobres registrados ja
   pousaram (+`LANDING_MARGIN`) e cujo pouso ainda nao foi tratado neste
   processo: le a lista de relatorios (o `ReportManager` unico do processo,
   §8.47), e, achado o relatorio do pouso, roda o acompanhamento da aldeia
   ancora -- posse confirmada, alvo perdido, lealdade real, nobre extra --
   com o aviso de Telegram junto. Sem o relatorio, insiste ate
   `REPORT_WAIT`; depois disso o inicio do ciclo segue cuidando, como antes.

O gatilho do pouso e o RELOGIO, nao o contador `new_report` do jogo: a
chegada de cada nobre nosso esta em `noble_arrivals`, gravada da confirmacao
do proprio jogo. E exata, e nao depende de haver requisicao (no sono nao ha
`game_data` para ler contador nenhum).

Nada aqui decide sozinho: o que roda e o mesmo `Village.run_conquest()` do
inicio do ciclo, com as mesmas travas (nobre em voo por chegada, posse antes
de tudo, portao de origem, nobre no ar lido da praca -- fase 3). Rodar duas
vezes o mesmo pouso nao duplica envio: o extra grava a chegada dele, e a
trava de nobre em voo segura a segunda passada.
"""

import logging
import time

from core.filemanager import FileManager
from core.village_label import village_label
from game.attack import ConquestCache

logger = logging.getLogger("EventTick")


class EventTick:
    # O relatorio do pouso nasce no segundo do pouso; a folga cobre relogio e
    # a primeira leitura depois dele.
    LANDING_MARGIN = 30
    # Quanto o tick insiste num pouso sem relatorio. Passado isto, o pouso
    # fica para o inicio do ciclo (estimativa), que e o caminho de antes.
    REPORT_WAIT = 45 * 60
    # Relatorio do pouso: `when` dele contra o pouso registrado. A chegada
    # registrada e a prevista (o Hunter manda ~1 s depois do send_time).
    REPORT_TOLERANCE = 120

    def __init__(self):
        # Mutaveis em __init__ (1o padrao).
        self._handled = {}
        self._reinforce_tried = {}
        self._busy = False

    # ------------------------------------------------------------------
    # O que esta pendente (sem rede)
    # ------------------------------------------------------------------

    @staticmethod
    def landing_of(data):
        """
        Ultimo pouso registrado, se TODOS ja tem hora conhecida; senao None.
        Reforco agendado (§8.71) conta pela chegada planejada: acompanhar no
        pouso do trem, com o reforco ainda por pousar, nao decide nada.
        """
        arrivals = list(data.get("noble_arrivals") or [])
        reinforcement = data.get("reinforcement") or {}
        if reinforcement.get("status") == "scheduled" and reinforcement.get("arrival"):
            arrivals.append(reinforcement["arrival"])
        if not arrivals or any(a is None for a in arrivals):
            return None
        try:
            return max(float(a) for a in arrivals)
        except (TypeError, ValueError):
            return None

    def due_landings(self, now, conquests=None):
        """[(target_id, data, pouso)] dos pousos que ja podem ser acompanhados."""
        conquests = ConquestCache.active_conquests() if conquests is None else conquests
        out = []
        for target_id, data in sorted(conquests.items()):
            if data.get("status") not in ("train_sent", "extra_pending"):
                continue
            landing = self.landing_of(data)
            if landing is None or now < landing + self.LANDING_MARGIN:
                continue
            if self._handled.get(str(target_id)) == landing:
                continue
            out.append((str(target_id), data, landing))
        return out

    def next_landing(self, now, conquests=None):
        """Proximo instante em que um pouso fica acompanhavel, ou None."""
        conquests = ConquestCache.active_conquests() if conquests is None else conquests
        best = None
        for _tid, data in conquests.items():
            if data.get("status") not in ("train_sent", "extra_pending"):
                continue
            landing = self.landing_of(data)
            if landing is None:
                continue
            ready = landing + self.LANDING_MARGIN
            if ready > now and (best is None or ready < best):
                best = ready
        return best

    @staticmethod
    def promotions_due(conquests=None, schedules=None):
        """Alvos `train_scheduled` cujo schedule do Hunter ja nao manda mais nada."""
        from game.conquest_planner import BarbarianTrainPlanner
        from game.hunter import Hunter

        if conquests is None:
            conquests = ConquestCache.active_conquests()
        if schedules is None:
            schedules = FileManager.load_json_file(Hunter.SCHEDULE_CACHE) or {}
        due = []
        for target_id, data in sorted(conquests.items()):
            reinforcement = data.get("reinforcement") or {}
            if data.get("status") == "train_scheduled":
                key = data.get("hunter_schedule_key")
            elif reinforcement.get("status") == "scheduled":
                key = reinforcement.get("sched_key")  # §8.71: reforco que ja saiu
            else:
                continue
            sched = schedules.get(key or "")
            if not sched:
                continue
            attacks = sched.get("attacks", [])
            if (any(atk.get("status") == "pending" for atk in attacks)
                    and not BarbarianTrainPlanner._schedule_over(sched)):
                continue
            due.append(str(target_id))
        return due

    # Uma tentativa de reforco por alvo a cada tanto: o tick roda antes de
    # cada alvo do farm, e sem isto o mesmo "nao fecha escolta" iria ao log
    # centenas de vezes por ciclo.
    REINFORCE_RETRY = 30 * 60

    @staticmethod
    def troop_fingerprint(villages):
        """
        Foto da tropa em casa das aldeias com nobre. Muda quando alguma delas
        rele a praca -- e e nesse instante que uma escolta que estava fora
        (coleta, apoio voltando) pode ter chegado.
        """
        out = []
        for vid, village in sorted((villages or {}).items()):
            troops = getattr(getattr(village, "units", None), "troops", None) or {}
            try:
                if int(troops.get("snob", 0) or 0) <= 0:
                    continue
            except (TypeError, ValueError):
                continue
            out.append((str(vid), tuple(sorted((str(k), str(v)) for k, v in troops.items()))))
        return tuple(out)

    def reinforcements_due(self, conquests, config, now, villages=None):
        """
        Alvos com trem incompleto no ar que pedem reforco (§8.71).

        Reavalia no maximo a cada `REINFORCE_RETRY` -- OU quando a tropa em
        casa de uma aldeia com nobre mudou desde a ultima tentativa. Caso da
        81800 (19/10): a escolta da BBM 008 estava fora (coleta, apoio
        voltando da BBM 055) e volta durante a vez dela no laco. So o relogio
        podia perder a janela entre a releitura da praca e a coleta sair de
        novo; a mudanca da tropa e o sinal certo.
        """
        from game.attack import ConquestManager
        from game.conquest_planner import BarbarianTrainPlanner

        fingerprint = self.troop_fingerprint(villages) if villages is not None else None
        out = []
        for target_id, data in sorted(conquests.items()):
            tried_at, tried_print = self._reinforce_tried.get(str(target_id), (0, None))
            if (now - tried_at < self.REINFORCE_RETRY
                    and (fingerprint is None or fingerprint == tried_print)):
                continue
            drop_max = (data.get("loyalty_drop_range") or [None, None])[1]
            if drop_max is None:
                drop_max = ConquestManager.world_drop_range(config)[1]
            missing, _landing, _why = BarbarianTrainPlanner.reinforcement_need(
                data, now, drop_max, BarbarianTrainPlanner.BARB_START_LOYALTY)
            if missing:
                out.append(str(target_id))
        return out

    # ------------------------------------------------------------------
    # O relatorio do pouso
    # ------------------------------------------------------------------

    def landing_report(self, report_manager, target_id, landing):
        """(lealdade, when) do relatorio de nobre deste pouso, ou (None, None)."""
        best = None
        for entry in (getattr(report_manager, "last_reports", None) or {}).values():
            if str(entry.get("dest")) != str(target_id):
                continue
            extra = entry.get("extra") or {}
            if "loyalty_after" not in extra or "snob" not in (extra.get("units_sent") or {}):
                continue
            try:
                when = int(extra.get("when") or 0)
                loyalty = float(extra["loyalty_after"])
            except (TypeError, ValueError):
                continue
            if when < landing - self.REPORT_TOLERANCE:
                continue
            # Mesmo desempate do ConquestManager: no mesmo instante a
            # lealdade so cai, entao fica a menor.
            key = (when, -loyalty)
            if best is None or key > best[0]:
                best = (key, loyalty, when)
        return (best[1], best[2]) if best else (None, None)

    # ------------------------------------------------------------------
    # O tick
    # ------------------------------------------------------------------

    def tick(self, config, villages, report_manager=None, gate=None, prime=None,
             planner_factory=None, now=None):
        """
        Um checkpoint. Devolve True se acompanhou algum pouso.

        - `villages`: {vid: Village} gerenciadas (o dict do ciclo);
        - `gate(fase) -> bool`: o `Hunter.gate` do twb, para nao comecar
          leitura nem envio colado numa saida (False = deixa para o proximo);
        - `prime(vids)`: le aldeias que ainda nao tem tropa/mapa neste
          processo (`TWB._prime_villages`);
        - `planner_factory()`: um `BarbarianTrainPlanner` do ciclo, so para a
          promocao.
        """
        if self._busy or not (config or {}).get("conquest", {}).get("enabled", False):
            return False
        now = time.time() if now is None else now
        try:
            conquests = ConquestCache.active_conquests()
            promote = self.promotions_due(conquests)
            due = self.due_landings(now, conquests)
            reinforce = self.reinforcements_due(conquests, config, now, villages)
        except Exception as exc:
            logger.warning("Eventos: nao consegui ler o estado da conquista (%s)", exc)
            return False
        if not promote and not due and not reinforce:
            return False

        self._busy = True
        try:
            planner = planner_factory() if callable(planner_factory) else None
            if promote and planner is not None:
                logger.info("Eventos: trem(ns)/reforco(s) %s com o Hunter encerrado -- "
                            "promovendo agora", ", ".join(village_label(t) for t in promote))
                planner._promote_scheduled_trains()
                planner.promote_reinforcements()
                planner._sync_reinforcement_reserves()
                # Trem recem-promovido incompleto: o reforco se decide ja.
                reinforce = self.reinforcements_due(
                    ConquestCache.active_conquests(), config, now, villages)
            if reinforce and planner is not None and (not callable(gate) or gate("eventos")):
                if callable(prime):
                    stale = [vid for vid, v in (villages or {}).items()
                             if (not getattr(v, "units", None) or not getattr(v, "area", None))
                             and self._may_hold_noble(vid, v)]
                    if stale:
                        prime(sorted(stale))
                # A foto e tirada DEPOIS do prime: a tentativa vale para a
                # tropa que ela de fato viu.
                fingerprint = self.troop_fingerprint(villages)
                for target_id in reinforce:
                    self._reinforce_tried[target_id] = (now, fingerprint)
                logger.info("Eventos: trem incompleto no ar contra %s -- avaliando reforco agora",
                            ", ".join(village_label(t) for t in reinforce))
                planner.plan_reinforcements(now=now)
            handled = False
            for target_id, data, landing in due:
                if callable(gate) and not gate("eventos"):
                    break
                if self._follow_landing(config, villages, report_manager, prime,
                                        target_id, data, landing, now):
                    handled = True
            return handled
        except Exception as exc:
            logger.exception("Eventos: falha no tick (%s) -- o inicio do ciclo segue cuidando", exc)
            return False
        finally:
            self._busy = False

    def _follow_landing(self, config, villages, report_manager, prime,
                        target_id, data, landing, now):
        label = village_label(target_id)
        if report_manager is not None:
            last_read = getattr(report_manager, "last_list_read", None) or 0
            if last_read < landing + self.LANDING_MARGIN:
                report_manager.read(full_run=False)
        loyalty, when = self.landing_report(report_manager, target_id, landing)
        if when is None:
            if now - landing > self.REPORT_WAIT:
                logger.info(
                    "Eventos: pouso em %s as %s sem relatorio de nobre em %d min -- "
                    "fica para o inicio do ciclo", label,
                    time.strftime("%H:%M:%S", time.localtime(landing)), self.REPORT_WAIT // 60)
                self._handled[target_id] = landing
            return False

        anchor_id = str(data.get("reserved_by") or "")
        anchor = (villages or {}).get(anchor_id)
        if anchor is None:
            logger.warning("Eventos: pouso em %s, mas a aldeia ancora %s nao esta "
                           "entre as gerenciadas", label, village_label(anchor_id))
            self._handled[target_id] = landing
            return False

        # Quem pode mandar o extra precisa de tropa/mapa lidos neste processo
        # (o portao de origem barra quem nao tem). So se le quem ainda nao
        # tem -- quem ja rodou tem contagem de horas atras no maximo, e o jogo
        # recusa na confirmacao o que nao existir mais.
        if loyalty > 0 and callable(prime):
            stale = [vid for vid, v in (villages or {}).items()
                     if (not getattr(v, "units", None) or not getattr(v, "area", None))
                     and self._may_hold_noble(vid, v)]
            if not getattr(anchor, "config", None) or not getattr(anchor, "units", None):
                stale.append(anchor_id)
            if stale:
                prime(sorted(set(stale)))
        elif not getattr(anchor, "config", None) and callable(prime):
            prime([anchor_id])

        logger.info(
            "Eventos: pouso em %s as %s, relatorio lido (lealdade %.0f) -- "
            "acompanhando agora, sem esperar o inicio do ciclo",
            label, time.strftime("%H:%M:%S", time.localtime(when)), loyalty)
        self._handled[target_id] = landing
        if not getattr(anchor, "config", None):
            logger.warning("Eventos: aldeia ancora %s sem dados -- fica para o ciclo",
                           village_label(anchor_id))
            return False
        anchor.run_conquest()
        return True

    @staticmethod
    def _may_hold_noble(vid, village):
        units = getattr(village, "units", None)
        if int(((getattr(units, "troops", None) or {}).get("snob", 0)) or 0) > 0:
            return True
        cached = FileManager.load_json_file(f"cache/managed/{vid}.json") or {}
        return int(((cached.get("troops") or {}).get("snob", 0)) or 0) > 0
