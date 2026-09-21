import asyncio
import logging

import telegram

from core.filemanager import FileManager
from core.exceptions import InvalidJSONException


class _Notification:
    """Telegram notifier. Best-effort by construction: nunca levanta.

    Duas mudancas em relacao a versao original, ambas do mesmo defeito de fundo
    (uma notificacao nao pode ser a coisa que derruba o bot):

    1. **Config preguicosa.** O modulo instancia este objeto no corpo (linha
       final do arquivo), entao ler `config.json` no `__init__` era I/O de disco
       em todo `import core.notification` -- inclusive nos testes e no
       webmanager, que importam `twb.py`. Vigesimo padrao do CLAUDE.md. Agora o
       config e lido na primeira chamada a `send()`, o que de brinde faz
       `notifications.enabled` valer **ao vivo**: ligar/desligar no painel passa
       a ter efeito sem reiniciar o bot.
    2. **`send()` nunca propaga excecao.** `telegram` faz rede, e rede falha.
       Os dois lugares que mais chamam isto sao justamente os piores para uma
       excecao secundaria: o handler de crash do `twb.py` (que esta *dentro* de
       um `except` e, se levantar de novo, escapa do laco de retry -- o bot sai
       em vez de reiniciar) e o caminho de bot protection do `core/request.py`
       (onde a excecao seria engolida pelo `except` generico do `get_url`,
       transformando "captcha detectado" em "GET falhou" e pulando a espera
       inteira).

    Ainda **nao** implementado, de proposito: filtro por categoria
    (`notify_<categoria>`), que o fork LazyTurtle tem. Ele exige chaves novas em
    `config.example.json` e, por tabela, bump de `build.version` -- o que dispara
    o merge no `config.json` vivo de 27 aldeias. Fica para uma fatia propria.
    """

    bot = None
    enabled = False
    channel_id = None
    token = None
    loop = None
    logger = logging.getLogger("Notification")

    def __init__(self):
        # Sem I/O aqui. Ver o item 1 do docstring da classe.
        pass

    def get_config(self):
        try:
            config = FileManager.load_json_file("config.json")
        except InvalidJSONException:
            config = None
        if not config:
            self.enabled = False
            return
        notification_config = config.get("notifications", {}) or {}
        self.enabled = notification_config.get("enabled", False)
        self.channel_id = notification_config.get("channel_id")
        self.token = notification_config.get("token")

    def _ensure_bot(self):
        """Rele o config e constroi bot/loop sob demanda. True = pronto para enviar."""
        self.get_config()
        if not self.enabled or not self.token or not self.channel_id:
            return False
        if self.loop is None:
            self.loop = asyncio.new_event_loop()
        if self.bot is None:
            self.bot = telegram.Bot(token=self.token)
        return True

    def send(self, message):
        try:
            if not self._ensure_bot():
                return
            task = self.loop.create_task(self.send_async(message))
            self.loop.run_until_complete(task)
        except Exception as exc:
            # Inclui o _ensure_bot de proposito: token invalido faz o construtor
            # do telegram.Bot levantar, e isso acontecia antes de qualquer
            # try/except.
            self.logger.warning("Nao foi possivel notificar: %s", exc)

    async def send_async(self, message):
        await self.bot.send_message(chat_id=self.channel_id, text=message)


Notification = _Notification()
