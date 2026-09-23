"""
Anything that has to do with the recruiting of troops
"""
import logging
import math
import random
import time

from core import game_data_shadow
from core.extractors import Extractor
from core.templates import UNIT_BUILDING
from game.resources import ResourceManager

logger = logging.getLogger("TroopManager")


class TroopManager:
    """
    Troopmanager class
    """
    can_recruit = True
    can_attack = True
    can_dodge = False
    can_scout = True
    can_farm = True
    can_gather = True
    can_unlock_scavenge = False
    can_fix_queue = True
    randomize_unit_queue = True

    queue = []
    troops = {}

    total_troops = {}

    _research_wait = 0

    wrapper = None
    village_id = None
    recruit_data = {}
    game_data = {}
    logger = None
    max_batch_size = 50
    wait_for = {}

    _waits = {}

    wanted = {"barracks": {}}

    # Maps troops to the building they are created from.
    # A definicao vive em core/templates.py, que valida os templates contra
    # este mesmo mapa. A copia que existia aqui era codigo morto -- nenhum
    # leitor em todo o projeto -- e foi justamente por nao haver consumidor
    # que o bloco "workshop" de templates/troops/offensive.txt pode sumir em
    # silencio (aríete nunca recrutado em nenhuma aldeia).
    unit_building = UNIT_BUILDING

    wanted_levels = {}

    last_gather = 0

    resman = None
    template = None

    def __init__(self, wrapper=None, village_id=None):
        """
        Create the troop manager
        """
        self.wrapper = wrapper
        self.village_id = village_id
        self.wait_for = {village_id: {"barracks": 0, "stable": 0, "garage": 0}}
        # Feature 8 / Feature 13 bugfix (2026-08-07): troops reserved by any
        # in-flight conquest commitment for this village, keyed by an owner
        # id so multiple independent reservations can coexist without one
        # overwriting another -- {owner_key: {unit: qty}}.
        #
        # Owners today:
        #   "barbarian_conquest" -- ConquestManager (Feature 8), set when
        #     nobles are ready but escort is still insufficient, so farm
        #     doesn't spend the escort while waiting for it to build up.
        #     Cleared once the train fires (or nobles are lost).
        #   "pvp:{target_id}" -- PvpConquestManager (Feature 13), set the
        #     moment a clear+noble Hunter schedule is built, since the
        #     actual attacks may not fire for minutes to hours (Hunter
        #     waits to synchronize arrival times). Without this, farm/gather
        #     or the barbarian conquest above could spend those same troops
        #     in the meantime, causing the scheduled attack to fail when
        #     Hunter finally sends it. Released once those Hunter schedules
        #     resolve (sent or failed) -- see PvpConquestManager._release_reserve.
        #
        # Respected by AttackManager (farm, via total_conquest_reserve()) and
        # gather() below so reserved troops are never spent by either.
        self.conquest_reserve = {}
        # `village.keep_resources`: recurso poupado que o desbloqueio de
        # coleta não pode comer. Dict mutável, logo mora aqui e não no corpo
        # da classe -- há uma instância deste manager por aldeia, e um dict de
        # classe seria compartilhado por todas (1º padrão do CLAUDE.md).
        self.keep_resources = {}
        if not self.resman:
            self.resman = ResourceManager(
                wrapper=self.wrapper, village_id=self.village_id
            )

    def total_conquest_reserve(self, exclude_owner=None):
        """
        Sums conquest_reserve across every owner_key into a single
        {unit: qty} dict. This is what farm/gather should actually subtract
        -- multiple independent reservations (e.g. a barbarian noble train
        AND a PvP conquest escort from the same village at the same time)
        must stack, not overwrite each other.

        exclude_owner skips one owner_key. It exists so a reserving system can
        ask "how much is spoken for by everyone *else*" without counting its
        own reservation -- otherwise it blocks itself (see
        ConquestManager._available_troops). Callers that just want to know what
        is off-limits (farm, gather) pass nothing and get the full total.
        """
        total = {}
        for owner_key, reservation in self.conquest_reserve.items():
            if exclude_owner is not None and owner_key == exclude_owner:
                continue
            for unit, qty in reservation.items():
                total[unit] = total.get(unit, 0) + int(qty)
        return total

    def update_totals(self):
        """
        Updates the total amount of recruited units
        """
        shadow_prev = game_data_shadow.before(self.wrapper, self.village_id)
        main_data = self.wrapper.get_action(
            action="overview", village_id=self.village_id
        )
        game_data_shadow.record_reread(
            self.wrapper, self.village_id, "update_totals", shadow_prev)
        if main_data is None:
            (self.logger or logger).warning("TroopManager: request timed out, skipping this cycle")
            return
        self.game_data = Extractor.game_state(main_data)

        if self.resman:
            if "research" in self.resman.requested:
                # new run, remove request
                self.resman.requested["research"] = {}

        if not self.logger:
            village_name = self.game_data["village"]["name"]
            self.logger = logging.getLogger(f"Recruitment: {village_name}")
        self.troops = {}

        get_all = (
                f"game.php?village={self.village_id}&screen=place&mode=units&display=units"
        )
        result_all = self.wrapper.get_url(get_all)
        if result_all is None:
            self.logger.warning("TroopManager: units request timed out, skipping this cycle")
            return

        for u in Extractor.units_in_village(result_all):
            k, v = u
            self.troops[k] = v

        self.logger.debug("Units in village: %s", str(self.troops))

        if not self.can_recruit:
            return

        self.total_troops = {}
        for u in Extractor.units_owned_total(result_all):
            k, v = u
            if k in self.total_troops:
                self.total_troops[k] = self.total_troops[k] + int(v)
            else:
                self.total_troops[k] = int(v)
        self.logger.debug("Village units total: %s", str(self.total_troops))

    def start_update(self, building="barracks", disabled_units=[]):
        """
        Starts the unit update for a building
        """
        if self.wait_for[self.village_id][building] > time.time():
            human_ts = self.readable_ts(self.wait_for[self.village_id][building])
            self.logger.info(
                "%s still busy for %s",
                building, human_ts
            )
            return False

        run_selection = list(self.wanted[building].keys())
        if self.randomize_unit_queue:
            random.shuffle(run_selection)

        for wanted in run_selection:
            # Ignore disabled units
            if wanted in disabled_units:
                continue

            if wanted not in self.total_troops:
                if self.recruit(
                        wanted, self.wanted[building][wanted], building=building
                ):
                    return True
                continue

            if self.wanted[building][wanted] > self.total_troops[wanted]:
                if self.recruit(
                        wanted,
                        self.wanted[building][wanted] - self.total_troops[wanted],
                        building=building,
                ):
                    return True

        self.logger.info("Recruitment:%s up-to-date", building)
        return False

    def get_min_possible(self, entry):
        """
        Calculates which units are needed the most
        To get some balance of the total amount
        """
        return min(
            [
                math.floor(self.game_data["village"]["wood"] / entry["wood"]),
                math.floor(self.game_data["village"]["stone"] / entry["stone"]),
                math.floor(self.game_data["village"]["iron"] / entry["iron"]),
                math.floor(
                    (
                            self.game_data["village"]["pop_max"]
                            - self.game_data["village"]["pop"]
                    )
                    / entry["pop"]
                ),
            ]
        )

    def get_template_action(self, levels):
        """
        Read data from templates and determine the troops based op building progression
        """
        last = None
        wanted_upgrades = {}
        for x in self.template:
            if x["building"] not in levels:
                return last

            if x["level"] > levels[x["building"]]:
                return last

            last = x
            if "upgrades" in x:
                for unit in x["upgrades"]:
                    if (
                            unit not in wanted_upgrades
                            or x["upgrades"][unit] > wanted_upgrades[unit]
                    ):
                        wanted_upgrades[unit] = x["upgrades"][unit]

            self.wanted_levels = wanted_upgrades
        return last

    def research_time(self, time_str):
        """
        Calculates unit research time
        """
        parts = [int(x) for x in time_str.split(":")]
        return parts[2] + (parts[1] * 60) + (parts[0] * 60 * 60)

    def attempt_upgrade(self):
        """
        Attempts to upgrade or research a (new) unit type
        """
        self.logger.debug("Managing Upgrades")
        if self._research_wait > time.time():
            self.logger.debug(
                "Smith still busy for %d seconds", int(self._research_wait - time.time())
            )
            return
        unit_levels = self.wanted_levels
        if not unit_levels:
            self.logger.debug("Not upgrading because nothing is requested")
            return
        result = self.wrapper.get_action(village_id=self.village_id, action="smith")
        smith_data = Extractor.smith_data(result)
        if not smith_data:
            self.logger.debug("Error reading smith data")
            return False
        for unit_type in unit_levels:
            if not smith_data or unit_type not in smith_data["available"]:
                self.logger.warning(
                    "Unit %s does not appear to be available or smith not built yet", unit_type
                )
                continue
            wanted_level = unit_levels[unit_type]
            current_level = int(smith_data["available"][unit_type]["level"])
            data = smith_data["available"][unit_type]

            if (
                    current_level < wanted_level
                    and "can_research" in data
                    and data["can_research"]
            ):
                if "research_error" in data and data["research_error"]:
                    self.logger.debug(
                        "Skipping research of %s because of research error", unit_type
                    )
                    # Add needed resources to res manager?
                    r = True
                    if data["wood"] > self.game_data["village"]["wood"]:
                        req = data["wood"] - self.game_data["village"]["wood"]
                        self.resman.request(source="research", resource="wood", amount=req)
                        r = False
                    if data["stone"] > self.game_data["village"]["stone"]:
                        req = data["stone"] - self.game_data["village"]["stone"]
                        self.resman.request(source="research", resource="stone", amount=req)
                        r = False
                    if data["iron"] > self.game_data["village"]["iron"]:
                        req = data["iron"] - self.game_data["village"]["iron"]
                        self.resman.request(source="research", resource="iron", amount=req)
                        r = False
                    if not r:
                        self.logger.debug("Research needs resources")
                    continue
                if "error_buildings" in data and data["error_buildings"]:
                    self.logger.debug(
                        "Skipping research of %s because of building error", unit_type
                    )
                    continue

                attempt = self.attempt_research(unit_type, smith_data=smith_data)
                if attempt:
                    self.logger.info(
                        "Started smith upgrade of %s %d -> %d",
                        unit_type, current_level, current_level + 1
                    )
                    self.wrapper.reporter.report(
                        self.village_id,
                        "TWB_UPGRADE",
                        "Started smith upgrade of %s %d -> %d"
                        % (unit_type, current_level, current_level + 1),
                    )
                    return True
        return False

    def attempt_research(self, unit_type, smith_data=None):
        if not smith_data:
            result = self.wrapper.get_action(village_id=self.village_id, action="smith")
            smith_data = Extractor.smith_data(result)
        if not smith_data or unit_type not in smith_data["available"]:
            self.logger.warning(
                "Unit %s does not appear to be available or smith not built yet", unit_type
            )
            return
        data = smith_data["available"][unit_type]
        if "can_research" in data and data["can_research"]:
            if "research_error" in data and data["research_error"]:
                self.logger.debug(
                    "Ignoring research of %s because of resource error %s", unit_type, str(data["research_error"])
                )
                # Add needed resources to res manager?
                r = True
                if data["wood"] > self.game_data["village"]["wood"]:
                    req = data["wood"] - self.game_data["village"]["wood"]
                    self.resman.request(source="research", resource="wood", amount=req)
                    r = False
                if data["stone"] > self.game_data["village"]["stone"]:
                    req = data["stone"] - self.game_data["village"]["stone"]
                    self.resman.request(source="research", resource="stone", amount=req)
                    r = False
                if data["iron"] > self.game_data["village"]["iron"]:
                    req = data["iron"] - self.game_data["village"]["iron"]
                    self.resman.request(source="research", resource="iron", amount=req)
                    r = False
                if not r:
                    self.logger.debug("Research needs resources")
                return False
            if "error_buildings" in data and data["error_buildings"]:
                self.logger.debug(
                    "Ignoring research of %s because of building error %s", unit_type, str(data["error_buildings"])
                )
                return False
            if (
                    "level" in data
                    and "level_highest" in data
                    and data["level_highest"] != 0
                    and data["level"] == data["level_highest"]
            ):
                return False
            res = self.wrapper.get_api_action(
                village_id=self.village_id,
                action="research",
                params={"screen": "smith"},
                data={
                    "tech_id": unit_type,
                    "source": self.village_id,
                    "h": self.wrapper.last_h,
                },
            )
            if res:
                if "research_time" in data:
                    self._research_wait = time.time() + self.research_time(
                        data["research_time"]
                    )
                self.logger.info("Started research of %s", unit_type)
                # self.resman.update(res["game_data"])
                return True
        self.logger.info("Research of %s not yet possible", unit_type)

    @staticmethod
    def effective_gather_selection(options, configured_selection=1):
        """Return the highest unlocked option allowed by the configured cap.

        ``gather_selection`` is a ceiling, not proof that the corresponding
        option is already unlocked.  The old gather loop indexed its troop
        split directly with that configured value and stopped at the first
        locked option.  A village configured for option 4 could therefore do
        no scavenging at all while options 1-3 were available.

        Keep the user's ceiling, but calibrate the split to what the game
        actually reported on this request.  Zero means that no option can be
        used yet.  Malformed/unknown option rows are ignored conservatively.
        """
        try:
            cap = max(1, min(4, int(configured_selection)))
        except (TypeError, ValueError):
            cap = 1

        if not isinstance(options, dict):
            return 0

        unlocked = []
        for option_id, option in options.items():
            try:
                option_num = int(option_id)
            except (TypeError, ValueError):
                continue
            if not 1 <= option_num <= cap or not isinstance(option, dict):
                continue
            # Missing lock state is unknown, not evidence that the option is
            # available.  The real scavenge payload publishes a boolean here.
            if "is_locked" in option and not bool(option.get("is_locked")):
                unlocked.append(option_num)
        return max(unlocked) if unlocked else 0

    @staticmethod
    def choose_scavenge_unlock(scavenge_config, options, resources, keep=None):
        """Qual opção de coleta desbloquear agora, ou None.

        Política decidida pelo usuário em 2026-09-21 (docs/backend.md §8.5):
        *"desbloqueia quando der"* -- sem gate de excedente e sem escalonamento
        por maturidade. A única condição é poder pagar.

        Regras, todas lidas do jogo e não presumidas:

        - **Uma por vez.** `unlock_time` preenchido em QUALQUER opção significa
          que a aldeia já está desbloqueando algo, e o jogo só permite um. É
          também o que faz o bot conviver com os desbloqueios manuais do
          usuário em vez de competir com eles. Medido no br143: a opção 3 da
          BBM 029 tinha `unlock_time` durante o desbloqueio, e as opções já
          concluídas (BBM 001, as quatro) têm `unlock_time: None` -- então o
          campo é limpo ao terminar e esta guarda não trava a aldeia para
          sempre.
        - **Mais baixa pendente**, e só se os pré-requisitos dela já estiverem
          destrancados. `prerequisite_option_ids` vem da config do mundo; não
          assumimos que a ordem numérica basta, mesmo que hoje ela baste.
        - **Poder pagar os três recursos**, com `unlock_cost` lido da tela.

        `keep` é `village.keep_resources`: recurso poupado (para nobre, tipicamente)
        que o desbloqueio não pode comer. Mesma semântica da Feature 9 --
        explícito, porque `required_resources` registra o que *falta* e some
        justamente quando a reserva mais importa.

        Dado malformado é ignorado de forma conservadora: na dúvida não gasta.
        """
        if not isinstance(scavenge_config, dict) or not isinstance(options, dict):
            return None

        keep = keep if isinstance(keep, dict) else {}
        resources = resources if isinstance(resources, dict) else {}

        def state(option_id):
            entry = options.get(str(option_id)) or options.get(int(option_id))
            return entry if isinstance(entry, dict) else None

        # "Ocupada" é uma propriedade da ALDEIA, não da opção: basta um
        # desbloqueio em andamento em qualquer opção para não tentar nada.
        for entry in options.values():
            if isinstance(entry, dict) and entry.get("unlock_time") is not None:
                return None

        for option_id in sorted(
            (int(k) for k in scavenge_config if str(k).isdigit())
        ):
            current = state(option_id)
            if current is None or "is_locked" not in current:
                # Sem estado publicado não dá para saber se está trancada.
                continue
            if not bool(current.get("is_locked")):
                continue

            entry = scavenge_config.get(str(option_id)) or {}
            if not isinstance(entry, dict):
                continue

            prereqs = entry.get("prerequisite_option_ids") or []
            if not isinstance(prereqs, (list, tuple)):
                continue
            blocked = False
            for prereq in prereqs:
                prereq_state = state(prereq)
                if prereq_state is None or bool(prereq_state.get("is_locked", True)):
                    blocked = True
                    break
            if blocked:
                # Mais baixa pendente com pré-requisito preso: as acima dela
                # também estarão, porque dependem desta.
                return None

            cost = entry.get("unlock_cost")
            if not isinstance(cost, dict) or not cost:
                continue
            try:
                affordable = all(
                    int(resources.get(res, 0)) - int(keep.get(res, 0)) >= int(amount)
                    for res, amount in cost.items()
                )
            except (TypeError, ValueError):
                continue
            if not affordable:
                # Não pode pagar a mais baixa. Pular para uma mais cara seria
                # gastar fora de ordem -- e o pré-requisito a impediria.
                return None
            return option_id

        return None

    @staticmethod
    def gather_option_keys(options, selection):
        """Option keys at or below ``selection``, highest first.

        The game currently publishes the strings ``"1"`` through ``"4"``.
        Filtering here keeps one malformed row from aborting every otherwise
        valid gather option in the village.
        """
        if not isinstance(options, dict):
            return []

        ordered = []
        for option_id in options:
            try:
                option_num = int(option_id)
            except (TypeError, ValueError):
                continue
            if 1 <= option_num <= selection:
                ordered.append((option_num, option_id))
        ordered.sort(key=lambda entry: entry[0], reverse=True)
        return [option_id for _, option_id in ordered]

    def unlock_scavenge(self, result, options):
        """Desbloqueia a coleta mais baixa pendente, se der para pagar.

        Recebe a resposta que `gather()` **já** baixou em vez de buscar a tela
        de novo: o limite de taxa é da CONTA, e em 2026-09-21 o servidor já
        respondeu *"você está fazendo muitos pedidos"* -- uma feature nova
        disputa orçamento de requisição com o farm. Por isso o desbloqueio
        custa zero GET extra e no máximo um POST por ciclo por aldeia.

        Como só roda de dentro de `gather()`, fica implicitamente preso a
        `gather_enabled`. Isso é intencional: desbloquear coleta numa aldeia
        que não coleta não rende nada.
        """
        if not self.can_unlock_scavenge:
            return False

        scavenge_config = Extractor.scavenge_config(result)
        if not scavenge_config:
            self.logger.warning(
                "Unlock: config de coleta não encontrada na tela -- sessão "
                "expirada ou markup novo? Nada desbloqueado neste ciclo."
            )
            return False

        option_id = self.choose_scavenge_unlock(
            scavenge_config, options, self.resman.actual if self.resman else {},
            keep=self.keep_resources,
        )
        if not option_id:
            return False

        entry = scavenge_config.get(str(option_id)) or {}
        cost = entry.get("unlock_cost") or {}
        res = self.wrapper.get_api_action(
            self.village_id,
            action="start_unlock",
            params={"screen": "scavenge_api"},
            data={"village_id": self.village_id, "option_id": option_id},
        )
        if res is None:
            self.logger.warning(
                "Unlock: coleta %s não confirmada pelo servidor (sem resposta)",
                option_id,
            )
            return False

        # "Mandei" e "termina" são momentos diferentes (6º padrão): o jogo
        # publica a conclusão em `unlock_time` na PRÓXIMA leitura da tela, e é
        # ela que a guarda de "uma por vez" consulta -- não este log.
        self.logger.info(
            "Unlock: iniciada coleta %s (%s) na aldeia %s por %s, %s s",
            option_id, entry.get("name"), self.village_id, cost,
            entry.get("unlock_duration_seconds"),
        )
        if self.resman:
            for resource, amount in cost.items():
                self.resman.actual[resource] = max(
                    0, int(self.resman.actual.get(resource, 0)) - int(amount)
                )
        return True

    def gather(self, selection=1, disabled_units=None, advanced_gather=True):
        """
        Used for the gather resources functionality where it uses two options:
        - Basic: all troops gather on the selected gather level
        - Advanced: troops are split
        """
        if not self.can_gather:
            return False
        url = f"game.php?village={self.village_id}&screen=place&mode=scavenge"
        result = self.wrapper.get_url(url=url)
        if result is None:
            self.logger.warning("Gather: request timed out, skipping this cycle")
            return False
        village_data = Extractor.village_data(result)
        options = (village_data or {}).get("options") or {}
        # Antes do teto efetivo de propósito: quando NADA está destrancado,
        # `selection` é 0 e o método retorna -- e é exatamente aí que
        # desbloquear é a única coisa útil a fazer.
        self.unlock_scavenge(result, options)
        selection = self.effective_gather_selection(options, selection)
        if selection == 0:
            self.logger.info("No unlocked gather operation is available yet.")
            return True
        disabled_units = disabled_units or []

        sleep = 0
        available_selection = 0

        self.troops = {}

        get_all = f"game.php?village={self.village_id}&screen=place&mode=units&display=units"
        result_all = self.wrapper.get_url(get_all)
        if result_all is None:
            self.logger.warning("Gather: units request timed out, skipping this cycle")
            return False

        for u in Extractor.units_in_village(result_all):
            k, v = u
            self.troops[k] = v

        troops = dict(self.troops)

        # Feature 8 / Feature 13: subtract all conquest reservations (summed
        # across owners -- see total_conquest_reserve()) so escort/clear
        # troops committed to any pending conquest are not sent to gather.
        reserved = self.total_conquest_reserve()
        if reserved:
            for unit, reserved_qty in reserved.items():
                if unit in troops:
                    troops[unit] = str(max(0, int(troops[unit]) - reserved_qty))

        haul_dict = [
            "spear:25",
            "sword:15",
            "heavy:50",
            "axe:10",
            "light:80"
        ]
        if "archer" in self.total_troops:
            haul_dict.extend(["archer:10", "marcher:50"])

        # ADVANCED GATHER: Goes from gather_selection to 1, trying the same time (approximately) for every gather. Active hours exclude LC and Axes, at night everything is used for gather (except Paladin)

        if advanced_gather:
            selection_map = [15, 21, 24,
                             26]  # Divider in order to split the total carrying capacity of the troops into pieces that can fit into pretty much the same time frame

            batch_multiplier = [15, 6, 3,
                                2]  # Multiplier for equal distribution of troops. Time(gather1) = Time(gather2) if gather2 = 2.5 * gather1

            troops = {key: int(value) for key, value in troops.items()}
            total_carry = 0
            for item in haul_dict:
                item, carry = item.split(":")
                if item == "knight":
                    continue
                if item in disabled_units:
                    continue
                if item in troops and int(troops[item]) > 0:
                    total_carry += int(carry) * int(troops[item])
                else:
                    pass
            gather_batch = math.floor(total_carry / selection_map[selection - 1])

            for option in self.gather_option_keys(options, selection):
                option_state = options.get(option) or {}
                self.logger.debug(
                    f"Option: {option} Locked? {option_state.get('is_locked')} Is underway? {option_state.get('scavenging_squad') is not None}")
                if not option_state.get('is_locked', True) and option_state.get('scavenging_squad') is None:
                    available_selection = int(option)
                    self.logger.info(f"Gather operation {available_selection} is ready to start.")

                    payload = {
                        "squad_requests[0][village_id]": self.village_id,
                        "squad_requests[0][option_id]": str(available_selection),
                        "squad_requests[0][use_premium]": "false",
                    }

                    curr_haul = gather_batch * batch_multiplier[available_selection - 1]
                    temp_haul = curr_haul

                    self.logger.debug(
                        f"Current Haul: {curr_haul} = Gather Batch ({gather_batch}) * Batch Multiplier {available_selection} ({batch_multiplier[available_selection - 1]})")

                    for item in haul_dict:
                        item, carry = item.split(":")
                        if item == "knight":
                            continue
                        if item in disabled_units:
                            continue

                        if item in troops and int(troops[item]) > 0:
                            troops_int = int(troops[item])
                            troops_selected = 0
                            for troop in range(troops_int):
                                if (temp_haul - int(carry) < 0):
                                    break
                                else:
                                    troops_selected += 1
                                    temp_haul -= int(carry)
                            troops_int -= troops_selected
                            troops[item] = str(troops_int)
                            payload["squad_requests[0][candidate_squad][unit_counts][%s]" % item] = str(troops_selected)
                        else:
                            payload["squad_requests[0][candidate_squad][unit_counts][%s]" % item] = "0"
                    payload["squad_requests[0][candidate_squad][carry_max]"] = str(curr_haul)
                    payload["h"] = self.wrapper.last_h
                    self.wrapper.get_api_action(
                        action="send_squads",
                        params={"screen": "scavenge_api"},
                        data=payload,
                        village_id=self.village_id,
                    )
                    sleep += random.randint(1, 5)
                    time.sleep(sleep)
                    self.last_gather = int(time.time())
                    self.logger.info(f"Using troops for gather operation: {available_selection}")
                else:
                    # A higher option being locked or already underway does
                    # not make the lower unlocked options unusable.
                    continue

        else:
            for option in self.gather_option_keys(options, selection):
                option_state = options.get(option) or {}
                self.logger.debug(
                    f"Option: {option} Locked? {option_state.get('is_locked')} Is underway? {option_state.get('scavenging_squad') is not None}")
                if not option_state.get('is_locked', True) and option_state.get('scavenging_squad') is None:
                    available_selection = int(option)
                    self.logger.info(f"Gather operation {available_selection} is ready to start.")
                    selection = available_selection

                    payload = {
                        "squad_requests[0][village_id]": self.village_id,
                        "squad_requests[0][option_id]": str(available_selection),
                        "squad_requests[0][use_premium]": "false",
                    }
                    total_carry = 0
                    for item in haul_dict:
                        item, carry = item.split(":")
                        if item == "knight":
                            continue
                        if item in disabled_units:
                            continue
                        if item in troops and int(troops[item]) > 0:
                            payload[
                                "squad_requests[0][candidate_squad][unit_counts][%s]" % item
                                ] = troops[item]
                            total_carry += int(carry) * int(troops[item])
                        else:
                            payload[
                                "squad_requests[0][candidate_squad][unit_counts][%s]" % item
                                ] = "0"
                    payload["squad_requests[0][candidate_squad][carry_max]"] = str(total_carry)
                    if total_carry > 0:
                        payload["h"] = self.wrapper.last_h
                        self.wrapper.get_api_action(
                            action="send_squads",
                            params={"screen": "scavenge_api"},
                            data=payload,
                            village_id=self.village_id,
                        )
                        self.last_gather = int(time.time())
                        self.logger.info(f"Using troops for gather operation: {selection}")
                        # Basic mode assigns the whole available army to one
                        # option.  Trying a second option would reuse the same
                        # counts and ask the server to spend troops that have
                        # just left the village.
                        break
                else:
                    # Try the next lower unlocked/idle option instead of
                    # aborting the village's whole gather pass.
                    continue
        self.logger.info("All gather operations are underway.")
        return True

    def cancel(self, building, id):
        """
        Cancel a troop recruiting action
        """
        self.wrapper.get_api_action(
            action="cancel",
            params={"screen": building},
            data={"id": id},
            village_id=self.village_id,
        )

    def recruit(self, unit_type, amount=10, wait_for=False, building="barracks"):
        """
        Recruit x amount of x from a certain building
        """
        data = self.wrapper.get_action(action=building, village_id=self.village_id)
        # Mesmo modo de falha do P1-11, mas na PRIMEIRA requisição da função:
        # get_action -> get_url devolve None em qualquer exceção de rede, e
        # Extractor.active_recruit_queue faz res.text direto -> AttributeError.
        # Este é o crash mais provável dos dois; a auditoria só viu o de baixo.
        if data is None:
            self.logger.warning(
                "Village %s: %s screen request failed, skipping recruitment this cycle",
                self.village_id, building
            )
            return False

        existing = Extractor.active_recruit_queue(data)
        if existing:
            self.logger.warning(
                "Building Village %s %s recruitment queue out-of-sync"
                % (self.village_id, building)
            )
            if not self.can_fix_queue:
                return True
            for entry in existing:
                self.cancel(building=building, id=entry)
                self.logger.info(
                    "Canceled recruit item %s on building %s" % (entry, building)
                )
            return self.recruit(unit_type, amount, wait_for, building)

        self.recruit_data = Extractor.recruit_data(data)
        # Extractor.recruit_data tem `return None` implícito quando o regex de
        # unit_managers.units não casa -- resposta 200 que não é a tela de
        # recrutamento (sessão expirada -> login, página de bot protection) ou
        # markup novo. Sem a guarda, a linha `unit_type not in self.recruit_data`
        # logo abaixo dava "argument of type 'NoneType' is not iterable".
        if not self.recruit_data:
            self.logger.warning(
                "Village %s: could not read unit data from the %s screen "
                "(session expired or markup changed?), skipping recruitment",
                self.village_id, building
            )
            return False
        self.game_data = Extractor.game_state(data)
        self.logger.info("Attempting recruitment of %d %s" % (amount, unit_type))

        if amount > self.max_batch_size:
            amount = self.max_batch_size

        if unit_type not in self.recruit_data:
            self.logger.warning(
                "Recruitment of %d %s failed because it is not researched"
                % (amount, unit_type)
            )
            self.attempt_research(unit_type)
            return False

        resources = self.recruit_data[unit_type]
        if not resources:
            self.logger.warning(
                "Recruitment of %d %s failed because invalid identifier"
                % (amount, unit_type)
            )
            return False
        if not resources["requirements_met"]:
            self.logger.warning(
                "Recruitment of %d %s failed because it is not researched"
                % (amount, unit_type)
            )
            self.attempt_research(unit_type)
            return False

        get_min = self.get_min_possible(resources)
        if get_min == 0:
            self.logger.info(
                "Recruitment of %d %s failed because of not enough resources"
                % (amount, unit_type)
            )
            self.reserve_resources(resources, amount, get_min, unit_type)
            return False

        needed_reserve = False
        if get_min < amount:
            if wait_for:
                self.logger.warning(
                    "Recruitment of %d %s failed because of not enough resources"
                    % (amount, unit_type)
                )
                self.reserve_resources(resources, amount, get_min, unit_type)
                needed_reserve = True
                return False
            if get_min > 0:
                self.logger.info(
                    "Recruitment of %d %s was set to %d because of resources"
                    % (amount, unit_type, get_min)
                )
                self.reserve_resources(resources, amount, get_min, unit_type)
                amount = get_min
                needed_reserve = True

        if not needed_reserve:
            # No need to reserve resources anymore!
            if f"recruitment_{unit_type}" in self.resman.requested:
                self.resman.requested.pop(f"recruitment_{unit_type}", None)

        result = self.wrapper.get_api_action(
            village_id=self.village_id,
            action="train",
            params={"screen": building, "mode": "train"},
            data={"units[%s]" % unit_type: str(amount)},
        )
        # get_api_action devolve None quando a resposta não é 200 ou o post
        # falhou (core/request.py). Sem a guarda, um timeout no meio de um
        # recrutamento -- que roda para toda aldeia todo ciclo -- derrubava o
        # processo com "argument of type 'NoneType' is not iterable" (P1-11).
        if result and "game_data" in result:
            self.resman.update(result["game_data"])
            self.wait_for[self.village_id][building] = int(time.time()) + (
                    amount * int(resources["build_time"])
            )
            # self.troops[unit_type] = str((int(self.troops[unit_type]) if unit_type in self.troops else 0) + amount)
            self.logger.info(
                "Recruitment of %d %s started (%s idle till %d)",
                    amount,
                    unit_type,
                    building,
                    self.wait_for[self.village_id][building],
            )
            self.wrapper.reporter.report(
                self.village_id,
                "TWB_RECRUIT",
                "Recruitment of %d %s started (%s idle till %d)"
                % (
                    amount,
                    unit_type,
                    building,
                    self.wait_for[self.village_id][building],
                ),
            )
            return True
        return False

    def reserve_resources(self, resources, wanted_times, has_times, unit_type):
        """
        Reserve resources for a certain recruiting action
        """
        # Resources per unit, batch wanted, batch already recruiting
        create_amount = wanted_times - has_times
        self.logger.debug(f"Requesting resources to recruit %d of %s", create_amount, unit_type)
        for res in ["wood", "stone", "iron"]:
            req = resources[res] * (wanted_times - has_times)
            self.resman.request(source=f"recruitment_{unit_type}", resource=res, amount=req)

    def readable_ts(self, seconds):
        """
        Human readable timestamp
        """
        seconds -= time.time()
        seconds = seconds % (24 * 3600)
        hour = seconds // 3600
        seconds %= 3600
        minutes = seconds // 60
        seconds %= 60

        return "%d:%02d:%02d" % (hour, minutes, seconds)
