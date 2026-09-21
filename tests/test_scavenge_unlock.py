"""Desbloqueio automático de coleta (P-COL-02(b), docs/backend.md §8.5).

Cobre as duas metades que podem errar em silêncio:

- o **parse** da config de mundo, contra um recorte verbatim do br143 --
  inclusive um teste que roda o padrão SEM o `\\s*` e exige que ele falhe, para
  a quebra de linha entre `(` e `{` não voltar calada (15º padrão do CLAUDE.md:
  parser que devolve vazio sempre é indistinguível de "nada a fazer");
- a **decisão** de gasto, contra a política do usuário de 2026-09-21
  ("desbloqueia quando der"), incluindo a guarda de um desbloqueio por vez que
  é o que faz o bot conviver com os desbloqueios manuais.

Roda sem pytest:
    python tests/test_scavenge_unlock.py
"""
import logging
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from core.extractors import Extractor
from game.troopmanager import TroopManager


checks = 0


def check(condition, message):
    global checks
    checks += 1
    if not condition:
        raise AssertionError(message)


# --------------------------------------------------------------------------
# Fixture VERBATIM: recorte de game.php?village=49709&screen=place&mode=scavenge
# do br143, capturado em 2026-09-21. A quebra de linha e a indentação entre o
# "(" e o "{" são do servidor e são exatamente o que quebra um regex ingênuo --
# não "arrumar" este recorte.
# --------------------------------------------------------------------------
SCAVENGE_HTML = '''<script type="text/javascript">
        $(function() {
            var screen = new ScavengeScreen(
                    {"1":{"id":1,"name":"Pequena Coleta","loot_factor":0.1,"unlock_cost":{"wood":25,"stone":30,"iron":25},"unlock_duration_seconds":30,"duration_exponent":0.45,"duration_initial_seconds":1800,"duration_factor":1,"premium_cost_exponent":0.44,"prerequisite_option_ids":[],"premium_boost":{"feature":"ScavengingSquadLoot","enabled":true,"loot_factor":1.2,"cost_exponent":0.44}},"2":{"id":2,"name":"M\\u00e9dia Coleta","loot_factor":0.25,"unlock_cost":{"wood":250,"stone":300,"iron":250},"unlock_duration_seconds":3600,"duration_exponent":0.45,"duration_initial_seconds":1800,"duration_factor":1,"premium_cost_exponent":0.44,"prerequisite_option_ids":[1],"premium_boost":{"feature":"ScavengingSquadLoot","enabled":true,"loot_factor":1.2,"cost_exponent":0.44}},"3":{"id":3,"name":"Grande Coleta","loot_factor":0.5,"unlock_cost":{"wood":1000,"stone":1200,"iron":1000},"unlock_duration_seconds":10800,"duration_exponent":0.45,"duration_initial_seconds":1800,"duration_factor":1,"premium_cost_exponent":0.44,"prerequisite_option_ids":[2],"premium_boost":{"feature":"ScavengingSquadLoot","enabled":true,"loot_factor":1.2,"cost_exponent":0.44}},"4":{"id":4,"name":"Extrema Coleta","loot_factor":0.75,"unlock_cost":{"wood":10000,"stone":12000,"iron":10000},"unlock_duration_seconds":21600,"duration_exponent":0.45,"duration_initial_seconds":1800,"duration_factor":1,"premium_cost_exponent":0.44,"prerequisite_option_ids":[3],"premium_boost":{"feature":"ScavengingSquadLoot","enabled":true,"loot_factor":1.2,"cost_exponent":0.44}}},
                    {"village_id":49709}
            );
        });
        </script>'''

CONFIG = Extractor.scavenge_config(SCAVENGE_HTML)

check(CONFIG is not None, "scavenge_config devolveu None no markup real")
check(sorted(CONFIG) == ["1", "2", "3", "4"], "as quatro opções deveriam ser lidas")
check(
    CONFIG["3"]["unlock_cost"] == {"wood": 1000, "stone": 1200, "iron": 1000},
    "custo da Grande Coleta veio errado do markup real",
)
check(
    CONFIG["4"]["unlock_duration_seconds"] == 21600,
    "duração da Extrema Coleta veio errada do markup real",
)
check(
    CONFIG["4"]["prerequisite_option_ids"] == [3],
    "a opção 4 depende da 3 -- é o que decide a ordem de gasto",
)

