"""
Anything with resources goes here
"""
import logging
import os
import re
import time

from core.extractors import Extractor
from core.filemanager import FileManager


class PremiumExchange:
    """
    Logic for interaction with the premium exchange
    """

    def __init__(self, wrapper, stock: dict, capacity: dict, tax: dict, constants: dict, duration: int, merchants: int):
        self.wrapper = wrapper
        self.stock = stock
        self.capacity = capacity
        self.tax = tax
        self.constants = constants
        self.duration = duration
        self.merchants = merchants

    # do not call this anihilation (calculate_cost) - i dechipered it from tribalwars js
    def calculate_cost(self, item, a):
        """
        Stock exchange cost calculation
        """
        t = self.stock[item]
        n = self.capacity[item]

        # tax = self.tax["buy"] if a >= 0 else self.tax["sell"]
        tax = self.tax["sell"]  # twb never buys on premium exchange

        return (1 + tax) * (self.calculate_marginal_price(t, n) + self.calculate_marginal_price(t - a, n)) * a / 2

    def calculate_marginal_price(self, e, a):
        """
        Math magic
        """
        c = self.constants
        return c["resource_base_price"] - c["resource_price_elasticity"] * e / (a + c["stock_size_modifier"])

    def calculate_rate_for_one_point(self, item: str):
        """
        Math magic
        """
        a = self.stock[item]
        t = self.capacity[item]
        n = self.calculate_marginal_price(a, t)
        r = int(1 / n)
        c = self.calculate_cost(item, r)
        i = 0

        while c > 1 and i < 50:
            r -= 1
            i += 1
            c = self.calculate_cost(item, r)

        return r

    @staticmethod
    def optimize_n(amount, sell_price, merchants, size=1000):
        """
        Math magic
        """
        def _ratio(a, b, size=1000):
            a = (size * b) - a
            return a / size

        offers = []

        for i in range(1, merchants + 1):
            for j in range(amount // sell_price + 1):
                r = _ratio(j * sell_price, i, size=size)
                if r >= 0:
                    offers.append((i, r, j))

        offers.sort(key=lambda x: (x[1], -x[0]))

        r = {
            "merchants": offers[0][0],
            "ratio": offers[0][1],
            "n_to_sell": offers[0][2]
        }

        return r


class ResourceManager:
    """
    Class to calculate, store and reserve resources for actions
    """
    storage = 0
    ratio = 2.5
    max_trade_amount = 4000
    logger = None
    # not allowed to bias
    trade_bias = 1
    last_trade = 0
    trade_max_per_hour = 1
    trade_max_duration = 2
    wrapper = None
    village_id = None
    do_premium_trade = False

    def __init__(self, wrapper=None, village_id=None):
        """
        Create the resource manager
        Preferably used by anything that builds/recruits/sends/whatever
        """
        self.wrapper = wrapper
        self.village_id = village_id
        # self.logger só era criado no fim de um update() bem-sucedido, então
        # qualquer self.logger.* antes disso (can_recruit, do_premium_stuff, e
        # agora a guarda de game_state em update) era AttributeError. update()
        # continua re-vinculando com o nome real da aldeia quando o conhece.
        self.logger = logging.getLogger(f"Resource Manager: {village_id}")
        # Por instância, não por classe: existe um ResourceManager por aldeia
        # e, como atributos de classe, os quatro compartilhavam o mesmo dict.
        # `requested` é gravado em required_resources (cache/managed/*.json) e
        # lido pelo ResourceSharingManager, que decidia com dados cruzados.
        # Ver P0-2 em docs/auditoria_codigo_2026-08-08.md
        self.actual = {}
        self.requested = {}
        # Tempo de viagem da última remessa enviada (segundos), lido da tela de
        # confirmação. None enquanto nada foi enviado ou quando não deu para
        # ler -- ver send_resources/_parse_travel_seconds.
        self.last_send_travel_seconds = None

    def update(self, game_state):
        """
        Update the current resources based on the game state
        """
        # Extractor.game_state() devolve None quando o regex não casa (resposta
        # 200 que não é uma tela de jogo: login após sessão expirada, página de
        # bot protection, markup novo). Os 4 chamadores passam o resultado
        # direto, sem guarda -- buildingmanager, snobber e village (2x) --,
        # então a guarda vale mais aqui do que replicada em cada um.
        # Manter os valores anteriores é o degradado certo: pior que resource
        # desatualizado por um ciclo é derrubar o processo.
        if not game_state or "village" not in game_state:
            self.logger.warning(
                "Village %s: no parseable game state in this response, "
                "keeping the previous resource values", self.village_id
            )
            return False
        self.actual["wood"] = game_state["village"]["wood"]
        self.actual["stone"] = game_state["village"]["stone"]
        self.actual["iron"] = game_state["village"]["iron"]
        self.actual["pop"] = (
                game_state["village"]["pop_max"] - game_state["village"]["pop"]
        )
        self.storage = game_state["village"]["storage_max"]
        self.check_state()
        store_state = game_state["village"]["name"]
        self.logger = logging.getLogger(f"Resource Manager: {store_state}")

    def do_premium_stuff(self):
        """
        Does premium stuff
        """
        gpl = self.get_plenty_off()
        self.logger.debug(
            "Trying premium trade: gpl %s do? %s", gpl, self.do_premium_trade
        )
        if gpl and self.do_premium_trade:
            url = f"game.php?village={self.village_id}&screen=market&mode=exchange"
            res = self.wrapper.get_url(url=url)
            if res is None:
                self.logger.warning("Premium trade: request timed out, skipping")
                return
            data = Extractor.premium_data(res.text)
            # P2-30: a checagem `if not data` existia, mas 15 linhas depois de
            # data["stock"] -- o TypeError vinha antes.
            if not data:
                self.logger.warning("Error reading premium data!")
                return

            premium_exchange = PremiumExchange(
                wrapper=self.wrapper,
                stock=data["stock"],
                capacity=data["capacity"],
                tax=data["tax"],
                constants=data["constants"],
                duration=data["duration"],
                merchants=data["merchants"]
            )

            cost_per_point = premium_exchange.calculate_rate_for_one_point(gpl)

            self.logger.debug("Cost per point: %s", cost_per_point)
            self.logger.info("Current %s price: ", self.actual[gpl])

            price_fetch = ["wood", "stone", "iron"]
            prices = {}

            for p in price_fetch:
                prices[p] = data["stock"][p] * data["rates"][p]

            self.logger.info("Actual premium prices: %s",  prices)

            if gpl in prices and prices[gpl] * 1.1 < self.actual[gpl]:
                self.logger.info(
                    "Attempting trade of %d %s for premium point", prices[gpl], gpl
                )

                if data["merchants"] < 1:
                    self.logger.info("Not enough merchants available!")
                    return

                self.logger.debug(f"Trying to trade {gpl} - exchange_begin")

                prices[gpl] = int(prices[gpl])

                gpl_data = PremiumExchange.optimize_n(
                    amount=prices[gpl],
                    sell_price=cost_per_point,
                    merchants=data["merchants"],
                    size=1000
                )

                self.logger.debug(f"Optimized trade: {gpl} {gpl_data} {gpl_data['n_to_sell'] * cost_per_point}")

                if gpl_data["ratio"] > 0.4:
                    self.logger.info("Not worth trading!")
                    return

                result = self.wrapper.get_api_action(
                    self.village_id,
                    action="exchange_begin",
                    params={"screen": "market"},
                    data={f"sell_{gpl}": (gpl_data["n_to_sell"] * cost_per_point)},
                )

                if result:
                    _rate_hash = result["response"][0]["rate_hash"]

                    trade_data = {
                        "sell_%s" % gpl: (gpl_data["n_to_sell"] * cost_per_point),
                        "rate_hash": _rate_hash,
                        "mb": "1"
                    }

                    result = self.wrapper.get_api_action(
                        self.village_id,
                        action="exchange_confirm",
                        params={"screen": "market"},
                        data=trade_data,
                    )

                    if result:
                        self.logger.info("Trade successful!")
                    else:
                        self.logger.info("Trade failed!")
                else:
                    self.logger.debug(
                        f"Trying to trade %s for premium points - exchange_begin - failed", gpl
                    )
                    self.logger.info("Trade failed!")

    def check_state(self):
        """
        Removes resource requests when the amount is met
        """
        for source in self.requested:
            for res in self.requested[source]:
                if self.requested[source][res] <= self.actual[res]:
                    self.requested[source][res] = 0

    def request(self, source="building", resource="wood", amount=1):
        """
        When called, resources can be taken from other actions

        """
        if source in self.requested:
            self.requested[source][resource] = amount
        else:
            self.requested[source] = {resource: amount}

    def can_recruit(self):
        """
        Checks of population is sufficient for recruitment
        """
        if self.actual["pop"] == 0:
            self.logger.info("Can't recruit, no room for pops!")
            # list() obrigatório: deletar durante a iteração dava RuntimeError
            # sempre que a população estivesse cheia com pedido de recrutamento
            # pendente -- cenário comum em aldeia madura (P1-12).
            for x in list(self.requested.keys()):
                if "recruitment" in x:
                    del self.requested[x]
            return False

        for x in self.requested:
            if "recruitment" in x:
                continue
            types = self.requested[x]
            for sub in types:
                if types[sub] > 0:
                    return False
        return True

    def get_plenty_off(self):
        """
        Checks of there is overcapacity in a village
        """
        most_of = 0
        most = None
        for sub in self.actual:
            f = 1
            for sr in self.requested:
                if sub in self.requested[sr] and self.requested[sr][sub] > 0:
                    f = 0
            if not f:
                continue
            if sub == "pop":
                continue
            # self.logger.debug(f"We have {self.actual[sub]} {sub}. Enough? {self.actual[sub]} > {int(self.storage / self.ratio)}")
            if self.actual[sub] > int(self.storage / self.ratio):
                if self.actual[sub] > most_of:
                    most = sub
                    most_of = self.actual[sub]
        if most:
            self.logger.debug(f"We have plenty of {most}")

        return most

    def in_need_of(self, obj_type):
        """
        Checks if the village lacks a certain resource
        """
        for x in self.requested:
            types = self.requested[x]
            if obj_type in types and self.requested[x][obj_type] > 0:
                return True
        return False

    def in_need_amount(self, obj_type):
        """
        Checks what would be needed in order to match requirements
        """
        amount = 0
        for x in self.requested:
            types = self.requested[x]
            if obj_type in types and self.requested[x][obj_type] > 0:
                amount += self.requested[x][obj_type]
        return amount

    def get_needs(self):
        """
        All of the above
        """
        needed_the_most = None
        needed_amount = 0
        for x in self.requested:
            types = self.requested[x]
            for obj_type in types:
                if (
                        self.requested[x][obj_type] > 0
                        and self.requested[x][obj_type] > needed_amount
                ):
                    needed_amount = self.requested[x][obj_type]
                    needed_the_most = obj_type
        if needed_the_most:
            return needed_the_most, needed_amount
        return None

    def trade(self, me_item, me_amount, get_item, get_amount):
        """
        Creates a new trading offer
        """
        url = f"game.php?village={self.village_id}&screen=market&mode=own_offer"
        res = self.wrapper.get_url(url=url)
        if res is None:
            self.logger.warning("Trade: request timed out, skipping")
            return False
        if 'market_merchant_available_count">0' in res.text:
            self.logger.debug("Not trading because not enough merchants available")
            return False
        payload = {
            "res_sell": me_item,
            "sell": me_amount,
            "res_buy": get_item,
            "buy": get_amount,
            "max_time": self.trade_max_duration,
            "multi": 1,
            "h": self.wrapper.last_h,
        }
        post_url = f"game.php?village={self.village_id}&screen=market&mode=own_offer&action=new_offer"
        self.wrapper.post_url(post_url, data=payload)
        self.last_trade = int(time.time())
        return True

    def drop_existing_trades(self):
        """
        Removes an existing trade if resources are needed elsewhere or it expired
        """
        url = f"game.php?village={self.village_id}&screen=market&mode=all_own_offer"
        data = self.wrapper.get_url(url)
        if data is None:
            self.logger.warning("Drop trades: request timed out, skipping")
            return
        existing = re.findall(r'data-id="(\d+)".+?data-village="(\d+)"', data.text)
        for entry in existing:
            offer, village = entry
            if village == str(self.village_id):
                post_url = f"game.php?village={self.village_id}&screen=market&mode=all_own_offer&action=delete_offers"
                post = {
                    "id_%s" % offer: "on",
                    "delete": "Verwijderen",
                    "h": self.wrapper.last_h,
                }
                self.wrapper.post_url(url=post_url, data=post)
                self.logger.info(
                    "Removing offer %s from market because it existed too long" % offer
                )

    # P1-14: o regex original ancorava no literal "Aankomend:" (holandes). O
    # servidor ativo e pt-BR ("Chegando:"), entao ele nunca casava e
    # resource_incoming ficava sempre {} -- o bot criava oferta duplicada para
    # recurso que ja estava a caminho, gastando mercadores a toa.
    # A alternacao cobre os idiomas conhecidos; a estrutura depois do rotulo
    # ("icon header <recurso>") e a mesma em todos. Se nenhum casar o
    # comportamento e identico ao de hoje ({}), so que agora logado.
    INCOMING_LABELS = "Chegando|Aankomend|Incoming|Ankommend|Entrante|Llegando|Arrivo|Przybywa"
    INCOMING_RE = re.compile(
        r"(?:" + INCOMING_LABELS + r"):\s.+?\"icon header (wood|stone|iron)\".+?</span>(.+?) ",
        re.M | re.S,
    )

    def _parse_incoming_resources(self, html):
        """
        Le o bloco "recursos a caminho" da tela de mercado.
        Retorna {} quando nao ha nada a caminho ou quando o bloco nao casa.
        """
        incoming = self.INCOMING_RE.findall(html)
        if not incoming:
            # A mensagem antiga juntava duas hipoteses muito diferentes num
            # DEBUG so ("nao ha nada a caminho" e "nao reconheci o rotulo"), o
            # que a tornava impossivel de agir. Procurar o rotulo sozinho
            # separa as duas: se ele esta na pagina, o que mudou foi a
            # estrutura depois dele, e ai vale WARNING e uma amostra.
            if re.search(r"(?:" + self.INCOMING_LABELS + r")", html):
                self.logger.warning(
                    "Market: o rotulo de recursos a caminho existe na pagina mas "
                    "a estrutura depois dele nao casou -- INCOMING_RE precisa "
                    "ser atualizado"
                )
                self._dump_response(
                    "cache/resource_sharing/market_incoming_mismatch.html", html
                )
            else:
                self.logger.debug(
                    "Market: nenhum rotulo de recursos a caminho na pagina "
                    "(provavelmente nao ha nada a caminho; se houver, o rotulo "
                    "deste idioma esta fora de INCOMING_LABELS)"
                )
            return {}
        resource, amount = incoming[0]
        digits = "".join(s for s in amount if s.isdigit())
        if not digits:
            return {}
        return {resource.strip(): int(digits)}

    def readable_ts(self, seconds):
        """
        Human readable timestamp
        """
        seconds -= int(time.time())
        seconds = seconds % (24 * 3600)
        hour = seconds // 3600
        seconds %= 3600
        minutes = seconds // 60
        seconds %= 60

        return "%d:%02d:%02d" % (hour, minutes, seconds)

    def manage_market(self, drop_existing=True):
        """
        Manages the market for you
        """
        last = self.last_trade + int(3600 * self.trade_max_per_hour)
        if last > int(time.time()):
            rts = self.readable_ts(last)
            self.logger.debug(f"Won't trade for {rts}")
            return

        get_h = time.localtime().tm_hour
        if get_h in range(0, 6) or get_h == 23:
            self.logger.debug("Not managing trades between 23h-6h")
            return
        if drop_existing:
            self.drop_existing_trades()

        plenty = self.get_plenty_off()
        if plenty and not self.in_need_of(plenty):
            need = self.get_needs()
            if need:
                # check incoming resources
                url = f"game.php?village={self.village_id}&screen=market&mode=other_offer"
                res = self.wrapper.get_url(url=url)
                if res is None:
                    self.logger.warning("Market: request timed out, skipping this cycle")
                    return
                resource_incoming = self._parse_incoming_resources(res.text)
                if resource_incoming:
                    self.logger.info(
                        "There are resources incoming! %s", resource_incoming
                    )

                item, how_many = need
                how_many = round(how_many, -1)
                if item in resource_incoming and resource_incoming[item] >= how_many:
                    self.logger.info(
                        f"Needed {item} already incoming! ({resource_incoming[item]} >= {how_many})"
                    )
                    return
                if how_many < 250:
                    return

                self.logger.debug("Checking current market offers")
                if self.check_other_offers(item, how_many, plenty):
                    self.logger.debug("Took market offer!")
                    return

                if how_many > self.max_trade_amount:
                    how_many = self.max_trade_amount
                    self.logger.debug(
                        "Lowering trade amount of %d to %d because of limitation", how_many, self.max_trade_amount
                    )
                biased = int(how_many * self.trade_bias)
                if self.actual[plenty] < biased:
                    self.logger.debug("Cannot trade because insufficient resources")
                    return
                self.logger.info(
                    "Adding market trade of %d %s -> %d %s", how_many, item, biased, plenty
                )
                self.wrapper.reporter.report(
                    self.village_id,
                    "TWB_MARKET",
                    "Adding market trade of %d %s -> %d %s"
                    % (how_many, item, biased, plenty),
                )

                self.trade(plenty, biased, item, how_many)

    def check_other_offers(self, item, how_many, sell):
        """
        Checks if there are offers that match our needs
        """
        url = f"game.php?village={self.village_id}&screen=market&mode=other_offer"
        res = self.wrapper.get_url(url=url)
        if res is None:
            self.logger.warning("Market offers: request timed out, skipping")
            return False
        p = re.compile(
            r"(?:<!-- insert the offer -->\n+)\s+<tr>(.*?)<\/tr>", re.S | re.M
        )
        cur_off_tds = p.findall(res.text)
        resource_incoming = self._parse_incoming_resources(res.text)

        if item in resource_incoming:
            how_many = how_many - resource_incoming[item]
            if how_many < 1:
                self.logger.info("Requested resource already incoming!")
                return False

        willing_to_sell = self.actual[sell] - self.in_need_amount(sell)
        self.logger.debug(
            f"Found {len(cur_off_tds)} offers on market, willing to sell {willing_to_sell} {sell}"
        )

        for tds in cur_off_tds:
            res_offer = re.findall(
                r"<span class=\"icon header (.+?)\".+?>(.+?)</td>", tds
            )
            off_id = re.findall(
                r"<input type=\"hidden\" name=\"id\" value=\"(\d+)", tds
            )

            if len(off_id) < 1:
                # Not enough resources to trade
                continue

            offer = self.parse_res_offer(res_offer, off_id[0])
            if (
                    offer["offered"] == item
                    and offer["offer_amount"] >= how_many
                    and offer["wanted"] == sell
                    and offer["wanted_amount"] <= willing_to_sell
            ):
                self.logger.info(
                    f"Good offer: {offer['offer_amount']} {offer['offered']} for {offer['wanted_amount']} {offer['wanted']}"
                )
                # Take the deal!
                payload = {
                    "count": 1,
                    "id": offer["id"],
                    "h": self.wrapper.last_h,
                }
                post_url = f"game.php?village={self.village_id}&screen=market&mode=other_offer&action=accept_multi&start=0&id={offer['id']}&h={self.wrapper.last_h}"
                # print(f"Would post: {post_url} {payload}")
                self.wrapper.post_url(post_url, data=payload)
                self.last_trade = int(time.time())
                self.actual[offer["wanted"]] = (
                        self.actual[offer["wanted"]] - offer["wanted_amount"]
                )
                return True

        # No useful offers found
        return False

    def send_resources(self, target_village_id, resources: dict, target_coords=None):
        """
        Feature 9: Envia recursos diretamente para outra aldeia do próprio jogador
        via mercado interno (screen=market&mode=send).
        Diferente de trade(), não cria oferta pública — é uma transferência direta.

        O modo correto é `send`, com o alvo na URL. Até 2026-08-11 esta função
        usava `mode=send_res`, que **não existe**: o jogo respondia "Modo
        inválido" num error_box tanto no GET quanto no POST. Confirmado com uma
        amostra real do br143 -- a própria página lista os modos válidos
        (`other_offer`, `exchange`, `own_offer`, `send`, `transports`,
        `traders`, `all_own_offer`) e o JS declara
        `VillageContext._urls.market = '...&screen=market&mode=send&target=__village__'`.
        Como a tela do formulário nunca chegou a carregar uma única vez, nem o
        contador de mercadores nem o payload jamais foram exercitados.

        Campos do formulário, confirmados no markup real do br143 (2026-08-11):

            <input name="wood">  <input name="stone">  <input name="iron">
            <input type="radio" name="target_type" value="coord" checked>
                                       (ou "village_name" / "player_name")
            <input type="text" name="input" placeholder="123|456">

        O destino é **coordenada**, não id de aldeia -- o campo se chama
        literalmente `input` e o formulário nem oferece a opção de id. O
        `target_village` que esta função mandava antes não existe em lugar
        nenhum do form.

        Args:
            target_village_id: ID da aldeia destino (string ou int)
            resources: dict com os recursos a enviar, ex: {"wood": 500, "stone": 200}
            target_coords: "x|y" do destino. Se omitido, é resolvido a partir de
                cache/managed/{id}.json -- sem coordenada não há envio, porque
                mandar sem destino resolvido seria pior que não mandar.

        Returns:
            True se o envio foi submetido com sucesso, False caso contrário
        """
        target_coords = target_coords or self._resolve_coords(target_village_id)
        if not target_coords:
            self.logger.warning(
                "send_resources: sem coordenada conhecida para a aldeia %s, "
                "envio cancelado", target_village_id
            )
            return False

        url = (
            f"game.php?village={self.village_id}"
            f"&screen=market&mode=send&target={target_village_id}"
        )
        res = self.wrapper.get_url(url=url)
        if not res:
            self.logger.warning("send_resources: não foi possível carregar tela de mercado")
            return False

        if '<div class="error_box">' in res.text:
            self.logger.warning(
                "send_resources: o jogo recusou a tela de envio para a aldeia %s",
                target_village_id
            )
            self._dump_response("cache/resource_sharing/last_send_error.html", res.text, overwrite=True)
            return False

        # Verifica mercadores disponíveis
        merchants = Extractor.merchant_data(res)
        if merchants and merchants["available"] < 1:
            self.logger.debug("send_resources: sem mercadores disponíveis")
            return False

        # Amostra da tela de envio de verdade, guardada uma única vez. Os nomes
        # dos campos abaixo nunca foram conferidos contra o formulário real
        # (até 2026-08-11 a URL estava errada e a tela nunca carregou), então
        # este dump é o que permite corrigi-los com o markup na mão em vez de
        # por tentativa e erro.
        self._dump_response("cache/resource_sharing/market_send_form.html", res.text)

        # O `input` visível é só a caixa que o usuário digita: o JS quebra
        # "579|304" e preenche os hidden `x`/`y`, que são o que o servidor de
        # fato lê. Mandar só o `input` fez o jogo responder "Não há nenhuma
        # aldeia em (0|0)!" -- as coordenadas estavam certas, o campo é que era
        # outro. Manda-se os três: `x`/`y` porque são os lidos, `input` porque é
        # o que um navegador enviaria.
        target_x, _, target_y = target_coords.partition("|")
        payload = {
            "wood": resources.get("wood", 0),
            "stone": resources.get("stone", 0),
            "iron": resources.get("iron", 0),
            "x": target_x,
            "y": target_y,
            "target_type": "coord",
            "input": target_coords,
            "h": self.wrapper.last_h,
        }

        # `try=confirm_send` é o action real do <form name="market">. O envio é
        # em duas etapas, como o de ataque: esta primeira valida e devolve uma
        # tela de confirmação, que precisa ser submetida para a carga sair.
        post_url = (
            f"game.php?village={self.village_id}"
            f"&screen=market&mode=send&try=confirm_send"
        )
        # P1-16: o try/except aqui era inalcancavel -- WebWrapper.post_url() ja
        # captura toda excecao internamente e devolve None (core/request.py).
        # Na pratica a resposta nunca era inspecionada e a funcao retornava
        # True sempre: o ResourceSharingManager descontava do excedente local e
        # gravava success:true no historico da Feature 20 para transferencias
        # que podem nunca ter acontecido. Mesmo padrao ja usado em attack() e
        # support().
        response = self.wrapper.post_url(post_url, data=payload)
        if response is None:
            self.logger.warning(
                "send_resources: sem resposta ao enviar %s → aldeia %s",
                resources, target_village_id
            )
            return False
        if '<div class="error_box">' in response.text:
            # Registrar so "houve error_box" nao diz por que o jogo recusou, e
            # este payload nunca foi validado em campo em nenhum idioma -- as
            # causas plausiveis (nome de campo errado, falta de mercador, alvo
            # invalido, etapa de confirmacao faltando) sao indistinguiveis sem
            # a mensagem. Extrai o texto e guarda a resposta inteira: e a
            # propria tela de mercado re-renderizada, entao serve de amostra do
            # formulario real e do contador de mercadores.
            self.logger.warning(
                "send_resources: o jogo recusou o envio de %s → aldeia %s: %s",
                resources, target_village_id, self._error_box_text(response.text)
            )
            self._dump_response("cache/resource_sharing/last_send_error.html", response.text, overwrite=True)
            return False

        # Etapa 2: submeter a tela de confirmação. Nada aqui é adivinhado -- o
        # formulário devolvido pelo jogo é reenviado como está, com os campos e
        # valores que ele mesmo preencheu (inclusive um `h` fresco). É o que o
        # navegador faz ao clicar em "Confirmar", e evita depender de nomes de
        # campo que só existem nessa segunda tela.
        self._dump_response("cache/resource_sharing/market_confirm.html", response.text)
        # Tempo de viagem, para o chamador saber até quando esta carga está em
        # trânsito. Lido antes de confirmar porque é a tela de confirmação que
        # o traz; quem usa é o livro-razão do ResourceSharingManager.
        self.last_send_travel_seconds = self._parse_travel_seconds(response.text)
        action, fields = self._confirmation_form(response.text)
        if not action:
            self.logger.warning(
                "send_resources: o jogo aceitou %s → aldeia %s mas não achei o "
                "formulário de confirmação; a carga NÃO saiu (resposta salva em "
                "cache/resource_sharing/market_confirm.html)",
                resources, target_village_id
            )
            return False

        confirmed = self.wrapper.post_url(action, data=fields)
        if confirmed is None:
            self.logger.warning(
                "send_resources: sem resposta ao confirmar %s → aldeia %s",
                resources, target_village_id
            )
            return False
        if '<div class="error_box">' in confirmed.text:
            self.logger.warning(
                "send_resources: o jogo recusou a confirmação de %s → aldeia %s: %s",
                resources, target_village_id, self._error_box_text(confirmed.text)
            )
            self._dump_response("cache/resource_sharing/last_confirm_error.html", confirmed.text, overwrite=True)
            return False

        self.logger.info(
            "send_resources: enviado %s → aldeia %s", resources, target_village_id
        )
        return True

    @staticmethod
    def _parse_travel_seconds(html):
        """
        Tempo de viagem da remessa, em segundos, lido da tela de confirmação.

        Markup real do br143 (2026-08-11):

            <tr><td>Duração (ida e volta):</td><td>0:08:29</td></tr>
            <tr><td>Chegada:</td><td>hoje às 20:49:53</td></tr>
            <tr><td>Retorno:</td><td>hoje às 20:58:22</td></tr>

        Os três valores casam com `H:MM:SS`, então o discriminador não é o
        formato e sim o **conteúdo da célula**: a duração é a única cujo texto é
        *só* o horário. Chegada e Retorno vêm com "hoje às " na frente. Isso
        evita depender do rótulo, que muda com o idioma, e de ordem de linha.

        Apesar do rótulo dizer "ida e volta", o valor é o trecho de ida:
        20:41:24 (envio) + 8:29 = 20:49:53 (chegada), e o retorno vem outros
        8:29 depois. Devolve None se não achar -- o chamador escolhe o
        fallback.
        """
        for cell in re.findall(r"<td[^>]*>([^<]*)</td>", html):
            match = re.fullmatch(r"(\d{1,2}):([0-5]\d):([0-5]\d)", cell.strip())
            if match:
                hours, minutes, seconds = (int(g) for g in match.groups())
                return hours * 3600 + minutes * 60 + seconds
        return None

    @staticmethod
    def _confirmation_form(html):
        """
        Encontra o formulário de confirmação do envio e devolve (action, campos).

        Reenviar o formulário como o jogo o devolveu é mais robusto do que
        montar um payload novo: os nomes e valores da segunda tela nunca foram
        vistos, e qualquer token que ela traga vai junto sem precisar ser
        identificado.

        A tela de confirmação re-renderiza o formulário de envio vazio junto com
        o de confirmação, então formulários cujos campos de recurso estejam
        todos em branco são descartados -- o que interessa é aquele que já traz
        as quantidades preenchidas pelo próprio jogo.
        """
        fallback = (None, None)
        for match in re.finditer(r"(?s)<form[^>]*>.*?</form>", html):
            block = match.group(0)
            action_match = re.search(r'action="([^"]*)"', block)
            if not action_match:
                continue
            action = action_match.group(1).replace("&amp;", "&")
            if "screen=market" not in action:
                continue

            fields = {}
            for tag in re.findall(r"<input[^>]*>", block):
                name = re.search(r'name="([^"]*)"', tag)
                if not name:
                    continue
                value = re.search(r'value="([^"]*)"', tag)
                fields[name.group(1)] = value.group(1) if value else ""

            resources_present = [fields.get(r, "") for r in ("wood", "stone", "iron") if r in fields]
            if not resources_present:
                continue
            if any(v.strip() for v in resources_present):
                return action, fields
            # Guarda como último recurso, mas continua procurando um preenchido.
            if fallback == (None, None):
                fallback = (action, fields)
        return fallback

    @staticmethod
    def _resolve_coords(village_id):
        """
        "x|y" de uma aldeia gerenciada, a partir de cache/managed/{id}.json
        (gravado por Village.set_cache_vars a cada ciclo).

        O formulário de envio só aceita coordenada, nome de aldeia ou nome de
        jogador -- não aceita id. Como o resto do sistema raciocina inteiramente
        em ids, a tradução acontece aqui, no único ponto que precisa dela.
        """
        data = FileManager.load_json_file(f"cache/managed/{village_id}.json")
        if not data:
            return None
        x, y = data.get("x"), data.get("y")
        if not x or not y:
            return None
        return f"{x}|{y}"

    @staticmethod
    def _error_box_text(html):
        """
        Texto legível do primeiro `error_box` da resposta. "Houve error_box" não
        distingue as causas plausíveis de uma recusa (campo com nome errado,
        falta de mercador, alvo inválido, modo inexistente) -- foi exatamente a
        mensagem "Modo inválido" que revelou, em 2026-08-11, que a URL usada
        pela Feature 9 desde sempre não existia.
        """
        box = re.search(r'<div class="error_box">(.*?)</div>\s*</div>', html, re.S)
        if not box:
            box = re.search(r'<div class="error_box">(.*?)</div>', html, re.S)
        if not box:
            return "sem error_box legível"
        text = re.sub(r"<[^>]+>", " ", box.group(1))
        return " ".join(text.split())[:300] or "vazio"

    def _dump_response(self, path, content, overwrite=False):
        """
        Guarda uma resposta HTML para diagnóstico. Best-effort: nunca derruba o
        ciclo por I/O.

        `overwrite=False` (amostras de markup): grava só na primeira vez, porque
        o markup é sempre o mesmo e reescrever a cada ciclo não acrescenta nada.

        `overwrite=True` (respostas de erro): sempre grava. Um arquivo chamado
        `last_send_error.html` que na verdade guarda o *primeiro* erro é pior que
        não ter arquivo nenhum -- levaria a diagnosticar a falha de hoje com a
        resposta de ontem.
        """
        try:
            full = FileManager.get_path(path)
            if os.path.exists(full) and not overwrite:
                return
            FileManager.create_directory(FileManager.get_path(os.path.dirname(path)))
            with open(full, "w", encoding="utf-8") as fh:
                fh.write(content)
            self.logger.info("send_resources: amostra salva em %s", full)
        except Exception as dump_error:
            self.logger.debug("send_resources: falha ao salvar a amostra: %s", dump_error)

    def parse_res_offer(self, res_offer, id):
        """
        Parse an offer
        """
        off, want, ratio = res_offer
        res_offer, res_offer_amount = off
        res_wanted, res_wanted_amount = want

        return {
            "id": id,
            "offered": res_offer,
            "offer_amount": int("".join([s for s in res_offer_amount if s.isdigit()])),
            "wanted": res_wanted,
            "wanted_amount": int(
                "".join([s for s in res_wanted_amount if s.isdigit()])
            ),
        }
