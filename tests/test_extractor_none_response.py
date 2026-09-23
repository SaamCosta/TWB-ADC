"""
Todo parser do Extractor aceita resposta None sem levantar excecao.

`WebWrapper.get_url()` devolve None em QUALQUER excecao (2o padrao do
CLAUDE.md). Em 2026-09-23, 14:1x, um soluco de rede fez `smith_data(None)`
levantar `AttributeError: 'NoneType' object has no attribute 'text'` e o bot
inteiro caiu no meio de um ciclo. 24 parsers tinham o mesmo `res.text` sem
guarda; agora todos passam por `_page_text()`.

O teste varre a classe em vez de listar nomes: parser novo que copiar a linha
antiga (`if type(res) != str: res = res.text`) sem a guarda nao entra na lista
por esquecimento -- ele e pego pela segunda checagem.

Rodar: python tests/test_extractor_none_response.py
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.extractors import Extractor


def _parsers():
    for nome, fn in inspect.getmembers(Extractor, predicate=inspect.isfunction):
        params = list(inspect.signature(fn).parameters.values())
        obrigatorios = [p for p in params if p.default is inspect.Parameter.empty]
        if len(obrigatorios) == 1 and obrigatorios[0].name == "res":
            yield nome, fn


def test_nenhum_parser_quebra_com_none():
    quebrados = []
    for nome, fn in _parsers():
        try:
            fn(None)
        except Exception as exc:  # noqa: BLE001
            quebrados.append("%s: %r" % (nome, exc))
    assert not quebrados, quebrados


def test_nenhum_parser_usa_res_text_sem_guarda():
    fonte = inspect.getsource(Extractor)
    assert "if type(res) != str:\n            res = res.text" not in fonte


def test_a_varredura_encontra_os_parsers():
    """Guarda da guarda: se _parsers() vier vazio o primeiro teste passa a toa."""
    nomes = {nome for nome, _ in _parsers()}
    assert {"smith_data", "game_state", "recruit_data", "attack_duration"} <= nomes


if __name__ == "__main__":
    falhas = 0
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok   %s" % nome)
            except Exception as exc:
                falhas += 1
                print("FALHA %s: %r" % (nome, exc))
    sys.exit(1 if falhas else 0)
