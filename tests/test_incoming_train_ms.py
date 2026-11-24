"""
Milissegundo da chegada de comando recebido (`arrival_ms` de
`Extractor.incoming_commands`), F0 do P-SNIPE-TREM (docs/backend.md §9
item 29).

Fixture `incoming_noble_train_br143.html`: as quatro linhas verbatim do widget
de comandos da visão geral da BBM 010 (74689), br143, 24/11/2026 04:52, um
trem de 4 nobres de jogador com acordo, todos marcados pela torre ("Ataque
pequeno (1-1000 tropas)" + "Com nobre"), pousando no mesmo segundo
(`data-endtime` igual) e separados só pelo milissegundo. Só o rótulo (aldeia
de origem, de terceiro) foi trocado por "Aldeia C".

Guarda provada: as linhas do fixture de torre pendente, de outro formato de
data, continuam lidas, e uma linha sem o `<span class="grey small">` dá None,
não 0.

Rodar: python tests/test_incoming_train_ms.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.extractors import Extractor

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return fh.read()


TRAIN = _fixture("incoming_noble_train_br143.html")


def test_trem_mesmo_segundo_ms_diferente():
    cmds = Extractor.incoming_commands(TRAIN)
    assert len(cmds) == 4, cmds
    assert {c["arrival_at"] for c in cmds} == {1795509538}
    assert [c["arrival_ms"] for c in cmds] == [237, 360, 460, 592]
    for c in cmds:
        assert c["watchtower"] == "detected" and c["size"] == "small"
        assert c["tower_noble"] is True
        assert c["origin"] == "Aldeia C"


def test_sem_ms_da_none():
    row = TRAIN.split("</tr>")[0] + "</tr>"
    row = row.replace(':<span class="grey small">237</span>', "")
    cmds = Extractor.incoming_commands(row)
    assert len(cmds) == 1 and cmds[0]["arrival_ms"] is None, cmds


def test_fixture_de_torre_pendente_segue_lido():
    cmds = Extractor.incoming_commands(_fixture("watchtower_mark_pending_br143.html"))
    assert cmds and all("arrival_ms" in c for c in cmds)


if __name__ == "__main__":
    test_trem_mesmo_segundo_ms_diferente()
    test_sem_ms_da_none()
    test_fixture_de_torre_pendente_segue_lido()
    print("ok")
