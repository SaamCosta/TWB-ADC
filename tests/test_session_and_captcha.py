"""
Testes do `WebWrapper.start()` e do caminho de bot protection (captcha).

MOTIVACAO. O `core/request.py` tinha dois `input()` num programa que o painel
sobe sem console:

    core/request.py:79   input("Press any key...")          # captcha
    core/request.py:115  input("Enter browser cookie string> ")  # sessao

O `bot_output.log` guarda a prova do segundo desde 30/06/2026: duas tentativas
de iniciar pelo painel, ambas terminando na linha

    Enter browser cookie string>

com o processo **vivo, com pid valido e parado para sempre** -- e o painel, que
so olhava o pid, dizendo "rodando" (vigesimo segundo padrao do CLAUDE.md).

O do captcha era pior de tres jeitos: quem resolve o captcha resolve no
NAVEGADOR e nao no console do bot; o `input()` estava dentro do `try`, entao um
stdin fechado levantava EOFError e o log dizia so "GET falhou", escondendo o
motivo; e o POST nao tinha guarda nenhuma, entao um captcha durante um envio de
ataque voltava 200 com a pagina de bot protection e o chamador tratava como
acao aceita (decimo quinto padrao: detector que nunca dispara).

O QUE ESTE ARQUIVO PROVA, e que e o oposto de "nao quebrou":

 - `test_start_*`               a sessao vem de arquivo, e `input()` nunca e chamado;
 - `test_session_only_persisted_when_proven`  cookie vencido nao sobrescreve o
                                cache que funcionava;
 - `test_captcha_get_*`         o GET bloqueado se resolve sozinho e devolve a
                                pagina boa;
 - `test_captcha_post_*`        o POST bloqueado devolve None e **nao** e
                                refeito (reenviar as cegas duplicaria ataque);
 - `test_notification_failure_*` uma falha do telegram nao derruba a espera.

Nada aqui toca rede, `cache/session.json` ou `cache/cookies.txt` reais: o
`FileManager` e o `time` do modulo sao substituidos por fakes em memoria
(vigesimo primeiro padrao -- um teste nao obtem sua verificacao escrevendo no
artefato de producao).

Rodar: python tests/test_session_and_captcha.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.request as request_module
from core.request import WebWrapper, BOT_PROTECT_MARKER

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


# ---------------------------------------------------------------- fakes

ENDPOINT = "https://br143.tribalwars.com.br/game.php"
GAME_URL = "https://br143.tribalwars.com.br/game.php?screen=overview"
LOGIN_URL = "https://www.tribalwars.com.br/index.php?logout"

# A pagina que o jogo devolve quando exige captcha. O marcador e o unico
# pedaco que o codigo le; o resto existe para o teste nao depender do formato.
CAPTCHA_PAGE = '<html><body %s><div id="bot_check"></div></body></html>' % BOT_PROTECT_MARKER
GAME_PAGE = '<meta content="tokenABC" name="csrf-token"><a href="x&h=deadbeef">ok</a>'


class FakeResponse:
    def __init__(self, text=GAME_PAGE, url=GAME_URL, status_code=200):
        self.text = text
        self.url = url
        self.status_code = status_code


class FakeCookie:
    def __init__(self, name, value):
        self.name = name
        self.value = value


class FakeJar:
    """So o que o WebWrapper usa: clear(), update(dict) e iteracao."""

    def __init__(self):
        self._data = {}

    def clear(self):
        self._data.clear()

    def update(self, other):
        self._data.update(other)

    def __iter__(self):
        return iter([FakeCookie(k, v) for k, v in self._data.items()])

    def as_dict(self):
        return dict(self._data)


class FakeSession:
    """Devolve as respostas de `script` em ordem; a ultima se repete."""

    def __init__(self, script):
        self.cookies = FakeJar()
        self.script = list(script)
        self.gets = []
        self.posts = []

    def _next(self):
        if len(self.script) > 1:
            return self.script.pop(0)
        return self.script[0]

    def get(self, url=None, headers=None, timeout=None):
        self.gets.append((url, self.cookies.as_dict()))
        res = self._next()
        if isinstance(res, Exception):
            raise res
        return res

    def post(self, url=None, data=None, headers=None, timeout=None):
        self.posts.append((url, data))
        res = self._next()
        if isinstance(res, Exception):
            raise res
        return res


class FakeClock:
    """time.sleep nao dorme; so avanca o relogio que time.time() devolve."""

    def __init__(self):
        self.now = 1_000_000.0
        self.slept = []

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds

    def time(self):
        return self.now


class FakeFileManager:
    """FileManager em memoria. `reads` registra a ordem de leitura."""

    def __init__(self, files=None):
        self.files = dict(files or {})
        self.json = {}
        self.writes = []
        self.reads = []

    # --- API usada pelo core/request.py
    def load_json_file(self, path):
        self.reads.append(path)
        return self.json.get(path)

    def save_json_file(self, data, path):
        self.writes.append((path, data))
        self.json[path] = data

    def read_file(self, path, encoding=None):
        self.reads.append(path)
        return self.files.get(path)

    def get_path(self, path):
        return "C:\\fake\\" + path


class FakeNotification:
    def __init__(self, explode=False):
        self.messages = []
        self.explode = explode

    def send(self, message):
        self.messages.append(message)
        if self.explode:
            raise RuntimeError("telegram timeout")


class InputGuard:
    """Qualquer chamada a input() e o bug que este arquivo existe para impedir.

    Registra ANTES de levantar porque a excecao cairia no `except Exception`
    generico do get_url/post_url e sumiria -- que e exatamente como o EOFError
    do stdin fechado se disfarcava de "GET falhou" na versao antiga.
    """

    def __init__(self):
        self.called = []

    def __call__(self, prompt=""):
        self.called.append(prompt)
        raise EOFError("stdin fechado (bot sem console)")


def build(script, files=None, session_json=None, notification=None):
    """Monta um WebWrapper isolado: sem rede, sem disco, sem relogio real."""
    wrapper = WebWrapper(ENDPOINT, server="br143", endpoint=ENDPOINT)
    wrapper.web = FakeSession(script)
    wrapper.priority_mode = True  # pula o sleep aleatorio de get_url/post_url

    fm = FakeFileManager(files)
    if session_json is not None:
        fm.json["cache/session.json"] = session_json
    clock = FakeClock()
    guard = InputGuard()
    notif = notification or FakeNotification()

    request_module.FileManager = fm
    request_module.time = clock
    request_module.Notification = notif
    request_module.input = guard
    return wrapper, fm, clock, guard, notif


def restore():
    import time as real_time
    from core.filemanager import FileManager as real_fm
    from core.notification import Notification as real_notification
    request_module.FileManager = real_fm
    request_module.time = real_time
    request_module.Notification = real_notification
    if "input" in request_module.__dict__:
        del request_module.__dict__["input"]


# ---------------------------------------------------------------- parser

def test_parse_cookie_string_basico():
    got = WebWrapper._parse_cookie_string("sid=abc; cid=123; global_village_id=40808")
    check(got == {"sid": "abc", "cid": "123", "global_village_id": "40808"},
          "parser simples falhou: %r" % (got,))


def test_parse_cookie_string_tolera_cabecalho_e_bom():
    # Quem copia do DevTools copia o cabecalho inteiro; quem salva no Bloco de
    # Notas grava BOM. Nenhum dos dois pode corromper o primeiro cookie.
    raw = chr(0xFEFF) + "cookie: sid=abc;\r\n cid=123"
    got = WebWrapper._parse_cookie_string(raw)
    check(got == {"sid": "abc", "cid": "123"},
          "parser nao tolerou cabecalho/BOM: %r" % (got,))


def test_parse_cookie_string_valor_com_igual():
    # Cookie de sessao com base64 termina em '=' e nao pode ser truncado.
    got = WebWrapper._parse_cookie_string("token=YWJj==; x=1")
    check(got.get("token") == "YWJj==",
          "valor com '=' foi truncado: %r" % (got,))


def test_parse_cookie_string_ignora_lixo():
    got = WebWrapper._parse_cookie_string("sid=abc; ; lixo ;=vazio")
    check(got == {"sid": "abc"},
          "entrada sem '=' virou chave: %r" % (got,))


# ---------------------------------------------------------------- start()

def test_start_usa_cache_valido():
    wrapper, fm, clock, guard, _ = build(
        [FakeResponse()], session_json={"cookies": {"sid": "abc"}})
    try:
        ok = wrapper.start()
    finally:
        restore()
    check(ok is True, "start() com cache valido devia devolver True")
    check(guard.called == [], "start() chamou input(): %r" % (guard.called,))
    check(fm.reads.count(WebWrapper.COOKIE_FILE) == 0,
          "cache valido nao devia precisar ler cookies.txt")
    check(len(wrapper.web.gets) == 1,
          "cache valido devia custar 1 requisicao, custou %d" % len(wrapper.web.gets))


def test_start_le_cookie_de_arquivo_quando_cache_vence():
    # Cache vencido = o jogo redireciona para fora de game.php.
    wrapper, fm, clock, guard, _ = build(
        [FakeResponse(url=LOGIN_URL), FakeResponse()],
        files={WebWrapper.COOKIE_FILE: "sid=novo; cid=9"},
        session_json={"cookies": {"sid": "velho"}})
    try:
        ok = wrapper.start()
    finally:
        restore()
    check(ok is True, "start() devia aceitar o cookie de cache/cookies.txt")
    check(guard.called == [], "start() chamou input(): %r" % (guard.called,))
    check(wrapper.web.cookies.as_dict() == {"sid": "novo", "cid": "9"},
          "jar ficou com o cookie errado: %r" % (wrapper.web.cookies.as_dict(),))
    written = dict(fm.writes)
    check("cache/session.json" in written, "sessao provada nao foi persistida")
    check(written.get("cache/session.json", {}).get("cookies") ==
          {"sid": "novo", "cid": "9"},
          "session.json gravou cookies errados: %r" % (written,))


def test_session_only_persisted_when_proven():
    # O ponto: um cookie vencido colado por engano NAO pode sobrescrever o
    # cache/session.json que funcionava. Na versao antiga a escrita era
    # incondicional, logo em seguida ao input().
    wrapper, fm, clock, guard, _ = build(
        [FakeResponse(url=LOGIN_URL)],  # tudo falha
        files={WebWrapper.COOKIE_FILE: "sid=vencido"},
        session_json={"cookies": {"sid": "velho"}})
    wrapper.COOKIE_POLL_SECONDS = 1
    # A espera e infinita de proposito; interrompe no primeiro poll.
    original_read = fm.read_file

    def read_once(path, encoding=None):
        if path == WebWrapper.COOKIE_FILE and fm.reads.count(path) >= 1:
            raise KeyboardInterrupt
        return original_read(path, encoding=encoding)

    fm.read_file = read_once
    try:
        try:
            wrapper.start()
            check(False, "start() devia continuar esperando, nao retornar")
        except KeyboardInterrupt:
            pass
    finally:
        restore()
    check(fm.writes == [],
          "cookie nao provado foi persistido mesmo assim: %r" % (fm.writes,))


def test_start_espera_arquivo_aparecer():
    # Nenhuma sessao no inicio; o cookie aparece depois, com o bot ja rodando.
    wrapper, fm, clock, guard, notif = build(
        [FakeResponse()], files={}, session_json=None)
    wrapper.COOKIE_POLL_SECONDS = 5

    polls = {"n": 0}
    original_read = fm.read_file

    def read_late(path, encoding=None):
        if path == WebWrapper.COOKIE_FILE:
            polls["n"] += 1
            if polls["n"] >= 3:
                fm.files[path] = "sid=chegou"
        return original_read(path, encoding=encoding)

    fm.read_file = read_late
    try:
        ok = wrapper.start()
    finally:
        restore()
    check(ok is True, "start() devia aceitar o cookie que apareceu depois")
    check(guard.called == [], "start() chamou input(): %r" % (guard.called,))
    check(polls["n"] == 3, "esperava 3 leituras do arquivo, houve %d" % polls["n"])
    check(clock.slept.count(5) >= 2,
          "a espera nao dormiu entre as leituras: %r" % (clock.slept,))


def test_start_nao_reprova_o_mesmo_texto():
    # Cada tentativa custa uma requisicao ao jogo. Reler o mesmo conteudo
    # recusado num laco de 15s seria bater no servidor 4x por minuto.
    wrapper, fm, clock, guard, _ = build(
        [FakeResponse(url=LOGIN_URL)],
        files={WebWrapper.COOKIE_FILE: "sid=vencido"}, session_json=None)
    wrapper.COOKIE_POLL_SECONDS = 1
    original_read = fm.read_file

    def read_three_times(path, encoding=None):
        if path == WebWrapper.COOKIE_FILE and fm.reads.count(path) >= 3:
            raise KeyboardInterrupt
        return original_read(path, encoding=encoding)

    fm.read_file = read_three_times
    try:
        try:
            wrapper.start()
        except KeyboardInterrupt:
            pass
    finally:
        restore()
    # Uma requisicao: a do texto quando ele foi lido a primeira vez.
    check(len(wrapper.web.gets) == 1,
          "o mesmo cookie recusado foi testado %d vezes" % len(wrapper.web.gets))


# ---------------------------------------------------------------- captcha

def test_captcha_get_retoma_sozinho():
    wrapper, fm, clock, guard, notif = build(
        [FakeResponse(text=CAPTCHA_PAGE),   # a requisicao original
         FakeResponse(text=CAPTCHA_PAGE),   # 1a reconferencia: ainda preso
         FakeResponse(text=GAME_PAGE)])     # 2a: resolvido
    wrapper.CAPTCHA_POLL_SECONDS = 30
    try:
        res = wrapper.get_url("game.php?screen=overview")
    finally:
        restore()
    check(res is not None, "get_url devolveu None depois do captcha sair")
    check(res is not None and BOT_PROTECT_MARKER not in res.text,
          "get_url devolveu a propria pagina de captcha como se fosse valida")
    check(guard.called == [], "o caminho de captcha chamou input(): %r" % (guard.called,))
    check(clock.slept == [30, 30], "poll de captcha errado: %r" % (clock.slept,))
    check(len(notif.messages) == 2,
          "esperava notificacao de entrada e de saida, houve %d" % len(notif.messages))


def test_captcha_nao_processa_a_pagina_bloqueada():
    # post_process extrai csrf e `&h=`. A pagina de captcha nao tem nenhum dos
    # dois; processa-la apagaria o token bom (`elif ... del self.headers[...]`)
    # e o bot voltaria do captcha sem conseguir agir.
    wrapper, fm, clock, guard, _ = build(
        [FakeResponse(text=CAPTCHA_PAGE), FakeResponse(text=GAME_PAGE)])
    wrapper.CAPTCHA_POLL_SECONDS = 1
    try:
        wrapper.get_url("game.php?screen=overview")
    finally:
        restore()
    check(wrapper.headers.get("x-csrf-token") == "tokenABC",
          "csrf da pagina boa nao ficou: %r" % (wrapper.headers.get("x-csrf-token"),))
    check(wrapper.last_h == "deadbeef",
          "token h da pagina boa nao ficou: %r" % (wrapper.last_h,))


def test_captcha_sobrevive_a_erro_de_rede_na_reconferencia():
    wrapper, fm, clock, guard, _ = build(
        [FakeResponse(text=CAPTCHA_PAGE),
         ConnectionError("getaddrinfo failed"),
         FakeResponse(text=GAME_PAGE)])
    wrapper.CAPTCHA_POLL_SECONDS = 1
    try:
        res = wrapper.get_url("game.php?screen=overview")
    finally:
        restore()
    check(res is not None and BOT_PROTECT_MARKER not in res.text,
          "erro de rede na reconferencia abortou a espera")


def test_captcha_post_nao_refaz_a_acao():
    # O ponto mais perigoso do arquivo. Refazer um POST depois do captcha
    # duplicaria envio de ataque/construcao; devolver a pagina de captcha faria
    # o chamador achar que a acao foi aceita. As duas saidas sao erradas, e a
    # certa e None + a acao ficar para o proximo ciclo.
    wrapper, fm, clock, guard, _ = build(
        [FakeResponse(text=CAPTCHA_PAGE),   # o POST bloqueado
         FakeResponse(text=GAME_PAGE)])     # reconferencia: saiu
    wrapper.CAPTCHA_POLL_SECONDS = 1
    try:
        res = wrapper.post_url("game.php?screen=place&try=confirm", data={"x": 1})
    finally:
        restore()
    check(res is None, "POST bloqueado devia devolver None, devolveu %r" % (res,))
    check(len(wrapper.web.posts) == 1,
          "a acao foi reenviada %d vezes" % len(wrapper.web.posts))
    check(guard.called == [], "o POST bloqueado chamou input(): %r" % (guard.called,))


def test_notificador_real_nao_derruba_a_espera():
    """O par do teste acima, com o Notification de verdade.

    O caminho de captcha esta DENTRO do `try` do get_url. Se `Notification.send`
    propagasse -- e ela propagava: nao havia try/except nenhum e `telegram` faz
    rede --, o captcha viraria um "GET ... : timeout" generico no log e a espera
    inteira seria pulada. Aqui o `send_async` e forcado a falhar; o esperado e
    que a espera aconteca do mesmo jeito.
    """
    from core.notification import _Notification

    real = _Notification()
    real._ensure_bot = lambda: True
    real.loop = _ExplodingLoop()

    wrapper, fm, clock, guard, _ = build(
        [FakeResponse(text=CAPTCHA_PAGE), FakeResponse(text=GAME_PAGE)],
        notification=real)
    wrapper.CAPTCHA_POLL_SECONDS = 1
    try:
        res = wrapper.get_url("game.php?screen=overview")
    finally:
        restore()
    check(res is not None and BOT_PROTECT_MARKER not in res.text,
          "falha do telegram derrubou a espera de captcha (res=%r)" % (res,))


class _ExplodingLoop:
    def create_task(self, coro):
        coro.close()
        raise RuntimeError("telegram timeout")

    def run_until_complete(self, task):  # pragma: no cover - nao alcancado
        raise AssertionError("nao deveria chegar aqui")


# ---------------------------------------------------------------- runner

if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except Exception as exc:
                failures.append("%s levantou %s: %s"
                                % (name, type(exc).__name__, exc))
            finally:
                restore()
    if failures:
        print("FAIL (%d)" % len(failures))
        for f in failures:
            print("  - %s" % f)
        sys.exit(1)
    print("OK - sessao por arquivo e captcha com auto-resume")
