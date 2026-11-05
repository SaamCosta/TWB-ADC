"""
Entrada da sessao do jogo vinda da extensao do navegador (P-PUBLICO Fase 2,
docs/backend.md §8.87).

O testador loga no jogo no navegador e a extensao `browser_extension/` manda
os cookies daquele mundo para o painel local (`POST /api/session`). O `sid` e
HttpOnly: `document.cookie`, bookmarklet e o `GM_cookie` do Tampermonkey
estavel nao o leem, e o banco de cookies do Chrome/Edge no Windows tem
app-bound encryption. `chrome.cookies` le (medido, §8.87).

Este modulo e a parte isolavel: quem pode postar, o que o corpo tem que ter,
de qual mundo e a sessao. O teste da sessao e o mesmo do bot
(`WebWrapper._session_works`), e so depois dele algo vai para o disco.

O endpoint recebe credencial, entao a porta e estreita de proposito:
- `Host` tem que ser loopback (contra DNS rebinding: a pagina de fora que
  rebinda o proprio nome para 127.0.0.1 manda o `Host` dela);
- `Origin` tem que ser **a** extensao. O id e fixo porque o `manifest.json`
  carrega a chave publica (`key`); nenhuma pagina consegue mandar
  `Origin: chrome-extension://...`, e outra extensao manda o id dela;
- corpo em `application/json`, que formulario HTML nao consegue enviar sem
  preflight de CORS (e o painel nao responde CORS).
"""

import re
from urllib.parse import urlparse

# Mercados do Tribal Wars, do seletor de idioma do www.tribalwars.net
# (lido em 2026-11-04). O `no.tribalwars.com` e o `ua.tribalwars.net` sao
# mercados com mundos em `<mundo>.tribalwars.com`/`.net`, cobertos aqui.
# O `browser_extension/manifest.json` tem que dar permissao para todos
# (tests/test_session_intake.py confere).
TW_DOMAINS = (
    "tribalwars.ae", "plemena.com", "divokekmeny.cz", "tribalwars.dk",
    "tribalwars.nl", "tribalwars.net", "tribalwars.co.uk", "tribalwars.us",
    "guerretribale.fr", "die-staemme.de", "fyletikesmaxes.gr",
    "klanhaboru.hu", "tribals.it", "tribalwars.com", "plemiona.pl",
    "tribalwars.com.br", "tribalwars.com.pt", "tribalwars.works",
    "triburile.ro", "voynaplemyon.com", "divoke-kmene.sk", "vojnaplemen.si",
    "guerrastribales.es", "tribalwars.se", "staemme.ch", "tribalwars.asia",
    "klanlar.org",
)

# Id da extensao, derivado da chave publica do manifest (sha256 do DER, 32
# primeiros hex, 0-f -> a-p). O teste recalcula a partir do manifest.
EXTENSION_ID = "gikdfeagglngbcaibghlkgmeaeemchdj"
ALLOWED_ORIGINS = ("chrome-extension://" + EXTENSION_ID,)

# Mundo: br143, en153, nlc1, dep12, zz2... Letras e depois digitos.
WORLD_RE = re.compile(r"^[a-z]{2,6}\d{1,4}$")
COOKIE_NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")
MAX_COOKIES = 64
MAX_COOKIE_VALUE = 4096
MAX_USER_AGENT = 512
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "[::1]", "::1")


def world_from_url(url):
    """`https://br143.tribalwars.com.br/game.php?...` -> dict com `server`
    e `endpoint`, ou None se nao for tela de mundo do Tribal Wars.

    Aceita so `https` e so `<mundo>.<mercado>` exato: `www.` (portal) e
    subdominio a mais (`x.br143.tribalwars.com.br`) ficam fora.
    """
    if not isinstance(url, str) or len(url) > 2048:
        return None
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return None
    if parsed.scheme != "https" or not parsed.hostname:
        return None
    host = parsed.hostname.lower()
    if parsed.port not in (None, 443):
        return None
    for domain in TW_DOMAINS:
        suffix = "." + domain
        if host.endswith(suffix):
            world = host[: -len(suffix)]
            if WORLD_RE.match(world):
                return {
                    "server": world,
                    "endpoint": "https://%s/game.php" % host,
                    "host": host,
                }
            return None
    return None


def host_is_loopback(host_header):
    """O `Host` da requisicao e 127.0.0.1/localhost/[::1], com ou sem porta."""
    if not host_header:
        return False
    host = host_header.strip().lower()
    if host.startswith("["):
        host = host.split("]", 1)[0] + "]"
    elif host.count(":") == 1:
        host = host.split(":", 1)[0]
    return host in LOOPBACK_HOSTS


def request_refusal(origin, host_header, content_type, allowed_origins=ALLOWED_ORIGINS):
    """Motivo para recusar a requisicao, ou None se ela pode seguir.

    Sem `Origin` e recusado: diferente do resto do painel (que deixa passar
    curl), aqui nao ha cliente legitimo sem navegador -- quem tem o terminal
    escreve `cache/cookies.txt`.
    """
    if not host_is_loopback(host_header):
        return "host nao e loopback"
    if not origin or origin not in allowed_origins:
        return "origem nao autorizada"
    if (content_type or "").split(";", 1)[0].strip().lower() != "application/json":
        return "corpo precisa ser application/json"
    return None


