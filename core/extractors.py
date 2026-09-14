"""
File used for data extraction
"""

import html
import json
import re
import time

# Linha de comando recebido no widget "Comandos" da visão geral de uma aldeia.
# Vive no nível de módulo porque DUAS coisas precisam concordar sobre o que
# conta como "há comando recebido": o parser (Extractor.incoming_commands) e a
# guarda que decide se um parsing vazio é falha de markup ou ausência legítima
# de linhas (DefenceManager._parse_incoming_urgency).
#
# O motivo de não bastar procurar a string solta: no HTML do br143 ela também
# aparece num comentário de JavaScript da própria página --
#   //hide bar if all attacks are ignored  if ($('.no_ignored_command').length
# -- que está presente sempre que o widget renderiza, inclusive quando todos os
# comandos foram ignorados pelo jogador e não existe <tr> nenhum. Guarda frouxa
# nesse caso acusaria "markup mudou" para uma página perfeitamente normal (ver
# o décimo quinto padrão em CLAUDE.md: alerta que dispara sozinho é
# indistinguível de alerta quebrado).
INCOMING_ROW_RE = re.compile(
    r'<tr[^>]*class="[^"]*\bno_ignored_command\b[^"]*"[^>]*>(.*?)</tr>', re.S
)

# Efeitos ativos da aldeia, no widget "Efeitos ativos" da visao geral.
#
# ⚠️ O atributo `title` desta celula carrega HTML literal (`<h3>`, `<i>`,
# `<b>`, `<ul>`), entao ele contem `>`. Consequencia medida no br143 em
# 2026-08-22 (ver tests/test_support_speed_bonus.py, que fixa os tres fatos):
# `<td[^>]*>` TRUNCA a tag de abertura no `>` do `<h3>` de dentro do title, e
# por isso extrair `title="..."` da tag casada falha. A forma em bloco abaixo
# nao sofre disso porque o `(.*?)` atravessa o resto do atributo -- ancora na
# classe, fim no `</td>`. Nao trocar por um regex que escope no atributo.
EFFECT_CELL_RE = re.compile(
    r'<td\s+class="[^"]*village_overview_effect[^"]*"(.*?)</td>', re.S
)
# "+30%" dentro do <li> de expiracao. O percentual e lido, nunca assumido:
# o item existe em mais de uma potencia (o jogador tem um de 30% e outro de
# valor diferente), e chumbar 30 daria numero errado no dia em que o outro
# for usado.
EFFECT_PERCENT_RE = re.compile(r"<b>\s*\+?(\d+)\s*%\s*</b>")
# Nome do icone servido pelo jogo. Serve de chave INDEPENDENTE DE IDIOMA --
# o nome visivel ("Sinal da Aflicao" em pt-BR) muda por mercado, o arquivo do
# icone nao.
INCOMING_SUPPORT_SPEED_ICON = "benefit_incoming_support_speed"


