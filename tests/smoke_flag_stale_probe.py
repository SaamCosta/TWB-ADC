"""
Prova que o gate de frescor de bandeira E CAPAZ DE FALHAR (21o padrao).

Um teste verde nao distingue "guarda funcionando" de "guarda que nao faz
nada". Este probe roda as asercoes COMPORTAMENTAIS do gate sem usar nenhuma
API nova, entao ele pode ser copiado para uma arvore do HEAD anterior e
rodado la:

    git worktree add --detach $tmp HEAD
    copy tests/smoke_flag_stale_probe.py $tmp/tests/
    cd $tmp; python tests/smoke_flag_stale_probe.py

Esperado na arvore ANTIGA: as duas asercoes de "inventario velho nao move
bandeira" FALHAM (o codigo antigo nao tem o conceito e move sempre).
Esperado nesta arvore: passam.

Fora do glob test_*.py porque ele e um instrumento de comparacao entre duas
arvores, nao uma regressao -- a regressao mora em tests/test_flag_supply.py.
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game.defence_manager import DefenceManager

results = []


def make(current, inventory, stale):
    d = DefenceManager(village_id="99999", wrapper=None)
    d.logger = logging.getLogger("probe")
    d.manage_flags_enabled = True
    d.has_academy = False
    d.current_flag = list(current) if current else None
    d.flags = dict(inventory)
    d._can_change_flag = True
    d._flag_state_confirmed = True
    # Na arvore antiga este atributo simplesmente nao e consultado por
    # ninguem -- setar nao tem efeito, que e exatamente o que se quer expor.
    if stale:
        d._flags_fresh = False
    else:
        d._flags_fresh = True
    d.sent = []
    d.flag_set = lambda flag, level: d.sent.append((flag, level)) or True
    return d


def probe(label, current, inventory, stale, expected):
    d = make(current, inventory, stale)
    d.flag_logic(d.preferred_flags())
    ok = d.sent == expected
    results.append((ok, label, d.sent, expected))


# O caso BBM 029 x BBM 030: a aldeia acredita num tipo 6 nivel 7 que ja foi
# para outra aldeia. Mover arrancaria a bandeira de la.
probe("inventario VELHO nao move bandeira", [8, 2], {6: 7}, True, [])
probe("inventario VELHO nao equipa em aldeia sem bandeira", None, {6: 7}, True, [])
# Controles: com leitura do ciclo, a troca tem que acontecer.
probe("inventario FRESCO move bandeira", [8, 2], {6: 7}, False, [(6, 7)])
probe("inventario FRESCO equipa em aldeia sem bandeira", None, {6: 7}, False, [(6, 7)])

bad = [r for r in results if not r[0]]
for ok, label, got, expected in results:
    print(("  ok  " if ok else "  FALHOU  ") + label
          + (f"  (esperado {expected}, veio {got})" if not ok else ""))
print()
if bad:
    print(f"{len(bad)} de {len(results)} asercoes falharam -- "
          "esta arvore NAO tem o gate de frescor.")
    sys.exit(1)
print(f"{len(results)} de {len(results)} asercoes passaram -- gate presente e ativo.")
