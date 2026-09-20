"""
Feature 36 -- a lista de aldeias do MUNDO INTEIRO, da fonte publica do jogo.

Contexto: docs/backend.md 8.6, "O terceiro funil nao tem cura local".

O TribalWars publica, sem sessao e sem autenticacao:

    <mundo>/map/village.txt    id,nome,x,y,player_id,pontos,rank

uma linha por aldeia do mundo, com o nome URL-encoded e `player_id == "0"`
significando barbara -- a mesma convencao que o resto do bot ja usa. E a fonte
em que as ferramentas de mapa da comunidade sao construidas.

POR QUE ISTO EXISTE
-------------------
`ConquestManager._candidate_pool()` varria duas fontes, e as duas so contem o
que alguma aldeia NOSSA ja escaneou algum dia:

    scan vivo da ancora ....  332 aldeias  (0,25% do mundo)
    cache/villages .........  851 aldeias  (0,65% do mundo)
    map/village.txt ........ 130.909 aldeias

Medido em 2026-09-20. Com isso `conquest.max_radius` era uma peneira de
DESCOBERTA disfarcada de decisao de alcance: subir o raio nao alcanca alvo que
nunca entrou na lista.

O CLIENTE E `requests` PURO, E NAO O `WebWrapper` -- DE PROPOSITO
-----------------------------------------------------------------
A implementacao de referencia (o fork `TWBOT_LazyTurtle`) chama
`wrapper.get_url("map/village.txt")`. Aqui isso seria um bug silencioso:
`WebWrapper.post_process()` roda em TODA resposta e faz

    elif 'x-csrf-token' in self.headers: del self.headers['x-csrf-token']

ou seja, uma resposta sem `<meta name="csrf-token">` -- e village.txt e texto
puro, nao tem -- APAGA o token de CSRF da sessao, quebrando os POSTs seguintes
do ciclo (recrutamento, mercado, envio de ataque). De quebra, `post_process`
ainda roda dois regex sobre os 6,3 MB e guarda o corpo inteiro em
`last_response`, e o `Referer` da sessao passaria a apontar para um .txt.

Este arquivo e publico e estatico: nao precisa de cookie, de token nem do
Referer do jogo. Vai por `requests` direto, com o user-agent configurado, e
nao encosta no estado da sessao. (O setimo padrao do CLAUDE.md manda sondar
com o cliente que o bot usa; ele fala de FIXTURE -- reproduzir a resposta que
o bot vai receber. Aqui a resposta e identica nos dois clientes; o que muda e
o efeito colateral no cliente, e esse e o motivo de nao usar o wrapper.)

DUAS PERGUNTAS, DUAS PRECEDENCIAS
---------------------------------
Esta fonte e a mais COMPLETA e a mais VELHA ao mesmo tempo, mas "velha" nao
vale para as duas perguntas que o pool responde, e tratar como se valesse
seria perigoso. Medido em 2026-09-20, cruzando as 851 entradas de
`cache/villages` com o village.txt do mesmo instante:

    cache diz BARBARA e o mundo diz JOGADOR ....  38
    cache diz JOGADOR e o mundo diz BARBARA ....   0

38 a 0. A assimetria nao e ruido: barbara vira aldeia de jogador o tempo todo
(e isso que conquista faz), e o caminho inverso quase nao existe. As 38
entradas erradas tinham 20,6 dias de idade. Ou seja, para POSSE o village.txt
nao e a fonte velha -- ele e a fonte NOVA, e `cache/villages` e que apodrece.

Entao:

  DESCOBERTA (quem existe, e onde) -- village.txt e o piso; as outras somam.
  POSSE e PONTOS -- scan vivo > village.txt > cache/villages.

Deixar `cache/villages` ganhar em posse, como "fresca vence" sugere a primeira
vista, manteria 38 barbaras fantasma no pool: alvos que o bot elegeria, e que
na verdade pertencem a jogadores. E o incidente da 8.7 entrando por outra
porta, com nobre de verdade.
"""
import logging
import os
import time
import urllib.parse

