"""
Teste da guarda contra a limpeza destrutiva de aldeias (TWB.purge_refusal_reason).

O incidente, em campo, 2026-08-22 as 08:26: o bot subiu com a sessao expirada
("Current session cache not valid"), pediu o cookie do navegador, e a
requisicao seguinte a screen=overview_villages voltou 200 -- mas com a landing
page do portal, nao com a tela do jogo. `Extractor.village_ids_from_overview`
nao casou nada e devolveu [], `OverviewPage` nao levantou excecao nenhuma
(do ponto de vista dele o HTTP deu certo), e a limpeza logo abaixo concluiu
que as 11 aldeias tinham sido perdidas:

    Removed stale managed cache for lost village 38409
    ...
    Removed lost village 41123 from config

Todo o cache/managed foi apagado e o config.json ficou com zero aldeias. So
nao foi perda definitiva porque a copia config.bak e feita na linha logo antes
do pop().

E o segundo padrao do CLAUDE.md (parse que devolve vazio em silencio numa
resposta 200 que nao e a tela esperada) com o maior raio de destruicao do
projeto: nenhum outro consumidor de parse vazio APAGA configuracao.

O fato do jogo que sustenta a guarda: uma conta ativa sempre tem pelo menos
uma aldeia. Se voce perde a ultima, e eliminado e nao ha bot para rodar.
Portanto "zero aldeias lidas" com aldeias conhecidas no config e sempre falha
de leitura, nunca um fato sobre o mundo.

Rodar: python tests/test_village_purge_guard.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from twb import TWB

# As 11 aldeias reais do config no momento do incidente.
CONFIG_11 = {
    v: {} for v in [
        "41123", "38409", "44683", "39292", "38997",
        "41283", "40314", "41114", "39975", "74689", "74690",
    ]
}


def _check(label, got, expected):
    assert got == expected, f"{label}: esperado {expected!r}, veio {got!r}"
    print(f"  ok  {label}: {got!r}")


def _recusa(label, found, config_villages):
    reason = TWB.purge_refusal_reason(found, config_villages)
    assert reason, f"{label}: esperava recusa, veio None"
    print(f"  ok  {label} -> recusado: {reason[:70]}...")


def _permite(label, found, config_villages):
    reason = TWB.purge_refusal_reason(found, config_villages)
    assert reason is None, f"{label}: esperava permitir, veio {reason!r}"
    print(f"  ok  {label} -> permitido")


def test_o_incidente_exato():
    """Lista vazia com 11 aldeias no config -- o caso que apagou tudo."""
    print("test_o_incidente_exato")
    _recusa("[] com 11 no config", [], CONFIG_11)
    _recusa("None com 11 no config", None, CONFIG_11)


def test_leitura_de_outra_tela():
    """
    Leu aldeias, mas nenhuma conhecida. Id de aldeia nao muda, entao isto e
    outra conta ou outra tela -- nao 11 perdas simultaneas.
    """
    print("test_leitura_de_outra_tela")
    _recusa("ids totalmente diferentes", ["99991", "99992"], CONFIG_11)


def test_perda_real_continua_funcionando():
    """
    A guarda nao pode engessar o caso legitimo: perder uma ou algumas aldeias
    e normal em PvP, e a limpeza tem que rodar.
    """
    print("test_perda_real_continua_funcionando")
    sobraram = [v for v in CONFIG_11 if v != "41123"]
    _permite("perdeu 1 de 11", sobraram, CONFIG_11)

    _permite("perdeu 10 de 11, sobrou 1 conhecida", ["41114"], CONFIG_11)
    # O caso acima e o limite: sobrou UMA conhecida, entao a leitura e
    # plausivel e a limpeza roda. E deliberado -- a guarda protege contra
    # "nao li nada", nao contra "li pouco".


def test_config_vazio_nao_recusa():
    """Sem aldeia no config nao ha o que limpar; nao e caso de recusa."""
    print("test_config_vazio_nao_recusa")
    _permite("config vazio, nada encontrado", [], {})
    _permite("config vazio, aldeias encontradas", ["41114"], {})
    _permite("config None", ["41114"], None)


def test_aldeia_nova_nao_atrapalha():
    """Aldeia recem-conquistada aparece na leitura e nao no config -- ok."""
    print("test_aldeia_nova_nao_atrapalha")
    com_nova = list(CONFIG_11) + ["80001"]
    _permite("11 conhecidas + 1 nova", com_nova, CONFIG_11)


if __name__ == "__main__":
    test_o_incidente_exato()
    test_leitura_de_outra_tela()
    test_perda_real_continua_funcionando()
    test_config_vazio_nao_recusa()
    test_aldeia_nova_nao_atrapalha()
    print("\nOK - todos os testes da guarda de limpeza passaram")