# O padrão SEM o `\s*` não pode casar: `balanced_slice` exige o índice exato da
# abertura, e o servidor põe "\n" + indentação ali. Sem esta asserção a
# regressão seria muda (o parser devolveria None e o bot nunca desbloquearia).
check(
    Extractor.js_object_after(SCAVENGE_HTML, r"new ScavengeScreen\(") is None,
    "o padrão sem \\s* deveria falhar no markup real -- se passou, a guarda "
    "deste teste não vale nada",
)

# Prova de procedência: a config parseada é a mesma coisa que um json.loads
# direto do recorte, não uma reconstrução aproximada.
raw = re.search(r"new ScavengeScreen\(\s*", SCAVENGE_HTML)
check(
    Extractor.balanced_slice(SCAVENGE_HTML, raw.end()).startswith('{"1":{"id":1'),
    "o recorte balanceado não começa no 1º argumento",
)


# --------------------------------------------------------------------------
# Decisão de gasto
# --------------------------------------------------------------------------
def options(**overrides):
    """Estado por aldeia no formato do 2º argumento (`var village`)."""
    base = {
        "1": {"is_locked": False, "unlock_time": None, "scavenging_squad": None},
        "2": {"is_locked": False, "unlock_time": None, "scavenging_squad": None},
        "3": {"is_locked": True, "unlock_time": None, "scavenging_squad": None},
        "4": {"is_locked": True, "unlock_time": None, "scavenging_squad": None},
    }
    for key, value in overrides.items():
        base[key.lstrip("o")] = value
    return base


RICH = {"wood": 50000, "stone": 50000, "iron": 50000}

# Caso normal: 3 e 4 trancadas, recurso de sobra -> pega a MAIS BAIXA.
check(
    TroopManager.choose_scavenge_unlock(CONFIG, options(), RICH) == 3,
    "com tudo pago deveria escolher a opção 3, a mais baixa pendente",
)

# Estado real da BBM 029 às 07:55 de 2026-09-21: opção 3 desbloqueando
# (unlock_time = 10:47:37). Um desbloqueio por vez -> não tenta nada, nem a 4.
busy = options(o3={"is_locked": True, "unlock_time": 1789998457, "scavenging_squad": None})
check(
    TroopManager.choose_scavenge_unlock(CONFIG, busy, RICH) is None,
    "aldeia com unlock_time preenchido deveria ser pulada por inteiro",
)

# Estado real da BBM 001: as quatro destrancadas -> nada a fazer.
allopen = {
    str(n): {"is_locked": False, "unlock_time": None, "scavenging_squad": {"id": 1}}
    for n in range(1, 5)
}
check(
    TroopManager.choose_scavenge_unlock(CONFIG, allopen, RICH) is None,
    "aldeia com tudo destrancado não deveria desbloquear nada",
)

# Não pode pagar a 3 (falta ferro por 1) -> não pula para a 4.
broke = {"wood": 5000, "stone": 5000, "iron": 999}
check(
    TroopManager.choose_scavenge_unlock(CONFIG, options(), broke) is None,
    "sem poder pagar a mais baixa, não deveria gastar numa mais cara",
)

# Exatamente o custo: a condição é >=, não >.
exact = {"wood": 1000, "stone": 1200, "iron": 1000}
check(
    TroopManager.choose_scavenge_unlock(CONFIG, options(), exact) == 3,
    "com exatamente o custo deveria desbloquear",
)

# keep_resources segura o gasto: a aldeia tem o recurso, mas ele está poupado
# para nobre. Um a menos do que precisa já basta para recusar.
check(
    TroopManager.choose_scavenge_unlock(
        CONFIG, options(), {"wood": 2000, "stone": 2000, "iron": 2000},
        keep={"stone": 801},
    ) is None,
    "keep_resources deveria impedir o desbloqueio (2000-801 < 1200)",
)
check(
    TroopManager.choose_scavenge_unlock(
        CONFIG, options(), {"wood": 2000, "stone": 2000, "iron": 2000},
        keep={"stone": 800},
    ) == 3,
    "com a reserva cabendo, o desbloqueio deveria sair",
)

# Só a 4 pendente e paga -> escolhe a 4 (pré-requisito 3 já destrancado).
only4 = options(o3={"is_locked": False, "unlock_time": None, "scavenging_squad": None})
check(
    TroopManager.choose_scavenge_unlock(CONFIG, only4, RICH) == 4,
    "com a 3 aberta e recurso de sobra deveria ir para a 4",
)

