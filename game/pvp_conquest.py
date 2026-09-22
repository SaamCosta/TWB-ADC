"""
Feature 13 — Conquista PvP semi-manual

Fluxo por alvo:
  pending_scout   → bot envia scout de qualquer aldeia com espiões
  pending_troops  → farm/coleta suspensos nas origens; espera o exército voltar
                    para casa antes de deixar o Simulator julgar a operação
  pending_sim     → relatório chegou; Simulator avalia se a limpeza é viável
  scheduled       → Hunter agendou clear + noble train com chegada simultânea
  complete        → conquista concluída (loyalty ≤ 0 ou aldeia ownership confirmada)
  failed          → clear inviável, noble train não disparou, ou o train chegou
                    e a posse não mudou dentro da janela de tolerância

Cache: cache/pvp_conquest/{target_id}.json
"""

import datetime
import logging
import time

from core.extractors import Extractor
from core.filemanager import FileManager
from core.templates import UNIT_POP
from core.world_config import WorldConfig
from game.hunter import Hunter
from game.reservations import manual_exclusion
from game.simulator import Simulator

logger = logging.getLogger("PvpConquest")

DATETIME_FMT = "%Y-%m-%d %H:%M:%S"


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

class PvpConquestCache:
    DIR = "cache/pvp_conquest"

    @staticmethod
    def get(target_id):
        return FileManager.load_json_file(f"{PvpConquestCache.DIR}/{target_id}.json")

    @staticmethod
    def set(target_id, data):
        FileManager.save_json_file(data, f"{PvpConquestCache.DIR}/{target_id}.json")

    @staticmethod
    def delete(target_id):
        FileManager.remove_file(f"{PvpConquestCache.DIR}/{target_id}.json")

    @staticmethod
    def all():
        out = {}
        for fname in FileManager.list_directory(PvpConquestCache.DIR, ends_with=".json"):
            tid = fname.replace(".json", "")
            data = FileManager.load_json_file(f"{PvpConquestCache.DIR}/{fname}")
            if data:
                out[tid] = data
        return out


# ---------------------------------------------------------------------------
# Main manager — called once per cycle from twb.py
# ---------------------------------------------------------------------------

