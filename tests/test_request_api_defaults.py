"""
Testes dos argumentos default de WebWrapper (core/request.py).

Fecham o bug do token `h` velho: `get_api_action` tinha `data={}` como
default E escrevia dentro dele (`data['h'] = self.last_h`). Como default
mutavel e avaliado uma unica vez, o token da PRIMEIRA chamada ficava gravado
no proprio default e era reenviado em todas as seguintes -- pelo resto da
vida do processo, que roda por dias. Primeiro padrao recorrente do CLAUDE.md,
num argumento em vez de num atributo de classe.

Nao usa rede: `post_url`/`get_url` sao substituidos por um gravador de
chamadas, e a instancia e criada com __new__ para nao passar por __init__
(que abre uma requests.session e um ReporterObject).

Rodar: python tests/test_request_api_defaults.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.request import WebWrapper


class _FakeResponse:
    status_code = 200

    def json(self):
        return {"response": True}


def _wrapper():
    """
    WebWrapper sem __init__: so os atributos que os metodos de API tocam.
    `headers` ja existe como atributo de classe.
    """
    w = WebWrapper.__new__(WebWrapper)
    w.endpoint = "https://br143.tribalwars.com.br/game.php"
    w.last_h = None
    w.enviados = []

    def post_url(url, data, headers=None):
        w.enviados.append({"url": url, "data": data})
        return _FakeResponse()

    def get_url(url, headers=None):
        w.enviados.append({"url": url, "data": None})
        return _FakeResponse()

    w.post_url = post_url
    w.get_url = get_url
    return w


def test_token_h_novo_a_cada_chamada_sem_data():
    """
    O caso real: Village.get_quests() chama sem `data`. Com o default mutavel,
    a segunda missao do processo ia com o token da primeira.
    """
    w = _wrapper()

    w.last_h = "tokenA"
    w.get_api_action(village_id="41123", action="quest_complete",
                     params={"quest": "1", "skip": "false"})
    w.last_h = "tokenB"
    w.get_api_action(village_id="41123", action="quest_complete",
                     params={"quest": "2", "skip": "false"})

    assert [e["data"]["h"] for e in w.enviados] == ["tokenA", "tokenB"]


def test_default_nao_guarda_estado_entre_instancias():
    """
    Duas instancias diferentes nao podem compartilhar o default -- era esse o
    mecanismo do vazamento, so que entre chamadas da mesma funcao.
    """
    primeira = _wrapper()
    primeira.last_h = "tokenA"
    primeira.get_api_action(village_id="1", action="quest_complete")

    segunda = _wrapper()
    segunda.last_h = "tokenB"
    segunda.get_api_action(village_id="1", action="quest_complete")

    assert segunda.enviados[0]["data"]["h"] == "tokenB"


def test_h_explicito_do_chamador_continua_vencendo():
    """Os outros 11 chamadores passam `data`; o comportamento deles nao muda."""
    w = _wrapper()
    w.last_h = "token_do_wrapper"
    w.get_api_action(village_id="1", action="quest_complete",
                     data={"h": "token_do_chamador", "x": "1"})
    assert w.enviados[0]["data"] == {"h": "token_do_chamador", "x": "1"}


def test_nao_escreve_no_dicionario_de_quem_chamou():
    """
    Antes, `data['h'] = ...` sujava o dict do chamador. Um chamador que
    reaproveitasse o mesmo dict entre iteracoes herdaria o token velho pela
    mesma mecanica, mesmo sem tocar no default.
    """
    w = _wrapper()
    w.last_h = "tokenA"
    do_chamador = {"reward_id": "7"}
    w.get_api_action(village_id="1", action="claim_reward", data=do_chamador)
    assert do_chamador == {"reward_id": "7"}, "o dict do chamador foi mutado"
    assert w.enviados[0]["data"]["h"] == "tokenA"


def test_post_api_data_tem_as_mesmas_garantias():
    """Mesma assinatura, mesma escrita de `h` -- e o unico chamador
    (Village.get_quest_rewards) passa um dict novo a cada recompensa."""
    w = _wrapper()
    w.last_h = "tokenA"
    w.post_api_data(village_id="1", action="claim_reward")
    w.last_h = "tokenB"
    w.post_api_data(village_id="1", action="claim_reward")
    assert [e["data"]["h"] for e in w.enviados] == ["tokenA", "tokenB"]


def test_params_omitido_nao_quebra_a_url():
    """`params` virou None; `req.update(params or {})` tem que aguentar."""
    w = _wrapper()
    w.last_h = "tokenA"
    w.get_api_action(village_id="41123", action="quest_complete")
    w.get_api_data(village_id="41123", action="get_inventory")
    w.post_api_data(village_id="41123", action="claim_reward")
    for enviado in w.enviados:
        assert "village=41123" in enviado["url"]
        assert "screen=api" in enviado["url"]


def test_params_do_chamador_nao_e_mutado():
    w = _wrapper()
    w.last_h = "tokenA"
    do_chamador = {"screen": "inventory"}
    w.get_api_data(village_id="1", action="get_inventory", params=do_chamador)
    assert do_chamador == {"screen": "inventory"}
    assert "screen=inventory" in w.enviados[0]["url"]


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
