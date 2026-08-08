import json
import logging
import random
import re
import time

from core.extractors import Extractor

# Mapeamento dos 8 tipos de bandeira do jogo (ver docs/bugs_flags.md).
# O bot hoje só gerencia ativamente os tipos 1 (produção) e 4 (defesa) via
# set_flag_not_under_attack/set_flag_under_attack, mas o mapeamento completo
# é usado para exibir nomes legíveis no webmanager (Feature 19).
FLAG_TYPES = {
    1: "Produção",
    2: "Recrutamento",
    3: "Ataque",
    4: "Defesa",
    5: "Sorte",
    6: "População",
    7: "Custo de cunhagem",
    8: "Saque",
}


class DefenceManager:
    wrapper = None
    village_id = None
    units = None
    map = None

    under_attack = False
    auto_evacuate = False

    allow_support_send = True
    allow_support_recv = True

    defensive_units = ["spear", "sword", "archer", "marcher", "spy"]

    hide_units = ["snob", "axe"]

    runs = 0
    logger = None
    manage_flags_enabled = True
    support_factor = 0.25
    support_max_villages = 2

    # Feature 16: só evacua imediatamente quando o comando recebido mais
    # próximo está a <= urgency_threshold_sec segundos de distância.
    # Comandos ainda distantes (horas) apenas mantêm a bandeira de defesa
    # ativa e ficam registrados em log/cache -- evita evacuação prematura
    # de tropas frágeis (e possível troca de bandeira redundante) para
    # ataques que ainda vão demorar muitos ciclos para chegar.
    urgency_threshold_sec = 1800
    incoming_eta = None
    incoming_attacker = None
    incoming_command_id = None

    _can_change_flag = False
    # True once manage_flags() has confirmed the real flag state from the
    # server at least once. Distinguishes "no flag equipped" (current_flag
    # is None, confirmed) from "state not read yet" (also falsy, but unknown).
    _flag_state_confirmed = False

    # increased production
    set_flag_not_under_attack = 1
    # increased defence
    set_flag_under_attack = 4

    _sf_logged = False

    def __init__(self, village_id=None, wrapper=None):
        self.village_id = village_id
        self.wrapper = wrapper
        self.logger = logging.getLogger("Defence Manager")
        # {(flag_type, level): attempt_count} - limita tentativas de upgrade
        # por sessão para evitar loop infinito (ver docs/bugs_flags.md Bug 2)
        self._upgrade_attempts = {}
        # Todos por instância, não por classe: existe um DefenceManager por
        # aldeia. `supported` era o Bug 3 de docs/bugs_flags.md -- suporte
        # enviado por uma aldeia marcava o alvo como "já suportado" para
        # todas as outras. Os demais são a mesma classe de problema,
        # corrigidos junto. Ver Lote 1 em docs/auditoria_codigo_2026-08-08.md
        self.supported = []
        self.attacks = []
        self.flags = {}
        # flag_index, flag_level
        self.current_flag = []
        # list of village_id, attack_state
        self.my_other_villages = {}

    def support_other(self, requesting_village):

        if self.under_attack or not self.allow_support_send:
            return False
        if not self.units:
            return False
        send_support = {}
        for u in self.defensive_units:
            if u in self.units.troops and int(self.units.troops[u]) > 0:
                send_support[u] = int(int(self.units.troops[u]) * self.support_factor)

        self.logger.info(
            "Sending requested support to village %s: %s", requesting_village, str(send_support)
        )
        return self.support(requesting_village, troops=send_support)

    def update(self, main, with_defence=False):
        ok = True
        self.manage_flags()
        self.runs += 1
        if 'no_ignored_command' in main:
            self._parse_incoming_urgency(main)
            urgent = self._is_urgent(self.incoming_eta)

            if self.incoming_eta is not None:
                self.logger.warning(
                    "Village %s: incoming command from %s, eta %ds (command_id=%s) -- %s",
                    self.village_id,
                    self.incoming_attacker or "?",
                    self.incoming_eta,
                    self.incoming_command_id or "?",
                    "urgent, evacuating now" if urgent else "not urgent yet, monitoring",
                )
            else:
                self.logger.warning(
                    "Village %s: incoming command detected, but ETA/attacker "
                    "could not be parsed from overview HTML -- treating as urgent",
                    self.village_id,
                )

            self.under_attack = True
            ok = False
            self.flag_logic(self.set_flag_under_attack)
            if self.auto_evacuate and with_defence and urgent:
                self.evacuate()
        else:
            self.incoming_eta = None
            self.incoming_attacker = None
            self.incoming_command_id = None
            self.flag_logic(self.set_flag_not_under_attack)
            if not with_defence:
                self.under_attack = False
                return False
            self.under_attack = False

            # my_other_villages já exclui a própria aldeia (village.py::
            # setup_defence_manager), mas o twb.py sobrescreve o dict no fim
            # do ciclo com um que a inclui -- daí a guarda continuar valendo.
            for vil in self.my_other_villages:
                if vil == self.village_id:
                    continue
                if len(self.supported) >= self.support_max_villages:
                    self.logger.debug(
                        "Already supported %d villages, ignoring", self.support_max_villages
                    )
                    break
                if (
                        not self.under_attack
                        and self.my_other_villages[vil]
                        and self.allow_support_send
                ):
                    if vil in self.supported:
                        continue
                    if self.support_other(vil):
                        self.supported.append(vil)
                    ok = False
        if ok:
            self.logger.info("Area OK for village %s, nice and quiet", self.village_id)
            # All is well

    def _parse_incoming_urgency(self, main):
        """
        Feature 16: lê os comandos recebidos (via Extractor.incoming_commands)
        e guarda o mais urgente em self.incoming_eta/_attacker/_command_id.

        Sem comandos parseáveis (lista vazia -- markup não reconhecido ou
        já mudou no jogo), zera o ETA/atacante/command_id explicitamente:
        _is_urgent() trata incoming_eta=None como "assume urgente", que é
        o comportamento seguro de antes da Feature 16 (evacua sempre que
        'no_ignored_command' aparece no HTML).
        """
        commands = Extractor.incoming_commands(main)
        if not commands:
            self.incoming_eta = None
            self.incoming_attacker = None
            self.incoming_command_id = None
            return
        soonest = min(commands, key=lambda c: c["eta_seconds"])
        self.incoming_eta = soonest["eta_seconds"]
        self.incoming_attacker = soonest.get("attacker")
        self.incoming_command_id = soonest.get("command_id")

    def _is_urgent(self, eta_seconds):
        # eta_seconds is None quando o parsing não achou nada usável --
        # assume urgente (fallback seguro, ver _parse_incoming_urgency).
        if eta_seconds is None:
            return True
        return eta_seconds <= self.urgency_threshold_sec

    def evacuate(self):
        if not self.units:
            return False
        to_hide = {}
        for u in self.hide_units:
            if u in self.units.troops and int(self.units.troops[u]) > 0:
                to_hide[u] = int(self.units.troops[u])
        if not to_hide or len(self.my_other_villages) == 0:
            # nothing to evacuate or nowhere to send
            return False
        for vid in self.my_other_villages:
            attack_state = self.my_other_villages[vid]
            if vid == self.village_id:
                continue
            if not attack_state:
                self.logger.info(
                    "Evacuating troops from village %s to safe haven %s: %s",
                    self.village_id, vid, str(to_hide)
                )
                self.support(vid, troops=to_hide)
                return True

    def flag_logic(self, set_flag):
        if not self.manage_flags_enabled:
            return

        # Sem confirmação do estado real via manage_flags() ainda (primeiro
        # ciclo, ou ciclo intermediário pulado pela randomização), não age.
        # Evita disparar flag_set() em todo ciclo enquanto current_flag
        # está vazio apenas por falta de leitura, não por ausência real.
        if not self._flag_state_confirmed:
            return

        highest_flag_possible = self.get_highest_flag_possible(flag_id=set_flag)
        if not highest_flag_possible:
            return

        if self.current_flag:
            already_correct = self.current_flag[0] == set_flag
            already_best = self.current_flag[1] >= highest_flag_possible
        else:
            # Estado confirmado: nenhuma bandeira equipada no momento.
            already_correct = False
            already_best = False

        if already_correct and already_best:
            return

        if not self._can_change_flag:
            if not self._sf_logged:
                self.logger.info(
                    "Unable to set new flag on village %s because of cool down", self.village_id
                )
                self._sf_logged = True
            return
        self._sf_logged = False
        self.flag_set(set_flag, level=highest_flag_possible)
        # Atualiza o estado local imediatamente para não re-disparar
        # flag_set() nos ciclos seguintes antes da próxima confirmação.
        self.current_flag = [set_flag, highest_flag_possible]
        self.logger.info(
            "Setting flag %d level %d for village %s",
            set_flag, highest_flag_possible, self.village_id
        )

    def flag_upgrade(self, flag, level):
        return self.wrapper.get_api_action(
            self.village_id,
            action="upgrade_flag",
            params={"screen": "flags", "h": self.wrapper.last_h},
            data={"flag_type": flag, "from_level": level},
        )

    def flag_set(self, flag, level):
        return self.wrapper.get_api_action(
            self.village_id,
            action="assign_flag",
            params={"screen": "flags", "h": self.wrapper.last_h},
            data={
                "flag_type": str(flag),
                "level": str(level),
                "village_id": self.village_id,
            },
        )

    def get_highest_flag_possible(self, flag_id=1):
        if flag_id not in self.flags:
            return None
        return self.flags[flag_id]

    def manage_flags(self):
        if not self.manage_flags_enabled:
            return
        # Randomize flag runs
        if self.runs != 0 and self.runs % random.randint(3, 8) != 0:
            return
        self.logger.info("Managing flags")

        url = f"game.php?village={self.village_id}&screen=flags"
        result = self.wrapper.get_url(url=url)
        if result is None:
            self.logger.warning("Flags: request timed out, skipping this cycle")
            return

        self._can_change_flag = '<span class="timer cooldown">' not in result.text

        get_flag_data = re.search(r"FlagsScreen\.setFlagCounts\((.+?)\);", result.text)
        if not get_flag_data:
            self.logger.warning("Error reading flag data")
            return
        # Bugfix (2026-08-07): _flag_state_confirmed used to be set True only
        # inside `if get_current_flag:` below, i.e. only when the regex for a
        # *currently equipped* flag matched. A village that has never had any
        # flag equipped (e.g. a freshly conquered one) legitimately never
        # matches that pattern, so confirmation never fired and the
        # webmanager /flags panel showed "Estado ainda não lido" forever,
        # even though this method had already successfully fetched and
        # parsed the real flags page every time it ran (confirmed live:
        # "Managing flags" logged with no warning, yet flag_state_confirmed
        # stayed false in cache/managed/*.json). Reaching this point means
        # get_flag_data already matched -- that alone is a successful read of
        # the real server state, independent of whether a flag happens to be
        # equipped right now, so confirmation belongs here instead.
        self._flag_state_confirmed = True
        # Bugfix (2026-08-07): hardcoded .png extension -- the game now
        # serves flag images as .webp (confirmed live on br143, e.g.
        # ".../graphic/flags/big/1_7.webp"), so this never matched at all
        # for a flag that was never assigned by the bot itself in this
        # runtime (self.current_flag also gets set directly, bypassing this
        # regex entirely, right after a successful flag_set() call -- which
        # is why an already-managed village with a bot-assigned flag looked
        # fine while a freshly conquered one, with a flag inherited from the
        # previous owner and never assigned by the bot, always showed "no
        # flag equipped" in the webmanager /flags panel even though it
        # genuinely had one). \w+ matches any extension, present or future.
        get_current_flag = re.search(
            r'(?s)<div id="current_flag".+?/(\d+)_(\d+)\.\w+.+?<p>(.+?)</p>.+?</div>',
            result.text,
        )
        if get_current_flag:
            if '<div id="current_flag" style="margin-top: 10px; display: none">' in result.text:
                self.logger.warning(
                    "No flag was identified on village, setting default one"
                )
                self.current_flag = None
            else:
                cflag = [int(get_current_flag.group(1)), int(get_current_flag.group(2))]
                if cflag != self.current_flag:
                    self.current_flag = cflag
                    self.logger.info(
                        "Current village flag: %s", get_current_flag.group(3).strip()
                    )
        upgraded = 0
        raw_flags = json.loads(get_flag_data.group(1))
        self.flags = {}
        for flag_type in raw_flags:
            for level in raw_flags[flag_type]:
                for amount in raw_flags[flag_type][level]:
                    if int(amount) >= 3:
                        attempt_key = (flag_type, level)
                        attempts = self._upgrade_attempts.get(attempt_key, 0)
                        if attempts >= 2:
                            self.logger.warning(
                                "Upgrade de bandeira %s/%s falhou apos %d tentativas, desistindo",
                                flag_type, level, attempts
                            )
                        else:
                            self._upgrade_attempts[attempt_key] = attempts + 1
                            upgrade_result = self.flag_upgrade(flag=flag_type, level=level)
                            if upgrade_result:
                                self.logger.info("Upgraded flag %s", flag_type)
                                self._upgrade_attempts.pop(attempt_key, None)
                                upgraded += 1
                            else:
                                self.logger.warning(
                                    "Upgrade de bandeira %s/%s falhou (tentativa %d/2)",
                                    flag_type, level, attempts + 1
                                )
                    if int(amount) > 0:
                        if int(flag_type) not in self.flags or self.flags[
                            int(flag_type)
                        ] < int(level):
                            self.flags[int(flag_type)] = int(level)
        if upgraded:
            # Da tempo do inventario do servidor refletir o upgrade antes
            # de reler o HTML, evitando reler a mesma contagem obsoleta.
            time.sleep(2)
            return self.manage_flags()

    def support(self, vid, troops=None):
        url = f"game.php?village={self.village_id}&screen=place&target={vid}"
        pre_support = self.wrapper.get_url(url)
        if pre_support is None:
            self.logger.warning("[Support] %s -> %s: request timed out, aborting", self.village_id, vid)
            return False
        pre_data = {}
        for u in Extractor.attack_form(pre_support):
            k, v = u
            pre_data[k] = v
        if troops:
            pre_data.update(troops)
        else:
            pre_data.update(self.units.troops)

        if not self.map or vid not in self.map.map_pos:
            return False

        x, y = self.map.map_pos[vid]
        post_data = {"x": x, "y": y, "target_type": "coord", "support": "Ondersteunen"}
        pre_data.update(post_data)

        confirm_url = f"game.php?village={self.village_id}&screen=place&try=confirm"
        conf = self.wrapper.post_url(url=confirm_url, data=pre_data)
        if conf is None:
            self.logger.warning("[Support] %s -> %s: confirm request timed out, aborting", self.village_id, vid)
            return False
        if '<div class="error_box">' in conf.text:
            return False
        duration = Extractor.attack_duration(conf)
        self.logger.info(
            "[Support] %s -> %s duration %f.1 h",
            self.village_id, vid, duration / 3600
        )

        confirm_data = {}
        for u in Extractor.attack_form(conf):
            k, v = u
            if k == "attack":
                continue
            confirm_data[k] = v
        new_data = {"h": self.wrapper.last_h}
        confirm_data.update(new_data)
        # The extractor doesn't like the empty cb value, and mistakes its value for x. So I add it here.
        if "x" not in confirm_data:
            confirm_data["x"] = x
        result = self.wrapper.get_api_action(
            village_id=self.village_id,
            action="popup_command",
            params={"screen": "place"},
            data=confirm_data,
        )

        return result
