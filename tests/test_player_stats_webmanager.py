"""
webmanager/utils.py::PlayerStatsReader -- o lado que a pagina /empire le.

Le `cache/player_stats.json`, escrito por game/player_stats.py (Feature 37).
Cobre a formatacao para o template (data por dia, mais recente primeiro,
marca de "pode estar parcial" no primeiro dia) e os dois casos de ausencia
que a pagina precisa distinguir de uma lista vazia de verdade: arquivo que
nunca existiu e JSON parcial (o bot grava atomico, mas o fallback in-place
existe).

`CACHE_PATH` e trocado por um arquivo temporario -- o bot escreve
cache/player_stats.json enquanto roda (vigesimo primeiro padrao do
CLAUDE.md), entao um teste nao pode ler/escrever o arquivo real.

Rodar: python tests/test_player_stats_webmanager.py
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from webmanager.utils import PlayerStatsReader

checks = 0


def check(cond, msg):
    global checks
    checks += 1
    if not cond:
        raise AssertionError(msg)


def _ler(payload_ou_texto):
    """Roda PlayerStatsReader.load() contra um arquivo temporario."""
    pasta = tempfile.mkdtemp()
    try:
        caminho = os.path.join(pasta, "player_stats.json")
        with open(caminho, "w", encoding="utf-8") as fh:
            if isinstance(payload_ou_texto, str):
                fh.write(payload_ou_texto)
            else:
                json.dump(payload_ou_texto, fh)
        original = PlayerStatsReader.CACHE_PATH
        PlayerStatsReader.CACHE_PATH = caminho
        try:
            return PlayerStatsReader.load()
        finally:
            PlayerStatsReader.CACHE_PATH = original
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


PAYLOAD = {
    "fetched_at": 1758470400,
    "series": {
        "Saqueado": [
            {"observed_at": 1789959600, "wood": 55165, "stone": 44169,
             "iron": 47914, "total": 147248, "percent": 26.24},
            {"observed_at": 1789873200, "wood": 109841, "stone": 65162,
             "iron": 107768, "total": 282771, "percent": 50.77},
        ],
        "Coletado": [
            {"observed_at": 1789959600, "wood": 137967, "stone": 137967,
             "iron": 137957, "total": 413891, "percent": 73.76},
            {"observed_at": 1789873200, "wood": 91388, "stone": 91388,
             "iron": 91383, "total": 274159, "percent": 49.23},
        ],
    },
}


def test_arquivo_ausente_nao_e_lista_vazia_de_verdade():
    """
    Distincao que a pagina precisa fazer: "ainda nao li" contra "li e nao ha
    dado" -- sem `available`, as duas renderizariam a mesma tabela vazia.
    """
    pasta = tempfile.mkdtemp()
    try:
        original = PlayerStatsReader.CACHE_PATH
        PlayerStatsReader.CACHE_PATH = os.path.join(pasta, "nao_existe.json")
        try:
            out = PlayerStatsReader.load()
        finally:
            PlayerStatsReader.CACHE_PATH = original
    finally:
        shutil.rmtree(pasta, ignore_errors=True)
    check(out["available"] is False, "arquivo ausente -> available False")
    check(out["days"] == [], "sem dias")


def test_json_parcial_degrada_para_ausente_sem_levantar():
    out = _ler('{"fetched_at": 123, "series": {"Saqueado": [')  # cortado
    check(out["available"] is False, "JSON quebrado deveria degradar, nao levantar")


def test_dias_vem_do_mais_recente_para_o_mais_antigo():
    out = _ler(PAYLOAD)
    check(out["available"] is True, "payload valido deveria estar disponivel")
    check(len(out["days"]) == 2, "dois dias no payload de teste")
    check(out["days"][0]["observed_at"] == 1789959600, "mais recente primeiro")
    check(out["days"][1]["observed_at"] == 1789873200, "depois o mais antigo")


def test_so_o_primeiro_dia_e_marcado_como_possivelmente_parcial():
    out = _ler(PAYLOAD)
    check(out["days"][0]["maybe_partial"] is True,
          "o dia mais recente pode ainda estar acumulando (contrato d)")
    check(out["days"][1]["maybe_partial"] is False,
          "dias anteriores ja fecharam -- nao marcar parcial neles")


def test_totais_saqueado_e_coletado_batem_com_o_payload():
    out = _ler(PAYLOAD)
    d0 = out["days"][0]
    check(d0["looted_total"] == 147248, "total saqueado do dia mais recente")
    check(d0["gathered_total"] == 413891, "total coletado do dia mais recente")
    check(d0["looted_wood"] == 55165 and d0["gathered_iron"] == 137957,
          "quebra por recurso deveria sobreviver para o tooltip")


def test_dia_presente_so_numa_das_duas_series_nao_quebra():
    payload = {
        "fetched_at": 1,
        "series": {
            "Saqueado": [{"observed_at": 100, "wood": 1, "stone": 1,
                          "iron": 1, "total": 3, "percent": 100.0}],
            "Coletado": [],
        },
    }
    out = _ler(payload)
    check(len(out["days"]) == 1, "um dia so, mesmo sem Coletado naquele dia")
    check(out["days"][0]["looted_total"] == 3, "saqueado presente")
    check(out["days"][0]["gathered_total"] is None,
          "coletado ausente naquele dia -- None, nao 0 inventado")


def test_fetched_at_formatado_para_o_rodape_do_card():
    out = _ler(PAYLOAD)
    check(out["fetched_at"] == 1758470400, "epoch cru preservado")
    check(out["fetched_at_fmt"] != "—", "deveria formatar quando ha timestamp")


def test_series_ausente_no_payload_e_tratada_como_vazia():
    out = _ler({"fetched_at": 1, "series": {}})
    check(out["available"] is False, "sem nenhuma serie -> nada disponivel")
    check(out["days"] == [], "sem dias")


for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
    fn()

print("OK: %d checagens em %s" % (checks, os.path.basename(__file__)))