import requests

from core.filemanager import FileManager

logger = logging.getLogger("WorldVillages")

# O arquivo bruto, como o servidor mandou. Guardado em texto e nao em JSON de
# proposito: sao 6,3 MB crus contra ~20 MB de JSON, e o .txt e exatamente o
# que se abre para conferir uma linha na mao quando algo nao bate.
CACHE_PATH = "cache/world/villages_%s.txt"

# Posse muda na escala de conquistas, nao de minutos.
DEFAULT_TTL = 6 * 3600

# Um mundo cheio da ~6 MB. Recusar o absurdo em vez de ler uma pagina de erro
# ou um redirect para dentro da memoria como se fosse dado.
MAX_BYTES = 40 * 1024 * 1024

# Todo mundo tem milhares de aldeias. Um punhado significa que veio outra
# coisa -- e isto e o decimo quinto padrao do CLAUDE.md aplicado: a guarda tem
# que separar "li e esta vazio" de "isto nao e o arquivo". Sem ela, um
# redirect vira "o mundo tem 3 aldeias" e a conquista para sem erro nenhum.
MIN_VILLAGES = 100


def parse(text):
    """
    {village_id: (x, y, owner, points, nome_cru)} do arquivo cru.

    TUPLA E NAO DICT, E NOME AINDA URL-ENCODED -- de proposito
    ----------------------------------------------------------
    Sao 130 mil entradas, guardadas por 6h e atravessando os ciclos. Medido em
    2026-09-20 sobre o village.txt real do br143:

        dict {"id","name","location","owner","points"} ... 65,9 MB, 5,5 s
        tupla com o nome cru ........................... 42,4 MB, 2,8 s
        tupla sem o nome ............................... 33,6 MB

    O dict custava 24 MB a mais e o dobro do tempo, e quase todo o tempo extra
    era `unquote_plus` em 130 mil nomes dos quais o bot olha algumas milhares
    (so as da caixa de coordenadas). Entao a decodificacao do nome mudou de
    lugar, nao sumiu: acontece em `_entry()`, so para quem sai por `in_box()`.

    O consumidor nao ve nada disso -- `in_box()` devolve dicts na mesma forma
    de `cache/villages`. Esta funcao e a representacao interna.

    Linha malformada e pulada em silencio: o arquivo tem 130 mil linhas e uma
    quebrada nao pode derrubar as outras.
    """
    out = {}
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        parts = line.split(",")
        if len(parts) < 6:
            continue
        try:
            # "0" em owner = barbara, a mesma convencao do resto do bot.
            out[parts[0]] = (int(parts[2]), int(parts[3]), parts[4],
                             int(parts[5]), parts[1])
        except (TypeError, ValueError):
            continue
    return out


def _entry(vid, row):
    """
    Uma linha compacta na forma de `cache/villages` (`Map.build_cache_entry`).

    Mesma forma de proposito, incluindo `location` como lista [x, y]: e o que
    deixa `_candidate_pool()` misturar as tres fontes sem o consumidor
    precisar saber de qual delas veio cada entrada.
    """
    x, y, owner, points, raw_name = row
    return {
        "id": vid,
        "name": urllib.parse.unquote_plus(raw_name),
        "location": [x, y],
        "owner": owner,
        "points": points,
    }


