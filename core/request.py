"""
Class for using one generic cookie jar, emulating a single tab
"""

import requests

from core import game_data_shadow
from core.cycle_meter import CycleMeter
from core.filemanager import FileManager
from core.notification import Notification

import logging
import re
import time
import random
from urllib.parse import urljoin, urlencode

from core.reporter import ReporterObject

# Default timeout for all HTTP requests (connect, read) in seconds.
# br143 occasionally hangs; 45s is generous enough for slow responses
# but prevents the bot from blocking indefinitely.
REQUEST_TIMEOUT = (15, 45)

# Marcador que o jogo coloca na pagina quando exige captcha ("bot protection").
BOT_PROTECT_MARKER = 'data-bot-protect="forced"'


class WebWrapper:
    """
    WebWrapper object for sending HTTP requests
    """
    web = None
    headers = {
        'user-agent': 'Mozilla/5.0 (Windows NT 6.3; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/78.0.3904.97 Safari/537.36',
        'upgrade-insecure-requests': '1'
    }
    endpoint = None
    logger = logging.getLogger("Requests")
    server = None
    last_response = None
    last_h = None
    priority_mode = False
    auth_endpoint = None
    reporter = None
    delay = 1.0

    # Espera entre duas reconferencias de captcha. Nao precisa ser curto: quem
    # resolve o captcha e uma pessoa no navegador, e o custo de descobrir um
    # minuto depois e um minuto.
    CAPTCHA_POLL_SECONDS = 60
    # Espera entre duas leituras de cache/cookies.txt enquanto nao ha sessao.
    COOKIE_POLL_SECONDS = 15
    # De quanto em quanto tempo a instrucao de como destravar e reimpressa.
    COOKIE_REMIND_SECONDS = 600
    COOKIE_FILE = "cache/cookies.txt"

    def __init__(self, url, server=None, endpoint=None, reporter_enabled=False, reporter_constr=None):
        self.web = requests.session()
        self.auth_endpoint = url
        self.server = server
        self.endpoint = endpoint
        self.reporter = ReporterObject(enabled=reporter_enabled, connection_string=reporter_constr)
        # P-CICLO-MEDIDA: todo GET/POST passa por aqui, entao e aqui que se
        # conta. Uma instancia por wrapper, e o wrapper e um so por processo
        # (vigesimo quinto padrao), logo um medidor so para o ciclo inteiro.
        self.meter = CycleMeter()
        # P-OVERVIEW-SOMBRA: ultimo game_data visto por aldeia, de qualquer
        # tela. Em __init__, nao no corpo da classe (primeiro padrao).
        self.game_data_seen = {}
        # §9 item 20a (corte): game_data COMPLETO da ultima resposta HTML de
        # cada aldeia, para as releituras 2 e 3 da visao geral reaproveitarem
        # em vez de fazer o GET. 0 desliga; twb.py regrava por ciclo a partir
        # de `bot.reuse_game_data_max_age`.
        self.game_data_full = {}
        self.reuse_game_data_max_age = 0

    def _remember_game_data(self, response):
        """Guarda o recorte do game_data desta resposta, se houver. Nunca
        levanta: e observabilidade, igual ao medidor."""
        try:
            ajax = "json" in (response.headers.get("content-type") or "")
            gd = game_data_shadow.extract_game_data(response.text)
            snap = game_data_shadow.snapshot(gd, source_url=response.url, ajax=ajax) if gd else None
            if snap:
                self.game_data_seen[snap["village_id"]] = snap
                game_data_shadow.remember_full(self, snap["village_id"], gd, response.text)
        except Exception:
            pass

    def _meter(self, method, slept, started, captcha=0.0, ok=True, url=None):
        """Registra uma requisicao no medidor de ciclo. Nunca levanta: o
        medidor e observabilidade e nao pode derrubar uma requisicao."""
        try:
            self.meter.record_request(
                method, slept=slept, net=time.time() - started - captcha,
                captcha=captcha, ok=ok, url=url)
        except Exception:
            pass

    def _pause(self):
        """O sono entre requisicoes. Devolve quanto dormiu, para o medidor.

        `time.time()` e nao `monotonic()` em todo o registro: os testes de
        captcha trocam o `time` deste modulo por um relogio falso, e medir com
        o mesmo relogio que o resto do arquivo mantem os numeros coerentes."""
        if self.priority_mode:
            return 0.0
        started = time.time()
        time.sleep(random.randint(int(3 * self.delay), int(7 * self.delay)))
        return time.time() - started

    def post_process(self, response):
        xsrf = re.search('<meta content="(.+?)" name="csrf-token"', response.text)
        if xsrf:
            self.headers['x-csrf-token'] = xsrf.group(1)
            self.logger.debug("Set CSRF token")
        elif 'x-csrf-token' in self.headers:
            del self.headers['x-csrf-token']
        self.headers['Referer'] = response.url
        self.last_response = response
        get_h = re.search(r'&h=(\w+)', response.text)
        if get_h:
            self.last_h = get_h.group(1)
        self._remember_game_data(response)

    def get_url(self, url, headers=None):
        self.headers['Origin'] = (self.endpoint if self.endpoint else self.auth_endpoint).rstrip('/')
        slept = self._pause()
        started = time.time()
        url = urljoin(self.endpoint if self.endpoint else self.auth_endpoint, url)
        if not headers:
            headers = self.headers
        try:
            res = self.web.get(url=url, headers=headers, timeout=REQUEST_TIMEOUT)
            self.logger.debug("GET %s [%d]", url, res.status_code)
            self.post_process(res)
            if BOT_PROTECT_MARKER in res.text:
                # GET e idempotente: da para repetir a propria requisicao
                # bloqueada e devolver a resposta boa ao chamador.
                blocked_at = time.time()
                res = self._await_captcha_clear(probe_url=url, headers=headers)
                self._meter("GET", slept, started, url=url,
                            captcha=time.time() - blocked_at, ok=res is not None)
                return res
            self._meter("GET", slept, started, url=url)
            return res
        except Exception as e:
            self.logger.warning("GET %s: %s", url, str(e))
            self._meter("GET", slept, started, url=url, ok=False)
            return None

    def post_url(self, url, data, headers=None):
        slept = self._pause()
        started = time.time()
        self.headers['Origin'] = (self.endpoint if self.endpoint else self.auth_endpoint).rstrip('/')
        url = urljoin(self.endpoint if self.endpoint else self.auth_endpoint, url)
        enc = urlencode(data)
        if not headers:
            headers = self.headers
        try:
            res = self.web.post(url=url, data=data, headers=headers, timeout=REQUEST_TIMEOUT)
            self.logger.debug("POST %s %s [%d]", url, enc, res.status_code)
            self.post_process(res)
            if BOT_PROTECT_MARKER in res.text:
                # Construcao, recrutamento, coleta e envio de ataque passam por
                # aqui. Antes desta guarda um captcha durante um POST era
                # *invisivel*: a pagina de bot protection voltava com 200 e o
                # chamador a tratava como "acao aceita" -- decimo quinto padrao,
                # um detector que nunca dispara.
                #
                # A acao **nao** e repetida depois que o captcha sai. Reenviar
                # um POST as cegas duplicaria ataque/construcao, que e o tipo de
                # estrago que a §8.7 documenta; `None` e o valor de falha que os
                # chamadores ja tratam.
                blocked_at = time.time()
                self._await_captcha_clear(
                    probe_url="game.php?screen=overview", headers=self.headers)
                self.logger.warning(
                    "POST %s foi bloqueado por bot protection e NAO foi refeito; "
                    "a acao sera retentada no proximo ciclo", url)
                self._meter("POST", slept, started, url=url,
                            captcha=time.time() - blocked_at, ok=False)
                return None
            self._meter("POST", slept, started, url=url)
            return res
        except Exception as e:
            self.logger.warning("POST %s %s: %s", url, enc, str(e))
            self._meter("POST", slept, started, url=url, ok=False)
            return None

    def _await_captcha_clear(self, probe_url, headers=None):
        """Espera o captcha ("bot protection") sair, reconferindo a pagina.

        Substitui o `input("Press any key...")` que existia aqui. O prompt era
        inutil em tres situacoes distintas e todas reais:

        - o bot subido pelo painel nao tem console, entao ninguem podia
          responder: o processo ficava **vivo, com pid valido e parado para
          sempre** enquanto o painel dizia "rodando" (vigesimo segundo padrao);
        - quem resolve o captcha resolve **no navegador**, nao no console do
          bot, e a tecla so era apertada quando alguem passava na frente da
          maquina;
        - o `input()` estava dentro do `try`, entao um stdin fechado levantava
          `EOFError` e virava um `GET falhou` generico no log -- o motivo real
          sumia.

        Agora o proprio bot descobre sozinho quando o bloqueio saiu. A espera e
        **sem limite** de proposito: desistir devolveria `None` para todo mundo
        e faria os managers decidirem sobre dado ausente, e o captcha nao se
        resolve sozinho. Cada tentativa loga, entao a idade da ultima linha do
        log -- o unico sinal honesto de atividade (vigesimo segundo padrao) --
        continua andando enquanto o bot espera.

        Devolve a resposta ja limpa de `probe_url`, ou `None` se a reconferencia
        nunca chegar a acontecer por erro de rede persistente (esse caminho so
        existe no laco, que nao sai sem sucesso).
        """
        started = time.time()
        self.logger.warning(
            "Bot protection! Resolva o captcha no navegador (mesma sessao); "
            "o bot volta sozinho quando sair. Reconferindo a cada %ds.",
            self.CAPTCHA_POLL_SECONDS)
        self.reporter.report(
            0, "TWB_RECAPTCHA",
            "Bot protection: resolva o captcha no navegador, o bot retoma sozinho")
        Notification.send(
            "Bot protection! Resolva o captcha no navegador da mesma sessao - "
            "o bot retoma sozinho quando sair.")

        probe_url = urljoin(self.endpoint if self.endpoint else self.auth_endpoint, probe_url)
        if not headers:
            headers = self.headers
        while True:
            time.sleep(self.CAPTCHA_POLL_SECONDS)
            try:
                res = self.web.get(url=probe_url, headers=headers, timeout=REQUEST_TIMEOUT)
            except Exception as exc:
                self.logger.warning("Reconferencia de captcha falhou: %s", exc)
                continue
            waited = int(time.time() - started)
            if BOT_PROTECT_MARKER in res.text:
                # De proposito sem `post_process`: a pagina de captcha nao tem
                # csrf-token nem `&h=`, e processa-la jogaria fora os que valem.
                self.logger.warning(
                    "Ainda bloqueado por bot protection (%ds esperando)", waited)
                continue
            self.post_process(res)
            self.logger.info("Bot protection saiu apos %ds, retomando", waited)
            Notification.send("Captcha resolvido, o bot retomou.")
            return res

    @staticmethod
    def _parse_cookie_string(raw):
        """Converte um `k=v; k2=v2` de navegador em dict.

        Tolera o BOM do Bloco de Notas, quebras de linha e o prefixo `cookie:`
        (quem copia do DevTools copia o cabecalho inteiro). Par sem `=` e
        ignorado em vez de virar chave de valor vazio.
        """
        cookies = {}
        raw = (raw or "").replace(chr(0xFEFF), "").replace("\n", "").replace("\r", "").strip()
        if raw.lower().startswith("cookie:"):
            raw = raw.split(":", 1)[1].strip()
        for item in raw.split(";"):
            item = item.strip()
            if not item or "=" not in item:
                continue
            key, value = item.split("=", 1)
            key = key.strip()
            if key:
                cookies[key] = value
        return cookies

    def _persist_session(self):
        """Grava a sessao **ja provada**. Nunca chamar antes do teste passar."""
        FileManager.save_json_file({
            'endpoint': self.endpoint,
            'server': self.server,
            'cookies': {c.name: c.value for c in self.web.cookies}
        }, "cache/session.json")

    def _session_works(self, cookies):
        """Carrega os cookies e diz se eles dao uma pagina de jogo logada.

        Nada e persistido antes da prova, entao um cookie vencido colado por
        engano nao sobrescreve um `cache/session.json` que funcionava.
        """
        if not cookies:
            return False
        self.web.cookies.clear()
        self.web.cookies.update(cookies)
        test = self.get_url("game.php?screen=overview")
        if not test or "game.php" not in test.url:
            return False
        self._persist_session()
        return True

    def start(self):
        """Obtem uma sessao utilizavel. Nunca pergunta nada no console.

        Ordem: `cache/session.json` -> `cache/cookies.txt` -> espera o arquivo
        aparecer. O `input("Enter browser cookie string> ")` que existia aqui
        saiu por dois motivos independentes:

        1. **Sem console nao ha resposta.** Bot subido pelo painel ficava parado
           para sempre nesse prompt, com o painel dizendo "rodando" -- e o
           `bot_output.log` guardava a prova disso desde 30/06/2026 (vigesimo
           segundo padrao).
        2. **Console trunca linha longa.** Um cookie de Tribal Wars e maior que
           o buffer de linha do `cmd.exe`, entao colar ali corta a string em
           silencio: o bot aceita, o servidor nao, e todo ciclo seguinte diz
           "sessao invalida" sem dizer por que. Essa e a observacao do fork
           LazyTurtle, e e o motivo de o prompt nao ter sido mantido nem quando
           existe console.

        Um arquivo nao tem limite de linha e pode ser escrito de fora do
        processo -- inclusive com o bot ja rodando e esperando.
        """
        session_data = FileManager.load_json_file("cache/session.json")
        if session_data and session_data.get("cookies"):
            if self._session_works(session_data["cookies"]):
                self.logger.info("Game Endpoint: %s", self.endpoint)
                return True
            self.logger.warning("Current session cache not valid")

        raw = FileManager.read_file(self.COOKIE_FILE, encoding="utf-8-sig")
        if raw and raw.strip():
            if self._session_works(self._parse_cookie_string(raw)):
                self.logger.info(
                    "Sessao carregada de %s. Game Endpoint: %s",
                    self.COOKIE_FILE, self.endpoint)
                return True
            self.logger.warning(
                "O cookie em %s nao autenticou (vencido ou incompleto)",
                self.COOKIE_FILE)

        return self._wait_for_session(tried=raw)

    def _session_instructions(self):
        return (
            "Sem sessao utilizavel.\n"
            "Cole a string de cookie do navegador (o cabecalho 'cookie:' inteiro) "
            "no arquivo:\n"
            "    %s\n"
            "Salve como UTF-8 e o bot comeca sozinho em ate %ds -- nao precisa "
            "reiniciar.\n"
            "NAO cole no console: ele corta linha longa e o cookie chega "
            "truncado."
            % (FileManager.get_path(self.COOKIE_FILE), self.COOKIE_POLL_SECONDS)
        )

    def _wait_for_session(self, tried=None):
        """Espera um cookie utilizavel aparecer em `cache/cookies.txt`."""
        message = self._session_instructions()
        print(message)
        self.logger.warning("Esperando uma sessao (cole o cookie em %s)", self.COOKIE_FILE)
        Notification.send(
            "TWB esta sem sessao: cole a string de cookie em cache/cookies.txt")
        last_reminder = time.time()
        while True:
            time.sleep(self.COOKIE_POLL_SECONDS)
            raw = FileManager.read_file(self.COOKIE_FILE, encoding="utf-8-sig")
            # `raw != tried` evita reprovar em laco o mesmo texto ja recusado --
            # cada tentativa custa uma requisicao ao jogo.
            if raw and raw.strip() and raw != tried:
                tried = raw
                if self._session_works(self._parse_cookie_string(raw)):
                    self.logger.info(
                        "Sessao aceita. Game Endpoint: %s", self.endpoint)
                    Notification.send("TWB: sessao aceita, iniciando.")
                    return True
                self.logger.warning(
                    "O cookie colado nao deu uma sessao logada; copie o cabecalho "
                    "'cookie:' inteiro de novo")
            if time.time() - last_reminder > self.COOKIE_REMIND_SECONDS:
                print(message)
                last_reminder = time.time()

    def get_action(self, village_id, action):
        url = "game.php?village=%s&screen=%s" % (village_id, action)
        response = self.get_url(url)
        return response

    def get_api_data(self, village_id, action, params=None):
        custom = dict(self.headers)
        custom['accept'] = "application/json, text/javascript, */*; q=0.01"
        custom['x-requested-with'] = "XMLHttpRequest"
        custom['tribalwars-ajax'] = "1"
        req = {
            'ajax': action,
            'village': village_id,
            'screen': 'api'
        }
        req.update(params or {})
        payload = f"game.php?{urlencode(req)}"
        url = urljoin(self.endpoint, payload)
        res = self.get_url(url, headers=custom)
        if res and res.status_code == 200:
            try:
                return res.json()
            except:
                return res

    def post_api_data(self, village_id, action, params=None, data=None):
        custom = dict(self.headers)
        custom['accept'] = "application/json, text/javascript, */*; q=0.01"
        custom['x-requested-with'] = "XMLHttpRequest"
        custom['tribalwars-ajax'] = "1"
        req = {
            'ajax': action,
            'village': village_id,
            'screen': 'api'
        }
        req.update(params or {})
        payload = f"game.php?{urlencode(req)}"
        url = urljoin(self.endpoint, payload)
        # Ver a nota em get_api_action: copiar em vez de mutar o argumento.
        data = dict(data or {})
        if 'h' not in data:
            data['h'] = self.last_h
        res = self.post_url(url, data=data, headers=custom)
        if res and res.status_code == 200:
            try:
                return res.json()
            except:
                return res

    def get_api_action(self, village_id, action, params=None, data=None):
        """
        ⚠️ `params`/`data` eram `{}` como default, e este método **escreve**
        em `data` (o token `h`). Default mutável é avaliado uma vez, na
        definição da função: o `h` da primeira chamada ficava gravado dentro
        do próprio default e, da segunda em diante, `'h' not in data` era
        falso — todo chamador que omitisse `data` reenviava para sempre o
        token da primeira chamada do processo, que roda por dias.

        Na prática só `Village.get_quests()` omitia `data`, então a conclusão
        automática de missões funcionava na primeira missão e falhava em
        silêncio nas seguintes (o retorno só é checado com `if qres:`).

        `dict(...)` resolve as duas metades: descola do default e para de
        escrever `h` dentro do dicionário de quem chamou. Primeiro padrão
        recorrente do CLAUDE.md, desta vez num argumento em vez de num
        atributo de classe.
        """
        custom = dict(self.headers)
        custom['Accept'] = "application/json, text/javascript, */*; q=0.01"
        custom['X-Requested-With'] = "XMLHttpRequest"
        custom['TribalWars-Ajax'] = "1"
        req = {
            'ajaxaction': action,
            'village': village_id,
            'screen': 'api'
        }
        req.update(params or {})
        payload = f"game.php?{urlencode(req)}"
        url = urljoin(self.endpoint, payload)
        data = dict(data or {})
        if 'h' not in data:
            data['h'] = self.last_h
        res = self.post_url(url, data=data, headers=custom)
        if res and res.status_code == 200:
            try:
                return res.json()
            except:
                return res
        return None
