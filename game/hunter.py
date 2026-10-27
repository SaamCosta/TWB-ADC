"""
Feature 10: Coordinated attack scheduler (Hunter).

Manages noble trains and fake attacks from multiple source villages
with simultaneous arrival at the target.

Schedule format in config.json under the "hunter" key:

  "hunter": {
    "enabled": true,
    "schedules": [
      {
        "target_id": "12345",
        "arrival_time": "2026-06-21 15:00:00",
        "attacks": [
          {"source_village_id": "111", "troops": {"axe": 5000, "snob": 1}, "is_fake": false},
          {"source_village_id": "222", "troops": {"axe": 5000, "snob": 1}, "is_fake": false},
          {"source_village_id": "333", "troops": {"axe": 3000},            "is_fake": true}
        ]
      }
    ]
  }

Um comando pode ser APOIO (`"kind": "support"`, §8.61): sai pelo botao de
apoio da praca (`DefenceManager.support`) e o schedule pode levar
`arrive_after` -- o instante antes do qual ele NAO pode pousar. E o apoio
agendado para chegar alguns segundos depois de um nobre nosso: pousando
antes, ele defenderia a aldeia contra o proprio trem. `after_sched` liga o
apoio ao schedule do trem; se um nobre de la falhou, o apoio nao sai.

Runtime state is persisted in cache/hunter/schedules.json.
Each attack's send_time is computed by probing the confirm page so the
server's own travel-time calculation is used — no local formula needed.
"""

import copy
import datetime
import logging
import time

from core.extractors import Extractor
from core.village_label import village_label
from core.file_lock import file_lock
from core.filemanager import FileManager
from core.notification import Notification