class WorldVillages:
    """
    A lista do mundo, relida no maximo uma vez por TTL e memoizada no processo.

    Uma instancia por processo, compartilhada por todas as aldeias do ciclo:
    o conteudo e global (nao ha recorte por aldeia) e sao 6,3 MB -- uma
    instancia por aldeia baixaria isso 30 vezes por ciclo para obter
    exatamente o mesmo arquivo.
    """

    def __init__(self, config=None, world=None, endpoint=None):
        self.config = config or {}
        server = (self.config.get("server") or {})
        self.world = world or server.get("server") or "world"
        self.endpoint = endpoint or server.get("endpoint") or ""
        self.logger = logger
        # Mutaveis em __init__, nao no corpo da classe (1o padrao do CLAUDE.md).
        self._villages = {}
        self._parsed_at = 0.0
        self._last_error = None
        # Por instancia, e nao lido direto do modulo, para os testes poderem
        # baixa-lo sem mexer em estado global: a fixture verbatim tem 8 linhas
        # e o mundo real tem 130 mil, e inventar 100 linhas plausiveis so para
        # passar pela guarda e o oposto do que a regra de fixture manda.
        self.min_villages = MIN_VILLAGES

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    @property
    def enabled(self):
        return self.config.get("conquest", {}).get("use_world_village_list", True)

    def _ttl(self):
        return self.config.get("conquest", {}).get(
            "world_village_list_ttl", DEFAULT_TTL
        )

    def _cache_path(self):
        return CACHE_PATH % self.world

    def _url(self):
        base = (self.endpoint or "").rsplit("/", 1)[0]
        return "%s/map/village.txt" % base if base else None

    # ------------------------------------------------------------------
    # Leitura
    # ------------------------------------------------------------------

    def _download(self):
        """O arquivo cru do servidor, ou None. Nunca levanta."""
        url = self._url()
        if not url:
            self._last_error = "sem endpoint configurado"
            return None
        headers = {}
        agent = (self.config.get("bot") or {}).get("user_agent")
        if agent:
            headers["user-agent"] = agent
        try:
            res = requests.get(url, headers=headers, timeout=(15, 120))
        except requests.RequestException as exc:
            self._last_error = str(exc)
            return None
        if res.status_code != 200:
            self._last_error = "HTTP %d" % res.status_code
            return None
        if len(res.content) > MAX_BYTES:
            # Nao e "grande demais para caber": e sinal de que nao e o arquivo.
            self._last_error = "corpo de %d bytes acima do teto de %d" % (
                len(res.content), MAX_BYTES
            )
            return None
        self.logger.debug("village.txt: %d bytes de %s", len(res.content), url)
        return res.text

    def _read_disk(self):
        """O ultimo arquivo bom que baixamos, ou None."""
        path = self._cache_path()
        full = FileManager.get_path(path)
        if not os.path.exists(full):
            return None
        try:
            with open(full, "r", encoding="utf-8") as handle:
                return handle.read()
        except OSError as exc:
            self.logger.warning("village.txt: falha ao ler o cache %s: %s", path, exc)
            return None

    def _write_disk(self, text):
        path = self._cache_path()
        full = FileManager.get_path(path)
        try:
            FileManager.create_directory(os.path.dirname(full))
            with open(full, "w", encoding="utf-8") as handle:
                handle.write(text)
        except OSError as exc:
            self.logger.warning("village.txt: falha ao gravar o cache %s: %s", path, exc)

    def _disk_age(self):
        full = FileManager.get_path(self._cache_path())
        try:
            return time.time() - os.path.getmtime(full)
        except OSError:
            return None

    def rows(self):
        """
        {village_id: (x, y, owner, points, nome_cru)} do mundo inteiro, ou {}.

        Representacao interna (ver `parse()`); quem consome quer `in_box()`.

        Ordem: memoria dentro do TTL, depois disco dentro do TTL, depois a
        rede. Qualquer falha na rede cai no disco por mais velho que ele
        esteja, e na falta do disco na propria lista em memoria -- uma lista de
        ontem e imensamente melhor que nenhuma, porque "nenhuma" devolve o bot
        aos 851 do cache local sem dizer nada.

        A queda para a memoria vencida foi acrescentada depois de
        `test_lista_curta_nao_apaga_a_leitura_boa_que_ja_estava_em_memoria`
        reprovar: o TTL vencer e o refresh falhar faziam este metodo devolver
        `{}` mesmo com a lista boa ainda carregada, porque o unico caminho de
        volta passava pelo disco. Num processo que roda por dias e o caso
        comum de um soluco do servidor.
        """
        if not self.enabled:
            return {}

        ttl = self._ttl()
        if self._villages and (time.time() - self._parsed_at) < ttl:
            return self._villages

        age = self._disk_age()
        if age is not None and age < ttl:
            text = self._read_disk()
            if self._adopt(text, "cache em disco (%.1f h)" % (age / 3600)):
                return self._villages

        text = self._download()
        if self._adopt(text, "rede"):
            self._write_disk(text)
            return self._villages

        # A rede falhou ou devolveu algo que nao e o arquivo. O disco velho
        # vale mais que nada.
        stale = self._read_disk()
        if self._adopt(stale, "cache VENCIDO em disco (%s)" % (
                "%.1f h" % (age / 3600) if age is not None else "idade desconhecida")):
            self.logger.warning(
                "village.txt: nao consegui atualizar (%s) -- seguindo com o "
                "cache vencido de %s. Posse pode estar velha; a revalidacao "
                "em _handle_existing() continua sendo a rede de baixo.",
                self._last_error, self._cache_path()
            )
            return self._villages

        if self._villages:
            # Nem rede nem disco, mas a lista boa de horas atras continua
            # carregada. Servir ela e estritamente melhor que devolver {}, que
            # apagaria a descoberta inteira sem nada a ganhar. O `_parsed_at`
            # NAO e atualizado de proposito: a proxima chamada tenta de novo,
            # em vez de congelar esta lista por mais um TTL.
            self.logger.warning(
                "village.txt: nao consegui atualizar (%s) e nao ha cache em "
                "disco -- seguindo com as %d aldeias ja carregadas nesta "
                "sessao", self._last_error, len(self._villages)
            )
            return self._villages

        self.logger.warning(
            "village.txt: sem lista do mundo (%s) e sem cache em disco -- a "
            "descoberta de alvo volta a depender so do que o imperio ja "
            "escaneou", self._last_error
        )
        return {}

    def _adopt(self, text, origem):
        """
        Parseia e aceita `text` como a lista do mundo, ou recusa.

        Devolve False sem tocar no estado atual quando o conteudo nao passa na
        guarda das `MIN_VILLAGES` linhas -- que e o caso do redirect para
        login e da pagina de erro, os dois indistinguiveis de um arquivo bom
        se so olharmos o codigo HTTP.
        """
        if not text:
            return False
        parsed = parse(text)
        if len(parsed) < self.min_villages:
            self._last_error = (
                "%d aldeias parseadas, abaixo do minimo de %d (%s)"
                % (len(parsed), self.min_villages, origem)
            )
            self.logger.warning("village.txt: %s -- recusado", self._last_error)
            return False
        self._villages = parsed
        self._parsed_at = time.time()
        self.logger.info(
            "village.txt: %d aldeias do mundo %s, via %s",
            len(parsed), self.world, origem
        )
        return True

    # ------------------------------------------------------------------
    # Consulta
    # ------------------------------------------------------------------

    def in_box(self, x_min, x_max, y_min, y_max):
        """
        So as aldeias dentro da caixa de coordenadas.

        Existe para que o chamador nao precise materializar as 130 mil
        entradas a cada ciclo: o recorte roda ANTES de qualquer pontuacao, e
        e o que mantem o laco de `find_target()` no mesmo custo de antes
        mesmo com um pool 150x maior (docs/backend.md 8.6).
        """
        out = {}
        for vid, row in self.rows().items():
            if x_min <= row[0] <= x_max and y_min <= row[1] <= y_max:
                out[vid] = _entry(vid, row)
        return out

    # Nao definir __len__ aqui. O objeto e testado por verdade em
    # `ConquestManager._world_box()` (`if not self.world_villages`), e um
    # __len__ tornaria a instancia FALSY quando a lista viesse vazia -- alem
    # de disparar o download inteiro so para avaliar um `if`. Para contar,
    # `len(world.rows())` explicitamente.
