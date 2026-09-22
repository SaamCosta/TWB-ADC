"""
Feature 37 -- a serie historica que o proprio jogo ja publica, lida uma vez
por ciclo e cacheada para o painel.

Contexto: docs/backend.md 8.13 (P-STATS-JOGO) e docs/frontend.md 6.1.2, item 6.

    game.php?village=<vid>&screen=info_player&mode=stats_own

publica, dentro do HTML (sem canvas, sem XHR), as series "Saqueado" e
"Coletado" -- recurso saqueado/coletado por DIA, dos ultimos 7 dias, na CONTA
INTEIRA. E a unica fonte do sistema que enxerga o RESULTADO venha de onde
vier, inclusive do que o usuario faz na mao (docs/backend.md 8.13, que
corrigiu o P-COL-03 original -- "nao ha como descobrir depois" estava errado).

⚠️ ESCOPO: guardamos SO "Saqueado"/"Coletado" (ver SERIES_OF_INTEREST). A
prova mais citada da 8.13 -- 204.240 + 105.600 gastos desbloqueando coleta com
o gate do bot desligado e zero linhas `Unlock:` no log -- veio da serie
"Coleta de Recursos", que e de GASTO e que este modulo DESCARTA hoje, por nao
ter consumidor. Ou seja: a capacidade de ver o gasto manual existe na tela e
esta a uma linha de distancia (acrescentar o label a SERIES_OF_INTEREST), mas
nao esta ligada. Registrado aqui para ninguem ler o paragrafo acima e concluir
que o cache ja tem esse numero.

CONTRATOS A PRESERVAR (frontend.md 6.1.2, item 6) -- os quatro que limitam o
uso desta serie a "agregado de controle", e que o consumidor no webmanager
precisa repetir, nao so este modulo:

  (a) e CONTA INTEIRA, nunca por aldeia -- nao substitui ReportReader nem
      farmscores para decisao operacional;
  (b) retencao de 7 dias -- janela maior exige acumular localmente, o que
      este modulo NAO faz de proposito (ver `_write_disk` abaixo);
  (c) `percent` e participacao NO TOTAL DO DIA, nao "aproveitamento" -- e
      Extractor.stats_own_series quem documenta a medicao;
  (d) e SALDO, nao EVENTO -- sem `observed_at` por operacao, nao alimenta o
      painel "Em voo" (frontend.md 6.1.2, item 1).

SO UMA REQUISICAO POR TTL, NAO POR CICLO
------------------------------------------
A resolucao da serie e diaria; reler a cada ciclo (minutos) nao muda o numero
e so gasta orcamento de requisicao da conta -- o mesmo raciocinio do TTL de 6h
do WorldVillages (docs/backend.md 8.6, `game/world_villages.py`).

NAO ACUMULA HISTORICO ALEM DO QUE O JOGO DEVOLVE
--------------------------------------------------
`cache/player_stats.json` e sobrescrito a cada leitura boa, com so os dias que
a resposta trouxe. Guardar janela maior exigiria decidir o que fazer com um
dia que sumiu (saiu da janela? falha de leitura?) sem nenhum jeito de
distinguir os dois a partir desta tela sozinha -- e ninguem pediu retencao
maior ainda (frontend.md 6.1.2: "o card precisa dizer que a serie comeca onde
o jogo corta", nao fingir uma janela que nao tem).
"""
import logging
import time

from core.extractors import Extractor
from core.filemanager import FileManager

logger = logging.getLogger("PlayerStats")

CACHE_PATH = "cache/player_stats.json"

DEFAULT_TTL = 6 * 3600

# As duas series que respondem "a coleta rendeu mais que o farm nas ultimas
# 24h" -- as demais ("Unidades", "Edificios", "Notabilidade", "Pesquisa",
# "Coleta de Recursos", "Comercio") sao GASTO, e nenhum consumidor pediu esse
# card ainda. Recortar aqui, e nao no consumidor, evita gravar no cache um
# dado que nada le -- se um card de gasto aparecer, e um ajuste desta lista.
SERIES_OF_INTEREST = ("Saqueado", "Coletado")