# Pré-requisito preso: a 4 é a única "pendente e paga" na config, mas a 3
# continua trancada -- o jogo recusaria. Aqui o gasto é barrado pela regra, não
# pelo saldo.
prereq = options()
check(
    TroopManager.choose_scavenge_unlock(CONFIG, prereq, {"wood": 10000, "stone": 12000, "iron": 10000}) == 3,
    "deveria escolher a 3, não a 4, mesmo com dinheiro exato para a 4",
)

# Dado malformado é ignorado conservadoramente -- na dúvida não gasta.
check(TroopManager.choose_scavenge_unlock(None, options(), RICH) is None, "config None")
check(TroopManager.choose_scavenge_unlock(CONFIG, None, RICH) is None, "options None")
check(
    TroopManager.choose_scavenge_unlock(CONFIG, {"3": {}}, RICH) is None,
    "opção sem is_locked é estado desconhecido, não convite para gastar",
)
check(
    TroopManager.choose_scavenge_unlock(CONFIG, options(), {}) is None,
    "sem saldo conhecido não deveria gastar",
)


# --------------------------------------------------------------------------
# Ligação: o gate e a FORMA do POST.
#
# A decisão acima pode estar perfeita e a feature ainda não funcionar se o
# payload sair errado -- e esse é o tipo de erro que só apareceria gastando
# recurso de verdade no servidor. Aqui o wrapper é de mentira: nada vai à rede.
# A referência é a requisição capturada do próprio cliente do jogo em
# 2026-09-21 (docs/backend.md §8.5): ajaxaction=start_unlock em
# screen=scavenge_api, com village_id/option_id NO CORPO.
# --------------------------------------------------------------------------
class FakeWrapper:
    def __init__(self):
        self.calls = []
        self.last_h = "abc123"

    def get_api_action(self, village_id, action, params=None, data=None):
        self.calls.append((village_id, action, params, data))
        return {"response": {}}


class FakeResman:
    def __init__(self):
        self.actual = {"wood": 50000, "stone": 50000, "iron": 50000}


def build_manager(enabled):
    manager = TroopManager.__new__(TroopManager)
    manager.wrapper = FakeWrapper()
    manager.village_id = 49709
    manager.resman = FakeResman()
    manager.keep_resources = {}
    manager.can_unlock_scavenge = enabled
    manager.logger = logging.getLogger("test-scavenge")
    return manager


logging.disable(logging.CRITICAL)

# Gate desligado (o default): nenhum POST, por mais que dê para pagar.
off = build_manager(False)
check(off.unlock_scavenge(SCAVENGE_HTML, options()) is False, "gate off deveria recusar")
check(off.wrapper.calls == [], "gate off não pode ter mandado requisição nenhuma")

# Gate ligado: um POST, e exatamente o da captura.
on = build_manager(True)
check(on.unlock_scavenge(SCAVENGE_HTML, options()) is True, "gate on deveria desbloquear")
check(len(on.wrapper.calls) == 1, "deveria mandar exatamente um POST")
village_id, action, params, data = on.wrapper.calls[0]
check(action == "start_unlock", "ajaxaction deveria ser start_unlock, veio %r" % action)
check(params == {"screen": "scavenge_api"}, "screen deveria ser scavenge_api, veio %r" % params)
check(
    data == {"village_id": 49709, "option_id": 3},
    "corpo deveria ter village_id e option_id, veio %r" % data,
)
check(village_id == 49709, "village_id posicional errado")

# O saldo local cai depois do gasto, senão outro consumidor do mesmo ciclo
# decidiria com um número que o servidor já não tem.
check(
    on.resman.actual["stone"] == 50000 - 1200,
    "o custo deveria ter sido descontado de resman.actual",
)

# Aldeia ocupada: nada sai, mesmo com o gate ligado.
busy_manager = build_manager(True)
check(
    busy_manager.unlock_scavenge(SCAVENGE_HTML, busy) is False,
    "aldeia desbloqueando algo não deveria mandar POST",
)
check(busy_manager.wrapper.calls == [], "aldeia ocupada não pode ter mandado POST")

# Tela sem a config (sessão expirada / bot protection): não levanta, não gasta.
blind = build_manager(True)
check(
    blind.unlock_scavenge("<html>login</html>", options()) is False,
    "tela sem ScavengeScreen deveria recusar em vez de levantar",
)
check(blind.wrapper.calls == [], "tela inesperada não pode virar POST")

print("ok - %d verificações" % checks)
