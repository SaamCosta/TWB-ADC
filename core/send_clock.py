"""
Relogio do envio cronometrado do Hunter (docs/backend.md §8.72).

O jogo carimba a chegada de um comando no instante em que PROCESSA o envio
final, com milissegundos, e soma a duracao da viagem (segundos inteiros). Ate
§8.72 o Hunter acordava no `send_time` e so entao fazia as tres requisicoes do
envio (GET da praca, POST de confirmacao, POST final): o comando nascia 1 a 3 s
depois do previsto, e a chegada junto.

Agora o envio e PRE-ARMADO: a praca e a confirmacao saem alguns segundos
antes, e so o POST final espera o instante certo. Dois numeros saem da propria
resposta da confirmacao, sem requisicao a mais:

- o deslocamento do relogio local para o do servidor, pelo `time_generated`
  (ms) do `game_data`, contra a hora local do meio da ida-e-volta;
- a latencia de ida, metade do `elapsed` da confirmacao.

Com eles, o POST final sai para o servidor processa-lo `AIM_SECONDS` depois do
inicio do segundo do `send_time` -- o meio da faixa em que a chegada ainda cai
no segundo pedido, com folga para os dois lados.

Funcoes puras: sem rede e sem relogio proprio, para o teste fixar os numeros.
"""

from core import game_data_shadow

# Onde, dentro do segundo do `send_time`, o servidor deve processar o envio
# final. A chegada pedida e `HH:MM:SS`; qualquer instante em [SS.000, SS.999]
# a cumpre. 0,4 s deixa 0,4 s de folga para cedo e 0,6 s para tarde -- tarde
# tem mais porque o servidor ainda processa o pedido depois de recebe-lo.
AIM_SECONDS = 0.4

# Deslocamento acima disto e relogio do Windows fora de sincronia, e vale
# aviso: o Hunter acorda pelo relogio local, entao um deslocamento maior que o
# pre-armado faz o envio sair atrasado.
WARN_OFFSET_SECONDS = 2.0


def time_generated(response):
    """`time_generated` (ms) do `game_data` de uma resposta, ou None."""
    text = getattr(response, "text", None)
    if text is None and isinstance(response, dict):
        gd = response.get("game_data")
        value = gd.get("time_generated") if isinstance(gd, dict) else None
    else:
        gd = game_data_shadow.extract_game_data(text) if text else None
        value = gd.get("time_generated") if gd else None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def elapsed_seconds(response):
    """Ida-e-volta da resposta (`requests` mede no `elapsed`), ou None."""
    elapsed = getattr(response, "elapsed", None)
    try:
        value = elapsed.total_seconds()
    except AttributeError:
        return None
    return value if value >= 0 else None


def server_offset(generated_ms, received_at, elapsed):
    """
    Relogio do servidor menos o local, em segundos, ou None.

    O servidor gera a pagina em algum ponto da ida-e-volta; o meio dela e a
    melhor estimativa, com erro de no maximo meia ida-e-volta.
    """
    if not generated_ms or received_at is None:
        return None
    return float(generated_ms) / 1000.0 - (float(received_at) - float(elapsed or 0) / 2.0)


def local_fire_time(send_time, offset, one_way, aim=AIM_SECONDS):
    """
    Instante LOCAL para soltar o POST final.

    `send_time` e epoch na hora do servidor (a chegada pedida menos a
    duracao). O servidor deve processar em `send_time + aim`; o pedido leva
    `one_way` para chegar la, e o relogio local esta `offset` atras do dele.
    """
    return float(send_time) + aim - float(offset or 0.0) - max(0.0, float(one_way or 0.0))
