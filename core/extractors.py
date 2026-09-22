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

# `screen=info_player&mode=stats_own`: series "ricas" (recurso por dia) que o
# jogo embute no HTML como `data.push({label: 'Saqueado', ..., details: [...]})`.
# O label identifica a serie -- nao ha id no bloco, e a ORDEM nao e garantia
# (docs/backend.md 8.13).
#
# ⚠️ O RECORTE E POR BLOCO, e isso NAO e preciosismo -- a primeira versao
# escaneava o documento inteiro com
#
#     label:\s*'([^']+)'.*?details:\s*(\[\{.*?\}\])     (re.S)
#
# e um `label:` SEM `details:` no proprio bloco fazia o `.*?` atravessar a
# fronteira e casar aquele label com os numeros do bloco SEGUINTE. Medido em
# 2026-09-22 contra um caso construido: `Saqueado` desapareceu e os numeros
# dele sairam rotulados `Pontos`. Nenhum erro, nenhum log -- so a resposta
# errada, que e a forma exata do decimo quinto padrao do CLAUDE.md. Na pagina
# de hoje os 8 blocos tem os dois campos e o pareamento sai certo por sorte;
# basta o jogo acrescentar UMA serie de linha (que tem label e nao tem
# details) antes de "Saqueado" para o card de /empire passar a mostrar
# coletado como se fosse saqueado.
STATS_OWN_PUSH_RE = re.compile(r"data\.push\(")
STATS_OWN_LABEL_RE = re.compile(r"label:\s*'([^']+)'")
STATS_OWN_DETAILS_RE = re.compile(r"details:\s*")


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
    def scavenge_config(res):
        """
        Config das opções de coleta, do 1º argumento de `new ScavengeScreen(`.

        É a tabela do MUNDO (custo e duração de desbloqueio, `loot_factor`,
        `prerequisite_option_ids`), não o estado da aldeia -- este último vem
        do 2º argumento e sai por `village_data()`.

        Existe para que o desbloqueio (P-COL-02(b)) leia o preço da própria
        tela em vez de carregar uma tabela chumbada: o custo é do servidor e
        varia por mundo, e um número copiado para cá é uma foto que expira sem
        avisar (14º padrão do CLAUDE.md).

        O `\\s*` no padrão não é enfeite: o jogo quebra a linha e indenta entre
        o `(` e o `{`, e `balanced_slice` exige o índice exato da abertura --
        sem ele isto devolve None em toda chamada, que é a falha muda do 15º
        padrão. Fixture verbatim do br143 em tests/test_scavenge_unlock.py.
        """
        if type(res) != str:
            res = res.text
        return Extractor.js_object_after(res, r"new ScavengeScreen\(\s*")

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

    # Ancora de "esta e de fato a tela de reservas". O que motiva a guarda: a
    # resposta de sessao expirada e um 200 com a pagina de login (51 KB, medida
    # em 2026-09-20), e nela o regex de linha simplesmente nao casa -- sem esta
    # checagem, "sessao morreu" e "a tribo nao reservou nada" viram o mesmo
    # `[]`, e o consumidor liberaria conquista justamente quando esta cego.
    # Ancorada no MESMO padrao que a tela usa, nao numa versao frouxa dele
    # (15o padrao do CLAUDE.md): na pagina de login ha zero ocorrencias, na
    # tela real havia 122.
    RESERVATION_SCREEN_ANCHOR = "mode=reservations"

    RESERVATION_ROW_RE = re.compile(r'<tr id="reservation_(\d+)">(.*?)</tr>', re.S)
    RESERVATION_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)

    # Fase 2: o token CSRF das acoes de escrita. Sai do `action` do proprio
    # formulario de criar reserva, e nao de um `h` solto na pagina -- ha varios
    # formularios na tela (`action=submit`, `save_page_size`,
    # `new_reservation`, `save_reservation_settings`) e todos carregam `h`,
    # mas so este e o que a Fase 2 pode disparar. Ancorar no formulario certo
    # evita que uma mudanca de ordem na pagina troque o token por acidente.
    RESERVATION_CSRF_RE = re.compile(
        r'<form action="[^"]*mode=reservations[^"]*action=new_reservation'
        r'[^"]*?h=([a-f0-9]+)',
        re.I,
    )

    # A linha NAO traz o TEXTO do comentario, so um flag binario; o texto vem
    # de um POST em `ajax=load_comment`, um por reserva. O flag e o que torna
    # essa leitura barata -- so vale pedir o texto de quem tem um.
    #
    # ⚠️ O sinal e a IMAGEM, nao o link. A primeira versao deste regex casava
    # `id="show_reservation_comment_<id>"`, e isso estava errado de um jeito
    # que so a captura de 2026-09-21 mostrou: nas reservas DA PROPRIA CONTA o
    # jogo renderiza esse link sempre, mesmo sem comentario nenhum, porque o
    # dono pode EDITAR. Medido nas 441 linhas do quadro: o link casava 16
    # linhas e so 13 tinham comentario, e as 3 falsas positivas eram
    # exatamente as 3 reservas da conta -- ou seja, 100% de erro justamente
    # nas linhas de que a procedencia depende (15o padrao). As duas imagens
    # sao exaustivas e exclusivas (13 + 428 = 441).
    RESERVATION_HAS_COMMENT_RE = re.compile(r"show_comment\.png")

    # Link "Apagar" que o jogo renderiza SO nas reservas da propria conta
    # (medido: 3 linhas em 441, que sao exatamente as 3 da conta). E uma
    # afirmacao DO SERVIDOR sobre quem pode remover o que, e por isso vale
    # mais que qualquer URL montada aqui: o href ja vem com `h`, `page`,
    # `sort`, `order` e `filter` da propria leitura.
    RESERVATION_DELETE_HREF_RE = re.compile(
        r'href="([^"]*action=delete_reservations[^"]*)"', re.I
    )

    @staticmethod
    def tribe_reservations(res):
        """
        Reservas do sistema OFICIAL da tribo (`screen=ally&mode=reservations`).

        Devolve lista de dicts, ou **None** quando a resposta nao e a tela de
        reservas -- e a distincao importa mais que o conteudo: `None` significa
        "nao sei o que esta reservado" e `[]` significa "nada esta reservado".
        Confundir os dois faria o bot conquistar livremente durante uma sessao
        expirada, que e exatamente o incidente que a Feature existe para
        impedir (docs/backend.md 8.7, "Custo de errar").

        Markup real do br143, capturado ao vivo em 2026-09-20 com o WebWrapper
        do bot (7o padrao). Uma linha, verbatim e sem cortes no meio:

            <tr id="reservation_75920">
                <td>
                    <input type="checkbox" name="ids[]" value="75920"/>
                    <span class="village_anchor" data-player="0" data-id="40808">
                      <a href="...screen=info_village&amp;id=40808">
                        Aldeia de barbaros (531|289) K25</a></span>
                </td>
                <td>1012</td>
                <td>---</td>
                <td>
                    <a href="...screen=info_ally&amp;&amp;id=16">[RANDOW]</a>
                    <a href="...screen=info_player&amp;id=919714218">Conde ...</a>
                </td>
                <td>hoje as 07:45</td>
                ...
            </tr>

        Tres armadilhas que a captura desfez, e que um parser escrito de
        cabeca teria errado:

        1. **O id do `<tr>` e o id da RESERVA, nao da aldeia** (75920 contra
           40808). A aldeia sai de `data-id` no `span.village_anchor`; o dono
           atual sai de `data-player` (`"0"` = barbara). Usar o id do `<tr>`
           como alvo nunca casaria com nada em `cache/conquest`.
        2. **A coluna 5 e "Data de validade", nao a data de criacao** -- lido
           do `<th>`, que ordena por `sort=expires_at`. O texto e relativo e em
           portugues ("hoje as 07:45"), entao ele e guardado **cru**, sem
           virar timestamp: a Fase 1 nao precisa da data (estar na lista ja
           significa reservada, porque o servidor nao lista o que expirou) e
           inventar um parser de data relativa seria fragilidade de graca.
        3. **A celula do reservante tem DOIS links** quando ele tem tribo: o
           da tribo (`info_ally`) vem antes do jogador (`info_player`). Pegar
           "o primeiro id da linha" traria a tribo, e pegar "o ultimo id da
           linha" traria o icone de mapa. Por isso o parse e por celula
           posicional, com `info_player` so dentro da celula 3.

        A premissa do parse por celula -- nenhum `<td>` aninhado dentro da
        linha -- foi **medida** contra a fixture real (6 celulas), nao suposta;
        ver `tests/test_tribe_reservations.py`.
        """
        if res is None:
            return None
        html = res if isinstance(res, str) else getattr(res, "text", "") or ""
        if Extractor.RESERVATION_SCREEN_ANCHOR not in html:
            return None

        reservations = []
        for reservation_id, row in Extractor.RESERVATION_ROW_RE.findall(html):
            cells = Extractor.RESERVATION_CELL_RE.findall(row)
            if len(cells) < 5:
                continue

            anchor = re.search(r'data-player="(\d+)"\s+data-id="(\d+)"', cells[0])
            if not anchor:
                continue
            owner, village_id = anchor.group(1), anchor.group(2)

            coords = re.search(r"\((\d+)\|(\d+)\)", cells[0])
            name = re.search(r"<a[^>]*>(.*?)</a>", cells[0], re.S)

            player = re.search(
                r'info_player&(?:amp;)?id=(\d+)[^>]*>(.*?)</a>', cells[3], re.S
            )
            tribe = re.search(r"\[([^\]]+)\]", cells[3])
            delete = Extractor.RESERVATION_DELETE_HREF_RE.search(row)

            reservations.append({
                "reservation_id": reservation_id,
                "village_id": village_id,
                "owner": owner,
                "location": (int(coords.group(1)), int(coords.group(2))) if coords else None,
                "village_name": " ".join(name.group(1).split()) if name else "",
                "reserved_by_id": player.group(1) if player else None,
                "reserved_by_name": " ".join(player.group(2).split()) if player else "",
                "reserved_by_tribe": tribe.group(1) if tribe else "",
                "expires_text": " ".join(re.sub(r"<[^>]+>", " ", cells[4]).split()),
                # Flag binario, nao o texto -- ver RESERVATION_HAS_COMMENT_RE.
                "has_comment": bool(Extractor.RESERVATION_HAS_COMMENT_RE.search(row)),
                # Presente so nas reservas desta conta. `None` nas dos outros,
                # e e por isso que ele e uma guarda de procedencia e nao so uma
                # conveniencia: sem href nao ha como remover.
                "delete_href": (
                    delete.group(1).replace("&amp;", "&") if delete else None
                ),
            })
        return reservations

    @staticmethod
    def reservation_csrf(res):
        """
        Token `h` das acoes de escrita do quadro, lido do formulario de criar
        reserva. `None` quando a resposta nao e a tela (sessao expirada) --
        e sem ele a Fase 2 nao escreve nada, em vez de postar sem token e
        tratar a recusa como sucesso.
        """
        if res is None:
            return None
        html = res if isinstance(res, str) else getattr(res, "text", "") or ""
        match = Extractor.RESERVATION_CSRF_RE.search(html)
        return match.group(1) if match else None

    @staticmethod
    def reservation_comment(res):
        """
        Resposta de `ajax=load_comment` / `ajaxaction=save_comment`.

        O contrato NAO foi deduzido do HTML: veio do proprio
        `ReservationManager.js` que a tela carrega (buscado do CDN estatico
        `dsbr.innogamescdn.com`, que nao tem sessao e por isso nao gasta o
        limite de taxa da conta). O `success` do jQuery trata a resposta como

            {"code": <truthy>, "id": <reservation_id>, "comment": "<texto>",
             "rights": "write"|...}

        e o proprio JS so considera a chamada boa quando `code` e truthy
        (`e.code||alert(...)`) -- entao a guarda aqui e a mesma que o jogo usa,
        nao uma inventada.

        Devolve o dict cru, ou `None` quando nao deu para ler. `None` e
        "nao sei o que esta escrito ali", e quem consome NUNCA pode ler isso
        como "nao e do bot": e com base nesse texto que se decide remover, e
        remover reserva alheia e o incidente da 8.7 ao contrario.
        """
        if res is None:
            return None
        if isinstance(res, dict):
            payload = res
        else:
            try:
                payload = res.json()
            except Exception:
                return None
        if not isinstance(payload, dict) or not payload.get("code"):
            return None
        return payload

    @staticmethod
    def own_player_id(res):
        """
        Id do jogador da propria conta, lido do `game_state` que vem em quase
        toda tela -- inclusive na propria tela de reservas.

        Existe para separar "reservado por mim" de "reservado por outro" sem
        config nova: uma chave de config com o id errado faria o bot furar
        reserva alheia (achando que e sua) ou barrar os proprios alvos, e nada
        no log denunciaria. Confirmado ao vivo em 2026-09-20 na resposta de
        `screen=ally&mode=reservations`: `player.id = 5955651`, que e o mesmo
        numero que o filtro "[Sua]" da propria tela usa
        (`group_id=creator_id&filter=5955651`) -- ou seja, o jogo concorda que
        este e o campo que identifica o criador da reserva.

        Devolve string (os ids das reservas vem do HTML como string) ou None.
        """
        state = Extractor.game_state(res) or {}
        player_id = (state.get("player") or {}).get("id")
        return str(player_id) if player_id else None

    @staticmethod
    def stats_own_series(res):
        """
        `screen=info_player&mode=stats_own`: series "ricas" de recurso por dia
        (`Saqueado`, `Coletado`, e as de gasto), ja agregadas server-side.

        Devolve {label: [{"observed_at", "wood", "stone", "iron", "total",
        "percent"}, ...]} na mesma ordem do jogo (mais recente primeiro) ou
        None se a tela nao trouxer nenhuma serie reconhecivel -- resposta de
        login/bot-protection, ou markup que mudou.

        Contratos MEDIDOS em docs/backend.md 8.13, nao supostos, e que quem
        consome isto precisa preservar:
          (a) e CONTA INTEIRA, nunca por aldeia;
          (b) so os dias que a resposta trouxe (retencao curta do jogo) --
              esta funcao nao acumula nada, so traduz o que veio;
          (c) `percent` e a participacao daquela serie no total DAQUELE DIA
              (confere: `Saqueado` 25,997% + `Coletado` 74,003% = 100% em
              21/09), nao "aproveitamento";
          (d) e SALDO, nao evento -- um `observed_at` por DIA, nao por
              operacao.

        O laco recorta um bloco `data.push(...)` por vez ANTES de procurar
        label e details, para que um bloco sem details nao possa se apropriar
        dos numeros do bloco seguinte -- ver o comentario de
        STATS_OWN_PUSH_RE, que registra a medicao desse defeito. `details` sai
        por `balanced_slice` e nao por `\\[\\{.*?\\}\\]`: o lazy para no
        primeiro `}]` e truncaria a lista se o jogo aninhasse um objeto dentro
        de cada ponto -- e o proprio docstring de `balanced_slice` existe por
        causa dessa armadilha.
        """
        if type(res) != str:
            res = res.text
        if not res:
            return None

        bounds = [m.start() for m in STATS_OWN_PUSH_RE.finditer(res)]
        out = {}
        for i, start in enumerate(bounds):
            end = bounds[i + 1] if i + 1 < len(bounds) else len(res)
            block = res[start:end]

            label_match = STATS_OWN_LABEL_RE.search(block)
            details_match = STATS_OWN_DETAILS_RE.search(block)
            if not label_match or not details_match:
                # Bloco sem um dos dois campos: e uma serie de outro tipo
                # (linha, legenda). Pular sem deixar vazar para o proximo.
                continue
            label = label_match.group(1)

            raw = Extractor.balanced_slice(block, details_match.end())
            if raw is None:
                continue
            try:
                rows = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                continue
            parsed = []
            for row in rows:
                try:
                    parsed.append({
                        "observed_at": int(row["time"]) // 1000,
                        "wood": int(row["wood"]),
                        "stone": int(row["stone"]),
                        "iron": int(row["iron"]),
                        "total": int(row["total"]),
                        "percent": float(row["percent"]),
                    })
                except (KeyError, TypeError, ValueError):
                    continue
            if parsed:
                out[label] = parsed
        return out or None

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