def parse_payload(payload):
    """Valida o corpo `{url, cookies, user_agent?, flags?}` da extensao.

    Devolve `(dados, None)` ou `(None, motivo)`. `dados` tem `server`,
    `endpoint`, `host`, `cookies` (dict nome -> valor), `user_agent` (ou
    None) e `flags` (dict nome -> atributos, so para o log).
    """
    if not isinstance(payload, dict):
        return None, "corpo nao e um objeto JSON"
    world = world_from_url(payload.get("url"))
    if not world:
        return None, "url nao e de um mundo do Tribal Wars"
    raw = payload.get("cookies")
    if not isinstance(raw, dict) or not raw:
        return None, "sem cookies"
    if len(raw) > MAX_COOKIES:
        return None, "cookies demais"
    cookies = {}
    for name, value in raw.items():
        if not isinstance(name, str) or not COOKIE_NAME_RE.match(name):
            return None, "nome de cookie invalido"
        if not isinstance(value, str) or len(value) > MAX_COOKIE_VALUE:
            return None, "valor de cookie invalido (%s)" % name
        if any(ch in value for ch in "\r\n;"):
            return None, "valor de cookie invalido (%s)" % name
        cookies[name] = value
    if not cookies.get("sid"):
        return None, "sem o cookie sid: o navegador nao esta logado neste mundo"
    user_agent = payload.get("user_agent")
    if not isinstance(user_agent, str) or not user_agent.strip() \
            or len(user_agent) > MAX_USER_AGENT or "\n" in user_agent or "\r" in user_agent:
        user_agent = None
    else:
        user_agent = user_agent.strip()
    flags = {}
    raw_flags = payload.get("flags")
    if isinstance(raw_flags, dict):
        for name, attrs in raw_flags.items():
            if name in cookies and isinstance(attrs, dict):
                flags[name] = {k: attrs.get(k) for k in
                               ("httpOnly", "secure", "hostOnly", "domain", "session")
                               if isinstance(attrs.get(k), (bool, str))}
    data = dict(world)
    data.update(cookies=cookies, user_agent=user_agent, flags=flags)
    return data, None


def world_mismatch(config, server):
    """Mensagem se o `config.json` existe e e de outro mundo; senao None.

    Sem `config.json` (primeiro uso, Fase 3) qualquer mundo serve: o
    `cache/session.json` guarda `server`/`endpoint`/`user_agent` para quem
    for montar a configuracao.
    """
    if not isinstance(config, dict):
        return None
    configured = ((config.get("server") or {}).get("server") or "").strip().lower()
    if configured and configured != server:
        return ("o bot esta configurado para o mundo %s e esta sessao e do %s; "
                "abra o jogo no %s" % (configured, server, configured))
    return None


def flags_summary(flags):
    """`sid(HttpOnly,host)` ... para o log: atributos, nunca valores."""
    parts = []
    for name in sorted(flags or {}):
        attrs = flags[name]
        marks = []
        if attrs.get("httpOnly") is True:
            marks.append("HttpOnly")
        if attrs.get("secure") is True:
            marks.append("Secure")
        if attrs.get("hostOnly") is True:
            marks.append("host")
        elif isinstance(attrs.get("domain"), str):
            marks.append(attrs["domain"])
        parts.append("%s(%s)" % (name, ",".join(marks)) if marks else name)
    return " ".join(parts)


def _panel_wrapper_class():
    """WebWrapper sem a espera de captcha, como o `_PanelWrapper` do
    `TribeSupportReader` (webmanager/utils.py): o `get_url` do bot espera o
    captcha sair, em laco, e no painel isso congelaria a requisicao da
    extensao. Aqui captcha volta como `None` na hora."""
    from core.request import WebWrapper

    class _IntakeWrapper(WebWrapper):
        def _await_captcha_clear(self, probe_url, headers=None):
            return None

    return _IntakeWrapper


def accept(data, config, wrapper_factory=None):
    """Prova a sessao e, so se ela der tela logada, grava `cache/session.json`.

    Devolve `(ok, mensagem)`. A prova e `WebWrapper._session_works`, a mesma
    do bot: um GET `game.php?screen=overview` que tem que terminar em
    `game.php`, e so depois dela `_persist_session` grava. Sessao recusada
    nao toca no `cache/session.json` que ja existe.
    """
    mismatch = world_mismatch(config, data["server"])
    if mismatch:
        return False, mismatch
    if wrapper_factory is None:
        wrapper_factory = _panel_wrapper_class()
    wrapper = wrapper_factory(data["endpoint"], server=data["server"],
                              endpoint=data["endpoint"])
    # Um GET so, a pedido do usuario no navegador: sem o sono de 3-7 s.
    wrapper.delay = 0
    configured_ua = None
    if isinstance(config, dict):
        configured_ua = (config.get("bot") or {}).get("user_agent")
    # O bot vai usar o user-agent do config; sem config, o do navegador que
    # acabou de logar, que e o que o jogo ja viu nesta sessao.
    user_agent = configured_ua or data.get("user_agent")
    if user_agent:
        wrapper.headers["user-agent"] = user_agent
    wrapper.session_extra = {
        "source": "extension",
        "browser_user_agent": data.get("user_agent"),
    }
    if wrapper._session_works(data["cookies"]):
        return True, "sessao do %s aceita e gravada" % data["server"]
    last = getattr(wrapper, "last_response", None)
    if last is not None and BOT_PROTECT_MARKER in (getattr(last, "text", "") or ""):
        return False, ("o jogo pediu captcha: resolva no navegador e clique "
                       "em enviar de novo")
    return False, ("o jogo nao aceitou esta sessao (deslogada ou vencida); "
                   "entre no jogo de novo e reenvie")


# Mesmo marcador de core/request.py, repetido para este modulo nao importar
# `requests` so por ser importado (os testes de logica pura nao precisam).
BOT_PROTECT_MARKER = 'data-bot-protect="forced"'
