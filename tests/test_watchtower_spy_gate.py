"""
templates/troops/watchtower_support.txt -- o estagio que produz espiao nao pode
estar gateado no requisito da cavalaria pesada.

Motivo de existir (P-TMPL-SCOUT, docs/backend.md 8.12): o primeiro estagio que
constroi alguma coisa nesse template estava em `smith:15`. O 15 e o requisito do
Explorador? Nao -- e o da cavalaria pesada, herdado da versao anterior do
arquivo. Medido na captura real da tela do ferreiro (cache/_smith_br143.html):
com Ferreiro nivel 7 o Explorador ja aparece "Pesquisado", enquanto a Cavalaria
pesada aparece "Requisitos em falta: Ferreiro (15)". Logo o requisito do espiao
e <= 7 e o 15 nao tem nada a ver com ele.

Por que o estrago e silencioso: get_template_action() percorre os estagios em
ordem e devolve `last` no PRIMEIRO estagio cujo nivel exigido nao foi atingido.
Nao pula estagio. Entao uma aldeia com ferreiro abaixo de 15 para no estagio 0
(`stable:1`, `build: {}`), pede zero unidade, e o log nao registra erro nenhum:
a torre simplesmente nunca constroi espiao. Foi o que aconteceu com a BBM 030
(52755, conquistada em 2026-09-19): ferreiro 9, estabulo 5, watchtower 0,
**0 espioes** contra ~2.600 nas outras duas aldeias de torre, que passaram do
estagio quando o ferreiro delas ja era alto.

Os niveis de edificio usados aqui sao os reais das tres aldeias de torre, lidos
de cache/managed/{vid}.json em 2026-09-22. Ficam chumbados no teste de
proposito: o cache e estado de runtime e nao pode ser premissa de teste, mas o
caso que motivou o bug precisa continuar sendo exercitado depois de a aldeia
crescer e deixar de sofrer dele.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game.troopmanager import TroopManager

TEMPLATE = "templates/troops/watchtower_support.txt"

# cache/managed/{38409,38412,52755}.json, chave "buidling_levels" (o typo e do
# codigo), lidos em 2026-09-22.
ALDEIAS_DE_TORRE = {
    "38409 BBM 002": {"stable": 20, "smith": 20, "watchtower": 10, "barracks": 5},
    "38412 BBM 023": {"stable": 12, "smith": 20, "watchtower": 0, "barracks": 17},
    "52755 BBM 030": {"stable": 5, "smith": 9, "watchtower": 0, "barracks": 9},
}


def _carrega(caminho=TEMPLATE):
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(raiz, caminho), encoding="utf-8") as arquivo:
        return json.load(arquivo)


class _Fake:
    """
    O minimo que get_template_action() toca: `self.template` e a escrita em
    `self.wanted_levels`. Construir um TroopManager de verdade exigiria wrapper
    HTTP, e o metodo nao usa nada disso.
    """

    def __init__(self, template):
        self.template = template
        self.wanted_levels = {}


def _estagio_escolhido(levels, template=None):
    fake = _Fake(template if template is not None else _carrega())
    return TroopManager.get_template_action(fake, levels)


def _espioes_pedidos(estagio):
    if not estagio:
        return 0
    return (estagio.get("build") or {}).get("stable", {}).get("spy", 0)


def test_as_tres_aldeias_de_torre_pedem_espiao():
    """
    O caso central. A BBM 030 e a unica que mudou de comportamento, mas as
    outras duas entram para provar que a correcao nao rebaixou ninguem: quem ja
    alcancava um estagio alto continua alcancando.
    """
    esperado_minimo = {
        "38409 BBM 002": 1500,  # watchtower 10
        "38412 BBM 023": 440,   # watchtower 0, estabulo 12
        "52755 BBM 030": 440,   # o caso que estava em zero
    }
    for nome, levels in ALDEIAS_DE_TORRE.items():
        pedido = _espioes_pedidos(_estagio_escolhido(levels))
        assert pedido >= esperado_minimo[nome], (
            f"{nome}: template pediu {pedido} espioes, esperado >= "
            f"{esperado_minimo[nome]}"
        )


def test_o_gate_antigo_deixava_a_bbm_030_em_zero():
    """
    A guarda contra o bug voltar. Roda o template ANTIGO (o unico diff e
    `smith:15` no lugar de `stable:3`) contra os mesmos niveis reais e exige que
    ele devolva o estagio vazio -- ou seja, que o sintoma medido em campo seja
    reproduzivel a partir do arquivo, e nao uma teoria sobre ele.

    Sem este teste, o outro sozinho passaria tambem com o template quebrado se
    alguem por acaso subisse o ferreiro da aldeia: a asercao viraria verdadeira
    pelo motivo errado.
    """
    antigo = _carrega()
    alvo = [e for e in antigo if e.get("build")][0]
    alvo["building"], alvo["level"] = "smith", 15

    estagio = _estagio_escolhido(ALDEIAS_DE_TORRE["52755 BBM 030"], template=antigo)
    assert _espioes_pedidos(estagio) == 0, (
        "o template antigo deveria deixar a BBM 030 sem pedir espiao; se isto "
        "falhou, get_template_action() mudou de semantica e o diagnostico do "
        "P-TMPL-SCOUT precisa ser relido"
    )
    assert estagio == antigo[0], (
        "com smith:15 a aldeia deveria parar no estagio 0 (stable:1, build "
        f"vazio), e parou em {estagio}"
    )


def test_o_estagio_de_espiao_nao_depende_do_ferreiro():
    """
    A regra, escrita como propriedade em vez de como valor. O ferreiro aparece
    neste template so por heranca; qualquer estagio que construa espiao gateado
    em `smith` e o bug de volta, com outro numero.
    """
    for estagio in _carrega():
        if _espioes_pedidos(estagio):
            assert estagio["building"] != "smith", (
                f"estagio {estagio} volta a gatear espiao no ferreiro"
            )


def test_os_estagios_estao_em_ordem_nao_decrescente_de_espiao():
    """
    get_template_action() nao pula estagio, entao a ordem do arquivo E a
    progressao. Um estagio que peca menos espiao que o anterior significaria
    que crescer um edificio REDUZ a tropa pedida -- sempre erro de edicao.
    """
    anterior = 0
    for estagio in _carrega():
        pedido = _espioes_pedidos(estagio)
        if pedido:
            assert pedido >= anterior, (
                f"estagio {estagio.get('building')}:{estagio.get('level')} pede "
                f"{pedido} espioes depois de um estagio que pedia {anterior}"
            )
            anterior = pedido


if __name__ == "__main__":
    for nome, fn in sorted(list(globals().items())):
        if nome.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {nome}")
    print("\ntodos os testes passaram")
