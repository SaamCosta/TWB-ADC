"""
game/player_stats.py::PlayerStats -- controle de TTL, gate e degradacao
segura em torno de Extractor.stats_own_series (coberto a parte em
tests/test_stats_own_extractor.py, que usa o fixture verbatim do jogo).

O que importa aqui NAO e o parser, e o comportamento ao redor dele:
  - uma leitura ruim nunca apaga uma leitura boa anterior (mesmo raciocinio
    de WorldVillages.rows(), docs/backend.md 8.6);
  - o TTL evita reler a cada ciclo uma serie cuja resolucao e diaria
    (docs/backend.md 8.13: reler em minutos nao muda o numero);
  - so as series de interesse (Saqueado/Coletado) sao guardadas -- as de
    gasto (Unidades, Edificios, ...) nao tem consumidor ainda.

`_write_disk` e trocado por um duble em memoria: o bot escreve
cache/player_stats.json enquanto roda (vigesimo primeiro padrao do
CLAUDE.md), entao um teste nao pode passar por cima dele.

Rodar: python tests/test_player_stats_reader.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from game.player_stats import PlayerStats, SERIES_OF_INTEREST, DEFAULT_TTL

checks = 0


def check(cond, msg):
    global checks
    checks += 1
    if not cond:
        raise AssertionError(msg)


# HTML minimo, autoral (o markup real ja e coberto verbatim em
# test_stats_own_extractor.py) -- so precisa ter as tres series para testar o
# FILTRO por SERIES_OF_INTEREST.
HTML_COM_TRES_SERIES = (
    "<script>"
    "data.push({label: 'Saqueado', details: ["
    '{"time":"1000","wood":"1","stone":"1","iron":"1","total":"3","percent":50.0}]});'
    "data.push({label: 'Coletado', details: ["
    '{"time":"1000","wood":"2","stone":"2","iron":"2","total":"6","percent":30.0}]});'
    "data.push({label: 'Unidades', details: ["
    '{"time":"1000","wood":"9","stone":"9","iron":"9","total":"27","percent":20.0}]});'
    "</script>"
)

HTML_SEM_SERIE_DE_INTERESSE = (
    "<script>data.push({label: 'Unidades', details: ["
    '{"time":"1000","wood":"9","stone":"9","iron":"9","total":"27","percent":100.0}]});'
    "</script>"
)

HTML_SEM_SERIES_RECONHECIVEIS = "<html>login</html>"


class _FakeResponse:
    def __init__(self, text):
        self.text = text


class _FakeWrapper:
    """`get_url` devolve o proximo item da fila; None simula rede fora."""

    def __init__(self, respostas):
        self._fila = list(respostas)
        self.chamadas = []

    def get_url(self, url):
        self.chamadas.append(url)
        item = self._fila.pop(0) if self._fila else None
        return None if item is None else _FakeResponse(item)


def _reader(wrapper=None, config=None):
    r = PlayerStats(wrapper=wrapper, config=config or {})
    r._disk_writes = []
    r._write_disk = lambda: r._disk_writes.append(
        {"fetched_at": r._fetched_at, "series": dict(r._series)}
    )
    return r


def test_sem_wrapper_nao_faz_nada():
    r = _reader(wrapper=None)
    check(r.refresh("41123") is False, "sem wrapper nao deveria tentar nada")
    check(r._series == {}, "estado deveria continuar vazio")


def test_gate_desligado_nao_chama_a_rede():
    w = _FakeWrapper([HTML_COM_TRES_SERIES])
    r = _reader(wrapper=w, config={"player_stats": {"enabled": False}})
    check(r.refresh("41123") is False, "gate desligado deveria recusar")
    check(w.chamadas == [], "gate desligado nao pode gerar requisicao")


def test_sem_village_id_nao_faz_nada():
    w = _FakeWrapper([HTML_COM_TRES_SERIES])
    r = _reader(wrapper=w)
    check(r.refresh(None) is False, "sem aldeia nao ha endereco para o GET")
    check(r.refresh("") is False, "string vazia tambem nao e endereco valido")
    check(w.chamadas == [], "nenhuma das duas chamadas deveria ir a rede")


def test_leitura_boa_grava_so_as_series_de_interesse():
    w = _FakeWrapper([HTML_COM_TRES_SERIES])
    r = _reader(wrapper=w)
    check(r.refresh("41123") is True, "primeira leitura deveria ser aceita")
    check(set(r._series) == set(SERIES_OF_INTEREST),
          "so Saqueado/Coletado deveriam sobreviver ao filtro: %r" % r._series)
    check("Unidades" not in r._series, "serie de gasto nao devia ser guardada")
    check(len(r._disk_writes) == 1, "uma leitura boa == uma escrita")
    check(r._disk_writes[0]["series"] == r._series,
          "o payload gravado tem que ser o estado atual")


def test_ttl_nao_vencido_nao_gera_segunda_requisicao():
    w = _FakeWrapper([HTML_COM_TRES_SERIES, HTML_COM_TRES_SERIES])
    r = _reader(wrapper=w)
    check(r.refresh("41123") is True, "primeira leitura")
    check(r.refresh("41123") is False, "dentro do TTL nao deveria reler")
    check(len(w.chamadas) == 1,
          "resolucao diaria -- reler dentro do TTL so gasta requisicao")


def test_ttl_vencido_gera_nova_requisicao():
    w = _FakeWrapper([HTML_COM_TRES_SERIES, HTML_COM_TRES_SERIES])
    r = _reader(wrapper=w, config={"player_stats": {"cache_seconds": 60}})
    check(r.refresh("41123") is True, "primeira leitura")
    r._fetched_at = time.time() - 61  # forca o TTL de 60s vencer
    check(r.refresh("41123") is True, "TTL vencido deveria reler")
    check(len(w.chamadas) == 2, "duas leituras aceitas == duas requisicoes")


def test_ttl_default_e_seis_horas():
    check(DEFAULT_TTL == 6 * 3600, "default documentado em backend.md 8.13")


def test_falha_de_rede_preserva_a_leitura_anterior():
    w = _FakeWrapper([HTML_COM_TRES_SERIES, None])
    r = _reader(wrapper=w, config={"player_stats": {"cache_seconds": 0}})
    check(r.refresh("41123") is True, "primeira leitura boa")
    estado_bom = dict(r._series)
    check(r.refresh("41123") is False, "get_url devolveu None -- deveria falhar")
    check(r._series == estado_bom,
          "uma falha de rede nao pode apagar a serie boa anterior")
    check(r._last_error, "o motivo da falha deveria ficar registrado")
    check(len(r._disk_writes) == 1, "a leitura falha nao pode gerar escrita nova")


def test_markup_sem_series_reconheciveis_preserva_a_leitura_anterior():
    w = _FakeWrapper([HTML_COM_TRES_SERIES, HTML_SEM_SERIES_RECONHECIVEIS])
    r = _reader(wrapper=w, config={"player_stats": {"cache_seconds": 0}})
    check(r.refresh("41123") is True, "primeira leitura boa")
    estado_bom = dict(r._series)
    check(r.refresh("41123") is False,
          "markup sem serie nenhuma deveria ser tratado como falha")
    check(r._series == estado_bom, "estado bom anterior preservado")
    check(len(r._disk_writes) == 1, "sem escrita nova")


def test_resposta_sem_as_series_de_interesse_preserva_e_nao_grava():
    w = _FakeWrapper([HTML_COM_TRES_SERIES, HTML_SEM_SERIE_DE_INTERESSE])
    r = _reader(wrapper=w, config={"player_stats": {"cache_seconds": 0}})
    check(r.refresh("41123") is True, "primeira leitura boa")
    estado_bom = dict(r._series)
    # A pagina respondeu normalmente e tem series -- so nao as que interessam
    # aqui. Distinto do caso "markup quebrado": aqui o jogo falou direito.
    check(r.refresh("41123") is False,
          "resposta so com series de gasto nao deveria ser aceita")
    check(r._series == estado_bom, "estado bom anterior preservado")
    check(len(r._disk_writes) == 1, "sem escrita nova")


def test_enabled_e_true_por_padrao():
    r = _reader(wrapper=_FakeWrapper([]), config={})
    check(r.enabled is True, "leitura e so-leitura e sem custo de jogo -- default ligado")


for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
    fn()

print("OK: %d checagens em %s" % (checks, os.path.basename(__file__)))