class Extractor:
    """
    Defines various non-compiled regexes for data retrieval
    TODO: use compiled various for CPU efficiency
    """

    @staticmethod
    def balanced_slice(text, start):
        """
        Dado o índice de um caractere de abertura ('{' ou '['), devolve a
        substring desde esse índice até o fechamento correspondente,
        ignorando corretamente colchetes/chaves que apareçam dentro de
        strings JSON entre aspas (inclusive aspas escapadas). Devolve None
        se `start` não apontar para uma abertura ou se ela nunca fechar.

        Existe porque os regexes não-gulosos usados no resto deste arquivo
        (`\\{.+?\\}`) param no primeiro "}" interno — o que basta para os
        payloads rasos do jogo, mas não para os aninhados: o roster de
        Paladinos (pages/statue.py) e o catálogo de inventário
        (pages/inventory.py) quebrariam.
        """
        if start is None or start < 0 or start >= len(text):
            return None
        open_ch = text[start]
        close_ch = {"{": "}", "[": "]"}.get(open_ch)
        if close_ch is None:
            return None
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
        return None

    @staticmethod
    def js_object_after(text, pattern):
        """
        Acha `pattern` (regex) no texto e devolve, já parseado, o objeto ou
        array JSON que vem logo depois — o formato de
        `Inventory.item_types = {...};` e afins embutidos em <script>.

        Devolve None em qualquer falha (padrão ausente, nada abrindo depois
        dele, JSON inválido) em vez de levantar: o consumidor típico está num
        caminho de rede, onde a resposta pode ser um login ou uma página de
        bot protection em vez da tela esperada.
        """
        if not text:
            return None
        match = re.search(pattern, text)
        if not match:
            return None
        raw = Extractor.balanced_slice(text, match.end())
        if raw is None:
            return None
        try:
            return json.loads(raw, strict=False)
        except (json.JSONDecodeError, ValueError):
            return None

    @staticmethod
    def village_data(res):
        """
        Detects village data on a page
        """
        if type(res) != str:
            res = res.text
        grabber = re.search(r'var village = (.+);', res)
        if grabber:
            data = grabber.group(1)
            return json.loads(data, strict=False)

    @staticmethod
    def game_state(res):
        """
        Detects the game state that is available on most pages
        """
        if type(res) != str:
            res = res.text
        grabber = re.search(r'TribalWars\.updateGameData\((.+?)\);', res)
        if grabber:
            data = grabber.group(1)
            return json.loads(data, strict=False)

    @staticmethod
    def building_data(res):
        """
        Fetches building data from the main building
        """
        if type(res) != str:
            res = res.text
        dre = re.search(r'(?s)BuildingMain.buildings = (\{.+?\});', res)
        if dre:
            return json.loads(dre.group(1), strict=False)

        return None

    @staticmethod
    def get_quests(res):
        """
        Gets quest data on almost any page
        """
        if type(res) != str:
            res = res.text
        get_quests = re.search(r'Quests.setQuestData\((\{.+?\})\);', res)
        if get_quests:
            result = json.loads(get_quests.group(1), strict=False)
            for quest in result:
                data = result[quest]
                if data['goals_completed'] == data['goals_total']:
                    return quest
        return None

    @staticmethod
    def get_quest_rewards(res):
        """
        Detects if there are rewards available for quests
        """
        if type(res) != str:
            res = res.text
        get_rewards = re.search(r'RewardSystem\.setRewards\(\s*(\[\{.+?\}\]),', res)
        rewards = []
        if get_rewards:
            result = json.loads(get_rewards.group(1), strict=False)
            for reward in result:
                if reward['status'] == "unlocked":
                    rewards.append(reward)
        # Return all off them
        return rewards

    @staticmethod
    def map_data(res):
        """
        Detects other villages on the map page
        """
        if type(res) != str:
            res = res.text
        data = re.search(r'(?s)TWMap.sectorPrefech = (\[(.+?)\]);', res)
        if data:
            result = json.loads(data.group(1), strict=False)
            return result

    @staticmethod
    def smith_data(res):
        """
        Gets smith data
        """
        if type(res) != str:
            res = res.text
        data = re.search(r'(?s)BuildingSmith.techs = (\{.+?\});', res)
        if data:
            result = json.loads(data.group(1), strict=False)
            return result
        return None

    @staticmethod
    def merchant_data(res):
        """
        Reads the merchant counters from a market screen. Markup confirmed live
        on br143 (2026-08-11, pt-BR):

            <span id="market_merchant_available_count">13</span>
            <span id="market_merchant_total_count">13</span>
            <th>Quantidade máxima de transporte:
                <span id="market_merchant_max_transport">13000</span></th>

        `max_transport` is the game's own answer for how much can be carried,
        so a world with a merchant bonus needs no extra configuration: dividing
        it by `total` gives the real per-merchant capacity instead of trusting
        a hardcoded 1000.

        Returns None when the page has no counters at all -- which is what
        happens on a screen that isn't the market (before 2026-08-11 the bot
        requested a non-existent `mode=send_res` and got an "invalid mode"
        error page, so this never matched and the failure looked like a broken
        regex rather than a wrong URL).
        """
        if type(res) != str:
            res = res.text

        def _num(element_id):
            match = re.search(fr'{element_id}["\s>]+(\d+)', res)
            return int(match.group(1)) if match else None

        available = _num("market_merchant_available_count")
        if available is None:
            return None
        return {
            "available": available,
            "total": _num("market_merchant_total_count"),
            "max_transport": _num("market_merchant_max_transport"),
        }

    @staticmethod
    def premium_data(res):
        """
        Detects data on the premium exchange page
        """
        if type(res) != str:
            res = res.text
        data = re.search(r'(?s)PremiumExchange.receiveData\((.+?)\);', res)
        if data:
            result = json.loads(data.group(1), strict=False)
            return result
        return None

    @staticmethod
    def recruit_data(res):
        """
        Fetches recruit data for the current building
        """
        if type(res) != str:
            res = res.text
        data = re.search(r'(?s)unit_managers.units = (\{.+?\});', res)
        if data:
            raw = data.group(1)
            quote_keys_regex = r'([\{\s,])(\w+)(:)'
            processed = re.sub(quote_keys_regex, r'\1"\2"\3', raw)
            result = json.loads(processed, strict=False)
            return result

    @staticmethod
    def units_in_village(res):
        """
        Detects all units in the village
        """
        if type(res) != str:
            res = res.text
        matches = re.search(r'<table id="units_home".*?</tr>(.*?)</tr>', res, re.DOTALL)
        # We get the start of the table and grab the 2nd row (Where "From this village" troops are located)
        if matches:
            table_content = matches.group(1)
            unit_matches = re.findall(r'class=\'unit-item unit-item-(.*?)\'[^>]*>(\d+)</td>', table_content)
            # Find all the tuples (name, quantity) under the class "unit-item unit-item-*troop_name*"
            units = [(re.sub(r'\s*tooltip\s*', '', unit_name), unit_quantity) for unit_name, unit_quantity in
                     unit_matches if int(unit_quantity) > 0]
            # Filter units with quantity = 0, also for the Paladin,
            # the name would be "knight tooltip", so we had to remove that.
            return units
        return []

    @staticmethod
    def active_building_queue(res):
        """
        Detects queued building entries
        """
        if type(res) != str:
            res = res.text
        builder = re.search('(?s)<table id="build_queue"(.+?)</table>', res)
        if not builder:
            return 0

        return builder.group(1).count('<a class="btn btn-cancel"')

    @staticmethod
    def active_recruit_queue(res):
        """
        Detects active recruitment entries
        """
        if type(res) != str:
            res = res.text
        builder = re.findall(r'(?s)TrainOverview\.cancelOrder\((\d+)\)', res)
        return builder

    @staticmethod
    def village_ids_from_overview(res):
        """
        Fetches villages from the overview page
        """
        if type(res) != str:
            res = res.text
        villages = re.findall(r'<span class="quickedit-vn" data-id="(\w+)"', res)
        return list(set(villages))

    @staticmethod
    def units_in_total(res):
        """
        Gets total amount of units in a village
        """
        if type(res) != str:
            res = res.text
        # hide units from other villages
        res = re.sub(r'(?s)<span class="village_anchor.+?</tr>', '', res)
        data = re.findall(r'(?s)class=\Wunit-item unit-item-([a-z]+)\W.+?(\d+)</td>', res)
        return data

    @staticmethod
    def attack_form(res):
        """
        Detects input fiels in the attack form
        ... because there are many :)
        """
        if type(res) != str:
            res = res.text
        data = re.findall(r'(?s)<input.+?name="(.+?)".+?value="(.*?)"', res)
        return data

    @staticmethod
    def attack_duration(res):
        """
        Detects the duration of an attack
        """
        if type(res) != str:
            res = res.text
        data = re.search(r'<span class="relative_time" data-duration="(\d+)"', res)
        if data:
            return int(data.group(1))
        return 0

    @staticmethod
    def report_table(res):
        """
        Fetches information from a report
        """
        if type(res) != str:
            res = res.text
        data = re.findall(r'(?s)class="report-link" data-id="(\d+)"', res)
        return data

    @staticmethod
    def error_box_text(res):
        """
        Texto legivel do primeiro `error_box` de uma resposta do jogo. Aceita a
        resposta do requests ou o HTML ja em string.

        Saber apenas que "houve error_box" nao distingue as causas de uma
        recusa, e elas pedem reacoes opostas -- falta de unidade quer dizer
        "pare de tentar este pacote neste ciclo", enquanto aldeia inexistente
        quer dizer "tire este alvo da lista". Quatro pontos do bot faziam
        `if '<div class="error_box">' in resposta` e jogavam o motivo fora:
        game/attack.py (farm), game/defence_manager.py (suporte, sem log
        nenhum), game/hunter.py (logava que houve, nao o que dizia) e
        game/resources.py -- este ultimo era o unico que lia o texto, com uma
        copia local desta funcao. Foi justamente a mensagem "Modo invalido",
        lida por ela em 2026-08-11, que revelou que a URL usada pela Feature 9
        desde sempre nao existia.

        Devolve string curta e sempre truthy, para poder ir direto num log sem
        o chamador ter que tratar None.
        """
        if res is None:
            return "sem resposta"
        html = res if isinstance(res, str) else getattr(res, "text", "") or ""
        # A forma com </div></div> casa o box completo quando ele embrulha um
        # bloco interno; a segunda e o fallback para o box de linha unica.
        box = re.search(r'<div class="error_box">(.*?)</div>\s*</div>', html, re.S)
        if not box:
            box = re.search(r'<div class="error_box">(.*?)</div>', html, re.S)
        if not box:
            return "sem error_box legivel"
        text = re.sub(r"<[^>]+>", " ", box.group(1))
        return " ".join(text.split())[:300] or "vazio"

    @staticmethod
    def loyalty_from_report(res):
        """
        Extrai a lealdade *depois* do ataque de nobre (snob) do HTML do
        relatorio. Retorna float ou None.

        Markup real do br143, confirmado ao vivo em 2026-08-13 buscando cinco
        relatorios de nobre com a sessao do bot. O rotulo esta num <th> e a
        celula tem texto antes do numero:

            <tr><th>Lealdade:</th>
            <td colspan="2">Descida <b>32</b> para <b>11</b></td></tr>

        A versao anterior exigia o numero colado no <td>
        (`<t[dh][^>]*>(\\d+)`), entao a palavra "Descida" fazia o casamento
        falhar sempre: nenhum relatorio em cache tinha `loyalty_after` e o
        ConquestManager caia na estimativa em 100% dos casos. Foi assim que o
        bot achou que a lealdade era 0 quando o servidor dizia 11, no
        incidente da Barbara #40314 (2026-08-12).

        Duas armadilhas que as amostras revelaram:

        - A lealdade fica NEGATIVA. Os relatorios de conquista trazem
          "Descida <b>18</b> para <b>-7</b>" e "<b>25</b> para <b>-8</b>". Um
          \\d+ sem sinal capturaria "7" -- lealdade positiva num relatorio que
          significa exatamente o contrario.
        - Sao DOIS numeros na mesma celula, o antes e o depois. Interessa o
          segundo.

        Por isso a celula e localizada pelo rotulo e o numero extraido e o
        ultimo dela: sobrevive a redacao ("Descida X para Y", "Decreased from
        X to Y") sem depender do idioma da frase.
        """
        if type(res) != str:
            res = res.text

        # Span dedicado, mantido como primeira tentativa: existe em alguns
        # temas/mundos e e inequivoco quando esta presente.
        match = re.search(r'id=["\']loyalty_new_value["\'][^>]*>\s*(-?\d+(?:\.\d+)?)', res)
        if match:
            return float(match.group(1))

        # Linha da tabela do relatorio. So o rotulo pt-BR foi confirmado
        # contra o servidor; os outros sao alternativas inofensivas -- se
        # estiverem errados simplesmente nao casam, que e o comportamento de
        # hoje.
        row = re.search(
            r'(?:Lealdade|Loyalty|Loyaliteit)\s*:?\s*</t[dh]>\s*<t[dh][^>]*>(.*?)</t[dh]>',
            res, re.IGNORECASE | re.DOTALL
        )
        if row:
            numbers = re.findall(r'-?\d+', row.group(1))
            if numbers:
                return float(numbers[-1])
        return None

    @staticmethod
    def incoming_command_type(block):
        """Classifica uma linha do widget de comandos recebidos.

        O jogo usa a mesma classe ``no_ignored_command`` para ataques e
        apoios.  O primeiro tooltip associado ao ``data-command-id`` traz o
        tipo visivel (por exemplo ``Ataque`` ou ``Apoio``); alguns temas usam
        tambem o nome do icone no ``src``.  Tipo desconhecido fica como
        ``unknown`` para o DefenceManager manter o fallback conservador.
        """
        if not isinstance(block, str):
            return "unknown"

        candidates = []
        for tag in re.findall(r"<(?:span|img)\b[^>]*>", block, re.I):
            lowered = tag.lower()
            if "data-command-id" in lowered or "graphic/command/" in lowered:
                for attribute in ("data-title", "title"):
                    title = re.search(
                        rf'{attribute}=["\']([^"\']*)["\']', tag, re.I
                    )
                    if title and title.group(1).strip():
                        candidates.append(title.group(1))
                src = re.search(r'src=["\']([^"\']*)["\']', tag, re.I)
                if src:
                    candidates.append(src.group(1))

        # O tooltip real e a fonte principal. O nome do arquivo e a alternativa
        # independente de idioma para temas que nao incluem title.
        normalized = " ".join(html.unescape(value).casefold() for value in candidates)
        if re.search(
                r"(?:^|[\s/_-])(apoio|suporte|support|supports|ondersteun|unterstutz|soutien)"
                r"(?:[\s/_.-]|$)", normalized):
            return "support"
        if re.search(
                r"(?:^|[\s/_-])(ataque|attack|aanval|angriff|attaque)"
                r"(?:[\s/_.-]|$)", normalized):
            return "attack"
        return "unknown"

    @staticmethod
    def incoming_commands(res):
        """
        Feature 16: extrai comandos recebidos (não ignorados) da página de
        overview de uma aldeia -- usado pelo DefenceManager para priorizar
        evacuação por urgência real (ETA) em vez de reagir igual a qualquer
        comando recebido, esteja ele chegando em minutos ou horas.

        Markup real do br143, capturado em 2026-08-22 com quatro ataques a
        caminho da aldeia 41114 (recorte verbatim em
        tests/test_incoming_commands.py). Uma linha do widget é:

            <tr class="command-row no_ignored_command">
              <td> ... <span class="quickedit" data-id="421560489">
                         ... <span class=" tooltip" data-command-id="421560489"
                                   title="Ataque"> ... </span>
                         ... <span class="quickedit-label">
                               0014 | Aldeia de bárbaros</span> ... </td>
              <td>hoje às 13:13:09:<span class="grey small">598</span></td>
              <td><span class="widget-command-timer"
                        data-endtime="1787415189">5:27:17</span></td>
            </tr>

        A versão anterior procurava data-command-id **no próprio <tr>** e por
        isso não casava linha nenhuma: o atributo mora em spans aninhados,
        seis níveis abaixo. O regex tinha sido inferido de padrões de outras
        telas e nunca conferido contra um ataque real -- limitação que estava
        registrada em docs/backend.md e se confirmou em campo. A falha era
        silenciosa e cara: lista vazia é lida por _is_urgent() como "urgente",
        então o bot evacuava em **todo** ataque, que é precisamente o que a
        Feature 16 existia para evitar.

        A âncora agora é a classe `no_ignored_command` do <tr> -- o mesmo
        marcador que DefenceManager.update() já usa para decidir "sob ataque",
        e que vem do bot base (portanto não é markup de conta premium).

        ETA em três fontes, nesta ordem de confiança:
          - data-endtime="UNIX_TS" (timestamp absoluto de chegada)
          - data-duration="SEGUNDOS" (segundos restantes já calculados)
          - texto renderizado do contador ("5:27:17") que, ao contrário do
            caso do Paladino em StatuePage, **vem preenchido pelo servidor**
            no HTML cru -- conferido na captura de 2026-08-22.

        Retorna lista de dicts
        {command_id, eta_seconds, origin, attacker, command_type}.
        `attacker` é o nome do jogador e vem None nesta tela: a linha traz o
        nome da *aldeia* de origem (devolvido em `origin`), não o do dono.
        Lista vazia se nada casou -- chamadores devem tratar isso como
        "urgência desconhecida", não como "sem ataques" (ver
        DefenceManager._parse_incoming_urgency).
        """
        if type(res) != str:
            res = res.text
        commands = []
        try:
            rows = INCOMING_ROW_RE.findall(res)
        except Exception:
            return commands
        for block in rows:
            eta_seconds = None
            endtime_match = re.search(r'data-endtime="(\d+)"', block)
            if endtime_match:
                eta_seconds = int(endtime_match.group(1)) - int(time.time())
            else:
                duration_match = re.search(r'data-duration="(\d+)"', block)
                if duration_match:
                    eta_seconds = int(duration_match.group(1))
                else:
                    timer_match = re.search(
                        r'class="[^"]*widget-command-timer[^"]*"[^>]*>\s*'
                        r'(\d+):([0-5]\d):([0-5]\d)\s*<',
                        block,
                    )
                    if timer_match:
                        hours, minutes, seconds = (int(g) for g in timer_match.groups())
                        eta_seconds = hours * 3600 + minutes * 60 + seconds
            if eta_seconds is None:
                continue
            id_match = re.search(r'data-(?:command-)?id="(\d+)"', block)
            origin_match = re.search(
                r'class="[^"]*quickedit-label[^"]*"[^>]*>\s*(.*?)\s*</span>',
                block,
                re.S,
            )
            attacker_match = re.search(r'screen=info_player[^"]*"[^>]*>([^<]+)</a>', block)
            commands.append({
                "command_id": id_match.group(1) if id_match else None,
                "eta_seconds": max(0, eta_seconds),
                "origin": origin_match.group(1).strip() if origin_match else None,
                "attacker": attacker_match.group(1).strip() if attacker_match else None,
                "command_type": Extractor.incoming_command_type(block),
            })
        return commands

    @staticmethod
    def incoming_support_speed_bonus(res):
        """
        Percentual de aceleracao do apoio que CHEGA nesta aldeia, do item
        "Sinal da Aflicao" (icone benefit_incoming_support_speed). Zero quando
        o efeito nao esta ativo.

        Medido no br143 em 2026-08-22, com o item ativo na BBM 008 e um envio
        real da BBM 009 (3,16 campos, espada a 22 min/campo):

            sem bonus   3,16227 x 22 x 60 = 4.174 s = 1:09:34
            o jogo deu                              = 0:53:31
            4.174 / 1,3                   = 3.211 s = 0:53:30   <-- bate

        Ou seja, **"30% mais rapido" e duracao / 1,3**, e nao duracao x 0,7
        (que daria 0:48:41, cinco minutos a menos). A leitura ingenua erra
        para menos e o erro cresce com a distancia. Ver
        WorldConfig.travel_seconds para onde o numero e aplicado.

        Duas propriedades do efeito, do texto do proprio jogo:
          - vale no momento do ENVIO ("sem efeito em apoio ja enviado"), o que
            e o que permite trata-lo como um fator no calculo de viagem;
          - fica na aldeia de DESTINO, nao na doadora -- por isso o valor
            trafega por cache/managed e nao pelo estado local de quem envia.

        Devolve int (0..100). Zero tanto para "sem efeito" quanto para
        "markup nao reconhecido": aqui as duas coisas levam a mesma acao
        correta (usar a viagem sem bonus), que e a estimativa conservadora --
        o bot manda mais cedo do que precisaria, nunca mais tarde.
        """
        if type(res) != str:
            res = res.text
        try:
            cells = EFFECT_CELL_RE.findall(res)
        except Exception:
            return 0
        for block in cells:
            if INCOMING_SUPPORT_SPEED_ICON not in block:
                continue
            match = EFFECT_PERCENT_RE.search(block)
            if not match:
                continue
            pct = int(match.group(1))
            # Sanidade: um bonus fora de 0-100 e leitura errada, nao um item
            # milagroso. Melhor ignorar do que dividir a viagem por 6.
            if 0 < pct <= 100:
                return pct
        return 0

    @staticmethod
    def get_daily_reward(res):
        """
        Detects if there are unopened daily rewards
        """
        if type(res) != str:
            res = res.text
        get_daily = re.search(r'DailyBonus.init\((\s+\{.*\}),', res)
        res = json.loads(get_daily.group(1))
        reward_count_unlocked = str(res["reward_count_unlocked"])
        if reward_count_unlocked and res["chests"][reward_count_unlocked]["is_collected"]:
            return reward_count_unlocked
        return None
