"""
Rotulo `nome (id)` das aldeias proprias em log e aviso (`core/village_label.py`).

Sem rede e sem tocar o `cache/managed` real: o diretorio e trocado por um
temporario em cada teste.
"""

import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import village_label as vl  # noqa: E402

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


def _with_cache(entries):
    """Diretorio temporario no lugar de cache/managed, com {vid: nome}."""
    tmp = tempfile.mkdtemp()
    for vid, name in entries.items():
        with open(os.path.join(tmp, "%s.json" % vid), "w", encoding="utf-8") as fh:
            json.dump({"name": name, "x": 1, "y": 2}, fh)
    vl.reset()
    vl.MANAGED_DIR = tmp
    return tmp


def test_nome_do_cache_managed():
    _with_cache({"40618": "BBM 022"})
    check(vl.village_label("40618") == "BBM 022 (40618)", vl.village_label("40618"))
    check(vl.village_label(40618) == "BBM 022 (40618)", "id int deveria casar com o arquivo")


def test_aldeia_alheia_fica_so_com_id():
    _with_cache({"40618": "BBM 022"})
    check(vl.village_label("57033") == "57033", "barbara nao pode ganhar nome inventado")
    check(vl.village_label(None) == "None", "None nao pode levantar")


def test_register_vence_o_cache_e_acompanha_renomeio():
    _with_cache({"40618": "BBM 022"})
    vl.register("40618", "BBM 022 nova")
    check(vl.village_label("40618") == "BBM 022 nova (40618)", "register deveria vencer o cache")
    vl.register("40618", "")
    check(vl.village_label("40618") == "BBM 022 nova (40618)", "nome vazio apagou o conhecido")


def test_miss_relê_o_disco_depois_do_intervalo():
    tmp = _with_cache({})
    check(vl.village_label("74690") == "74690", "sem arquivo deveria ser so o id")
    # Aldeia recem-conquistada ganha arquivo no primeiro ciclo dela.
    with open(os.path.join(tmp, "74690.json"), "w", encoding="utf-8") as fh:
        json.dump({"name": "BBM 042"}, fh)
    check(vl.village_label("74690") == "74690", "miss deveria ficar em cache dentro do intervalo")
    vl._misses["74690"] -= vl.MISS_RETRY_SECONDS + 1
    check(vl.village_label("74690") == "BBM 042 (74690)", "miss vencido deveria reler o disco")


def test_arquivo_ilegivel_nao_derruba():
    tmp = _with_cache({})
    with open(os.path.join(tmp, "1.json"), "w", encoding="utf-8") as fh:
        fh.write("{nao e json")
    check(vl.village_label("1") == "1", "json quebrado deveria cair no id")


def test_lista():
    _with_cache({"1": "A", "2": "B"})
    check(vl.village_labels(["1", "3", "2"]) == "A (1), 3, B (2)", vl.village_labels(["1", "3", "2"]))


if __name__ == "__main__":
    original = vl.MANAGED_DIR
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except Exception as exc:
                failures.append("%s: %r" % (name, exc))
    vl.MANAGED_DIR = original
    vl.reset()
    for f in failures:
        print("FALHA", f)
    print("OK" if not failures else "%d falha(s)" % len(failures))
    sys.exit(1 if failures else 0)
