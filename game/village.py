import copy
import json
import logging
import time
from codecs import decode
from datetime import datetime

from core.extractors import Extractor
from core.filemanager import FileManager
from core.templates import TemplateManager
from core.twstats import TwStats
from game.attack import AttackManager, ConquestManager
from game.resource_sharing import ResourceSharingManager
from game.buildingmanager import BuildingManager
from game.defence_manager import DefenceManager
from game.map import Map
from game.reports import ReportManager
from game.resources import ResourceManager
from game.snobber import SnobManager
from game.troopmanager import TroopManager
from game.zone_manager import ZoneManager
from core.exceptions import *


class Village:
    village_id = None
    builder = None
    units = None
    wrapper = None
    resources = {}
    game_data = {}
    logger = None
    force_troops = False
    area = None
    snobman = None
    attack = None
    resman = None
    def_man = None
    rep_man = None
    config = None
    forced_peace_today = False
    village_set_name = None
    last_attack = None
    build_config = None
    current_unit_entry = None
    forced_peace = False
    forced_peace_today_start = None
    disabled_units = []

    twp = TwStats()

    def __init__(self, village_id=None, wrapper=None):
        self.village_id = village_id
        self.wrapper = wrapper

    def get_config(self, section, parameter, default=None):
        if section not in self.config:
            self.logger.warning("Configuration section %s does not exist!" % section)
            return default
        if parameter not in self.config[section]:
            self.logger.warning(
                "Configuration parameter %s:%s does not exist!" % (section, parameter)
            )
            return default
        return self.config[section][parameter]

    def get_village_config(self, village_id, parameter, default=None):
        if village_id not in self.config["villages"]:
            return default
        vdata = self.config["villages"][village_id]
        if parameter not in vdata:
            self.logger.warning(
                "Village %s configuration parameter %s does not exist!",
                village_id, parameter
            )
            return default
        return vdata[parameter]

    def village_init(self):
        """
        Init the village entry and send first request
        """
        if not self.village_id:
            data = self.wrapper.get_url("game.php?screen=overview&intro")
            if data:
                self.game_data = Extractor.game_state(data)
            if self.game_data:
                self.village_id = str(self.game_data["village"]["id"])
                self.logger = logging.getLogger(
                    "Village %s" % self.game_data["village"]["name"]
                )
                self.logger.info("Read game state for village")
        else:
            data = self.wrapper.get_url(
                f"game.php?village={self.village_id}&screen=overview"
            )
            if data:
                self.game_data = Extractor.game_state(data)
                self.logger = logging.getLogger(
                    "Village %s" % self.game_data["village"]["name"]
                )
                self.logger.info("Read game state for village")
                self.wrapper.reporter.report(
                    self.village_id,
                    "TWB_START",
                    "Starting run for village: %s" % self.game_data["village"]["name"],
                )
        if (
                self.village_set_name
                and self.game_data["village"]["name"] != self.village_set_name
        ):
            self.logger.name = f"Village {self.village_set_name}"
        return data

    def set_world_config(self):
        """
        Sets basic world options
        """
        self.disabled_units = []
        if not self.get_config(
                section="world", parameter="archers_enabled", default=True
        ):
            self.disabled_units.extend(["archer", "marcher"])

        if not self.get_config(
                section="world", parameter="building_destruction_enabled", default=True
        ):
            self.disabled_units.extend(["ram", "catapult"])

        if self.get_config(
                section="server", parameter="server_on_twstats", default=False
        ):
            self.twp.run(world=self.get_config(section="server", parameter="server"))

    def update_pre_run(self):
        """
        Manage defence, resources and reports
        """
        if not self.resman:
            self.resman = ResourceManager(
                wrapper=self.wrapper, village_id=self.village_id
            )

        self.resman.update(self.game_data)
        self.wrapper.reporter.report(
            self.village_id, "TWB_PRE_RESOURCE", str(self.resman.actual)
        )

        if not self.rep_man:
            self.rep_man = ReportManager(
                wrapper=self.wrapper, village_id=self.village_id
            )
        self.rep_man.read(full_run=False)

        if not self.def_man:
            self.def_man = DefenceManager(
                wrapper=self.wrapper, village_id=self.village_id
            )
            self.def_man.map = self.area

        if not self.def_man.units and self.units:
            self.def_man.units = self.units

    def setup_defence_manager(self, data):
        """
        Set-up the defence manager
        """
        self.def_man.manage_flags_enabled = self.get_config(
            section="world", parameter="flags_enabled", default=False
        )
        self.def_man.support_factor = self.get_village_config(
            self.village_id, "support_others_factor", default=0.25
        )

        self.def_man.allow_support_send = self.get_village_config(
            self.village_id, parameter="support_others", default=False
        )
        self.def_man.allow_support_recv = self.get_village_config(
            self.village_id, parameter="request_support_on_attack", default=False
        )
        self.def_man.auto_evacuate = self.get_village_config(
            self.village_id, parameter="evacuate_fragile_units_on_attack", default=False
        )

        # Populate other villages state so support/evacuation logic can execute.
        # Reads cache/managed/*.json written by set_cache_vars() each cycle.
        other_villages = {}
        for cache_file in FileManager.list_directory("cache/managed", ends_with=".json"):
            cached_vid = cache_file.replace(".json", "")
            if cached_vid == self.village_id:
                continue
            if cached_vid not in self.config.get("villages", {}):
                continue
            cached = FileManager.load_json_file(f"cache/managed/{cache_file}")
            if cached:
                other_villages[cached_vid] = cached.get("under_attack", False)
        self.def_man.my_other_villages = other_villages
        if other_villages:
            self.logger.debug(
                "DefenceManager: %d other villages loaded %s",
                len(other_villages), list(other_villages.keys())
            )

        self.def_man.update(
            data.text,
            with_defence=self.get_config(
                section="units", parameter="manage_defence", default=False
            ),
        )
        if self.def_man.under_attack and not self.last_attack:
            self.logger.warning("Village under attack!")
            self.wrapper.reporter.report(
                self.village_id,
                "TWB_ATTACK",
                "Village: %s under attack" % self.game_data["village"]["name"],
            )
        self.last_attack = self.def_man.under_attack

        # Feature 12: preemptive regional evacuation
        self._check_zone_evacuation()

    def _check_zone_evacuation(self):
        """
        Feature 12 — Evacuação preventiva regional.

        Se um número configurável de aldeias vizinhas na mesma zona geográfica
        estiverem sob ataque, aciona evacuação das unidades frágeis (snob, axe)
        desta aldeia antes que ela própria seja atacada.

        Pré-requisitos por aldeia:
          - evacuate_on_zone_attack: true
          - evacuate_fragile_units_on_attack: true  (reutiliza a flag existente)
          - zone_attack_threshold: N  (quantidade mínima de vizinhos sob ataque)

        Idempotente: DefenceManager.evacuate() não faz nada se já não há
        unidades frágeis em casa, portanto chamadas repetidas são seguras.
        """
        # Não duplicar com a evacuação normal (aldeia já sob ataque)
        if self.def_man.under_attack:
            return

        if not self.get_village_config(
            self.village_id, "evacuate_on_zone_attack", default=False
        ):
            return

        if not self.get_village_config(
            self.village_id, "evacuate_fragile_units_on_attack", default=False
        ):
            self.logger.debug(
                "Feature 12: evacuate_on_zone_attack=true mas "
                "evacuate_fragile_units_on_attack=false — evacuação não executada"
            )
            return

        # Carrega dados de zona do ciclo anterior (lag de 1 ciclo aceitável)
        zone_data = ZoneManager.load()
        if not zone_data:
            self.logger.debug("Feature 12: cache de zonas não disponível ainda")
            return

        zm = ZoneManager()
        zm.zones = zone_data.get("zones", {})
        zm.village_zone = zone_data.get("village_zone", {})

        neighbors = zm.get_neighbors(self.village_id)
        if not neighbors:
            self.logger.debug(
                "Feature 12: aldeia %s não possui vizinhos de zona", self.village_id
            )
            return

        # Carrega estado de ataque dos vizinhos
        managed_cache = {}
        for nid in neighbors:
            cached = FileManager.load_json_file(f"cache/managed/{nid}.json")
            if cached:
                managed_cache[nid] = cached

        neighbors_under_attack = sum(
            1 for nid in neighbors
            if managed_cache.get(nid, {}).get("under_attack", False)
        )

        threshold = self.get_village_config(
            self.village_id, "zone_attack_threshold", default=1
        )

        if neighbors_under_attack < threshold:
            self.logger.debug(
                "Feature 12: %d/%d vizinhos sob ataque (threshold=%d) — sem evacuação",
                neighbors_under_attack, len(neighbors), threshold
            )
            return

        self.logger.warning(
            "Feature 12: %d/%d vizinho(s) de zona sob ataque — "
            "acionando evacuação preventiva para aldeia %s",
            neighbors_under_attack, len(neighbors), self.village_id
        )
        self.wrapper.reporter.report(
            self.village_id,
            "TWB_ZONE_EVACUATE",
            f"Evacuação preventiva: {neighbors_under_attack}/{len(neighbors)} "
            f"vizinho(s) de zona sob ataque (threshold={threshold})"
        )
        self.def_man.evacuate()

    def run_quest_actions(self, config):
        if self.get_config(section="world", parameter="quests_enabled", default=False):
            if self.get_quests():
                self.logger.info("There where completed quests, re-running function")
                self.wrapper.reporter.report(
                    self.village_id, "TWB_QUEST", "Completed quest"
                )
                return self.run(config=config)

            if self.get_quest_rewards():
                self.wrapper.reporter.report(
                    self.village_id, "TWB_QUEST", "Collected quest reward(s)"
                )

    def units_get_template(self):
        """
        Fetches the unit template
        """
        if not self.units:
            self.units = TroopManager(wrapper=self.wrapper, village_id=self.village_id)
            self.units.resman = self.resman
        self.units.max_batch_size = self.get_config(
            section="units", parameter="batch_size", default=25
        )

        # set village templates
        unit_config = self.get_village_config(
            self.village_id, parameter="units", default=None
        )
        if not unit_config:
            self.logger.warning(
                "Village %s does not have 'units' config override!", self.village_id
            )
            unit_config = self.get_config(
                section="units", parameter="default", default="basic"
            )
        try:
            self.units.template = TemplateManager.get_template(
                category="troops", template=unit_config, output_json=True
            )
        except Exception as e:
            self.logger.error(
                "Looks like the unit template file %s is either missing or corrupted", unit_config
            )
            raise InvalidUnitTemplateException

    def run_builder(self):
        """
        Run building construction actions
        """
        if not self.builder:
            self.builder = BuildingManager(
                wrapper=self.wrapper, village_id=self.village_id
            )
            self.builder.resman = self.resman
            # manage buildings (has to always run because recruit check depends on building levels)
        self.build_config = self.get_village_config(
            self.village_id, parameter="building", default=None
        )
        if self.build_config is False:
            self.logger.debug("Builder is disabled for village %s", self.village_id)
            return
        if not self.build_config:
            self.logger.warning(
                "Village %s does not have 'building' config override, using global default!", self.village_id
            )
            self.build_config = self.get_config(
                section="building", parameter="default", default="purple_predator"
            )
        new_queue = TemplateManager.get_template(
            category="builder", template=self.build_config
        )
        if not self.builder.raw_template or self.builder.raw_template != new_queue:
            self.builder.queue = new_queue
            self.builder.raw_template = new_queue
            if not self.get_config(
                    section="world", parameter="knight_enabled", default=False
            ):
                self.builder.queue = [
                    x for x in self.builder.queue if "statue" not in x
                ]
        self.builder.max_lookahead = self.get_config(
            section="building", parameter="max_lookahead", default=2
        )
        self.builder.max_queue_len = self.get_config(
            section="building", parameter="max_queued_items", default=2
        )
        self.builder.start_update(
            build=self.get_config(
                section="building", parameter="manage_buildings", default=True
            ),
            set_village_name=self.village_set_name,
        )

    def run_snob_recruit(self):
        """
        Uses the snob to mint coins, store resources and recruit snobs
        """
        if (
                self.get_village_config(self.village_id, parameter="snobs", default=None)
                and self.builder.levels["snob"] > 0
        ):
            if not self.snobman:
                self.snobman = SnobManager(
                    wrapper=self.wrapper, village_id=self.village_id
                )
                self.snobman.troop_manager = self.units
                self.snobman.resman = self.resman
            self.snobman.wanted = self.get_village_config(
                self.village_id, parameter="snobs", default=0
            )
            self.snobman.building_level = self.builder.get_level("snob")
            self.snobman.run()

    def check_forced_peace(self):
        """
        Checks if farming is disabled for the current time
        """
        # Set timeslots in order to prevent farming during events like national holidays
        forced_peace_times = self.get_config(section="farms", parameter="forced_peace_times", default=[])
        self.forced_peace = False
        self.forced_peace_today = False
        self.forced_peace_today_start = None
        for time_pairs in forced_peace_times:
            start_dt = datetime.strptime(time_pairs["start"], "%d.%m.%y %H:%M:%S")
            end_dt = datetime.strptime(time_pairs["end"], "%d.%m.%y %H:%M:%S")
            now = datetime.now()
            if start_dt.date() == datetime.today().date():
                forced_peace_today = True
                forced_peace_today_start = start_dt
            if start_dt < now < end_dt:
                self.logger.debug("Currently in a forced peace time! No attacks will be send.")
                self.forced_peace = True
                break

    def set_unit_wanted_levels(self):
        """
        Fetches wanted units for the current buildings
        """
        self.current_unit_entry = self.units.get_template_action(self.builder.levels)

        if self.current_unit_entry and self.units.wanted != self.current_unit_entry["build"]:
            # update wanted units if template has changed
            self.logger.info(
                "%s as wanted units for current village", str(self.current_unit_entry["build"])
            )
            self.units.wanted = self.current_unit_entry["build"]

        if self.units.wanted_levels != {}:
            # Remove disabled units
            for disabled in self.disabled_units:
                self.units.wanted_levels.pop(disabled, None)
            self.logger.info(
                "%s as wanted upgrades for current village", str(self.units.wanted_levels)
            )

    def run_unit_upgrades(self):
        """
        Uses smith to research or upgrade units
        """
        if (
                self.get_config(section="units", parameter="upgrade", default=False)
                and self.units.wanted_levels != {}
        ):
            self.units.attempt_upgrade()

    def do_recruit(self):
        """
        Recruits new units
        """
        if self.get_config(section="units", parameter="recruit", default=False):
            self.units.can_fix_queue = self.get_config(
                section="units", parameter="remove_manual_queued", default=False
            )
            self.units.randomize_unit_queue = self.get_config(
                section="units", parameter="randomize_unit_queue", default=True
            )
            # prioritize_building: will only recruit when builder has sufficient funds for queue items
            if (
                    self.get_village_config(
                        self.village_id, parameter="prioritize_building", default=False
                    )
                    and not self.resman.can_recruit()
            ):
                self.logger.info(
                    "Not recruiting because builder has insufficient funds"
                )
                for x in list(self.resman.requested.keys()):
                    if "recruitment_" in x:
                        self.resman.requested.pop(f"{x}", None)
            elif (
                    self.get_village_config(
                        self.village_id, parameter="prioritize_snob", default=False
                    )
                    and self.snobman
                    and self.snobman.can_snob
                    and self.snobman.is_incomplete
            ):
                self.logger.info("Not recruiting because snob has insufficient funds")
                for x in list(self.resman.requested.keys()):
                    if "recruitment_" in x:
                        self.resman.requested.pop(f"{x}", None)
            else:
                # do a build run for every
                for building in self.units.wanted:
                    if not self.builder.get_level(building):
                        self.logger.debug(
                            "Recruit of %s will be ignored because building is not (yet) available", building
                        )
                        continue
                    self.units.start_update(building, self.disabled_units)

    def run_resource_sharing(self):
        """
        Feature 9: Transferência automática de recursos entre aldeias do jogador.
        Só executa se resource_sharing.enabled = true no config.
        Deve rodar após manage_local_resources() para que resman.requested
        reflita as necessidades reais do ciclo atual.
        """
        if not self.config.get("resource_sharing", {}).get("enabled", False):
            return

        if not self.builder or not self.builder.get_level("market"):
            self.logger.debug("ResourceSharing: mercado não construído em %s, pulando", self.village_id)
            return

        sharing = ResourceSharingManager(
            wrapper=self.wrapper,
            current_village_id=self.village_id,
            config=self.config,
        )
        sharing.run(current_resman=self.resman)

    def manage_local_resources(self):
        to_dell = []
        for x in self.resman.requested:
            if all(res == 0 for res in self.resman.requested[x].values()):
                # remove empty requests!
                to_dell.append(x)

        for x in to_dell:
            self.resman.requested.pop(x)

        self.logger.debug("Current resources: %s", str(self.resman.actual))
        self.logger.debug("Requested resources: %s", str(self.resman.requested))

    def set_farm_options(self):
        """
        Sets various options for farming management
        """
        self.attack.target_high_points = self.get_config(
            section="farms", parameter="attack_higher_points", default=False
        )
        self.attack.farm_minpoints = self.get_config(
            section="farms", parameter="min_points", default=24
        )
        self.attack.farm_maxpoints = self.get_config(
            section="farms", parameter="max_points", default=1080
        )
        self.attack.farm_radius = self.get_config(
            section="farms", parameter="search_radius", default=50
        )
        self.attack.farm_default_wait = self.get_config(
            section="farms", parameter="default_away_time", default=1200
        )
        self.attack.farm_high_prio_wait = self.get_config(
            section="farms", parameter="full_loot_away_time", default=1800
        )
        self.attack.farm_low_prio_wait = self.get_config(
            section="farms", parameter="low_loot_away_time", default=7200
        )
        self.attack.scout_farm_amount = self.get_config(
            section="farms", parameter="farm_scout_amount", default=5
        )
        if self.current_unit_entry:
            self.attack.template = self.current_unit_entry["farm"]

    def run_conquest(self):
        """
        Feature 8: Runs the noble train conquest logic for any village with nobles.
        Skipped if conquest is globally disabled or if the village has
        conquest_enabled: false in its individual config.
        """
        if not self.config.get("conquest", {}).get("enabled", False):
            return

        village_cfg = self.config.get("villages", {}).get(self.village_id, {})
        if not village_cfg.get("conquest_enabled", True):
            self.logger.debug(
                "Conquest: skipping village %s (conquest_enabled: false)", self.village_id
            )
            return

        if not self.area or not self.units:
            self.logger.debug("Conquest: map or troop data not ready, skipping")
            return

        conquest = ConquestManager(
            wrapper=self.wrapper,
            village_id=self.village_id,
            troopmanager=self.units,
            map_obj=self.area,
            config=self.config,
        )
        conquest.run()

    def ensure_map_loaded(self):
        """
        Ensures self.area (Map) is initialised and populated before conquest
        or farming runs. Called once per cycle so both modules share the same
        Map instance without duplicating the HTTP request.
        """
        if not self.area:
            self.area = Map(wrapper=self.wrapper, village_id=self.village_id)
        self.area.get_map()

    def run_farming(self):
        """
        Runs the farming logic
        """
        if not self.forced_peace and self.units.can_attack:
            # Map already loaded by ensure_map_loaded() earlier in the cycle.
            # Re-calling get_map() here is safe (it uses cache), but area is
            # guaranteed non-None so the conquest guard at line 491 always passes.
            if self.area.villages:
                self.units.can_scout = self.get_config(
                    section="farms", parameter="force_scout_if_available", default=True
                )
                self.logger.info(
                    "%d villages from map cache, (your location: %s)",
                        len(self.area.villages),
                        ":".join([str(x) for x in self.area.my_location])
                )
                if not self.attack:
                    self.attack = AttackManager(
                        wrapper=self.wrapper,
                        village_id=self.village_id,
                        troopmanager=self.units,
                        map=self.area,
                    )
                    self.attack.repman = self.rep_man

                if self.forced_peace_today:
                    self.logger.info("Forced peace time coming up today!")
                    self.attack.forced_peace_time = self.forced_peace_today_start
                self.set_farm_options()

                if (
                        self.get_config(section="farms", parameter="farm", default=False)
                        and not self.def_man.under_attack
                ):
                    self.attack.extra_farm = self.get_village_config(
                        self.village_id, parameter="additional_farms", default=[]
                    )
                    self.attack.max_farms = self.get_config(
                        section="farms", parameter="max_farms", default=25
                    )
                    self.attack.run()

    def do_gather(self):
        """
        Runs gathering if unlocked and active
        """
        self.units.can_gather = self.get_village_config(
            self.village_id, parameter="gather_enabled", default=False
        )
        if not self.def_man or not self.def_man.under_attack:
            self.units.gather(
                selection=self.get_village_config(
                    self.village_id, parameter="gather_selection", default=1
                ),
                disabled_units=self.disabled_units,
                advanced_gather=self.get_village_config(self.village_id, parameter="advanced_gather", default=1)
            )

    def go_manage_market(self):
        """
        Manages the market
        """
        if self.get_config(
                section="market", parameter="auto_trade", default=False
        ) and self.builder.get_level("market"):
            self.logger.info("Managing market")
            self.resman.trade_max_per_hour = self.get_config(
                section="market", parameter="trade_max_per_hour", default=1
            )
            self.resman.trade_max_duration = self.get_config(
                section="market", parameter="max_trade_duration", default=1
            )
            if self.get_config(
                    section="market", parameter="trade_multiplier", default=False
            ):
                self.resman.trade_bias = self.get_config(
                    section="market", parameter="trade_multiplier_value", default=1.0
                )
            self.resman.manage_market(
                drop_existing=self.get_config(
                    section="market", parameter="auto_remove", default=True
                )
            )

        res = self.wrapper.get_action(village_id=self.village_id, action="overview")
        self.game_data = Extractor.game_state(res)
        self.resman.update(self.game_data)
        if self.get_config(
                section="world", parameter="trade_for_premium", default=False
        ) and self.get_village_config(
            self.village_id, parameter="trade_for_premium", default=False
        ):
            # Set the parameter correctly when the config says so.
            self.resman.do_premium_trade = True
            self.resman.do_premium_stuff()

    def run(self, config=None, first_run=False):
        # setup and check if village still exists / is accessible
        self.config = config
        self.wrapper.delay = self.get_config(
            section="bot", parameter="delay_factor", default=1.0
        )

        data = self.village_init()

        if not self.game_data:
            self.logger.error(
                "Error reading game data for village %s", self.village_id
            )
            raise VillageInitException

        self.set_world_config()

        if not self.get_config(section="villages", parameter=self.village_id):
            raise VillageInitException

        # Feature 6: apply nearest-village config inheritance on first run of a new village
        self.apply_nearest_village_inheritance(config)

        vdata = self.get_config(section="villages", parameter=self.village_id)
        if not self.get_village_config(
                self.village_id, parameter="managed", default=False
        ):
            return False
        if not self.game_data:
            raise InvalidGameStateException

        self.update_pre_run()

        self.setup_defence_manager(data=data)
        self.run_quest_actions(config=config)

        self.run_builder()
        self.units_get_template()
        self.set_unit_wanted_levels()

        self.units.update_totals()
        self.run_unit_upgrades()
        self.run_snob_recruit()
        self.do_recruit()
        self.manage_local_resources()
        self.run_resource_sharing()

        self.ensure_map_loaded()
        self.run_conquest()
        self.run_farming()

        self.do_gather()
        self.go_manage_market()

        self.set_cache_vars()
        self.logger.info("Village cycle done, returning to overview")
        self.wrapper.reporter.report(
            self.village_id, "TWB_POST_RESOURCE", str(self.resman.actual)
        )
        self.wrapper.reporter.add_data(
            self.village_id,
            data_type="village.resources",
            data=json.dumps(self.resman.actual),
        )
        self.wrapper.reporter.add_data(
            self.village_id,
            data_type="village.buildings",
            data=json.dumps(self.builder.levels),
        )
        self.wrapper.reporter.add_data(
            self.village_id,
            data_type="village.troops",
            data=json.dumps(self.units.total_troops),
        )
        self.wrapper.reporter.add_data(
            self.village_id, data_type="village.config", data=json.dumps(vdata)
        )

    def get_quests(self):
        result = Extractor.get_quests(self.wrapper.last_response)
        if result:
            qres = self.wrapper.get_api_action(
                action="quest_complete",
                village_id=self.village_id,
                params={"quest": result, "skip": "false"},
            )
            if qres:
                self.logger.info("Completed quest: %s", str(result))
                return True
        self.logger.debug("There where no completed quests")
        return False

    def get_quest_rewards(self):
        result = self.wrapper.get_api_data(
            action="quest_popup",
            village_id=self.village_id,
            params={"screen": 'new_quests', "tab": "main-tab", "quest": 0},
        )
        # The data is escaped for JS, so unescape it before sending it to the extractor.
        rewards = Extractor.get_quest_rewards(decode(result["response"]["dialog"], 'unicode-escape'))
        for reward in rewards:
            # First check if there is enough room for storing the reward
            for t_resource in reward["reward"]:
                if self.resman.storage - self.resman.actual[t_resource] < reward["reward"][t_resource]:
                    self.logger.info("Not enough room to store the %s part of the reward", t_resource)
                    return False

            qres = self.wrapper.post_api_data(
                action="claim_reward",
                village_id=self.village_id,
                params={"screen": "new_quests"},
                data={"reward_id": reward["id"]}
            )
            if qres:
                if not qres['response']:
                    self.logger.debug("Error getting reward! %s", qres)
                    return False
                else:
                    self.logger.info("Got quest reward: %s", str(reward))
                    for t_resource in reward["reward"]:
                        self.resman.actual[t_resource] += reward["reward"][t_resource]

        self.logger.debug("There where no (more) quest rewards")
        return len(rewards) > 0

    @staticmethod
    def get_needed_profile(config):
        """
        Feature 7: Calculates which profile (offensive/defensive) the next village
        should receive in order to maintain the configured empire ratio.
        """
        empire = config.get("empire", {})
        off_ratio = empire.get("offensive_ratio", 3)
        def_ratio = empire.get("defensive_ratio", 1)
        target_off_pct = off_ratio / (off_ratio + def_ratio)

        villages = config.get("villages", {})
        total = 0
        offensive = 0
        for vcfg in villages.values():
            if isinstance(vcfg, dict):
                total += 1
                if vcfg.get("profile") == "offensive":
                    offensive += 1

        if total == 0:
            return "offensive"

        current_off_pct = offensive / total
        if current_off_pct < target_off_pct:
            return "offensive"
        return "defensive"

    def apply_nearest_village_inheritance(self, config):
        """
        Feature 6 + 7: If a village was just added (inherit_on_first_run=True),
        copies the config from the nearest already-managed village.
        In 'empire_ratio' mode (Feature 7), filters donor candidates by the profile
        (offensive/defensive) needed to maintain the configured empire ratio.
        Falls back to global template if no suitable donor is found.
        """
        village_cfg = config["villages"].get(self.village_id, {})
        if not village_cfg.get("inherit_on_first_run", False):
            return

        inheritance_mode = config.get("inheritance", {}).get("mode", "empire_ratio")

        def clear_flag():
            config["villages"][self.village_id]["inherit_on_first_run"] = False
            FileManager.save_json_file(config, "config.json")

        if inheritance_mode == "global_template":
            self.logger.info(
                "Village %s: inheritance mode is 'global_template', keeping global template",
                self.village_id
            )
            clear_flag()
            return

        my_x = self.game_data["village"].get("x", 0)
        my_y = self.game_data["village"].get("y", 0)

        if not my_x or not my_y:
            self.logger.warning(
                "Village %s: no coordinates available for inheritance, keeping global template",
                self.village_id
            )
            clear_flag()
            return

        # Build candidate list from cache
        candidates = []
        for cache_file in FileManager.list_directory("cache/managed", ends_with=".json"):
            cached_vid = cache_file.replace(".json", "")
            if cached_vid == self.village_id:
                continue
            if cached_vid not in config["villages"]:
                continue
            cached = FileManager.load_json_file(f"cache/managed/{cache_file}")
            if not cached or not cached.get("x") or not cached.get("y"):
                continue
            candidates.append((cached_vid, cached))

        if not candidates:
            # No donor available — this is the first village or all caches are fresh.
            # Fall back to the global village_template from config instead of doing nothing.
            template_cfg = config.get("village_template", {})
            fallback_profile = template_cfg.get("profile") or "defensive"
            fallback_building = template_cfg.get("building") or config.get("building", {}).get("default", "purple_predator")
            fallback_units = template_cfg.get("units") or config.get("units", {}).get("default", "basic")

            self.logger.info(
                "Village %s: no donor village found — applying village_template fallback "
                "(profile=%s, building=%s, units=%s)",
                self.village_id, fallback_profile, fallback_building, fallback_units
            )

            # Write directly to config.json via FileManager
            import collections
            cfg_path = "config.json"
            raw = FileManager.load_json_file(cfg_path, object_pairs_hook=collections.OrderedDict) or {}
            if "villages" not in raw:
                raw["villages"] = {}
            if self.village_id not in raw["villages"]:
                raw["villages"][self.village_id] = {}
            raw["villages"][self.village_id]["profile"] = fallback_profile
            raw["villages"][self.village_id]["building"] = fallback_building
            raw["villages"][self.village_id]["units"] = fallback_units
            FileManager.save_json_file(raw, cfg_path)
            clear_flag()
            return

        # Feature 11: prefer donors from the same geographic zone
        zone_data = FileManager.load_json_file("cache/zones.json") or {}
        my_zone = zone_data.get("village_zone", {}).get(self.village_id)
        if my_zone:
            zone_candidates = [
                (vid, data) for vid, data in candidates
                if zone_data.get("village_zone", {}).get(vid) == my_zone
            ]
            if zone_candidates:
                self.logger.info(
                    "Village %s: restricting inheritance donors to zone '%s' (%d candidate(s))",
                    self.village_id, my_zone, len(zone_candidates)
                )
                candidates = zone_candidates
            else:
                self.logger.debug(
                    "Village %s: no donors in zone '%s', using all managed villages",
                    self.village_id, my_zone
                )

        # Feature 7: filter by needed profile when mode is empire_ratio
        needed_profile = None
        used_profile_template = False
        if inheritance_mode == "empire_ratio":
            needed_profile = Village.get_needed_profile(config)
            self.logger.info(
                "Village %s: empire_ratio inheritance — needed profile = %s",
                self.village_id, needed_profile
            )
            filtered = [
                (vid, data) for vid, data in candidates
                if data.get("profile") == needed_profile
            ]
            if filtered:
                candidates = filtered
            else:
                self.logger.warning(
                    "Village %s: no donor with profile '%s' found, "
                    "will apply profile_templates overrides after inheritance.",
                    self.village_id, needed_profile
                )
                used_profile_template = True

        # Find nearest candidate
        def dist(data):
            return ((my_x - data["x"]) ** 2 + (my_y - data["y"]) ** 2) ** 0.5

        best_vid, best_data = min(candidates, key=lambda c: dist(c[1]))
        best_dist = dist(best_data)

        donor_config = copy.deepcopy(config["villages"][best_vid])
        donor_config["inherit_on_first_run"] = False

        # Feature 7: stamp the correct profile on the new village
        if needed_profile:
            donor_config["profile"] = needed_profile

        # Feature 7: when no profile-matching donor existed, override building and units
        # from profile_templates to guarantee the correct template regardless of donor
        if used_profile_template and needed_profile:
            profile_tpl = config.get("profile_templates", {}).get(needed_profile, {})
            if profile_tpl:
                for key, value in profile_tpl.items():
                    donor_config[key] = value
                self.logger.info(
                    "Village %s: applied profile_templates[%s] overrides (building=%s, units=%s)",
                    self.village_id, needed_profile,
                    profile_tpl.get("building", "n/a"),
                    profile_tpl.get("units", "n/a")
                )
            else:
                self.logger.warning(
                    "Village %s: profile_templates[%s] not found in config, "
                    "donor templates kept as-is.",
                    self.village_id, needed_profile
                )

        config["villages"][self.village_id] = donor_config
        FileManager.save_json_file(config, "config.json")
        self.logger.info(
            "Village %s inherited config from village %s (profile: %s, %.1f tiles away)",
            self.village_id, best_vid, donor_config.get("profile", "n/a"), best_dist
        )

    def set_cache_vars(self):
        # Feature 11: load zone assignment from last cycle's zones.json (one cycle lag is acceptable)
        zone_data = FileManager.load_json_file("cache/zones.json") or {}
        current_zone = zone_data.get("village_zone", {}).get(self.village_id, None)

        village_entry = {
            "name": self.game_data["village"]["name"],
            "x": self.game_data["village"].get("x", 0),
            "y": self.game_data["village"].get("y", 0),
            "profile": self.config["villages"].get(self.village_id, {}).get("profile", "offensive"),
            "public": self.area.in_cache(self.village_id) if self.area else None,
            "resources": self.resman.actual,
            "required_resources": self.resman.requested,
            "available_troops": self.units.troops,
            "buidling_levels": self.builder.levels,
            "building_queue": self.builder.queue,
            "troops": self.units.total_troops,
            "under_attack": self.def_man.under_attack,
            "last_run": int(time.time()),
            "zone": current_zone,
        }
        FileManager.save_json_file(village_entry, f"cache/managed/{self.village_id}.json")
