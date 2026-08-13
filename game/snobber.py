"""
Used to create snobs
"""
import json
import logging
import re

from core.extractors import Extractor


class SnobManager:
    """
    Create the snob manager
    """
    wrapper = None
    village_id = None
    resman = None
    can_snob = True
    troop_manager = None
    wanted = 1
    building_level = 0
    is_incomplete = False
    using_coin_system = False
    mint_only = False

    def level_system(self):
        """
        Just return 0, that's what it does
        Just that, nothing more
        """
        return 0

    def __init__(self, wrapper=None, village_id=None):
        """
        Create the snob manager class
        """
        self.wrapper = wrapper
        self.village_id = village_id
        self.logger = logging.getLogger(f"Snob:{self.village_id}")

    def need_reserve(self, text):
        """
        Checks in a weird way if there is enough gold coins or stored resources
        """
        if not self.using_coin_system:
            need_amount = re.search(
                r'(?s)<th colspan="3">[\w\s]+</th>.+?data-unit="snob">.+?<td.+?>\s*(\d+)\sx',
                text,
            )
            if need_amount:
                return int(need_amount.group(1))
            return 0

        # O jogo já serviu esse ícone como gold_big.png; hoje (br143) é
        # gold_big.webp. Casa qualquer extensão em vez de fixar uma, para não
        # quebrar de novo se o jogo trocar o formato do asset outra vez.
        gold_icon = re.search(r"gold_big\.\w+", text)
        if not gold_icon:
            self.logger.warning("Error parsing snob content")
            return 0
        splits = text.split(gold_icon.group(0))[1].split("<table")[1].split("</table")[0]
        rows = re.search(r'<td class="nowrap">(\d+)', splits)
        if rows:
            return int(rows.group(1))
        return 0

    def attempt_recruit(self, amount):
        """
        Tries to recruit a new snob
        """
        result = self.wrapper.get_action(action="snob", village_id=self.village_id)
        if result is None:
            self.logger.warning(
                "Snob screen request failed (timeout / non-200), skipping this cycle"
            )
            return False
        if '"id":"coin"' in result.text:
            self.using_coin_system = True
        game_data = Extractor.game_state(result)
        self.resman.update(game_data)

        can_recruit = re.search(
            r"(?s)</th><th>(\d+)</th></tr>\s*</table><br />", result.text
        )
        if not can_recruit or int(can_recruit.group(1)) == 0:
            nres = self.need_reserve(result.text)
            if nres > 0:
                self.logger.debug(
                    "Not enough resources available, still %d needed, attempting storage", nres
                )
                cres = (
                    self.storage_item(result.text)
                    if not self.using_coin_system
                    else self.coin_item(result.text)
                )
                if cres:
                    return self.attempt_recruit(amount)
                self.is_incomplete = True
                self.logger.debug("Not enough resources available")
                return False
        if not can_recruit:
            # Chegar aqui significa: o regex não casou E need_reserve() disse
            # que não falta recurso -- ou seja, o markup da academia mudou (a
            # mesma classe de quebra do gold_big.png -> .webp acima). Antes,
            # esse caminho seguia para o .group(1) e dava AttributeError (P1-13).
            # is_incomplete fica False de propósito: com prioritize_snob ligado
            # ele barra TODO o recrutamento da aldeia (village.py), e travar
            # tudo por causa de um parse que não deu é pior que não nobilitar.
            self.logger.warning(
                "Could not read the snob recruit count from the academy screen "
                "(markup changed?), skipping snob recruitment this cycle"
            )
            self.is_incomplete = False
            return False
        self.is_incomplete = False
        r_num = int(can_recruit.group(1))
        if r_num == 0:
            self.logger.debug(
                "No more snobs available, awaiting snob creating, snob death or village loss"
            )
            return False
        train_snob_url = f"game.php?village={self.village_id}&screen=snob&action=train&h={self.wrapper.last_h}"
        self.wrapper.get_url(train_snob_url)
        return True

    def storage_item(self, result):
        """
        Tries to store resources for future snob creation
        """
        storage_re = re.search(r"train\.storage_item = (\{.+?})", result)
        if not storage_re:
            self.logger.warning(
                "Snob recruit is called but storage data not on page, error?"
            )
            return False
        raw_coin = storage_re.group(1)
        data = json.loads(raw_coin)

        if self.has_enough(data):
            get_post = f"game.php?village={self.village_id}&screen=snob&action=reserve"
            data = {"factor": "1", "h": self.wrapper.last_h}
            self.wrapper.post_url(url=get_post, data=data)
            return True
        else:
            self.is_incomplete = True
            return False

    def coin_item(self, result, request=True):
        """
        Tries to create a new gold coin
        """
        storage_re = re.search(r"train\.storage_item = (\{.+?})", result)
        if not storage_re:
            self.logger.warning(
                "Snob recruit is called but storage data not on page, error?"
            )
            return False
        raw_coin = storage_re.group(1)
        data = json.loads(raw_coin)

        if self.has_enough(data, request=request):
            get_post = f"game.php?village={self.village_id}&screen=snob&action=coin"
            data = {"coin_mint_count": "1", "count": "1", "h": self.wrapper.last_h}
            self.wrapper.post_url(url=get_post, data=data)
            return True
        else:
            # is_incomplete e' "a aldeia esta' poupando para um nobre": com
            # prioritize_snob ligado ele barra todo o recrutamento da aldeia
            # (village.py). Em mint_only nao ha' nobre nenhum a caminho, entao
            # faltar recurso para a moeda nao pode travar as tropas da aldeia.
            if request:
                self.is_incomplete = True
            return False

    def has_enough(self, build_item, request=True):
        """
        Checks if there are enough resources available
        If not, they will be requested from resources (unless request=False)
        """
        r = True
        for resource in ("wood", "stone", "iron"):
            if build_item[resource] > self.resman.actual[resource]:
                if request:
                    req = build_item[resource] - self.resman.actual[resource]
                    self.resman.request(
                        source="snob", resource=resource, amount=req
                    )
                r = False
        return r

    def builder_is_short(self):
        """
        True enquanto a fila de construcao ainda nao tem madeira/argila/ferro
        para o proximo item.

        `BuildingManager` registra o que falta em `resman.requested["building"]`
        e `Village.run()` roda o builder antes do snob, entao o dado e' deste
        ciclo. `pop` fica de fora de proposito: populacao nao e' recurso que a
        moeda dispute nem que o mercado compre.
        """
        pending = self.resman.requested.get("building", {})
        return any(pending.get(resource, 0) > 0 for resource in ("wood", "stone", "iron"))

    def troops_are_short(self):
        """
        True enquanto a aldeia ainda nao tem as tropas que o template pede.

        `TroopManager.wanted` e' `{predio: {unidade: quantidade}}` e
        `total_troops` vem da coluna "total" da tela de unidades -- ou seja,
        conta tambem a tropa que esta' fora dando suporte. Perder cavalaria
        pesada apoiando outra aldeia derruba esse numero, e a moeda para de ser
        cunhada ate' o estabulo repor: o excedente que vira moeda e' o que
        sobra *depois* do predio e da tropa, nessa ordem.

        Consequencia deliberada: uma aldeia que nunca alcanca o template nunca
        cunha. A moeda e' a ultima prioridade da aldeia, nao a primeira.
        """
        wanted = getattr(self.troop_manager, "wanted", None) or {}
        totals = getattr(self.troop_manager, "total_troops", None) or {}
        for per_building in wanted.values():
            for unit, amount in per_building.items():
                if int(totals.get(unit, 0)) < int(amount):
                    return True
        return False

    def mint_coins(self):
        """
        Cunha moeda de ouro sem nunca recrutar nobre.

        A moeda e' da conta inteira, o nobre e' da aldeia -- e a aldeia de torre
        de vigia existe para cobrir territorio, nao para nobrar (11.607 de
        populacao no nivel 20 nao deixa margem). Ate' aqui esse modo nao
        existia: `run()` so' alcancava `coin_item()` atraves de
        `attempt_recruit()`, dentro de `if self.wanted > 0`, entao cunhar era
        efeito colateral de querer um nobre e `snobs: 0` desligava os dois.
        """
        if self.builder_is_short():
            # O excedente e' o que sobra depois do predio. Enquanto a torre
            # esta' sendo construida, a aldeia nao tem excedente nenhum.
            self.logger.debug("Not minting coins, builder still needs resources")
            return False
        if self.troops_are_short():
            # A aldeia de torre e' tambem uma aldeia de suporte: se ela perdeu
            # cavalaria pesada apoiando alguem, o recurso e' do estabulo, nao
            # da moeda.
            self.logger.debug("Not minting coins, village is below its troop template")
            return False
        result = self.wrapper.get_action(action="snob", village_id=self.village_id)
        if result is None:
            self.logger.warning(
                "Snob screen request failed (timeout / non-200), skipping mint this cycle"
            )
            return False
        if '"id":"coin"' in result.text:
            self.using_coin_system = True
        if not self.using_coin_system:
            # Mundo sem moeda: o nobre sai de recurso guardado na propria
            # aldeia (action=reserve), e guardar so' faz sentido para quem vai
            # recrutar -- que e' exatamente o que mint_coins existe para nao
            # fazer.
            self.logger.warning(
                "mint_coins is on but this world does not use the gold coin system, nothing to do"
            )
            return False
        self.resman.update(Extractor.game_state(result))
        # request=False: em mint_only a aldeia cunha do que sobra, ela nao pede
        # recurso ao mercado/outras aldeias para cunhar.
        return self.coin_item(result.text, request=False)

    def run(self):
        """
        Run the snob updater
        """
        if not self.can_snob:
            return False
        if self.building_level == 0:
            return False
        if self.mint_only:
            return self.mint_coins()
        if self.wanted > 0:
            if "snob" not in self.troop_manager.total_troops:
                return self.attempt_recruit(amount=self.wanted)

            current = int(self.troop_manager.total_troops["snob"])
            if current < self.wanted:
                return self.attempt_recruit(amount=self.wanted - current)
            self.logger.info("Snob up-to-date (%d/%d)", current, self.wanted)
