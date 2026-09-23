"""
A heranca de config de aldeia nova grava SO a entrada dela, relendo o disco
(`Village._persist_village_config`, docs/backend.md 8.29).

O INCIDENTE: em 2026-09-23 a 51540 herdou config as 13:58:47 gravando o
config.json inteiro a partir da copia carregada no inicio do ciclo (09:01).
Isso desfez `conquest.reserve_max_slots: 3` e
`conquest.snipe_expiring_reservations: true`, escritos as 11:5x, e o timer de
reserva da 74694 subiu desarmado.

Nada aqui toca o config.json real: o FileManager do modulo e trocado por um
disco em memoria (21o padrao).

Rodar: python tests/test_village_config_persist.py
"""
import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import game.village as village_mod
from game.village import Village


class _Logger:
    def __init__(self):
        self.avisos = []

    def info(self, *a, **k): pass
    def debug(self, *a, **k): pass
    def warning(self, *a, **k): self.avisos.append(a[0] % a[1:])


def _disco(conteudo):
    estado = {"arquivo": copy.deepcopy(conteudo), "escritas": 0}

    class _FM:
        @staticmethod
        def load_json_file(path, **k):
            return copy.deepcopy(estado["arquivo"])

        @staticmethod
        def save_json_file(data, path, **k):
            estado["escritas"] += 1
            estado["arquivo"] = copy.deepcopy(data)

    village_mod.FileManager = _FM
    return estado


def _aldeia(vid="51540"):
    v = Village.__new__(Village)
    v.village_id = vid
    v.logger = _Logger()
    return v


# O que estava no disco as 13:58 (com a edicao das 11:5x) ...
NO_DISCO = {
    "conquest": {"reserve_max_slots": 3, "snipe_expiring_reservations": True},
    "villages": {"41123": {"building": "x"},
                 "51540": {"inherit_on_first_run": True}},
}
# ... e a copia que o ciclo carregou as 09:01.
EM_MEMORIA = {
    "conquest": {"reserve_max_slots": 1},
    "villages": {"41123": {"building": "x"},
                 "51540": {"inherit_on_first_run": True}},
    "inheritance": {"mode": "global_template"},
}


def test_heranca_nao_desfaz_edicao_feita_durante_o_ciclo():
    disco = _disco(NO_DISCO)
    config = copy.deepcopy(EM_MEMORIA)
    _aldeia().apply_nearest_village_inheritance(config)

    gravado = disco["arquivo"]
    assert gravado["conquest"] == NO_DISCO["conquest"], gravado["conquest"]
    assert gravado["villages"]["51540"]["inherit_on_first_run"] is False
    assert "inheritance" not in gravado, "nao pode trazer chave da copia velha"


def test_so_a_propria_aldeia_muda():
    disco = _disco(NO_DISCO)
    config = copy.deepcopy(EM_MEMORIA)
    config["villages"]["41123"]["building"] = "valor velho da memoria"
    config["villages"]["51540"] = {"building": "herdado", "inherit_on_first_run": False}
    assert _aldeia()._persist_village_config(config) is True
    assert disco["arquivo"]["villages"]["41123"] == {"building": "x"}
    assert disco["arquivo"]["villages"]["51540"]["building"] == "herdado"


def test_arquivo_ilegivel_nao_grava_nada():
    disco = _disco(None)
    aldeia = _aldeia()
    assert aldeia._persist_village_config(copy.deepcopy(EM_MEMORIA)) is False
    assert disco["escritas"] == 0
    assert aldeia.logger.avisos


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
