"""
Testes de ConquestManager._target_taken_by_other().

Cenario: o bot escolhe uma barbara e manda um trem de 4 nobres (~4h de voo).
Nesse meio tempo OUTRO jogador conquista a aldeia. A partir dai a lealdade que
o nosso relatorio registrou virou numero morto -- a do novo dono reiniciou em
25 e sobe do zero -- e continuar mandando nobre deixaria de ser limpeza de
barbaro para virar conquista de aldeia de jogador, sem passar pelo
PvpConquestManager. O alvo tem que ser encerrado.

Usa ids de aldeia ficticios (prefixo 999999) para nao colidir com o cache real
do bot, que pode estar rodando.

Rodar: python tests/test_conquest_target_lost.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.filemanager import FileManager
from game.attack import ConquestManager

NOSSA = "99999900"      # aldeia gerenciada ficticia, dona = jogador 12345
ALVO = "99999901"


def _grava_aldeia(vid, owner):
    FileManager.save_json_file(
        {"id": vid, "owner": owner, "points": 443, "location": [571, 308]},
        "cache/villages/%s.json" % vid,
    )


def _limpa(*vids):
    for vid in vids:
        FileManager.remove_file("cache/villages/%s.json" % vid)


def _manager():
    return ConquestManager(
        wrapper=None, village_id=NOSSA, troopmanager=None,
        map_obj=None, config={},
    )


def test_alvo_ainda_barbaro_nao_encerra():
    _grava_aldeia(NOSSA, "12345")
    _grava_aldeia(ALVO, "0")
    try:
        assert _manager()._target_taken_by_other(ALVO) is None
    finally:
        _limpa(NOSSA, ALVO)


def test_alvo_conquistado_por_outro_devolve_o_dono():
    """O caso que motivou a mudanca."""
    _grava_aldeia(NOSSA, "12345")
    _grava_aldeia(ALVO, "67890")
    try:
        assert _manager()._target_taken_by_other(ALVO) == "67890"
    finally:
        _limpa(NOSSA, ALVO)


def test_alvo_conquistado_por_nos_nao_conta_como_perdido():
    """Quem trata esse caso e _target_is_mine, com o log de conquista."""
    _grava_aldeia(NOSSA, "12345")
    _grava_aldeia(ALVO, "12345")
    try:
        assert _manager()._target_taken_by_other(ALVO) is None
    finally:
        _limpa(NOSSA, ALVO)


def test_sem_dado_do_alvo_nao_encerra():
    """
    Ausencia de informacao nunca encerra alvo: cache/villages so e alimentado
    pelo scan de mapa, e um alvo fora da regiao varrida neste ciclo nao tem
    arquivo. Concluir "perdido" ai jogaria fora uma conquista boa.
    """
    _grava_aldeia(NOSSA, "12345")
    _limpa(ALVO)
    try:
        assert _manager()._target_taken_by_other(ALVO) is None
    finally:
        _limpa(NOSSA)


def test_sem_dado_da_nossa_aldeia_ainda_detecta_terceiro():
    """
    Sem saber quem somos nao da para distinguir "nossa" de "de outro", mas o
    alvo tem dono != 0 e nao e barbaro. Encerrar e o lado seguro: no maximo
    perdemos o rastreio de uma conquista que foi nossa, e nesse caso a aldeia
    entra pelo add_new_villages.
    """
    _limpa(NOSSA)
    _grava_aldeia(ALVO, "67890")
    try:
        assert _manager()._target_taken_by_other(ALVO) == "67890"
    finally:
        _limpa(ALVO)


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
