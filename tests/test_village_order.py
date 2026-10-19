"""
Ordem das aldeias no ciclo: mais atrasada primeiro (`TWB.stale_first_order`,
docs/backend.md §8.68, 19/10/2026).

O defeito: `processing_order = list(self.villages)` repetia a ordem do config
todo ciclo. Com o corte das 23h (`active_hours`) e os reinícios, o ciclo nunca
chegava ao fim: em 19/10 BBM 032–053 estavam desde 17/10 sem rodar, e as três
últimas conquistas (81571, 74966, 69861) nunca tinham rodado — sem herança de
papel (`inherit_on_first_run` ainda verdadeiro), sem construir, sem farm.

O que se protege aqui: quem nunca rodou vem primeiro, depois a mais antiga;
empate fica na ordem do config; o padrão lê o mtime de `cache/managed`.

Rodar: python tests/test_village_order.py
"""
import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from twb import TWB  # noqa: E402

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


def v(vid):
    return SimpleNamespace(village_id=vid)


villages = [v("41123"), v("38409"), v("51540"), v("81571"), v("74966"), v("44683")]
last = {"41123": 1000.0, "38409": 1100.0, "44683": 1050.0, "51540": 500.0}
order = [x.village_id for x in TWB.stale_first_order(villages, lambda vid: last.get(vid, 0.0))]
check(order == ["81571", "74966", "51540", "41123", "44683", "38409"],
      "nunca rodou primeiro (na ordem do config), depois a mais antiga -> %r" % order)
check([x.village_id for x in TWB.stale_first_order([], lambda vid: 0)] == [], "lista vazia")
check(len(villages) == 6 and villages[0].village_id == "41123", "nao mexe na lista original")

# Padrao: mtime de cache/managed, que nao existe para um id inventado (= nunca rodou).
default = [x.village_id for x in TWB.stale_first_order([v("41123"), v("999999999")])]
check(default[0] == "999999999", "sem cache/managed: vem primeiro -> %r" % default)

if failures:
    print(f"FALHOU ({len(failures)} problema(s)):")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("OK: aldeia mais atrasada primeiro")