class PlayerStats:
    """
    A serie Saqueado/Coletado da conta, relida no maximo uma vez por TTL.

    Uma instancia por processo, construida em twb.py como WorldVillages e
    ReservationBoard: o conteudo e global, e uma instancia por aldeia bateria
    na mesma URL (conta inteira) ate 30 vezes por ciclo para o mesmo dado.

    NAO se chama `PlayerStatsReader`: esse nome e do leitor de CACHE do
    webmanager (`webmanager/utils.py`), e o repositorio nao tem um unico caso
    de classe homonima entre `game/` e `webmanager/` -- os pares sao sempre
    `ConquestManager`/`ConquestReader`, `DefenceManager`/`FlagReader`,
    `FarmExclusionLog`/`FarmExclusionReader`. O analogo direto desta classe e
    `WorldVillages` (fonte externa, uma por processo, TTL e cache em disco), e
    o nome segue ele.
    """

    def __init__(self, wrapper=None, config=None):
        self.wrapper = wrapper
        self.config = config or {}
        self.logger = logger
        # Mutaveis em __init__, nao no corpo da classe (1o padrao do CLAUDE.md
        # -- atributo de classe mutavel compartilhado entre instancias).
        self._series = {}
        self._fetched_at = 0.0
        self._last_error = None

    @property
    def enabled(self):
        return self.config.get("player_stats", {}).get("enabled", True)

    def _ttl(self):
        return self.config.get("player_stats", {}).get("cache_seconds", DEFAULT_TTL)

    def refresh(self, village_id):
        """
        Le `screen=info_player&mode=stats_own` se o TTL venceu.

        `village_id` e so o ENDERECO do GET -- a resposta e da conta inteira,
        entao qualquer aldeia gerenciada serve igualmente bem, e o chamador
        nao precisa escolher uma "certa".

        Devolve True quando uma leitura NOVA foi aceita e gravada; False em
        qualquer outro caso (TTL vigente, gate desligado, sem wrapper/aldeia,
        falha de rede, markup sem serie reconhecivel). O estado anterior --
        bom ou vazio -- nunca e apagado por uma leitura ruim: um soluco do
        servidor nao pode fazer o painel regredir de "tenho dado de ontem"
        para "sem dado nenhum" (mesmo raciocinio de `WorldVillages.rows()`).
        """
        if not self.enabled or self.wrapper is None or not village_id:
            return False
        if self._series and (time.time() - self._fetched_at) < self._ttl():
            return False

        url = "game.php?village=%s&screen=info_player&mode=stats_own" % village_id
        res = self.wrapper.get_url(url)
        if res is None:
            self._last_error = "sem resposta do servidor"
            self.logger.warning("PlayerStats: nao consegui ler stats_own (%s)",
                                 self._last_error)
            return False

        series = Extractor.stats_own_series(res)
        if not series:
            self._last_error = "markup sem series reconheciveis"
            self.logger.warning(
                "PlayerStats: stats_own respondeu 200 mas sem series "
                "reconheciveis -- login/bot-protection, ou o markup mudou"
            )
            return False

        found = {k: v for k, v in series.items() if k in SERIES_OF_INTEREST}
        if not found:
            # A tela respondeu e o parser achou series -- so nao as que
            # importam aqui. Distinto do caso acima (markup quebrado): aqui
            # o jogo esta falando normalmente.
            self._last_error = "series de interesse ausentes na resposta"
            self.logger.warning(
                "PlayerStats: stats_own trouxe %s mas nenhuma das series "
                "esperadas (%s)", sorted(series), ", ".join(SERIES_OF_INTEREST)
            )
            return False

        self._series = found
        self._fetched_at = time.time()
        self._last_error = None
        self._write_disk()
        self.logger.info(
            "PlayerStats: %d dia(s) de %s lidos",
            len(found.get("Saqueado") or found.get("Coletado") or []),
            "/".join(sorted(found)),
        )
        return True

    def _write_disk(self):
        payload = {
            "fetched_at": self._fetched_at,
            "series": self._series,
        }
        FileManager.save_json_file(payload, CACHE_PATH)