class PvpConquestManager:
    """
    Processes all pending PvP conquest targets each bot cycle.

    Requires:
      - villages: dict {village_id: Village} (managed villages, already run this cycle)
      - wrapper: WebWrapper instance
      - config: full bot config dict
    """

    def __init__(self, wrapper, villages, config, reservation_board=None):
        self.wrapper = wrapper
        self.villages = villages      # {village_id: Village}
        self.config = config
        # Feature 35: quadro de reservas da tribo. Por decisao do usuario a
        # regra vale para TODA conquista, nao so a barbara -- furar reserva de
        # companheiro numa aldeia de jogador custa o mesmo capital social.
        self.reservation_board = reservation_board
        self.sim = Simulator()
        # Feature 18: cached world settings (night bonus, moral) -- refreshed
        # at most every WorldConfig.CACHE_TTL, cheap to call every cycle.
        self.world_config = WorldConfig.get(
            server=config.get("server", {}).get("server"),
            endpoint=config.get("server", {}).get("endpoint"),
        )
        # P2-35: per-instance memos. twb.py builds one manager per cycle and
        # hands it to every village, so these are naturally cycle-scoped --
        # see Village.run_pvp_conquest(). Declared here, not on the class,
        # per the mutable-class-attribute rule in CLAUDE.md.
        self._reports_index = None
        self._reports_files = None
        self._player_id = None
        self._deadline_hunter = None
        self._deadline_probe_attempts = {}
        # Village ids whose routine troop spending must stop while a PvP
        # conquest is preparing/scheduling its clear and noble train.  This is
        # rebuilt from the target cache on every run, so deleting/failing a
        # target releases the lock without leaving process-local stale state.
        self.farm_suspended_villages = set()

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    # Real transitions are pending_scout -> pending_sim -> scheduled, plus
    # the completion check once scheduled. 4 gives headroom without risking
    # a runaway loop if a future step is added carelessly.
    MAX_STEPS_PER_CALL = 5
    FARM_SUSPEND_STATUSES = {
        "pending_scout", "pending_troops", "pending_sim", "scheduled",
    }
    # Statuses where the operation is still choosing/holding its sources and
    # nothing has been committed to Hunter yet.  Several preparation steps
    # gate on exactly this set; keeping it named means adding a future stage
    # does not mean hunting down four separate literal tuples (P2-22).
    PREPARING_STATUSES = ("pending_scout", "pending_troops", "pending_sim")

    def run(self):
        # Always rebuild this process-local view.  In particular, disabling
        # PvP conquest between two Village.run() calls must not keep locks
        # published by an earlier call in the same bot cycle.
        self.farm_suspended_villages = set()
        cfg = self.config.get("pvp_conquest", {})
        if not cfg.get("enabled", False):
            return

        targets = PvpConquestCache.all()
        if not targets:
            return

        for target_id, data in targets.items():
            try:
                # Feature 35: reserva de ALVO da tribo. Antes de qualquer passo
                # da maquina de estados -- inclusive antes de travar origem --
                # porque a partir daqui o alvo so acumula compromisso.
                #
                # Nao checa `is_readable()`: um alvo PvP so entra aqui porque o
                # operador o colocou a mao, e derrubar o trabalho dele por uma
                # pagina que nao abriu seria pior que o problema. So reserva
                # efetivamente LIDA barra. O `finally` abaixo solta as travas
                # de origem assim que o status vira terminal.
                if self._block_if_reserved(target_id, data):
                    continue

                # Assign the future clear/noble sources before the state
                # machine waits for a scout report.  Previously these choices
                # only happened in _step_simulate(), leaving pending_scout and
                # pending_sim free to farm away the army the later schedule
                # expected to use.
                self._prepare_source_locks(target_id, data)
                self._prepare_departure_deadlines(target_id, data)

                # A fixed operation time is no longer useful after its first
                # required departure.  Do not keep re-scouting forever and do
                # not create a Hunter schedule that can only arrive late.
                if self._fail_if_scout_deadline_missed(target_id, data):
                    continue

                # Bugfix (2026-08-07): this used to do at most one step per
                # target per call (e.g. pending_scout -> pending_sim), so a
                # target that became ready to advance further *within this
                # same call* -- e.g. a scout report was already sitting in
                # cache the moment _step_scout ran, and _step_simulate could
                # have run immediately after -- had to wait an entire extra
                # bot cycle before anything happened. Conquest is supposed
                # to preempt routine play once it's underway, not crawl one
                # state per cycle, so now each target is chained through as
                # many ready steps as fit in one call. Stops as soon as a
                # step makes no progress (still genuinely waiting on
                # something external, like a report that hasn't arrived) or
                # lands on a status this loop doesn't recognise (terminal:
                # "complete"/"failed").
                for _ in range(self.MAX_STEPS_PER_CALL):
                    status = data.get("status", "pending_scout")
                    if status == "pending_scout":
                        self._step_scout(target_id, data)
                    elif status == "pending_troops":
                        self._step_wait_troops(target_id, data)
                    elif status == "pending_sim":
                        self._step_simulate(target_id, data)
                    elif status == "scheduled":
                        self._step_check_complete(target_id, data)
                        break
                    else:
                        break

                    if data.get("status", status) == status:
                        break  # no progress this step -- wait for next call
            except Exception as e:
                logger.error("PvpConquest: error processing target %s: %s", target_id, e)
            finally:
                # Re-evaluate after transitions: a failed/complete target (or
                # a scheduled target whose Hunter commands already resolved)
                # must release immediately, while an exception errs safe and
                # preserves the lock for an active target.
                self._sync_source_locks(target_id, data)

    def _target_location(self, target_id, data):
        """
        Coordenada `[x, y]` do alvo, ou None quando nenhuma fonte a conhece.

        Duas fontes, nesta ordem: o `map_pos` de qualquer aldeia gerenciada
        (prefetch de mapa daquela aldeia) e o `target_location` gravado no
        cadastro. A segunda existe porque o painel (`PvpConquestReader.add`)
        resolve o alvo contra `cache/villages`, que e o snapshot compartilhado:
        sem ela, um alvo fora do prefetch das aldeias gerenciadas chega ao
        quadro de reservas sem coordenada e a metade do casamento que usa o
        "(x|y)" do nome nunca dispara -- falha silenciosa, alvo passa como
        livre.

        Com `farms.map_sector_radius = 0` (o valor em campo) o prefetch de cada
        aldeia cobre pouco mais de um setor de 20x20, entao a primeira fonte
        falha com frequencia e a segunda e a que responde na pratica.
        """
        for village in self.villages.values():
            pos = getattr(getattr(village, "area", None), "map_pos", {}) or {}
            if str(target_id) in pos:
                return pos[str(target_id)]
        return data.get("target_location")

    def _block_if_reserved(self, target_id, data):
        """
        True (e marca "failed") quando o alvo PvP esta reservado por outra
        pessoa da tribo, ou listado em `conquest.excluded_targets`.

        Status "failed" e nao um novo estado proprio: `FARM_SUSPEND_STATUSES`
        ja trata como terminal tudo que nao esta nela, entao "failed" e o que
        faz `_sync_source_locks()` soltar as travas de origem no `finally` do
        chamador. Inventar um status novo aqui exigiria reler cada consumidor
        de status do modulo -- e a armadilha do P2-22 (alargar o conjunto de
        valores que algo devolve sem reler quem consome).
        """
        if data.get("status") in ("complete", "failed"):
            return False
        board = self.reservation_board
        location = self._target_location(target_id, data)

        matched = manual_exclusion(self.config, target_id, location)
        claim = board.claimed_by_other(target_id, location) if board else None
        if not matched and not claim:
            return False

        who = matched if matched else claim.get("reserved_by_name")
        reason = "excluded_targets" if matched else "tribe_reservation"
        logger.warning(
            "PvpConquest: alvo %s cancelado -- reservado por %s (%s)",
            target_id, who, reason
        )
        data["status"] = "failed"
        data["failure_reason"] = "Alvo reservado por %s (%s)" % (who, reason)
        data["blocked_reason"] = reason
        data["blocked_at"] = int(time.time())
        if claim:
            data["reserved_by_id"] = claim.get("reserved_by_id")
            data["reserved_by_name"] = claim.get("reserved_by_name")
            data["reserved_by_tribe"] = claim.get("reserved_by_tribe")
            data["reservation_expires"] = claim.get("expires_text")
        PvpConquestCache.set(target_id, data)
        self._sync_source_locks(target_id, data)
        return True

    def is_troop_spending_suspended(self, village_id):
        """True while ``village_id`` is committed to an active PvP target."""
        return str(village_id) in self.farm_suspended_villages

    def _prepare_source_locks(self, target_id, data):
        """
        Choose and persist source villages before scout/simulation completes.

        Freezing the automatic choices early turns "could be selected later"
        into an exact, visible set that Village can protect now.  The existing
        scheduling step consumes these same ``clear_village_id`` and
        ``noble_villages`` fields, so the lock cannot drift from the eventual
        commands.
        """
        if data.get("status", "pending_scout") not in self.PREPARING_STATUSES:
            return

        changed = False
        clear_vid = data.get("clear_village_id")
        if clear_vid:
            clear_vid = str(clear_vid)
            if data.get("clear_village_id") != clear_vid:
                data["clear_village_id"] = clear_vid
                changed = True
        else:
            clear_vid = self._select_clear_village()
            if clear_vid:
                data["clear_village_id"] = str(clear_vid)
                changed = True

        noble_villages = data.get("noble_villages") or []
        if not noble_villages:
            max_count = self.config.get("pvp_conquest", {}).get(
                "nobles_per_target", 4
            )
            noble_villages = self._select_noble_attack_plan(max_count)
            if noble_villages:
                data["noble_villages"] = [str(vid) for vid in noble_villages]
                changed = True

        if changed:
            PvpConquestCache.set(target_id, data)

    def _sync_source_locks(self, target_id, data):
        """Publish this target's current source locks and persist them for UI."""
        active = (
            data.get("status", "pending_scout") in self.FARM_SUSPEND_STATUSES
            and not data.get("reserve_released", False)
        )
        source_ids = set()
        if active:
            if data.get("clear_village_id"):
                source_ids.add(str(data["clear_village_id"]))
            source_ids.update(str(vid) for vid in (data.get("noble_villages") or []))

        visible_ids = sorted(source_ids)
        if data.get("farm_suspended_villages", []) != visible_ids:
            data["farm_suspended_villages"] = visible_ids
            PvpConquestCache.set(target_id, data)

        self.farm_suspended_villages.update(source_ids)

    def _scout_max_age_seconds(self):
        hours = self.config.get("pvp_conquest", {}).get(
            "scout_max_age_hours", 24
        )
        return max(0, float(hours)) * 3600

    def _prepare_departure_deadlines(self, target_id, data):
        """Probe and persist the first exact departure required by this target."""
        if data.get("status", "pending_scout") not in self.PREPARING_STATUSES:
            return
        if data.get("departure_deadlines"):
            return

        arrival_ts = data.get("arrival_time")
        clear_vid = data.get("clear_village_id")
        noble_villages = data.get("noble_villages") or []
        if not arrival_ts or not clear_vid or not noble_villages:
            return

        source_ids = {str(clear_vid)} | {str(vid) for vid in noble_villages}
        for source_id in source_ids:
            source = self.villages.get(source_id)
            if (
                    not source or not source.units or not source.area
                    or str(target_id) not in source.area.map_pos):
                return

        clear_village = self.villages.get(str(clear_vid))
        if not clear_village or not clear_village.units:
            return
        attacker_units = self._build_clear_units(clear_village)
        noble_attacks = self._build_noble_attacks(
            str(clear_vid), attacker_units, noble_villages
        )
        if not attacker_units or len(noble_attacks) != len(noble_villages):
            return

        attempts = getattr(self, "_deadline_probe_attempts", {})
        last_attempt = float(attempts.get(str(target_id), 0) or 0)
        if time.time() - last_attempt < Hunter.PROBE_RETRY_SECONDS:
            return
        attempts[str(target_id)] = time.time()
        self._deadline_probe_attempts = attempts

        if getattr(self, "_deadline_hunter", None) is None:
            self._deadline_hunter = Hunter(wrapper=self.wrapper)
        self._deadline_hunter.villages = self.villages

        cfg = self.config.get("pvp_conquest", {})
        clear_arrival = float(arrival_ts) - float(
            cfg.get("arrival_buffer_seconds", 2)
        )
        probes = [("clear", str(clear_vid), attacker_units, clear_arrival)]
        probes.extend(
            ("noble", str(atk["source_village_id"]), atk["troops"], float(arrival_ts))
            for atk in noble_attacks
        )

        # Repeated nobles from one village have the same composition and use
        # one native batch.  Probe each distinct command shape only once.
        duration_cache = {}
        deadlines = []
        for label, source_id, troops, wave_arrival in probes:
            probe_key = (source_id, tuple(sorted(troops.items())))
            if probe_key not in duration_cache:
                duration_cache[probe_key] = self._deadline_hunter._probe_duration(
                    source_id, str(target_id), troops
                )
            duration = duration_cache[probe_key]
            if duration is None or duration <= 0:
                return
            deadlines.append({
                "label": label,
                "source_village_id": source_id,
                "duration_seconds": float(duration),
                "send_time": wave_arrival - float(duration),
            })

        first_send = min(item["send_time"] for item in deadlines)
        data["departure_deadlines"] = deadlines
        data["first_send_time"] = first_send
        PvpConquestCache.set(target_id, data)
        logger.info(
            "PvpConquest: first departure deadline for %s is %s",
            target_id,
            datetime.datetime.fromtimestamp(first_send).strftime(DATETIME_FMT),
        )

    def _fail_if_scout_deadline_missed(self, target_id, data):
        """Fail safely when valid intel did not arrive before first departure."""
        if data.get("status", "pending_scout") not in self.PREPARING_STATUSES:
            return False
        first_send = data.get("first_send_time")
        if not first_send or time.time() < float(first_send):
            return False
        if not data.get("scout_override") and not self._find_scout_report(target_id):
            data["status"] = "failed"
            data["fail_reason"] = "scout_deadline_missed"
        else:
            # Valid intel (or a human override) cannot rescue an operation the
            # bot did not schedule before its first required departure.
            data["status"] = "failed"
            data["fail_reason"] = "departure_deadline_missed"
        data["failed_at"] = int(time.time())
        PvpConquestCache.set(target_id, data)
        logger.warning(
            "PvpConquest: target %s failed because its first departure deadline passed",
            target_id,
        )
        return True

    # ------------------------------------------------------------------
    # Step 1 — Scout
    # ------------------------------------------------------------------

    SCOUT_MAX_ATTEMPTS = 5

    def _scout_floor(self):
        """
        `pvp_conquest.scout_amount` e um PISO, nao a quantidade enviada.

        Ele sempre foi as duas coisas ao mesmo tempo (`if spies < scout_amount:
        continue` era o filtro de elegibilidade e `troops={"spy":
        scout_amount}` era o envio). Ao passar a enviar o maximo (P-PVP-SCOUT,
        docs/backend.md 8.12), so um dos dois papeis podia sobrar; manter o
        piso preserva o significado da chave -- "menos que isto nao vale a
        viagem" -- em vez de deixa-la morta, que e o 4o padrao do CLAUDE.md.
        """
        return int(self.config.get("pvp_conquest", {}).get("scout_amount", 5) or 0)

    def _scout_candidates(self, target_id, data):
        """
        Origens possiveis para a espia, da melhor para a pior.

        Ordem: mais espioes em casa primeiro; empate resolvido pela MENOR
        distancia. A distancia entra so como desempate, e nao como peso, porque
        foi isso que o usuario decidiu em 2026-09-21: relatorio que nao chega e
        o que faz o alvo cair em `scout_deadline_missed`, e 5 exploradores
        contra aldeia de jogador defendida morrem sem relatorio. Entre duas
        origens que mandam a mesma quantidade, porem, a mais perto entrega a
        informacao mais cedo e sobra mais folga ate `first_send_time`.

        Consequencia medida e aceita: a aldeia com mais espioes tende a ser
        MAIS distante que a que a regra antiga escolhia (das 30 aldeias em
        2026-09-21, os maximos eram 80 espioes a 35,0 e 38,4 campos, contra a
        primeira da ordem de id com 50 a 34,7). A regra nova aumenta o tempo da
        espia de proposito, trocando velocidade por chance de o relatorio
        existir.

        Dois pontos sobre o que E e o que NAO E filtrado aqui:

        - A reserva de conquista e descontada (`total_conquest_reserve`). Hoje
          nenhum dono reserva `spy` -- `_build_clear_units()` e
          `_build_noble_attacks()` excluem espiao --, mas enviar o maximo
          disponivel e exatamente o caminho que transformaria uma reserva
          futura de espiao em tropa gasta sem aviso.
        - A elegibilidade NAO usa `village.area.map_pos`, que era o teste
          antigo. `AttackManager._resolve_position()` aceita a coordenada do
          snapshot compartilhado `cache/villages` quando o alvo esta fora do
          prefetch daquela aldeia, ou seja, o envio funciona para origens que o
          teste antigo descartava. Com `map_sector_radius = 0` o prefetch cobre
          pouco mais de um setor de 20x20, entao esse descarte era largo e
          arbitrario -- a aldeia com mais espioes podia nunca ser considerada
          por um motivo que nao tem a ver com alcance.
        """
        location = self._target_location(target_id, data)
        if not location:
            return []

        floor = self._scout_floor()
        candidates = []
        for vid, village in self.villages.items():
            if not village.units or not village.area or not village.attack:
                continue
            spies = int(village.units.troops.get("spy", 0)) - int(
                village.units.total_conquest_reserve().get("spy", 0)
            )
            if spies < max(floor, 1):
                continue
            # `my_location` e None quando a aldeia nao apareceu nos setores
            # lidos (Map._fallback_location tambem pode falhar). Nesse caso a
            # aldeia continua elegivel -- o envio nao depende da distancia --,
            # mas perde todo desempate.
            if village.area.my_location:
                distance = village.area.get_dist(location)
            else:
                distance = float("inf")
            candidates.append((vid, village, spies, distance))

        candidates.sort(key=lambda item: (-item[2], item[3]))
        return candidates

    def _step_scout(self, target_id, data):
        """
        Send a scout from the managed village with the MOST spies, carrying as
        many as it has at home.
        Marks status → pending_troops once the scout is sent.
        If a recent scout report already exists, skip straight to the wait.

        Por que a contagem e relida antes de enviar: os objetos `Village`
        sobrevivem entre ciclos e este passo abre o ciclo (docs/backend.md
        8.14), entao `units.troops` aqui e a foto do fim do ciclo passado -- ate
        ~4h de idade com 30 aldeias. Enviar 5 de uma contagem velha quase nunca
        falha; enviar "todos os 80" de uma contagem velha falha sempre que o
        farm scout gastou algum no meio, e o jogo recusa o ataque INTEIRO em vez
        de mandar menos. Sem a releitura, trocar 5 pelo maximo trocaria uma
        espia lenta por nenhuma espia. `update_totals()` custa duas requisicoes
        e e feita so para a origem escolhida.
        """
        if data.get("scout_override"):
            logger.warning(
                "PvpConquest: operator authorized target %s without a valid scout",
                target_id,
            )
            data["status"] = "pending_troops"
            PvpConquestCache.set(target_id, data)
            return

        # Check if there's already a usable scout report
        if self._find_scout_report(target_id):
            logger.info(
                "PvpConquest: scout report already available for %s, "
                "waiting for troops to come home", target_id
            )
            data["status"] = "pending_troops"
            PvpConquestCache.set(target_id, data)
            return

        floor = self._scout_floor()
        candidates = self._scout_candidates(target_id, data)
        if not candidates:
            logger.warning(
                "PvpConquest: no village with spies available to scout %s "
                "(piso pvp_conquest.scout_amount = %d)", target_id, floor
            )
            return

        logger.info(
            "PvpConquest: %d origem(ns) elegivel(is) para espiar %s; melhor: %s",
            len(candidates), target_id,
            ", ".join(
                "%s (%d espioes, %.1f campos)" % (vid, spies, distance)
                for vid, _village, spies, distance in candidates[:3]
            ),
        )

        # Teto de tentativas. Cada tentativa custa duas requisicoes de leitura
        # (`update_totals`) mais duas de envio, e as origens estao em ordem
        # decrescente de espiao: se as cinco primeiras falharem, o problema nao
        # e "esta aldeia especifica" e varrer as outras 25 so gasta orcamento de
        # requisicao num ciclo que ja vai terminar sem espia.
        for vid, village, _stale_spies, distance in candidates[:self.SCOUT_MAX_ATTEMPTS]:
            # Releitura viva. Ver o docstring: a contagem da ordenacao pode ter
            # horas e o jogo recusa o ataque inteiro por falta de uma unidade.
            village.units.update_totals()
            spies = int(village.units.troops.get("spy", 0)) - int(
                village.units.total_conquest_reserve().get("spy", 0)
            )
            if spies < max(floor, 1):
                logger.info(
                    "PvpConquest: %s caiu para %d espioes na leitura viva "
                    "(piso %d), tentando a proxima origem",
                    vid, spies, floor
                )
                continue

            result = village.attack.attack(target_id, troops={"spy": spies})
            if result and result != "forced_peace":
                logger.info(
                    "PvpConquest: scout sent from %s → %s (%d spies, %.1f campos)",
                    vid, target_id, spies, distance
                )
                data["status"] = "pending_troops"
                data["scout_village_id"] = vid
                data["scout_sent_at"] = int(time.time())
                data["scout_spies_sent"] = spies
                PvpConquestCache.set(target_id, data)
                return

        logger.warning(
            "PvpConquest: nenhuma das %d origens tentadas (de %d elegiveis) "
            "conseguiu espiar %s",
            min(len(candidates), self.SCOUT_MAX_ATTEMPTS), len(candidates), target_id
        )

    # ------------------------------------------------------------------
    # Step 1.5 — Wait for the army to come home
    # ------------------------------------------------------------------

    # Units that never take part in the clear wave or the escorts, so their
    # presence at home says nothing about whether the operation is ready.
    # Same exclusions as _build_clear_units()/_build_noble_attacks(): spies
    # are scouts, the Paladin never leaves automatically, and nobles are
    # counted separately by _select_noble_attack_plan().
    NON_COMBAT_UNITS = ("spy", "snob", "knight")

    def _step_wait_troops(self, target_id, data):
        """
        Hold the operation until the source villages' army is actually home.

        Why this stage exists (2026-09-21, target #44155).  The simulator is
        fed by `_build_clear_units()`, which reads `units.troops` -- troops
        **in the village right now**, not troops owned.  Suspending farm and
        gather (Village.run_farming/do_gather via
        `_pvp_troop_spending_suspended`) stops the bot sending *more* troops
        away, but it cannot recall the ones already flying: a farm run
        dispatched before the operator registered the target is still hours
        from landing back.

        So the old flow judged viability against whatever happened to be
        standing at home the minute the clear village's TroopManager first
        existed.  For #44155 that was 46 axes and 16 light cavalry out of
        1.486 and 739 owned -- roughly 3% of the army -- and the operation
        was declared `simulation_failed` and closed forever, with the other
        97% landing back home over the following hours with nothing to do.

        The wait is bounded from both ends: it ends early when the army is
        home, and it ends anyway when the first departure is close enough
        that there is no more time to spend waiting (a late simulation is
        worse than a pessimistic one -- `_fail_if_scout_deadline_missed()`
        would otherwise kill the target outright).
        """
        cfg = self.config.get("pvp_conquest", {})
        required = float(cfg.get("troops_home_ratio", 0.9))
        lead = float(cfg.get("sim_lead_seconds", 1800))
        max_wait = float(cfg.get("max_troop_wait_hours", 6)) * 3600

        started = data.get("troop_wait_started_at")
        if not started:
            started = int(time.time())
            data["troop_wait_started_at"] = started
            PvpConquestCache.set(target_id, data)

        ratio, sources = self._home_troop_ratio(data)
        if sources:
            data["troops_home_pct"] = round(ratio * 100, 1)
            data["troops_home_sources"] = sources
            PvpConquestCache.set(target_id, data)

        now = time.time()
        first_send = data.get("first_send_time")
        out_of_time = bool(first_send) and now >= float(first_send) - lead
        waited_too_long = now - float(started) >= max_wait

        if ratio is None:
            # No usable troop numbers for any source yet -- typically the
            # very first pass, before prime_for_conquest()/village.run() has
            # populated a TroopManager.  Waiting is the safe answer, but the
            # deadline still applies so this cannot stall forever.
            if not (out_of_time or waited_too_long):
                logger.info(
                    "PvpConquest: target %s waiting for troop data from its sources",
                    target_id,
                )
                return
            reason = "sem dados de tropa"
        elif ratio >= required:
            reason = None
        elif out_of_time:
            reason = "prazo de saída próximo"
        elif waited_too_long:
            reason = "teto de espera atingido"
        else:
            # Says how many sources went into the number, not just the
            # number: a source that could not be read is simply missing from
            # the measurement, and without the count the percentage looks
            # like it describes the whole operation when it does not.
            expected = len(self._source_village_ids(data))
            logger.info(
                "PvpConquest: target %s holding — %.1f%% of the source army is "
                "home (need %.0f%%), measured in %d/%d source village(s): %s",
                target_id, ratio * 100, required * 100,
                len(sources), expected,
                ", ".join(sorted(s["village_id"] for s in sources)) or "-",
            )
            return

        data["status"] = "pending_sim"
        data["troops_wait_ended_at"] = int(now)
        data["troops_wait_forced_reason"] = reason
        PvpConquestCache.set(target_id, data)
        if reason:
            logger.warning(
                "PvpConquest: target %s leaving the troop wait early (%s) with "
                "%s of the army home",
                target_id, reason,
                "%.1f%%" % (ratio * 100) if ratio is not None else "desconhecido",
            )
        else:
            logger.info(
                "PvpConquest: target %s has %.1f%% of its source army home, simulating",
                target_id, ratio * 100,
            )

    def _home_troop_ratio(self, data):
        """
        Population of the source armies standing at home / population owned.

        Returns ``(ratio, sources)``.  ``ratio`` is None when not a single
        source village could be measured -- distinguishable from 0.0, which
        means "measured, and the army really is all out" (the failure value
        of a parser must not look like a legitimate answer -- sixth pattern
        in CLAUDE.md).
        """
        source_ids = self._source_village_ids(data)
        sources = []
        home_total = 0
        owned_total = 0
        for vid in source_ids:
            village = self.villages.get(vid)
            if not village or not village.units:
                continue
            home = self._population(village.units.troops)
            owned = self._population(village.units.total_troops)
            if owned <= 0:
                # total_troops is only filled in when can_recruit is true
                # (TroopManager.update_totals returns early otherwise), so an
                # empty dict here means "not read", not "no army".
                cached = FileManager.load_json_file(f"cache/managed/{vid}.json") or {}
                owned = self._population(cached.get("troops") or {})
            if owned <= 0:
                continue
            home = min(home, owned)
            home_total += home
            owned_total += owned
            sources.append({
                "village_id": vid,
                "home_pop": home,
                "total_pop": owned,
                "pct": round(home / owned * 100, 1),
            })

        if owned_total <= 0:
            return None, sources
        return home_total / owned_total, sources

    @staticmethod
    def _source_village_ids(data):
        """
        Distinct source villages of an operation, clear village first.

        `noble_villages` holds one entry per noble *attack*, so the same
        village legitimately repeats there; anything counting villages has to
        de-duplicate, anything counting attacks must not.
        """
        source_ids = []
        if data.get("clear_village_id"):
            source_ids.append(str(data["clear_village_id"]))
        for vid in (data.get("noble_villages") or []):
            if str(vid) not in source_ids:
                source_ids.append(str(vid))
        return source_ids

    @classmethod
    def _population(cls, troops):
        """Farm population of a troop dict, ignoring non-combat units."""
        total = 0
        for unit, qty in (troops or {}).items():
            if unit in cls.NON_COMBAT_UNITS:
                continue
            try:
                total += int(qty) * UNIT_POP.get(unit, 0)
            except (TypeError, ValueError):
                continue
        return total

    # ------------------------------------------------------------------
    # Step 2 — Simulate & Schedule
    # ------------------------------------------------------------------

    def _step_simulate(self, target_id, data):
        """
        Reads the scout report, runs the simulator with the designated
        clear village's troops, and — if the attack is viable — creates
        a Hunter schedule (clear + nobles).
        """
        scout_report = self._find_scout_report(target_id)
        scout_override = bool(data.get("scout_override"))
        if not scout_report and not scout_override:
            # Scout report not yet available — wait next cycle
            age = time.time() - data.get("scout_sent_at", time.time())
            if age > 7200:
                logger.warning(
                    "PvpConquest: no scout report for %s after 2h — resetting to pending_scout",
                    target_id
                )
                data["status"] = "pending_scout"
                PvpConquestCache.set(target_id, data)
            return

        cfg = self.config.get("pvp_conquest", {})
        min_attack_power = cfg.get("min_attack_power", 50000)
        nobles_per_target = cfg.get("nobles_per_target", 4)
        arrival_buffer = cfg.get("arrival_buffer_seconds", 2)

        # Determine clear village
        clear_vid = data.get("clear_village_id")
        if not clear_vid or clear_vid not in self.villages:
            clear_vid = self._select_clear_village()
            if not clear_vid:
                logger.warning("PvpConquest: no offensive village available to clear %s", target_id)
                data["status"] = "failed"
                data["fail_reason"] = "no_clear_village"
                PvpConquestCache.set(target_id, data)
                return
            data["clear_village_id"] = clear_vid

        clear_village = self.villages[clear_vid]
        if not clear_village.units:
            logger.warning("PvpConquest: clear village %s has no troop data", clear_vid)
            return

        # Build attacker dict using clear_ratio of available troops.
        #
        # Bugfix (2026-08-07): "spy" was never excluded here. Simulator.
        # attack_sum() (called just below) indexes every unit through
        # attack_pool, which has no "spy" entry -- so this crashed with
        # KeyError("spy") for any clear village that simply has spies
        # parked at home (i.e. virtually always, since TroopManager always
        # reports the full in-village troop count). Also excluding "snob"
        # for the same reason escort_units does: any noble sitting idle in
        # the clear village shouldn't be thrown into the clear wave by
        # accident -- it's needed for the noble train itself.
        #
        # Bugfix (2026-08-07): "knight" (Paladino) excluded too, per user:
        # the Paladin should never leave the village automatically -- only
        # in specific, deliberately chosen clearing situations, which this
        # automatic troop-selection has no way to judge. Leave it out of
        # every auto-built attack here; sending it is a manual decision,
        # not something PvpConquestManager should do on its own.
        attacker_units = self._build_clear_units(clear_village)

        if scout_report:
            defender_units = scout_report.get("extra", {}).get("defence_units", {})
            wall_level = scout_report.get("extra", {}).get("buildings", {}).get("wall", 0)

            # Feature 18: moral/night bonus were previously hardcoded to neutral
            # values (moral=100, nightbonus=False), which could make the bot
            # recommend conquests that fail in practice against much smaller
            # targets or during the world's night bonus window.
            nightbonus = False
            moral = 100
            if cfg.get("dynamic_moral_night_bonus", False):
                nightbonus = WorldConfig.is_night_bonus_active(self.world_config)
                if nightbonus is None:
                    nightbonus = True
                    logger.warning(
                        "PvpConquest: world uses per-player night bonus windows -- "
                        "assuming the bonus applies to %s (defender window unknown)",
                        target_id
                    )
                target_points = self._target_points(target_id)
                attacker_points = getattr(clear_village, "points", 0)
                if target_points is not None and attacker_points:
                    moral = WorldConfig.estimate_moral(
                        self.world_config, attacker_points, target_points
                    )
                else:
                    logger.warning(
                        "PvpConquest: missing points data for %s "
                        "(attacker=%s, defender=%s) -- falling back to moral=100",
                        target_id, attacker_points, target_points
                    )

            try:
                sim_result = self.sim.simulate(
                    attackerUnits=dict(attacker_units),
                    defenderUnits={u: int(q) for u, q in defender_units.items()},
                    wall=wall_level,
                    nightbonus=nightbonus,
                    moral=moral,
                    luck=0,
                )
            except Exception as e:
                logger.error("PvpConquest: simulator error for %s: %s", target_id, e)
                return

            att_losses = sum(sim_result["attacker"]["losses"].values())
            att_total = sum(sim_result["attacker"]["quantity"].values())
            def_losses = sum(sim_result["defender"]["losses"].values())
            def_total = sum(sim_result["defender"]["quantity"].values())
            attack_power = self.sim.get_sum(self.sim.attack_sum(attacker_units))
            defender_wiped = def_losses >= def_total * 0.9
            acceptable_losses = att_losses <= att_total * 0.5
            data["last_simulation"] = {
                "att_power": attack_power,
                "att_losses": att_losses,
                "att_total": att_total,
                "def_losses": def_losses,
                "def_total": def_total,
                "wall_before": sim_result["wall_before"],
                "wall_after": sim_result["wall_after"],
                "viable": (
                    defender_wiped and acceptable_losses
                    and attack_power >= min_attack_power
                ),
            }
            if not data["last_simulation"]["viable"]:
                logger.warning("PvpConquest: attack on %s deemed not viable", target_id)
                data["status"] = "failed"
                data["fail_reason"] = "simulation_failed"
                PvpConquestCache.set(target_id, data)
                return
        else:
            # Explicit human authorization for coordinated tribe operations.
            # No invented defender data: record clearly that viability was not
            # evaluated and let the operator own that tactical decision.
            data["last_simulation"] = {
                "att_power": self.sim.get_sum(self.sim.attack_sum(attacker_units)),
                "att_losses": 0,
                "att_total": sum(attacker_units.values()),
                "def_losses": 0,
                "def_total": 0,
                "wall_before": None,
                "wall_after": None,
                "viable": True,
                "overridden": True,
            }

        # Select the noble attack plan (Feature 11b — bugfix 2026-08-07: one
        # entry per available noble, up to nobles_per_target, not one entry
        # per village -- see _select_noble_attack_plan() docstring for why
        # a village can now contribute more than one separate attack).
        # data["noble_villages"] keeps its old key name for backward
        # compatibility (used by _release_reserve()); may now contain the
        # same village_id more than once.
        noble_villages = data.get("noble_villages") or self._select_noble_attack_plan(nobles_per_target)
        if not noble_villages:
            logger.warning("PvpConquest: no villages with nobles available for %s", target_id)
            data["status"] = "failed"
            data["fail_reason"] = "no_nobles"
            PvpConquestCache.set(target_id, data)
            return
        data["noble_villages"] = noble_villages

        # Build Hunter schedule
        arrival_ts = data.get("arrival_time")
        if not arrival_ts:
            logger.error("PvpConquest: target %s has no arrival_time set", target_id)
            return

        arrival_str = datetime.datetime.fromtimestamp(arrival_ts).strftime(DATETIME_FMT)

        attacks = []

        # Clear attack — arrives `arrival_buffer` seconds before nobles
        clear_arrival_ts = arrival_ts - arrival_buffer
        clear_arrival_str = datetime.datetime.fromtimestamp(clear_arrival_ts).strftime(DATETIME_FMT)

        # Escort for nobles: reuse ConquestManager's ratio via config.
        conquest_cfg = self.config.get("conquest", {})
        escort_ratio = conquest_cfg.get("escort_ratio", 0.5)
        noble_count = max(len(noble_villages), 1)

        # Register clear in Hunter
        self._hunter_add_schedule(
            target_id=target_id,
            arrival_str=clear_arrival_str,
            attacks=[{
                "source_village_id": clear_vid,
                "troops": attacker_units,
                "is_fake": False,
            }],
            label="clear",
        )

        # Register noble train in Hunter
        #
        # Bugfix (2026-08-07): escort per noble attack must be built from
        # THAT noble village's own troops, not the clear village's. The
        # previous code computed one shared escort_units dict from
        # clear_village.units.troops and reused it verbatim for every noble
        # attack -- if a noble village had a different troop mix (missing a
        # unit type entirely, or far fewer of it), Hunter would later try to
        # send more of that unit than the village actually had, and the
        # whole escort attack would fail once fired (server rejects it).
        #
        # Critical bugfix (2026-08-07, second pass): when a noble village is
        # ALSO the clear village (the common case with few managed villages),
        # its troops were being double-booked -- attacker_units above claims
        # clear_ratio (default 0.8) of that village's troops, and this loop
        # independently claims escort_ratio (default 0.5) of the SAME raw
        # troop count for the escort, with neither claim aware of the other.
        # 0.8 + 0.5 = 130% of what the village actually has. Observed for
        # real on target 38409: the 4 noble escorts (sent first, since
        # nobles are slower and must depart earlier) consumed their share,
        # and the clear -- sent later -- failed outright with insufficient
        # troops once it actually reached the server (confirm POST came back
        # with an error_box, Hunter logged it FAILED). Fixed by subtracting
        # attacker_units from clear_vid's own troop pool before computing
        # its escort share, so the two claims add up to at most 100% of what
        # exists instead of being computed independently against the same
        # full total. Doesn't (yet) account for a village being shared
        # across *multiple different* pvp_conquest targets scheduled at once
        # -- only one target is in play in this environment today.
        noble_attacks = self._build_noble_attacks(
            clear_vid, attacker_units, noble_villages,
            escort_ratio=escort_ratio, noble_count=noble_count,
        )

        if noble_attacks:
            self._hunter_add_schedule(
                target_id=target_id,
                arrival_str=arrival_str,
                attacks=noble_attacks,
                label="nobles",
            )

        # Bugfix (2026-08-07): reserve the exact troops just committed to
        # Hunter (clear + each noble escort) so the regular farm loop and
        # the barbarian ConquestManager don't spend them before Hunter
        # actually fires -- which can be minutes to hours from now, since
        # send times are back-computed to synchronize arrival. Without this,
        # the scheduled attack can silently fail later (server rejects the
        # attack once the troops it expects are no longer in the village).
        # Released in _step_check_complete() once these Hunter schedules
        # resolve (see _maybe_release_reserve).
        self._reserve_troops(target_id, clear_vid, attacker_units, noble_attacks)

        data["status"] = "scheduled"
        data["scheduled_at"] = int(time.time())
        PvpConquestCache.set(target_id, data)
        logger.info(
            "PvpConquest: scheduled clear + %d noble(s) for target %s, arriving %s",
            len(noble_attacks), target_id, arrival_str
        )

    # ------------------------------------------------------------------
    # Step 3 — Check completion
    # ------------------------------------------------------------------

    def _step_check_complete(self, target_id, data):
        """
        Checks if the target village is now owned by us.
        Mirrors ConquestManager._target_is_mine().

        Also releases the troop reservation created by _reserve_troops()
        once it's safe to do so -- see _maybe_release_reserve().

        If the target is NOT ours and the arrival window is long past, hands
        off to _maybe_mark_failed() -- see its docstring for why "scheduled"
        used to be a dead end.
        """
        hunter_failure = self._hunter_schedule_failure(target_id)
        if hunter_failure:
            self._release_reserve(target_id, data)
            data["reserve_released"] = True
            data["status"] = "failed"
            data["fail_reason"] = "hunter_schedule_failed"
            data["hunter_fail_reason"] = hunter_failure
            data["failed_at"] = int(time.time())
            PvpConquestCache.set(target_id, data)
            logger.error(
                "PvpConquest: Hunter schedule failed for target %s (%s)",
                target_id, hunter_failure,
            )
            return

        self._maybe_release_reserve(target_id, data)

        village_data = FileManager.load_json_file(f"cache/villages/{target_id}.json")
        player_id = self._own_player_id()
        ownership_readable = bool(village_data and player_id)

        if ownership_readable and str(village_data.get("owner", "0")) == player_id:
            data["status"] = "complete"
            data["completed_at"] = int(time.time())
            PvpConquestCache.set(target_id, data)
            logger.info("PvpConquest: target %s confirmed conquered!", target_id)
            return

        self._maybe_mark_failed(target_id, data, ownership_readable)

    # Grace period after arrival_time before a still-unconquered target is
    # declared failed. Deliberately generous (2h vs. the 1h used by
    # _maybe_release_reserve): ownership only becomes visible here once some
    # managed village's map scan refreshes cache/villages/{target_id}.json,
    # which is driven by the bot cycle, not by the attack landing. Erring
    # long costs nothing (the target just stays "scheduled" a bit longer),
    # while erring short would flag a real, successful conquest as failed.
    FAILED_GRACE_SECONDS = 7200

    def _maybe_mark_failed(self, target_id, data, ownership_readable):
        """
        Marks a scheduled target as failed once its arrival window is well
        past and the village still isn't ours.

        Why this exists: _step_check_complete() only ever transitioned
        "scheduled" -> "complete", on ownership change. If the nobles landed
        and the conquest did NOT happen -- loyalty never reached 0, the clear
        failed so the nobles died on the wall, the train got sniped -- the
        target sat in "scheduled" forever. Nothing checked whether
        arrival_time had passed without success, and nothing surfaced that
        the target needs manual attention. Only _maybe_release_reserve() had
        a time-based fallback, so the troops were freed while the target's
        own status silently lied about still being in flight. Found during
        the live validation of target 38409 (2026-08-07), where the clear
        failed on insufficient troops.

        Deliberately does NOT retry (no reset to pending_scout): re-scheduling
        would send real nobles again without knowing why the first train
        died, which is exactly the situation that warrants a human look. The
        target is left terminal and visible on /pvp_conquest, where it can be
        deleted and re-added to try again.

        ownership_readable distinguishes "we checked and it isn't ours" from
        "we couldn't check at all" (no cache/villages entry for the target,
        or no own player id resolvable) -- both are failures as far as this
        target's lifecycle goes, but they point at different problems, so
        they get different fail_reasons rather than being collapsed.
        """
        arrival_ts = data.get("arrival_time")
        if not arrival_ts:
            return
        if time.time() <= arrival_ts + self.FAILED_GRACE_SECONDS:
            return

        data["status"] = "failed"
        data["fail_reason"] = (
            "train_arrived_no_conquest" if ownership_readable else "train_outcome_unknown"
        )
        data["failed_at"] = int(time.time())
        PvpConquestCache.set(target_id, data)
        logger.warning(
            "PvpConquest: target %s marked FAILED (%s) -- arrival was %s, "
            "still not ours %.0fs later. Needs manual review; will NOT retry "
            "on its own.",
            target_id,
            data["fail_reason"],
            datetime.datetime.fromtimestamp(arrival_ts).strftime(DATETIME_FMT),
            time.time() - arrival_ts,
        )

    def _own_player_id(self):
        """
        Bugfix (2026-08-07): this used to read self.wrapper.player_id /
        self.wrapper.game_state, but WebWrapper never actually sets either
        attribute -- those only exist on per-village objects (Village.game_data,
        BuildingManager.game_state, Reports.game_state). hasattr() on the first
        one was always False, and the game_state fallback always raised
        AttributeError, which the old code caught and silently `return`ed on --
        meaning _step_check_complete() could NEVER detect a real conquest,
        even a fully confirmed one (validated live against target 38409, which
        showed status stuck on "scheduled" forever despite cache/villages/
        38409.json already showing our own ownership).

        Fixed by reading the owner id straight off any of our own managed
        villages' cache/villages/{id}.json -- those are already known-owned
        (they're keys of self.villages) and don't need any wrapper plumbing
        at all. Mirrors the equivalent fix in
        ConquestManager._target_is_mine() (game/attack.py).

        P2-35: memoized per manager instance (one per cycle). Our own player
        id cannot change mid-cycle, but this was re-reading cache/villages
        files once per scheduled target, per village, per cycle. Only a
        successful resolution is cached -- a None result stays retryable, since
        it just means no managed village's map data has landed yet.
        """
        if self._player_id:
            return self._player_id
        for vid in self.villages:
            own_data = FileManager.load_json_file(f"cache/villages/{vid}.json")
            owner = str(own_data.get("owner", "0")) if own_data else "0"
            if owner != "0":
                self._player_id = owner
                return owner
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _target_points(self, target_id):
        """
        Feature 18: reads the target's points from cache/villages/{id}.json,
        populated by game/map.py scans. Returns None if the target hasn't
        been seen by any managed village's map scan yet.
        """
        village_data = FileManager.load_json_file(f"cache/villages/{target_id}.json")
        if not village_data:
            return None
        return village_data.get("points")

    def _scout_report_index(self):
        """
        P2-35: {dest_id: most_recent_scout_report} over cache/reports.

        This used to be a full directory scan -- json.load on every file --
        redone from scratch for every target in pending_sim, on every village's
        run_pvp_conquest() call. With ~500 report files observed in the field
        and one manager per village per cycle, that was the dominant I/O cost
        of this module.

        The index is rebuilt only when the *set of filenames* changes, which
        is a sound freshness check rather than a time-based guess:
        ReportManager.read() skips any report_id already in last_reports
        ("if report_id in self.last_reports: continue"), so a cached report
        file is written exactly once and never rewritten. A new report can
        therefore only appear as a new filename, and pruning (bot.max_cached_
        reports, P2-33) only removes filenames -- both change the set and force
        a rebuild. Comparing names rather than counting them also covers a
        delete plus an add landing in the same cycle.

        The listdir still happens on every call; only the per-file json.load
        is skipped. That's deliberate -- listdir is what detects the change.
        """
        files = FileManager.list_directory("cache/reports", ends_with=".json")
        signature = frozenset(files)
        if self._reports_index is not None and self._reports_files == signature:
            return self._reports_index

        index = {}
        for fname in files:
            rep = FileManager.load_json_file(f"cache/reports/{fname}")
            if not rep or rep.get("type") != "scout":
                continue
            when = rep.get("extra", {}).get("when", 0)
            # Reports without a usable timestamp are skipped, exactly as
            # before: the old loop seeded best_ts = 0 and required
            # `when > best_ts`, so a report missing extra.when could never
            # win. Keeping that is not pedantry -- reports cached before the
            # pt-BR date fix (2026-08-07, see game/reports.py) genuinely have
            # no `when`, and accepting one here would let _step_simulate()
            # commit troops based on a scout of unknown age.
            if not when:
                continue
            dest = str(rep.get("dest"))
            best = index.get(dest)
            if best is None or when > best[0]:
                index[dest] = (when, rep)

        self._reports_index = index
        self._reports_files = signature
        return index

    def _find_scout_report(self, target_id):
        """Most recent report within the configured validity window, or None."""
        best = self._scout_report_index().get(str(target_id))
        if not best:
            return None
        when, report = best
        try:
            age = time.time() - float(when)
        except (TypeError, ValueError):
            return None
        if age < 0:
            # Small clock skew is harmless; a report far in the future is not.
            if age < -300:
                return None
        elif age > self._scout_max_age_seconds():
            return None
        return report

    def _build_clear_units(self, clear_village):
        """Build the exact clear composition used by preflight and scheduling."""
        clear_ratio = self.config.get("pvp_conquest", {}).get("clear_ratio", 0.8)
        return {
            unit: int(int(qty) * clear_ratio)
            for unit, qty in clear_village.units.troops.items()
            if int(qty) > 0 and unit not in ("spy", "snob", "knight")
            and int(int(qty) * clear_ratio) > 0
        }

    def _build_noble_attacks(
            self, clear_vid, attacker_units, noble_villages,
            escort_ratio=None, noble_count=None):
        """Build the same per-noble command list for preflight and schedule."""
        if escort_ratio is None:
            escort_ratio = self.config.get("conquest", {}).get("escort_ratio", 0.5)
        if noble_count is None:
            noble_count = max(len(noble_villages), 1)

        attacks = []
        for raw_nvid in noble_villages:
            nvid = str(raw_nvid)
            nv = self.villages.get(nvid)
            if not nv or not nv.units:
                continue
            available_troops = dict(nv.units.troops)
            if nvid == str(clear_vid):
                for unit, qty in attacker_units.items():
                    if unit in available_troops:
                        available_troops[unit] = max(
                            0, int(available_troops[unit]) - int(qty)
                        )
            escort_units = {
                unit: max(1, int(int(qty) * escort_ratio) // noble_count)
                for unit, qty in available_troops.items()
                if int(qty) > 0 and unit not in ("spy", "snob", "knight")
            }
            troops = dict(escort_units)
            troops["snob"] = 1
            attacks.append({
                "source_village_id": nvid,
                "troops": troops,
                "is_fake": False,
            })
        return attacks

    def _select_clear_village(self):
        """
        Returns the village_id with the highest offensive attack power
        (profile == 'offensive' preferred, otherwise highest axe count).

        On the first cycle after a bot restart, only the village currently
        running has a live TroopManager.  Use the last managed-cache snapshot
        for the others so an early source lock is not biased toward whichever
        village happened to run first.
        """
        best_vid = None
        best_power = 0
        for vid, village in self.villages.items():
            troops = self._source_troops(vid, village)
            if not troops:
                continue
            profile = self.config.get("villages", {}).get(vid, {}).get("profile", "")

            # Attack power proxy: axes × 40 + light × 130
            power = int(troops.get("axe", 0)) * 40 + int(troops.get("light", 0)) * 130
            if profile == "offensive":
                power *= 2  # boost offensive villages

            if power > best_power:
                best_power = power
                best_vid = vid
        return best_vid

    @staticmethod
    def _source_troops(vid, village):
        """Live home troops, falling back to the last managed-cache snapshot."""
        if village.units and village.units.troops:
            return village.units.troops
        cached = FileManager.load_json_file(f"cache/managed/{vid}.json") or {}
        return cached.get("available_troops") or {}

    def _select_noble_attack_plan(self, max_count):
        """
        Feature 11b (bugfix 2026-08-07): builds a plan of up to `max_count`
        *separate noble attacks*, one entry per available noble -- NOT one
        entry per village.

        Loyalty only drops once per battle no matter how many nobles ride
        along in the same attack (extras in that attack are wasted); to get
        N loyalty-reducing hits you need N separate attacks converging on
        the target, each carrying exactly one noble. Those N attacks can
        come from N different villages, or the same village firing several
        of its nobles as several distinct attack commands -- both are
        legitimate, and a village should never be capped at contributing
        "at most one" just because it's one village.

        The previous version (_select_noble_villages) picked one *village*
        per slot and always sent exactly 1 noble from it, so a single
        managed village sitting on 6 idle nobles would only ever commit 1
        of them to a conquest, regardless of nobles_per_target.

        Returns a list of village_ids, length <= max_count, where each
        occurrence of a village_id represents one separate attack (1 noble)
        to be built from that village -- the same village_id may repeat if
        it has more than one noble to spare. Order follows self.villages
        iteration order (dict insertion order), draining each village's
        available nobles before moving to the next.
        """
        plan = []
        for vid, village in self.villages.items():
            troops = self._source_troops(vid, village)
            if not troops:
                continue
            available = int(troops.get("snob", 0))
            for _ in range(available):
                if len(plan) >= max_count:
                    return plan
                plan.append(vid)
        return plan

    def _hunter_add_schedule(self, target_id, arrival_str, attacks, label=""):
        """
        Adds a schedule to cache/hunter/schedules.json via HunterReader.

        Critical bugfix (2026-08-07): this used to pass
        target_id=f"{target_id}_pvp_{label}" (e.g. "38409_pvp_clear") to
        HunterReader.add_schedule(), which stores that string verbatim as
        the schedule's "target_id" field. Hunter.run() (game/hunter.py)
        uses that exact field to look up village.area.map_pos and to call
        village.attack.attack(target_id, ...) -- neither works with
        anything other than a real village id, so every PvP-conquest
        schedule failed at send time with "target ... not in map_pos" and
        could never actually fire, from the very first version of this
        integration. Fixed by passing the real target_id and moving the
        clear/nobles distinction to HunterReader.add_schedule's `label`
        param instead, which only affects the cache dict key (still
        guarantees clear and nobles never collide, even if
        arrival_buffer_seconds were ever set to 0) and is stored as its own
        "label" field, never as "target_id".
        """
        try:
            from webmanager.utils import HunterReader
        except ImportError:
            try:
                from utils import HunterReader
            except ImportError:
                logger.error("PvpConquest: cannot import HunterReader")
                return

        HunterReader.add_schedule(
            target_id=target_id,
            arrival_str=arrival_str,
            attacks=attacks,
            label=label,
        )

    # ------------------------------------------------------------------
    # Troop reservation (bugfix, 2026-08-07)
    # ------------------------------------------------------------------
    #
    # Farm and the barbarian ConquestManager both run synchronously -- they
    # decide to spend troops and send the attack in the same breath, so
    # there's no window for another system to steal those troops first.
    # PvpConquestManager is different: _step_simulate() commits to a set of
    # troops *now*, but Hunter may not actually send the resulting attacks
    # until much later (send_time is back-computed from arrival_time to
    # synchronize clear + nobles). During that whole window the committed
    # troops must be visibly reserved, or farm/gather/barbarian-conquest can
    # spend them first and the scheduled attack fails when Hunter fires it.

    def _add_reserve(self, village, key, troops):
        """
        Adds `troops` ({unit: qty}) to `village`'s conquest_reserve under
        `key`, merging additively with whatever's already reserved under
        that same key (relevant if the same village is both the clear
        village and a noble village for this target).
        """
        if not village or not village.units:
            return
        current = village.units.conquest_reserve.get(key, {})
        merged = dict(current)
        for unit, qty in troops.items():
            merged[unit] = merged.get(unit, 0) + int(qty)
        village.units.conquest_reserve[key] = merged

    def _reserve_troops(self, target_id, clear_vid, attacker_units, noble_attacks):
        """
        Reserves the clear troops (from clear_vid) and every noble attack's
        escort+snob (from noble_attacks, as actually registered with
        Hunter) under the shared key "pvp:{target_id}".
        """
        key = f"pvp:{target_id}"
        self._add_reserve(self.villages.get(str(clear_vid)), key, attacker_units)
        for atk in noble_attacks:
            self._add_reserve(
                self.villages.get(str(atk["source_village_id"])), key, atk["troops"]
            )

    def _release_reserve(self, target_id, data):
        """
        Removes the "pvp:{target_id}" reservation from every village that
        had troops committed to it (clear_village_id + noble_villages, as
        recorded in the target's cache). Idempotent -- safe to call even if
        nothing is reserved (e.g. target failed before scheduling).
        """
        key = f"pvp:{target_id}"
        village_ids = set()
        if data.get("clear_village_id"):
            village_ids.add(str(data["clear_village_id"]))
        for vid in data.get("noble_villages") or []:
            village_ids.add(str(vid))
        for vid in village_ids:
            village = self.villages.get(vid)
            if village and village.units and village.units.conquest_reserve.pop(key, None):
                logger.info(
                    "PvpConquest: released troop reservation for target %s from village %s",
                    target_id, vid
                )

    def _hunter_schedules_resolved(self, target_id):
        """
        Returns True once neither the clear nor the nobles Hunter schedule
        for this target still has a status of "pending" -- i.e. every
        attack in both has been sent or has failed. A schedule that was
        never created (e.g. no noble villages ended up available) counts
        as already resolved.

        Bugfix (2026-08-07, first pass): the dict key under which
        HunterReader.add_schedule actually stores a schedule is
        "{target_id}_{arrival_str}", NOT the bare "{target_id}_pvp_{label}"
        that used to be passed in as its `target_id` argument -- that value
        only ended up in the schedule's own "target_id" field, not as the
        cache dict key. A direct `schedules.get(...)` lookup by that bare
        string therefore never matched anything, which made this always
        return True (missing == "already resolved" by design) and release
        the PvP conquest troop reservation on the very next cycle, defeating
        its whole purpose. Fixed (at the time) to search by the "target_id"
        field on each stored schedule instead of the dict key.

        Bugfix (2026-08-07, second pass): that fix matched against
        "{target_id}_pvp_{label}", which was only ever a valid value to
        match against because _hunter_add_schedule() was, at the time,
        *storing* that same bogus string as the schedule's real
        "target_id" field -- which is also the field Hunter.run() uses to
        actually fire the attack (village.area.map_pos lookup,
        village.attack.attack() call). That meant every PvP-conquest
        schedule could never fire for real. Now that _hunter_add_schedule()
        stores the correct real target_id and puts "clear"/"nobles" in a
        separate "label" field instead (see its docstring), this needs to
        match on both fields together.
        """
        schedules = FileManager.load_json_file("cache/hunter/schedules.json") or {}
        for sched in schedules.values():
            if (
                str(sched.get("target_id")) == str(target_id)
                and sched.get("label") in ("clear", "nobles")
                and sched.get("status") == "pending"
            ):
                return False
        return True

    def _hunter_schedule_failure(self, target_id):
        """Return the first failure reason from this target's Hunter schedules."""
        schedules = FileManager.load_json_file("cache/hunter/schedules.json") or {}
        for sched in schedules.values():
            if (
                    str(sched.get("target_id")) != str(target_id)
                    or sched.get("label") not in ("clear", "nobles")):
                continue
            if sched.get("status") == "failed":
                for attack in sched.get("attacks", []):
                    if attack.get("status") == "failed":
                        return attack.get("fail_reason") or "send_failed"
                return "schedule_failed"
        return None

    def _maybe_release_reserve(self, target_id, data):
        """
        Releases the troop reservation once it's safe: either the Hunter
        schedules built for this target have all resolved (sent/failed), or
        -- as a robustness fallback in case that check ever misses something
        -- the arrival window is long past. Only acts once per target
        (tracked via data["reserve_released"]) to avoid pointless repeated
        cache writes every cycle.
        """
        if data.get("reserve_released"):
            return
        arrival_ts = data.get("arrival_time")
        overdue = bool(arrival_ts) and (time.time() > arrival_ts + 3600)
        if not (self._hunter_schedules_resolved(target_id) or overdue):
            return
        self._release_reserve(target_id, data)
        data["reserve_released"] = True
        PvpConquestCache.set(target_id, data)
