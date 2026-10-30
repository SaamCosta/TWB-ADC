"""
"Este alvo ja e nosso?" -- uma resposta so, para todo caminho que manda
ataque (docs/backend.md §8.81).

O INCIDENTE (29-30/10/2026)
---------------------------
A 88755 virou nossa (BBM 067) as 00:37 de 29/10. As 01:42 o planejador
barbaro agendou contra ela um trem de 4 nobres, porque o dono que ele le vem
das fontes de MAPA -- `cache/villages/88755.json` era de 23/10 e dizia `owner
'0'`. O Hunter mandou o primeiro nobre as 01:50 sem reconferir nada (so o
caminho do nobre ATRASADO reconferia). Pousou as 11:47 de 30/10 contra a nossa
propria guarnicao de apoio: o nobre e os 2.264 da escolta morreram
(relatorio 227831832).

DUAS FAMILIAS DE FONTE, E A PRECEDENCIA E POR CAMPO (27o padrao)
-----------------------------------------------------------------
- Listas da CONTA: `config["villages"]` e a visao geral (`overview_villages`)
  que o ciclo le no inicio (`TWB.found_villages`) e a defesa propria le a cada
  ataque novo. So ficam ATRASADAS (aldeia recem-conquistada ainda fora), nunca
  dizem "nossa" de uma aldeia que nao e -- a perda de aldeia sai do config so
  confirmada (`TWB.confirm_lost_villages`).
- Fontes de MAPA: scan vivo, `map/village.txt` (TTL 6 h do nosso lado) e
  `cache/villages` (sem prazo). Medido em 30/10: 60 entradas de
  `cache/villages` diziam barbara para aldeia que o village.txt dava como de
  jogador, ZERO no sentido inverso, mediana de 60 dias de idade. Na 88755 o
  arquivo ainda era o de 23/10 uma hora depois da conquista.

Para a pergunta "e nossa?", UM "sim" de uma lista da conta vence qualquer
"barbara" de fonte de mapa. A recíproca nao vale: ausencia nas listas da conta
nao prova nada (atraso), e e por isso que o fallback de mapa continua em
`ConquestManager._target_is_mine`.

O REGISTRO
----------
Em memoria, do processo: cada fonte guarda a ULTIMA lista lida (substitui a
anterior, entao aldeia perdida sai na leitura seguinte). Nao vai a disco: num
processo novo, a visao geral do ciclo roda antes do Hunter.

`stale()` usa o `player.villages` que o `game_data` de TODA resposta traz
(`core/account_pulse.py`): se o jogo diz que a conta tem mais aldeias do que a
lista mais nova, alguma aldeia nossa ainda nao esta em lista nenhuma -- e o
Hunter rele a visao geral antes de mandar ataque (1 GET, so nesse caso).
"""
import threading
import time

SOURCE_CONFIG = "config.json"
SOURCE_CYCLE = "visao geral do ciclo"
SOURCE_DEFENSE = "visao geral da defesa"
SOURCE_HUNTER = "visao geral do Hunter"
# `fail_reason` do comando que o Hunter cancelou por isto; a promocao do trem
# (`BarbarianTrainPlanner._promote_scheduled_trains`) le o mesmo valor.
FAIL_REASON = "target_is_ours"


class OwnVillages:
    def __init__(self, clock=time.time):
        self.clock = clock
        # {fonte: (frozenset de ids, instante da leitura)}
        self._lists = {}
        self._lock = threading.Lock()

    def note(self, source, ids, at=None):
        """
        Guarda a lista lida por `source`. Lista vazia NAO entra: resposta 200
        que nao e a tela (login, captcha) devolve [] e significaria "nenhuma
        aldeia" -- a mesma armadilha da guarda de `TWB.purge_refusal_reason`.
        """
        ids = frozenset(str(v) for v in (ids or []) if v is not None)
        if not ids:
            return False
        with self._lock:
            self._lists[source] = (ids, self.clock() if at is None else float(at))
        return True

    def newest(self):
        """(fonte, ids, instante) da lista mais nova, ou None."""
        with self._lock:
            if not self._lists:
                return None
            source, (ids, at) = max(self._lists.items(), key=lambda item: item[1][1])
            return source, ids, at

    def owner_source(self, target_id, config=None):
        """Nome da fonte que diz que `target_id` e nosso, ou None."""
        vid = str(target_id)
        if vid in ((config or {}).get("villages") or {}):
            return SOURCE_CONFIG
        with self._lock:
            ordered = sorted(self._lists.items(), key=lambda item: -item[1][1])
        for source, (ids, _at) in ordered:
            if vid in ids:
                return source
        return None

    def ids(self, config=None):
        """Todo id que alguma lista da conta (ou o config) da como nosso."""
        with self._lock:
            out = set().union(*(ids for ids, _at in self._lists.values()))
        return out | {str(v) for v in ((config or {}).get("villages") or {})}

    def stale(self, expected, config=None):
        """
        True quando o jogo diz que a conta tem MAIS aldeias (`expected`, o
        `player.villages`) do que a lista mais nova conhece. Sem lista, compara
        com o config. `expected` ilegivel nao e "esta tudo certo" nem "esta
        velho": devolve False e ninguem vai a rede por causa dele.
        """
        try:
            expected = int(expected)
        except (TypeError, ValueError):
            return False
        newest = self.newest()
        known = len(newest[1]) if newest else len((config or {}).get("villages") or {})
        return expected > known



REGISTRY = OwnVillages()


def own_target_reason(target_id, config=None, registry=None):
    """
    "o alvo ja e nosso (<fonte>)" quando alguma lista da conta tem o alvo,
    senao None. So memoria: cabe no segundo exato antes de um envio.
    """
    source = (registry or REGISTRY).owner_source(target_id, config)
    if source is None:
        return None
    return "o alvo ja e nosso (%s)" % source
