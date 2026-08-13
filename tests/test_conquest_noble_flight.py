"""
Testes da trava de nobre em voo (ConquestCache.nobles_in_flight).

Logica pura, sem rede e sem I/O: recebe o dict do cache e devolve as chegadas
ainda no futuro. Os timestamps abaixo sao os reais do incidente da Barbara
#40314 em 2026-08-12, lidos de cache/reports e cache/logs -- a ideia e que o
teste falhe se alguem reintroduzir o comportamento que custou 527 tropas.

Rodar: python -m pytest tests/ -q     (ou: python tests/test_conquest_noble_flight.py)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game.attack import ConquestCache


# --- Linha do tempo real do incidente (unix, br143) ---------------------
TREM_1_ENVIO = 1786546551      # 11:55:51 -- 4 nobres saem
TREM_1_POUSOS = [1786559836, 1786559886, 1786559937, 1786559980]  # 15:37-15:39
AVALIACAO_1813 = 1786569231    # 18:13:51 -- bot reavalia, trem 1 ja pousou
TREM_2_POUSOS = [1786588123, 1786588164, 1786588204, 1786588252]  # 23:28-23:30
AVALIACAO_2018 = 1786580332    # 20:18:52 -- o momento que mandou o nobre extra


def test_sem_registro_nao_trava():
    """Arquivos de cache antigos (sem o campo) nao podem travar o alvo."""
    assert ConquestCache.nobles_in_flight({}, now=AVALIACAO_2018) == []
    assert ConquestCache.nobles_in_flight(None, now=AVALIACAO_2018) == []
    assert ConquestCache.nobles_in_flight(
        {"status": "train_sent", "hits_done": 4}, now=AVALIACAO_2018
    ) == []


def test_nobres_ja_pousados_liberam_o_alvo():
    """As 18:13 os 4 nobres do trem 1 ja tinham pousado: nada em voo."""
    data = {"noble_arrivals": TREM_1_POUSOS}
    assert ConquestCache.nobles_in_flight(data, now=AVALIACAO_1813) == []


def test_o_envio_do_nobre_extra_seria_bloqueado():
    """
    O caso que importa. As 20:18:52 havia 4 nobres do trem 2 no ar, com pouso
    as 23:28. O bot mandou um nobre extra assim mesmo, que chegou as 00:00:59
    numa aldeia ja nossa: autoconquista + 421 defensores e 106 atacantes
    mortos, todos nossos. Com a trava, esse envio nao acontece.
    """
    data = {"noble_arrivals": TREM_2_POUSOS}
    em_voo = ConquestCache.nobles_in_flight(data, now=AVALIACAO_2018)
    assert len(em_voo) == 4
    assert em_voo[0] == 1786588123  # ordenado: o proximo pouso vem primeiro


def test_status_errado_nao_destrava():
    """
    A propriedade central: a trava ignora `status`. No incidente o registro
    dizia "complete" com nobre no ar -- era o status que estava mentindo, e
    era nele que a logica antiga confiava.
    """
    data = {"status": "complete", "noble_arrivals": TREM_2_POUSOS}
    assert len(ConquestCache.nobles_in_flight(data, now=AVALIACAO_2018)) == 4


def test_eta_desconhecido_trava_indefinidamente():
    """
    Extractor.attack_duration() devolve 0 quando o regex nao casa, entao a
    chegada e gravada como null. Somar 0 ao envio faria o nobre nascer "ja
    pousado" -- o estado exato do incidente. Tem que travar, nao liberar.
    """
    data = {"noble_arrivals": [None]}
    em_voo = ConquestCache.nobles_in_flight(data, now=AVALIACAO_2018)
    assert em_voo == [float("inf")]
    # e continua travado num futuro distante
    assert ConquestCache.nobles_in_flight(data, now=AVALIACAO_2018 + 10**7) == [float("inf")]


def test_mistura_de_pousados_e_em_voo():
    """Trem parcial: so os que ainda nao pousaram contam."""
    data = {"noble_arrivals": TREM_1_POUSOS + TREM_2_POUSOS}
    em_voo = ConquestCache.nobles_in_flight(data, now=AVALIACAO_2018)
    assert em_voo == TREM_2_POUSOS


if __name__ == "__main__":
    falhas = 0
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok   %s" % nome)
            except AssertionError as exc:
                falhas += 1
                print("FALHA %s: %s" % (nome, exc))
    sys.exit(1 if falhas else 0)