class Hunter:
    SCHEDULE_CACHE = "cache/hunter/schedules.json"
    DATETIME_FMT = "%Y-%m-%d %H:%M:%S"

    # Janela de silencio: a menos disto de uma saida, todo checkpoint entrega
    # o controle ao Hunter, que espera o segundo exato e manda. Era 120 s; em
    # 2026-10-08 um checkpoint passou com 168 s de folga, o trecho seguinte
    # levou 174 s e o 4o nobre do trem contra a 57033 saiu 6 s atrasado. 300 s
    # e o valor pedido pelo usuario. O que garante que nenhuma tarefa engula a
    # janela nao e este numero, e o `gate()` abaixo.
    window = 300
    # Folga que o Hunter precisa ANTES da saida para agir: prime da origem num
    # processo novo (~4 requisicoes, ~60 s medidos) mais o GET da praca. Uma
    # tarefa so comeca se a previsao dela terminar antes de `saida - PREP`.
    PREP_SECONDS = 90
    # Teto de voltas do gate() por chamada: cada volta despacha uma saida, e
    # nenhum checkpoint precisa servir mais que isso de uma vez.
    GATE_MAX_ROUNDS = 8
    PROBE_RETRY_SECONDS = 60
    # Sonda recusada pelo jogo (falta de unidade, alvo invalido): a proxima
    # so depois disto (§8.72).
    PROBE_REFUSED_RETRY_SECONDS = 900
    # Unidades da mais lenta para a mais rapida (minutos por campo na base:
    # nobre 35, ariete e catapulta 30, espada 22, lanca/machado/arqueiro 18,
    # pesada 11, leve/arqueiro a cavalo/paladino 10, explorador 9). O fator do
    # mundo multiplica todas igual, entao a ordem vale em qualquer mundo. A
    # duracao de um comando e a da sua unidade mais lenta.
    SLOWEST_FIRST = ("snob", "ram", "catapult", "sword", "spear", "axe", "archer",
                     "heavy", "light", "marcher", "knight", "spy")
    # Quanto antes da janela um processo que acabou de subir precisa acordar.
    # Medido em 2026-09-27: da volta da rede ate o Hunter conseguir agir foram
    # ~100 s (login, visao geral, reservas, estatisticas, comandos no ar e o
    # prime das origens). Quem dorme "ate a janela" sem essa folga acorda na
    # hora certa e chega atrasado -- foi o que perdeu o 4o nobre da 55647.
    WAKE_MARGIN = 120
    # Envio cronometrado (§8.72): o ataque comeca (praca + confirmacao) isto
    # antes do `send_time`, e so o POST final espera o instante. Cobre as duas
    # requisicoes (~1 s em priority_mode) e um relogio local alguns segundos a
    # frente do servidor; o `AttackManager` mede o deslocamento e acerta.
    PREARM_SECONDS = 10

    def __init__(self, wrapper=None):
        self.wrapper = wrapper
        # Populated by twb.py each cycle: {village_id: Village}
        self.villages = {}
        self.logger = logging.getLogger("Hunter")
        # Trava de reentrada: o prime preguicoso abaixo roda codigo de Village,
        # e nenhum checkpoint dali pode chamar o Hunter de volta no meio.
        self._running = False
        # Avisos de Telegram acumulados durante o run() e enviados so no fim:
        # `Notification.send` faz rede e pode levar segundos, e dentro da
        # janela de envio cada segundo e de outro comando do mesmo trem.
        self._notes = []
        # A ultima `_probe_duration()` foi recusada pelo jogo (error_box).
        self._probe_refused = False
        # Origens que a sonda ja tentou primar neste processo.
        self._probe_primed = set()

    # ------------------------------------------------------------------
    # Schedule persistence
    # ------------------------------------------------------------------

    def _load_schedules(self):
        return FileManager.load_json_file(self.SCHEDULE_CACHE) or {}

    def _save_schedules(self, schedules, baseline=None):
        """
        Grava so o que ESTE processo mudou desde `baseline` (a copia lida no
        inicio), por cima do que esta no disco agora.

        A26-12: o `_run()` le o arquivo, dorme ate 120 s na janela de envio e
        gravava a copia inteira de volta. Um schedule criado pelo painel nesse
        intervalo sumia, e um apagado voltava. Agora a gravacao rele o disco
        sob `file_lock` e aplica `merge_schedule_changes()`.
        """
        path = FileManager.get_path(self.SCHEDULE_CACHE)
        with file_lock(path):
            try:
                disk = FileManager.load_json_file(self.SCHEDULE_CACHE)
            except Exception as exc:
                # Arquivo corrompido: gravar a nossa copia inteira, como antes
                # do A26-12, e melhor que mesclar com um vazio e perder os
                # schedules que nao mudaram.
                self.logger.warning(
                    "Hunter: %s ilegivel na gravacao (%s) -- gravando a copia "
                    "deste processo inteira", self.SCHEDULE_CACHE, exc
                )
                FileManager.save_json_file(schedules, self.SCHEDULE_CACHE)
                return
            if disk is None:
                disk = {}  # arquivo apagado: quem apagou quis zerar
            merged, dropped = self.merge_schedule_changes(disk, schedules, baseline)
            for key in dropped:
                self.logger.warning(
                    "Hunter: schedule %s foi apagado fora do bot enquanto ele "
                    "rodava -- nao sera recriado", key
                )
            FileManager.save_json_file(merged, self.SCHEDULE_CACHE)

    @staticmethod
    def merge_schedule_changes(disk, mine, baseline):
        """
        Aplica as mudancas de `mine` (em relacao a `baseline`) sobre `disk`.

        - schedule que nao existia em `baseline`: foi criado por nos, entra;
        - schedule que mudou em relacao a `baseline`: entra, mas so se ainda
          existir no disco -- se sumiu, alguem apagou de proposito, e ele vai
          para a lista `dropped`;
        - schedule que nao mudou: fica o que esta no disco (o outro lado pode
          ter mexido nele);
        - schedule que so existe no disco: fica.

        `baseline=None` trata tudo de `mine` como criado por nos.
        Devolve `(merged, dropped)`.
        """
        baseline = baseline or {}
        merged = dict(disk)
        dropped = []
        for key, sched in mine.items():
            if key not in baseline:
                merged[key] = sched
            elif sched != baseline[key]:
                if key in disk:
                    merged[key] = sched
                else:
                    dropped.append(key)
        return merged, dropped

    @classmethod
    def remove_schedule(cls, sched_key):
        """
        Apaga um schedule sob a mesma trava do resto. Devolve o schedule
        removido, ou None se ele nao existia.
        """
        path = FileManager.get_path(cls.SCHEDULE_CACHE)
        with file_lock(path):
            schedules = FileManager.load_json_file(cls.SCHEDULE_CACHE) or {}
            sched = schedules.pop(sched_key, None)
            if sched is not None:
                FileManager.save_json_file(schedules, cls.SCHEDULE_CACHE)
        return sched

    def _schedule_deleted(self, sched_key):
        """
        True so quando o arquivo foi lido e o schedule nao esta mais nele.

        Arquivo vazio ou ilegivel responde False: um soluco de leitura nao
        pode cancelar um nobre. O custo e nao enxergar o caso "apagaram o
        ultimo schedule" -- esse comando ainda sai.
        """
        try:
            disk = self._load_schedules()
        except Exception as exc:
            # load_json_file LEVANTA em JSON corrompido. Esta leitura roda
            # dentro da janela de envio, depois da espera: deixar a excecao
            # subir derrubaria o run() e o comando nao sairia.
            self.logger.warning(
                "Hunter: nao consegui reler %s antes do envio (%s) -- enviando "
                "assim mesmo", self.SCHEDULE_CACHE, exc
            )
            return False
        return bool(disk) and sched_key not in disk

    # ------------------------------------------------------------------
    # Config → cache bootstrap
    # ------------------------------------------------------------------

    def build_schedules_from_config(self, config):
        """
        Reads hunter.schedules from config and writes to cache, probing
        travel durations to calculate exact per-attack send_times.

        - Deduplicates by (target_id, arrival_time) — safe to call every cycle.
        - Schedules whose arrival_time has already passed are skipped silently.
        - If a travel-duration probe fails, the attack is stored without a
          send_time and retried next cycle inside run().
        """
        cfg_schedules = config.get("hunter", {}).get("schedules", [])
        if not cfg_schedules:
            return

        cached = self._load_schedules()
        baseline = copy.deepcopy(cached)
        changed = False

        for entry in cfg_schedules:
            target_id = str(entry.get("target_id", ""))
            arrival_str = entry.get("arrival_time", "")
            if not target_id or not arrival_str:
                self.logger.warning("Hunter: schedule entry missing target_id or arrival_time, skipping")
                continue

            try:
                arrival_ts = datetime.datetime.strptime(
                    arrival_str, self.DATETIME_FMT
                ).timestamp()
            except ValueError:
                self.logger.error(
                    "Hunter: invalid arrival_time '%s' (expected %s), skipping",
                    arrival_str, self.DATETIME_FMT
                )
                continue

            if arrival_ts < time.time():
                self.logger.debug(
                    "Hunter: schedule for target %s at %s is in the past, skipping",
                    village_label(target_id), arrival_str
                )
                continue

            # Stable key: survives config reloads, avoids duplicates
            sched_key = f"{target_id}_{arrival_str.replace(' ', 'T')}"
            if sched_key in cached:
                continue  # already registered

            attacks = []
            for atk_cfg in entry.get("attacks", []):
                source_id = str(atk_cfg.get("source_village_id", ""))
                troops = atk_cfg.get("troops", {})
                is_fake = bool(atk_cfg.get("is_fake", False))
                kind = "support" if atk_cfg.get("kind") == "support" else "attack"

                if not source_id or not troops:
                    self.logger.warning(
                        "Hunter: attack entry missing source_village_id or troops, skipping"
                    )
                    continue

                send_time = None
                duration = self._probe_duration(source_id, target_id, troops, kind=kind)
                if duration is not None:
                    send_time = arrival_ts - duration
                    if send_time < time.time():
                        self.logger.warning(
                            "Hunter: send_time for %s -> %s already passed (%.0fs ago), skipping attack",
                            village_label(source_id), village_label(target_id), time.time() - send_time
                        )
                        continue
                    self.logger.info(
                        "Hunter: %s -> %s  travel=%.0fs  send_at=%s  [%s]",
                        village_label(source_id), village_label(target_id), duration,
                        datetime.datetime.fromtimestamp(send_time).strftime(self.DATETIME_FMT),
                        "APOIO" if kind == "support" else ("FAKE" if is_fake else "REAL"),
                    )
                else:
                    self.logger.warning(
                        "Hunter: could not probe duration %s -> %s, will retry next cycle",
                        village_label(source_id), village_label(target_id)
                    )

                attacks.append({
                    "source_village_id": source_id,
                    "troops": troops,
                    "is_fake": is_fake,
                    "kind": kind,
                    "send_time": send_time,   # None until probed
                    "status": "pending",
                })

            if not attacks:
                self.logger.warning(
                    "Hunter: no valid attacks for schedule %s, skipping", sched_key
                )
                continue

            cached[sched_key] = {
                "target_id": target_id,
                "arrival_time": arrival_ts,
                "arrival_str": arrival_str,
                "status": "pending",
                "attacks": attacks,
            }
            changed = True
            self.logger.info(
                "Hunter: registered schedule %s — %d attack(s) against %s arriving %s",
                sched_key, len(attacks), village_label(target_id), arrival_str
            )

        if changed:
            self._save_schedules(cached, baseline)

    # ------------------------------------------------------------------
    # Main run — fires due attacks
    # ------------------------------------------------------------------

    def run(self, config, horizon=None):
        """
        Called once per TWB cycle (after the normal village loop).

        `horizon` (segundos) alarga a janela desta chamada: o `gate()` usa
        para segurar o bot ate uma saida que esta alem de `window`, quando a
        tarefa seguinte nao cabe antes dela e nao pode ser adiada.

        For each pending attack whose send_time is within `window` seconds:
          - Sleeps until exact send_time (blocks; priority_mode set on wrapper).
          - Fires the attack via the source village's AttackManager.
          - Deducts troops from TroopManager so farming stays accurate.

        Attacks with no send_time yet (probe failed last cycle) are retried here.
        """
        if not config.get("hunter", {}).get("enabled", False):
            return
        if self._running:
            return
        self._running = True
        if self.wrapper is not None:
            self.wrapper.hunter_active = True
        try:
            self._run(config, horizon=horizon)
        finally:
            self._running = False
            if self.wrapper is not None:
                self.wrapper.hunter_active = False
            # A26-18 por tabela: uma excecao no meio de um schedule nao pode
            # deixar o wrapper preso em priority_mode.
            if hasattr(self.wrapper, "priority_mode"):
                self.wrapper.priority_mode = False
            notes, self._notes = self._notes, []
            for note in notes:
                Notification.send(note)

    def gate(self, config, phase, predicted, skippable=True, village_id=None):
        """
        Decide, ANTES de uma tarefa comecar, se ela cabe ate a proxima saida.

        Devolve True para rodar a tarefa e False para adia-la nesta passada.
        Quando a saida esta perto (dentro de `window`), ou a tarefa nao cabe
        e nao pode ser adiada, o proprio gate entrega o controle ao Hunter,
        que espera o segundo exato e manda -- e so depois volta a decidir.

        `predicted` e a duracao prevista da tarefa em segundos, vinda do
        historico do medidor de ciclo (`core/phase_forecast.py`).

        2026-10-08, Barbara #57033: o checkpoint olhou a fila com 168 s de
        folga, a janela era 120 s, e o trecho seguinte (recrutamento, nobre,
        mercado e compartilhamento) levou 174 s. O 4o nobre saiu atrasado e
        foi recusado. Checkpoint que so pergunta "esta na hora?" nao basta: a
        pergunta certa e "a proxima tarefa termina antes da saida?".
        """
        if not config.get("hunter", {}).get("enabled", False) or self._running:
            return True
        predicted = max(0.0, float(predicted or 0))
        for _ in range(self.GATE_MAX_ROUNDS):
            now = time.time()
            nearest = self.nearest_send_time(after=now)
            if self.wrapper is not None:
                self.wrapper.hunter_next_send = nearest
            if not nearest:
                return True
            t_left = nearest - now
            fits = predicted + self.PREP_SECONDS < t_left
            if t_left > self.window and fits:
                return True
            if t_left > self.window and skippable:
                self.logger.info(
                    "Hunter: %s de %s adiada -- previsao %.0f s, saida agendada "
                    "em %.0f s (%s)", phase, village_label(village_id) if village_id else "conta",
                    predicted, t_left,
                    datetime.datetime.fromtimestamp(nearest).strftime(self.DATETIME_FMT)
                )
                return False
            self.logger.info(
                "Hunter: segurando antes de %s de %s -- saida em %.0f s %s",
                phase, village_label(village_id) if village_id else "conta", t_left,
                "(janela de silencio)" if t_left <= self.window
                else "(previsao %.0f s nao cabe e a tarefa nao pode ser adiada)" % predicted
            )
            self.run(config, horizon=t_left + 1)
        return True

    def _village_label(self, village_id):
        """'BBM 011 (74690)' quando o nome e conhecido, senao so o id."""
        return village_label(village_id)

    @staticmethod
    def _kind(atk):
        return "support" if atk.get("kind") == "support" else "attack"

    @staticmethod
    def _label(atk):
        if atk.get("kind") == "support":
            return "APOIO"
        return "FAKE" if atk.get("is_fake") else "REAL"

    def _note_failure(self, atk, target_id, reason):
        label = self._label(atk)
        troops = atk.get("troops") or {}
        noble = " com nobre" if int(troops.get("snob", 0) or 0) > 0 else ""
        self._notes.append(
            "Hunter [%s]: comando%s %s -> %s NAO saiu: %s"
            % (label, noble, self._village_label(atk.get("source_village_id")),
               village_label(target_id), reason)
        )

    def _note_expired(self, sched_key):
        self._notes.append(
            "Hunter: operacao %s expirou -- a hora de chegada passou sem "
            "todos os comandos terem saido" % sched_key
        )

    def _expire_schedule(self, sched_key, sched):
        """
        A chegada passou: o schedule vira `failed` e cada ataque ainda
        `pending` tambem, com `fail_reason: arrival_passed`.

        A26-04: antes so o schedule mudava. Os ataques ficavam `pending` para
        sempre, e todo consumidor que pergunta "ainda ha comando por sair?"
        lendo os ataques respondia que sim: a promocao do trem barbaro
        (`BarbarianTrainPlanner._promote_scheduled_trains`) nunca promovia, e
        a reserva do PvP (`PvpConquestManager`, que soma a tropa dos ataques
        `pending`) nunca soltava a tropa daquela origem.
        """
        pending = [a for a in sched.get("attacks", []) if a.get("status") == "pending"]
        for atk in pending:
            atk["status"] = "failed"
            atk["fail_reason"] = "arrival_passed"
        sched["status"] = "failed"
        if pending:
            self._note_expired(sched_key)

    def _ensure_source_ready(self, source_id, config):
        """
        Garante que a aldeia de origem tem AttackManager antes do envio.

        Num processo que acabou de subir (reinicio depois de queda, ou bot
        iniciado na mao perto da hora), os objetos Village ainda nao rodaram:
        sem `attack`, `_send_attack_batch()` marcaria o comando como falho. O
        prime e somente-leitura (~4 requisicoes) e e o mesmo que a conquista
        usa no inicio do ciclo.
        """
        village = self.villages.get(str(source_id))
        if not village or village.attack:
            return
        prime = getattr(village, "prime_for_conquest", None)
        if not callable(prime):
            return
        self.logger.info(
            "Hunter: aldeia %s ainda nao rodou neste processo -- lendo antes do envio",
            village_label(source_id)
        )
        prime(config=config)

    def _prime_for_probe(self, source_id, config):
        """
        A sonda de duracao precisa do `area` da origem, que so existe depois
        de a aldeia rodar no ciclo (§8.72). Mesmo prime somente-leitura de
        `_ensure_source_ready`, mas pelo `area`, e nao pelo `attack`.
        """
        village = self.villages.get(str(source_id))
        if not village or getattr(village, "area", None):
            return
        prime = getattr(village, "prime_for_conquest", None)
        if not callable(prime):
            return
        self.logger.info(
            "Hunter: aldeia %s ainda nao rodou neste processo -- lendo para a sonda",
            village_label(source_id)
        )
        prime(config=config)

    def _refuse_late(self, atk, target_id, time_to_send, why=None):
        """A hora de saida passou: o comando vira `failed`, nunca sai atrasado."""
        missed = abs(float(time_to_send))
        atk["status"] = "failed"
        atk["fail_reason"] = "send_time_missed"
        atk["missed_by_seconds"] = missed
        if why:
            atk["late_refused_because"] = why
        self.logger.error(
            "Hunter: refusing late attack %s -> %s; send_time passed %.3fs ago%s",
            village_label(atk["source_village_id"]), village_label(target_id), missed,
            " (%s)" % why if why else ""
        )
        self._note_failure(atk, target_id, "a hora de saida passou ha %.0f s" % missed)

    # ------------------------------------------------------------------
    # Nobre atrasado de trem barbaro (§8.71, fase 4)
    # ------------------------------------------------------------------

    # Teto do atraso. Cada hora de atraso e uma hora a mais de regeneracao
    # (1/h no br143) entre o pouso do trem e o deste nobre; com queda minima
    # de 20, o nobre deixa de ajudar so com ~20 h. 4 h e folga larga para o
    # caso real (BBM 008, 401 s em 19/10) sem mandar nobre de um plano velho
    # depois de um bot parado a noite inteira.
    LATE_BARB_MAX_SECONDS = 4 * 3600
    BARB_START_LOYALTY = 100

    def _conquest_record(self, target_id):
        from game.attack import ConquestCache
        return ConquestCache.get(target_id)

    def _target_owners(self, target_id):
        """
        Dono do alvo segundo CADA fonte que o bot tem: `cache/villages` (scan
        de mapa) e a lista do mundo (`map/village.txt`, `WorldVillages.entry`).
        Lista de strings, "0" = barbaro; vazia = nao sei.

        As duas, e nao a primeira que responder: para POSSE a lista do mundo e
        a fonte nova -- em 38 alvos o snapshot local dizia barbara para aldeia
        que o village.txt ja dava como de jogador, e zero no sentido inverso
        (27o padrao, §8.6).
        """
        owners = []
        data = FileManager.load_json_file(f"cache/villages/{target_id}.json")
        if data and data.get("owner") is not None:
            owners.append(str(data.get("owner")))
        for village in (self.villages or {}).values():
            world = getattr(village, "world_villages", None)
            entry = getattr(world, "entry", None)
            if callable(entry):
                try:
                    row = entry(target_id)
                except Exception:
                    row = None
                if row and row.get("owner") is not None:
                    owners.append(str(row.get("owner")))
                break  # a lista do mundo e uma so, compartilhada
        return owners

    def _late_batch(self, sched, atk):
        return [c for c in sched.get("attacks", [])
                if c.get("status") == "pending"
                and str(c.get("source_village_id")) == str(atk.get("source_village_id"))
                and c.get("send_time") is not None and atk.get("send_time") is not None
                and abs(float(c["send_time"]) - float(atk["send_time"])) < 0.5
                and self._kind(c) == self._kind(atk)]

    def late_barbarian_verdict(self, config, sched_key, sched, atk, missed):
        """
        (pode_sair, motivo). Decide se um comando ATRASADO ainda sai.

        So nobre de trem barbaro. Trem PvP, snipe, fake e apoio dependem do
        instante exato (sincronia com o clear, chegada antes do ataque
        inimigo), e atrasado eles nao cumprem a promessa: continuam recusados,
        como sempre (§8.58). Nobre de barbaro atrasado pousa DEPOIS do trem e
        ainda derruba lealdade -- vira o nobre extra da §8.41, so que saindo
        horas mais cedo.

        Tudo e reconferido aqui, na hora de agir (6o padrao):
        - o schedule e do planejador barbaro (`label` "barb") e o registro em
          `cache/conquest` aponta para ele e ainda esta `train_scheduled` --
          trem ja promovido, encerrado, perdido ou bloqueado nao recebe nobre;
        - o alvo continua barbaro e nao e nosso;
        - o atraso cabe em `LATE_BARB_MAX_SECONDS`;
        - os OUTROS nobres do trem (enviados ou ainda por sair) nao zeram a
          lealdade sozinhos nem na queda maxima. Se zerassem, este pousaria
          depois da conquista: autoconquista, nobre gasto (a moeda nao: a vaga
          volta) e a guarnicao morta pelo proprio nobre (o incidente de 12/08, §6.1).
        """
        troops = atk.get("troops") or {}
        if self._kind(atk) != "attack" or atk.get("is_fake"):
            return False, "so ataque real sai atrasado"
        if int(troops.get("snob", 0) or 0) <= 0:
            return False, "sem nobre: so nobre de trem barbaro sai atrasado"
        if sched.get("label") != "barb":
            return False, "nao e trem barbaro (PvP, snipe e manual nunca saem atrasados)"
        if missed > self.LATE_BARB_MAX_SECONDS:
            return False, "atraso de %.0f s passa do teto de %d s" % (missed, self.LATE_BARB_MAX_SECONDS)
        target_id = str(sched.get("target_id"))
        record = self._conquest_record(target_id) or {}
        if record.get("hunter_schedule_key") != sched_key:
            return False, "o registro da conquista nao aponta para este schedule"
        if record.get("status") != "train_scheduled":
            return False, "conquista em '%s', nao mais agendada" % record.get("status")
        if target_id in ((config or {}).get("villages") or {}):
            return False, "o alvo ja e nosso"
        owners = self._target_owners(target_id)
        if not owners:
            return False, "nao sei se o alvo ainda e barbaro"
        taken = [o for o in owners if o != "0"]
        if taken:
            return False, "o alvo deixou de ser barbaro (dono %s)" % taken[0]
        batch = self._late_batch(sched, atk)
        # O lote sao ESTES objetos: comparo por identidade, nao por igualdade
        # de dict (os nobres de uma mesma origem sao dicts iguais).
        ahead = sum(
            int((c.get("troops") or {}).get("snob", 0) or 0)
            for c in sched.get("attacks", [])
            if not any(c is b for b in batch) and c.get("status") in ("sent", "pending"))
        drop_range = record.get("loyalty_drop_range") or []
        try:
            drop_max = float(drop_range[1])
        except (IndexError, TypeError, ValueError):
            from game.attack import ConquestManager
            drop_max = float(ConquestManager.world_drop_range(config)[1])
        if ahead * drop_max >= self.BARB_START_LOYALTY:
            return False, ("os outros %d nobre(s) podem conquistar sozinhos (queda "
                           "maxima %.0f): este pousaria depois e autoconquistaria"
                           % (ahead, drop_max))
        return True, ("trem barbaro: os outros %d nobre(s) derrubam no maximo %.0f, "
                      "este pousa depois e segue util" % (ahead, ahead * drop_max))

    def _send_late(self, config, sched_key, sched, atk, missed, why):
        """Manda o lote atrasado da mesma origem. Marca e anota; devolve o resultado."""
        target_id = sched["target_id"]
        batch = self._late_batch(sched, atk)
        self._ensure_source_ready(atk["source_village_id"], config)
        result = self._send_attack_batch(batch, target_id)
        sent_at = int(time.time())
        village = self.villages.get(str(atk["source_village_id"]))
        duration = getattr(getattr(village, "attack", None), "last_attack_duration", None)
        for batch_atk in batch:
            batch_atk["status"] = "sent" if result else "failed"
            batch_atk["sent_at"] = sent_at
            batch_atk["late_by_seconds"] = round(missed, 1)
            if not result:
                batch_atk["fail_reason"] = "late_send_failed"
            elif duration:
                # Chegada real: a deste nobre e a do trem nao coincidem mais.
                # 0/None do parser nao vira "ja pousou" (6o padrao): sem
                # duracao, quem le cai na chegada planejada + atraso.
                batch_atk["arrival_real"] = int(sent_at + duration)
            else:
                batch_atk["arrival_real"] = int(float(sched.get("arrival_time") or 0) + missed) or None
        self.logger.warning(
            "Hunter: [ATRASADO] %d nobre(s) %s -> %s sairam %.0f s depois da hora -- %s: %s",
            len(batch), village_label(atk["source_village_id"]), village_label(target_id),
            missed, "OK" if result else "FALHOU", why)
        self._notes.append(
            "Hunter: %d nobre(s) do trem barbaro %s -> %s %s %.0f s atrasado(s) (%s)."
            % (len(batch), village_label(atk["source_village_id"]), village_label(target_id),
               "saiu/sairam" if result else "NAO saiu/sairam,", missed, why))
        return result

    def _late(self, config, sched_key, sched, atk, time_to_send):
        """Comando cuja hora passou: sai atrasado se a regra deixar, senao recusa."""
        missed = abs(float(time_to_send))
        try:
            allowed, why = self.late_barbarian_verdict(config, sched_key, sched, atk, missed)
        except Exception as exc:
            allowed, why = False, "falha ao avaliar o envio atrasado (%s)" % exc
        if allowed:
            self._send_late(config, sched_key, sched, atk, missed, why)
        else:
            self._refuse_late(atk, sched["target_id"], time_to_send, why=why)

    def _run(self, config, horizon=None):
        window = self.window if horizon is None else max(self.window, float(horizon))
        schedules = self._load_schedules()
        self.sync_schedule_reserves(schedules)
        if not schedules:
            return
        # Copia do que foi lido: na gravacao, so o que mudou em relacao a ela
        # vai para o disco (A26-12, ver _save_schedules).
        baseline = copy.deepcopy(schedules)

        now = time.time()
        changed = False

        # Resolve travel times for every schedule before choosing what to
        # service.
        for sched_key, sched in schedules.items():
            if sched.get("status") != "pending":
                continue
            if sched.get("arrival_time", 0) < now:
                self.logger.warning(
                    "Hunter: schedule %s arrival has passed without all attacks being sent — marking failed",
                    sched_key
                )
                self._expire_schedule(sched_key, sched)
                changed = True
                continue
            target_id = sched["target_id"]
            for atk in sched.get("attacks", []):
                if atk.get("status") != "pending" or atk.get("send_time") is not None:
                    continue
                last_probe = float(atk.get("last_probe_attempt", 0) or 0)
                if time.time() - last_probe < self.PROBE_RETRY_SECONDS:
                    continue
                if time.time() < float(atk.get("next_probe_at", 0) or 0):
                    continue
                atk["last_probe_attempt"] = time.time()
                changed = True
                # Origem que ainda nao rodou neste processo nao tem `area`, e
                # ficava sem sonda ate a vez dela no ciclo -- horas (§8.72).
                # Uma vez por origem: prime que falha nao se repete por minuto.
                source = str(atk["source_village_id"])
                if source not in self._probe_primed:
                    self._probe_primed.add(source)
                    self._prime_for_probe(source, config)
                self._probe_refused = False
                duration = self._probe_duration(
                    atk["source_village_id"], target_id, atk["troops"],
                    kind=self._kind(atk),
                )
                if duration is not None:
                    atk["send_time"] = sched["arrival_time"] - duration
                    atk.pop("next_probe_at", None)
                    changed = True
                elif self._probe_refused:
                    # Recusa do jogo nao muda em 60 s; repetir a cada minuto
                    # eram 2 requisicoes/min so desta sonda.
                    atk["next_probe_at"] = time.time() + self.PROBE_REFUSED_RETRY_SECONDS

        # A26-05: UMA fila com os comandos pendentes de todos os schedules,
        # por send_time. Antes a ordem era por schedule, e cada um era servido
        # ate o fim: com A em T+10 e T+100 e B em T+50, o Hunter dormia ate
        # T+100 dentro de A e o comando de B virava send_time_missed. A
        # conquista PvP grava clear e nobres em schedules separados, que e
        # exatamente esse caso.
        queue = []
        for sched_key, sched in schedules.items():
            if sched.get("status") != "pending":
                continue
            for atk in sched.get("attacks", []):
                if atk.get("status") == "pending" and atk.get("send_time") is not None:
                    queue.append((float(atk["send_time"]), sched_key, atk))
        queue.sort(key=lambda item: item[0])

        for send_time, sched_key, atk in queue:
            if atk.get("status") != "pending":
                continue  # ja saiu no lote de um comando anterior
            sched = schedules[sched_key]
            target_id = sched["target_id"]

            time_to_send = send_time - time.time()

            # A coordinated operation is defined by its arrival time.
            # Sending after the computed departure cannot recover that
            # promise; it only creates a real, late attack.  This path is
            # deliberately strict -- even the explicit PvP scout override
            # never authorizes an expired departure.
            # §8.71 fase 4: a unica excecao e o nobre de trem BARBARO, que
            # atrasado vira extra util -- ver `late_barbarian_verdict`.
            if time_to_send <= 0:
                self._late(config, sched_key, sched, atk, time_to_send)
                changed = True
                continue

            if time_to_send > window:
                continue  # not our cycle yet

            # --- Within the send window ---
            self._ensure_source_ready(atk["source_village_id"], config)
            time_to_send = send_time - time.time()
            if time_to_send <= 0:
                self._late(config, sched_key, sched, atk, time_to_send)
                changed = True
                continue
            if hasattr(self.wrapper, "priority_mode"):
                self.wrapper.priority_mode = True
            label = self._label(atk)
            # Apoio sai pelo DefenceManager, que nao tem o envio pre-armado.
            prearm = 0 if self._kind(atk) == "support" else self.PREARM_SECONDS
            self.logger.info(
                "Hunter: [%s] %s -> %s — sleeping %.1fs to hit send_time",
                label, village_label(atk["source_village_id"]), village_label(target_id), time_to_send
            )
            time.sleep(max(0.0, time_to_send - prearm))

            # 6o padrao: reconferir a premissa na hora de agir. O schedule foi
            # lido antes da espera, e o painel pode te-lo apagado nela.
            if self._schedule_deleted(sched_key):
                self.logger.warning(
                    "Hunter: schedule %s foi apagado durante a espera -- "
                    "comando %s -> %s NAO enviado",
                    sched_key, village_label(atk["source_village_id"]), village_label(target_id)
                )
                continue

            # Feature 26: commands with the same source, target and send
            # time can use the game's native train form.  Different troop
            # compositions often have different travel durations; those
            # intentionally remain separate so they still converge on the
            # requested arrival time.
            batch = [
                candidate for candidate in sched["attacks"]
                if candidate.get("status") == "pending"
                and str(candidate.get("source_village_id"))
                == str(atk.get("source_village_id"))
                and candidate.get("send_time") is not None
                and abs(float(candidate["send_time"]) - float(send_time)) < 0.5
                and self._kind(candidate) == self._kind(atk)
            ]
            # O formulario de trem da praca e de ataque; apoio sai um a um.
            if self._kind(atk) == "support":
                batch = [atk]

            if len(batch) > 1:
                self.logger.info(
                    "Hunter: batching %d attacks %s -> %s at one send time",
                    len(batch), village_label(atk["source_village_id"]), village_label(target_id)
                )

            if self._kind(atk) == "support":
                result = self._send_support(atk, sched, schedules)
            else:
                result = self._send_attack_batch(batch, target_id, send_time=send_time)
            sent_at = int(time.time())
            village = self.villages.get(str(atk["source_village_id"]))
            estimate = getattr(getattr(village, "attack", None), "last_arrival_estimate", None)
            for batch_atk in batch:
                batch_atk["status"] = "sent" if result else "failed"
                batch_atk["sent_at"] = sent_at
                if result and estimate and self._kind(atk) != "support":
                    batch_atk["arrival_real"] = estimate
                if len(batch) > 1:
                    batch_atk["batch_size"] = len(batch)
            if result and estimate and self._kind(atk) != "support":
                self.logger.info(
                    "Hunter: %s -> %s chega %s (pedido %s, desvio %+.3f s)",
                    village_label(atk["source_village_id"]), village_label(target_id),
                    datetime.datetime.fromtimestamp(estimate).strftime("%d/%m %H:%M:%S.%f")[:-3],
                    datetime.datetime.fromtimestamp(sched["arrival_time"]).strftime("%d/%m %H:%M:%S"),
                    estimate - float(sched["arrival_time"]),
                )
            changed = True

            for batch_atk in batch:
                label = self._label(batch_atk)
                self.logger.info(
                    "Hunter: [%s] %s -> %s — %s%s",
                    label, village_label(batch_atk["source_village_id"]), village_label(target_id),
                    "OK" if result else "FAILED",
                    " (batch)" if len(batch) > 1 else "",
                )
                if not result:
                    self._note_failure(
                        batch_atk, target_id,
                        batch_atk.get("fail_reason") or "o envio falhou (ver o log do Hunter)",
                    )

        if hasattr(self.wrapper, "priority_mode"):
            self.wrapper.priority_mode = False

        for sched_key, sched in schedules.items():
            if sched.get("status") != "pending":
                continue
            attacks = sched.get("attacks", [])
            if any(a.get("status") == "pending" for a in attacks):
                continue
            failed = any(a.get("status") == "failed" for a in attacks)
            sched["status"] = "failed" if failed else "complete"
            self.logger.info(
                "Hunter: schedule %s %s",
                sched_key, "failed" if failed else "complete"
            )
            changed = True

        if changed:
            self._save_schedules(schedules, baseline)

    # ------------------------------------------------------------------
    # Sleep adjuster (called by twb.py before time.sleep)
    # ------------------------------------------------------------------

    def nearest_send_time(self, after=None):
        """
        Returns the nearest pending send_time across all schedules, or None.
        twb.py uses this to shorten the inter-cycle sleep so we wake up in
        time to enter the send window.

        `after` descarta horarios ja vencidos: quem so quer saber "ate quando
        posso dormir" (o sono de rede fora) nao deve ser acordado por um
        comando que o proximo Hunter.run() vai apenas marcar como falho.
        """
        schedules = self._load_schedules()
        nearest = None
        for sched in schedules.values():
            if sched.get("status") != "pending":
                continue
            for atk in sched.get("attacks", []):
                if atk.get("status") != "pending":
                    continue
                st = atk.get("send_time")
                if after is not None and st and st <= after:
                    continue
                if st and (nearest is None or st < nearest):
                    nearest = st
        return nearest

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _probe_troops(self, village, troops):
        """
        Tropa que a sonda de ataque poe na confirmacao (§8.72): so a unidade
        mais lenta do comando, que e quem define a duracao, com o que dela
        esta em casa.

        A sonda mandava o comando inteiro, e o jogo recusa a confirmacao
        ("Não existem unidades suficientes") com o full fora em farm ou
        coleta: o `send_time` so saia quando o full inteiro estivesse em casa.
        Nao e 1 unidade porque o br143 tem limite de fake (`fake_limit`): ataque
        com populacao pequena demais e recusado na mesma confirmacao.

        Unidade fora da tabela de lentidao, ou nada da mais lenta em casa:
        o comando inteiro, como antes.
        """
        planned = {u: int(q) for u, q in (troops or {}).items() if int(q) > 0}
        if not planned or any(u not in self.SLOWEST_FIRST for u in planned):
            return dict(troops)
        slowest = next(u for u in self.SLOWEST_FIRST if u in planned)
        home = (getattr(getattr(village, "units", None), "troops", None) or {}).get(slowest)
        try:
            qty = min(planned[slowest], int(home)) if home is not None else planned[slowest]
        except (TypeError, ValueError):
            qty = planned[slowest]
        if qty <= 0:
            return dict(troops)
        return {slowest: qty}

    def _probe_duration(self, source_id, target_id, troops, kind="attack"):
        """
        Posts to the confirm page to read the server-computed travel duration.
        Returns seconds (float) or None on failure.

        `kind="support"` sonda pelo botao de APOIO, e nao pelo de ataque: a
        duracao pode ser outra (o Sinal da Aflicao do destino so acelera
        apoio), e o par attack+support no POST o jogo monta como ataque
        (§8.39). A confirmacao precisa dizer "apoio" para a sonda valer.
        """
        source_id = str(source_id)
        village = self.villages.get(source_id)
        if not village or not village.area:
            self.logger.debug(
                "Hunter: village %s not ready for duration probe (no area)", village_label(source_id)
            )
            return None

        # Mesma resolucao de coordenada que o envio usa
        # (AttackManager._resolve_position): scan de mapa desta aldeia e, na
        # falta dele, o snapshot compartilhado cache/villages.
        #
        # Tem que ser a MESMA fonte dos dois lados. Enquanto a sonda exigia
        # map_pos e o envio nao, um alvo fora do scan local desta aldeia
        # falhava aqui e o comando ficava "pending" para sempre -- sem
        # send_time, invisivel em nearest_send_time(), ate a hora de chegada
        # passar e o schedule inteiro virar "failed". Indistinguivel de "ainda
        # nao chegou a hora" no log, que e exatamente como o bug de
        # `{target}_pvp_{label}` sobreviveu desde a primeira versao desta
        # integracao (ver HunterReader.add_schedule).
        if not village.attack:
            self.logger.warning(
                "Hunter: village %s has no attack manager for duration probe",
                village_label(source_id)
            )
            return None
        position = village.attack._resolve_position(target_id)
        if position is None:
            self.logger.warning(
                "Hunter: sem coordenada para o alvo %s a partir da aldeia %s",
                village_label(target_id), village_label(source_id)
            )
            return None

        url = f"game.php?village={source_id}&screen=place&target={target_id}"
        try:
            pre = self.wrapper.get_url(url)
        except Exception as e:
            self.logger.error("Hunter: probe GET failed: %s", e)
            return None
        if pre is None:
            self.logger.warning("Hunter: probe GET timed out for %s -> %s", village_label(source_id), village_label(target_id))
            return None

        pre_data = {}
        for k, v in Extractor.attack_form(pre):
            pre_data[k] = v
        pre_data.update(troops if kind == "support" else self._probe_troops(village, troops))

        x, y = position
        pre_data.update({"x": x, "y": y, "target_type": "coord"})
        if kind == "support":
            pre_data.pop("attack", None)
            pre_data["support"] = pre_data.get("support") or "Apoio"
        else:
            pre_data["attack"] = "Aanvallen"

        confirm_url = f"game.php?village={source_id}&screen=place&try=confirm"
        try:
            conf = self.wrapper.post_url(url=confirm_url, data=pre_data)
        except Exception as e:
            self.logger.error("Hunter: probe POST failed: %s", e)
            return None
        if conf is None:
            self.logger.warning("Hunter: probe POST timed out for %s -> %s", village_label(source_id), village_label(target_id))
            return None

        if '<div class="error_box">' in conf.text:
            self._probe_refused = True
            # Logava que houve error_box, nao o que ele dizia -- e a sonda do
            # Hunter existe justamente para descobrir por que um envio nao
            # sairia. Ver Extractor.error_box_text.
            self.logger.warning(
                "Hunter: probe %s -> %s recusada pelo jogo: %s",
                village_label(source_id), village_label(target_id), Extractor.error_box_text(conf)
            )
            return None

        if kind == "support":
            if Extractor.command_confirm_kind(conf) != "support":
                self.logger.warning(
                    "Hunter: sonda de apoio %s -> %s nao voltou como apoio -- sem duracao",
                    village_label(source_id), village_label(target_id))
                return None
            # 0 e o valor de falha do parser (sexto padrao), nao viagem nula.
            return Extractor.attack_duration(conf) or None

        return Extractor.attack_duration(conf)

    SUPPORT_RESERVE_PREFIX = "apoio_agendado"
    # Ataque cadastrado a mao no painel (§8.72): schedule sem `label`. Os de
    # `label` vem do PvP ("clear"/"nobles") e do planejador barbaro ("barb"),
    # que reservam a propria tropa -- reservar de novo aqui contaria duas vezes.
    MANUAL_RESERVE_PREFIX = "hunter_manual"

    def _reserve_prefix(self, sched, atk):
        if atk.get("kind") == "support":
            return self.SUPPORT_RESERVE_PREFIX
        if not sched.get("label"):
            return self.MANUAL_RESERVE_PREFIX
        return None

    def sync_schedule_reserves(self, schedules):
        """
        Tropa de comando agendado fica reservada na origem enquanto ele esta
        pendente: a coleta e o farm respeitam `conquest_reserve` (o mesmo
        mecanismo do trem barbaro). Vale para o apoio agendado (§8.61), sem o
        qual a pesada estaria coletando na hora da saida, e para o ataque
        cadastrado a mao (§8.72), sem o qual o full saia para farm entre o
        cadastro e a saida e o envio falhava por falta de unidade. Comando que
        saiu, falhou ou sumiu solta a reserva.

        Tropa fora de casa na hora do cadastro (farm, coleta) fica de fora da
        conta do farm quando volta, entao a reserva tambem cobre ela. Apoio
        estacionado em outra aldeia nao volta sozinho.
        """
        prefixes = (self.SUPPORT_RESERVE_PREFIX, self.MANUAL_RESERVE_PREFIX)
        wanted = {}
        for sched_key, sched in (schedules or {}).items():
            if sched.get("status") != "pending":
                continue
            for atk in sched.get("attacks", []):
                if atk.get("status") != "pending":
                    continue
                prefix = self._reserve_prefix(sched, atk)
                if prefix is None:
                    continue
                key = "%s:%s" % (prefix, sched_key)
                bucket = wanted.setdefault(str(atk.get("source_village_id")), {}).setdefault(key, {})
                for unit, qty in (atk.get("troops") or {}).items():
                    if int(qty) > 0:
                        bucket[unit] = bucket.get(unit, 0) + int(qty)
        for vid, village in (self.villages or {}).items():
            reserve = getattr(getattr(village, "units", None), "conquest_reserve", None)
            if reserve is None:
                continue
            mine = wanted.get(str(vid), {})
            for key in [k for k in reserve if str(k).split(":", 1)[0] in prefixes]:
                if key not in mine:
                    reserve.pop(key, None)
            for key, troops in mine.items():
                reserve[key] = troops

    @staticmethod
    def linked_arrive_after(sched, schedules):
        """
        (instante antes do qual o apoio nao pode pousar, motivo de recusa).

        Base: `arrive_after` do proprio schedule (a chegada planejada do
        trem). Se ele aponta para o schedule do trem (`after_sched`), cada
        nobre ja enviado empurra a base para a chegada REAL dele: o Hunter
        manda alguns segundos depois do `send_time` (GET da praca, confirmacao,
        envio), e a chegada do jogo conta do envio de verdade. Limite
        superior dela: `sent_at` + (chegada planejada - `send_time`).

        Recusa se um comando com nobre do trem falhou: a aldeia nao sera
        nossa, e apoio pousando nela defende o dono -- ou fica parado numa
        barbara.
        """
        base = sched.get("arrive_after")
        linked = schedules.get(sched.get("after_sched") or "")
        if not linked:
            return base, None
        planned = float(linked.get("arrival_time") or 0)
        for atk in linked.get("attacks", []):
            if int((atk.get("troops") or {}).get("snob", 0) or 0) <= 0:
                continue
            if atk.get("status") == "failed":
                return base, "o nobre de %s no trem falhou (%s)" % (
                    village_label(atk.get("source_village_id")),
                    atk.get("fail_reason") or "sem motivo")
            if atk.get("status") == "sent" and atk.get("sent_at") and atk.get("send_time"):
                real = float(atk["sent_at"]) + (planned - float(atk["send_time"]))
                base = max(float(base or 0), real)
        return base, None

    def _send_support(self, atk, sched, schedules):
        """
        Apoio agendado (§8.61). Mesmo caminho do apoio comum
        (`DefenceManager.support`, so o botao de apoio no POST e a
        confirmacao exigida como apoio), com `arrive_after`: o jogo mostra a
        duracao na confirmacao e o envio para antes de criar o comando se o
        apoio pousaria antes do nobre.
        """
        from game.defence_manager import DefenceManager

        target_id = sched["target_id"]
        source_id = str(atk["source_village_id"])
        arrive_after, refusal = self.linked_arrive_after(sched, schedules)
        if refusal:
            atk["fail_reason"] = refusal
            self.logger.warning("Hunter: [APOIO] %s -> %s nao sai: %s", village_label(source_id),
                                village_label(target_id), refusal)
            return False
        village = self.villages.get(source_id)
        position = None
        if village and village.attack:
            position = village.attack._resolve_position(target_id)
        if position is None:
            atk["fail_reason"] = "sem coordenada do alvo"
            self.logger.error("Hunter: [APOIO] %s -> %s sem coordenada do alvo",
                              village_label(source_id), village_label(target_id))
            return False
        dm = DefenceManager(village_id=source_id, wrapper=self.wrapper)
        result = dm.support(target_id, troops=dict(atk["troops"]), position=position,
                            arrive_after=arrive_after)
        if not result:
            atk["fail_reason"] = dm.last_support_error or "envio nao confirmado"
            return False
        atk["arrival_real"] = dm.last_support_arrival
        if village and village.units:
            for unit, qty in atk["troops"].items():
                current = int(village.units.troops.get(unit, 0) or 0)
                village.units.troops[unit] = str(max(0, current - int(qty)))
        return True

    def _send_attack(self, atk, target_id):
        """
        Fires a single attack via the source village's AttackManager.
        Deducts sent troops from TroopManager immediately.
        """
        return self._send_attack_batch([atk], target_id)

    def _send_attack_batch(self, attacks, target_id, send_time=None):
        """
        Fires one or more simultaneous attacks from the same source village.

        A one-item list preserves the old single-command path.  With multiple
        items, AttackManager sends the first command normally and the rest as
        the native ``train[2..N]`` fields captured on br143.  Troops are only
        deducted after the server accepts the whole request.

        `send_time` liga o envio cronometrado (§8.72): o AttackManager prepara
        a confirmacao e segura so o POST final ate o instante.
        """
        if not attacks:
            return False

        source_id = str(attacks[0]["source_village_id"])
        if any(str(atk["source_village_id"]) != source_id for atk in attacks):
            self.logger.error(
                "Hunter: refusing mixed-source batch for target %s", village_label(target_id)
            )
            return False

        village = self.villages.get(source_id)
        if not village:
            self.logger.error("Hunter: village %s not in managed villages dict", village_label(source_id))
            return False
        if not village.attack:
            self.logger.error("Hunter: village %s has no attack manager initialised", village_label(source_id))
            return False

        primary_troops = attacks[0]["troops"]
        additional = [atk["troops"] for atk in attacks[1:]]
        # So passa `send_time` quando ha um: os substitutos leves do
        # AttackManager (integracoes, testes) nao conhecem o argumento.
        timed = {"send_time": send_time} if send_time is not None else {}
        if additional:
            result = village.attack.attack(
                target_id,
                troops=primary_troops,
                additional_attacks=additional,
                **timed
            )
        else:
            # Keep the old call shape for ordinary attacks and for lightweight
            # AttackManager substitutes used by integrations/tests.
            result = village.attack.attack(target_id, troops=primary_troops, **timed)
        if result and result != "forced_peace":
            # Keep TroopManager in sync so farming doesn't over-commit
            if village.units:
                sent = {}
                for atk in attacks:
                    for unit, qty in atk["troops"].items():
                        sent[unit] = sent.get(unit, 0) + int(qty)
                for unit, qty in sent.items():
                    current = int(village.units.troops.get(unit, 0))
                    village.units.troops[unit] = str(max(0, current - int(qty)))
            return True

        if result == "forced_peace":
            self.logger.warning(
                "Hunter: attack %s -> %s blocked by forced peace", village_label(source_id), village_label(target_id)
            )
        return False
