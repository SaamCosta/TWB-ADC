"""
Feature 38 -- o que esta NO AR agora, lido da propria tela de comandos do jogo.

Contexto: docs/frontend.md 6.1.2, item 1 ("Painel Em voo"), apontado la como
"o mais valioso, e o unico que nao e cosmetico", e docs/backend.md 6.1.

    game.php?village=<vid>&screen=overview_villages&mode=commands&page=-1

lista TODO comando saindo desta conta -- ataque, retorno, apoio, retirada --
com origem, alvo, tropas e a hora de chegada que o SERVIDOR calculou.

POR QUE ESTA TELA, E NAO O NOSSO CACHE
---------------------------------------
Os dois contratos inegociaveis do item 1 existem por causa de incidentes
reais, e os dois se resolvem sozinhos ao ler o jogo em vez de nos:

  (a) a hora tem de ser a CONFIRMADA. A alternativa seria estimar com
      `Extractor.attack_duration()`, que devolve **0** quando o regex nao casa
      -- somar 0 a hora de envio faz o nobre "nascer pousado" (sexto padrao do
      CLAUDE.md). Aqui a hora vem pronta do servidor.
  (b) a lista NUNCA pode ser derivada do campo `status` do cache de conquista.
      Foi exatamente esse campo que dizia `"complete"` com QUATRO nobres no ar
      (docs/backend.md 6.1), e a trava que segurou o estrago foi construida
      sobre tempo de chegada justamente por isso. Este modulo nao le
      `cache/conquest` em momento algum.

⚠️ ESCOPO DELIBERADO: ISTO E OBSERVABILIDADE, NAO DECISAO
----------------------------------------------------------
Nada aqui altera o que o bot faz. Seria tecnicamente facil cruzar esta lista
com `ConquestManager` para uma segunda trava de nobre em voo -- e e tentador,
porque este e o dado que faltava quando `_get_my_conquest()` devolveu None com
quatro nobres voando. Nao foi feito de proposito: mudanca em ConquestManager
mexe em tropa real (CLAUDE.md), e a trava atual por tempo de chegada ja
funciona. O valor desta feature e alguem OLHAR e ver, que e o que nao existia.

⚠️ O DADO QUE ENVELHECE MAIS RAPIDO DO CACHE INTEIRO
-----------------------------------------------------
Todo o resto do `cache/` descreve estado que muda em horas. Este descreve
coisas que POUSAM -- um comando lido agora pode ter chegado antes de alguem
abrir o painel. Por isso o leitor separa "ainda no ar" de "ja deveria ter
chegado" em vez de mostrar uma lista so, e por isso a idade da leitura e
publicada junto (5o padrao: numero sem procedencia convence mais do que
deveria). Esconder o comando vencido seria mentir por omissao; mostra-lo como
"no ar" seria mentir por afirmacao.
"""
import logging
import time

from core.extractors import Extractor
from core.filemanager import FileManager

logger = logging.getLogger("InFlight")

CACHE_PATH = "cache/in_flight.json"

# Curto de proposito, ao contrario do TTL de 6h do PlayerStats: la a resolucao
# da fonte e diaria, aqui o conteudo muda a cada pouso. Isto e um teto contra
# reler varias vezes no mesmo ciclo, nao um ritmo -- na pratica quem manda e o
# intervalo do ciclo, medido em ~1h39 entre dois passes da mesma aldeia
# (docs/backend.md, 18o padrao).
DEFAULT_TTL = 600


class InFlight:
    """
    Os comandos no ar da conta, relidos no maximo uma vez por TTL.

    Uma instancia por processo, como `WorldVillages`, `ReservationBoard` e
    `PlayerStats`: a resposta e da CONTA INTEIRA (traz os comandos de todas as
    aldeias de uma vez), entao uma instancia por aldeia bateria na mesma URL
    ate 30 vezes por ciclo para exatamente o mesmo conteudo.

    Par no webmanager: `InFlightReader` (webmanager/utils.py), seguindo
    `ConquestManager`/`ConquestReader` -- nunca o mesmo nome nos dois lados.
    """

    def __init__(self, wrapper=None, config=None):
        self.wrapper = wrapper
        self.config = config or {}
        self.logger = logger
        # Mutaveis em __init__, nao no corpo da classe (1o padrao).
        self._commands = []
        self._fetched_at = 0.0
        self._server_time = None
        self._last_error = None

    @property
    def enabled(self):
        return self.config.get("in_flight", {}).get("enabled", True)

    def _ttl(self):
        return self.config.get("in_flight", {}).get("cache_seconds", DEFAULT_TTL)

    def refresh(self, village_id):
        """
        Le a visao geral de comandos se o TTL venceu.

        `village_id` e so o ENDERECO do GET: a tela responde com os comandos de
        todas as aldeias, entao qualquer aldeia gerenciada serve.

        Devolve True quando uma leitura NOVA foi aceita e gravada; False em
        qualquer outro caso. Uma leitura ruim nunca apaga a boa anterior --
        mesmo raciocinio de `PlayerStats.refresh()` e `WorldVillages.rows()`.

        ⚠️ Aqui essa regra tem um porem que la nao tinha, e ele e honesto:
        manter a leitura velha significa manter comandos que talvez ja tenham
        pousado. Isso e melhor que esvaziar o painel (que leria como "nada no
        ar", uma afirmacao FALSA e tranquilizadora), mas so porque a idade da
        leitura vai junto e o leitor separa o que venceu. Sem essas duas
        coisas, preservar seria pior que limpar.
        """
        if not self.enabled or self.wrapper is None or not village_id:
            return False
        if self._commands and (time.time() - self._fetched_at) < self._ttl():
            return False

        # `page=-1` NAO e opcional: sem ele a tela devolve so a primeira
        # pagina, e o `<th>Comando (N)</th>` conta a PAGINA, nao o total --
        # medido em 2026-09-22, 25 linhas de 65, com o cabecalho dizendo 25.
        # Um painel "Em voo" que esconde 62% do que voa e pior que nenhum
        # (26o padrao: lista curta e indistinguivel de lista completa).
        url = ("game.php?village=%s&screen=overview_villages"
               "&mode=commands&page=-1" % village_id)
        res = self.wrapper.get_url(url)
        if res is None:
            self._last_error = "sem resposta do servidor"
            self.logger.warning("InFlight: nao consegui ler a visao geral de "
                                "comandos (%s)", self._last_error)
            return False

        parsed = Extractor.own_commands(res)
        if parsed is None:
            self._last_error = "markup sem a tabela de comandos"
            self.logger.warning(
                "InFlight: a tela respondeu 200 mas sem tabela de comandos -- "
                "login/bot-protection, ou o markup mudou"
            )
            return False

        for warning in parsed["warnings"]:
            self.logger.warning("InFlight: %s", warning)

        self._commands = parsed["commands"]
        self._server_time = parsed["server_time"]
        self._fetched_at = time.time()
        self._last_error = None
        self._write_disk()

        nobles = sum(1 for c in self._commands if c["has_snob"])
        self.logger.info(
            "InFlight: %d comando(s) no ar%s",
            len(self._commands),
            " (%d com nobre)" % nobles if nobles else "",
        )
        return True

    def _write_disk(self):
        payload = {
            "fetched_at": self._fetched_at,
            "server_time": self._server_time,
            "commands": self._commands,
        }
        FileManager.save_json_file(payload, CACHE_PATH)
