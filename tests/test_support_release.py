"""
A26-08 (`docs/backend.md` §8.32): `DefenceManager.supported` nunca era zerado.

A lista existe para a doadora nao mandar apoio duas vezes no MESMO ataque. Como
so crescia, depois de `support_max_villages` apoios a doadora nunca mais
apoiava ninguem ate o bot reiniciar, e a mesma aldeia nao recebia apoio num
ataque futuro. Agora a vaga volta quando a aldeia sai de "sob ataque".

Sem rede: `support_timing` e `support_other` sao duble.

Rodar: python tests/test_support_release.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game.defence_manager import DefenceManager


def _dm(max_villages=2):
    dm = DefenceManager(village_id="me")
    dm.support_max_villages = max_villages
    dm.allow_support_send = True
    dm.under_attack = False
    dm.sent = []
    dm.support_timing = lambda vil: (True, "teste")
    dm.support_other = lambda vil: dm.sent.append(vil) or True
    return dm


def test_nao_apoia_duas_vezes_o_mesmo_ataque():
    dm = _dm()
    dm.my_other_villages = {"a": True}
    dm._support_others()
    dm._support_others()
    assert dm.sent == ["a"]


def test_vaga_volta_quando_o_ataque_acaba():
    dm = _dm(max_villages=2)
    dm.my_other_villages = {"a": True, "b": True}
    dm._support_others()
    assert dm.sent == ["a", "b"]

    # novo ataque em "c": sem a correcao, o limite de 2 ja estava gasto
    dm.my_other_villages = {"a": False, "b": False, "c": True}
    dm._support_others()
    assert dm.sent == ["a", "b", "c"], dm.sent
    assert dm.supported == ["c"]


def test_mesma_aldeia_e_apoiada_de_novo_num_ataque_futuro():
    dm = _dm()
    dm.my_other_villages = {"a": True}
    dm._support_others()
    dm.my_other_villages = {"a": False}
    dm._support_others()
    dm.my_other_villages = {"a": True}
    dm._support_others()
    assert dm.sent == ["a", "a"]


def test_aldeia_que_sumiu_do_cache_libera_a_vaga():
    dm = _dm(max_villages=1)
    dm.my_other_villages = {"a": True}
    dm._support_others()
    dm.my_other_villages = {"b": True}
    dm._support_others()
    assert dm.sent == ["a", "b"]


def test_limite_ainda_vale_durante_o_ataque():
    dm = _dm(max_villages=1)
    dm.my_other_villages = {"a": True, "b": True}
    dm._support_others()
    dm._support_others()
    assert dm.sent == ["a"]


def test_envio_recusado_nao_ocupa_vaga():
    dm = _dm(max_villages=1)
    dm.support_other = lambda vil: dm.sent.append(vil) and False
    dm.my_other_villages = {"a": True}
    assert dm._support_others() is True
    assert dm.supported == []


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok   %s" % name)
            except Exception as exc:
                failures += 1
                print("FALHA %s: %r" % (name, exc))
    sys.exit(1 if failures else 0)
