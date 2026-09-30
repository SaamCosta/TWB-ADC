"""
Pulso da conta: o que o `game_data` de QUALQUER resposta diz sobre a conta
inteira, gravado em `cache/account_pulse.json` para o painel (frontend 2.8,
W1/W4).

POR QUE EXISTE
--------------
O painel so via ataque pelo `cache/managed/<aldeia>.json`, escrito quando a
aldeia roda no laco -- que leva ~4h para chegar na ultima aldeia e dorme de
noite. Em 2026-09-23 a BBM 032, conquistada as 21:23, tinha ataque chegando as
00:05 e o painel dizia "0 sob ataque": ela nunca tinha rodado. O jogo publica
`player.incomings` e `player.supports` no `game_data` de toda tela, e o bot ja
parseia esse `game_data` em toda resposta (`WebWrapper._remember_game_data`).
Faltava guardar.

O QUE O NUMERO E, E O QUE NAO FOI MEDIDO
----------------------------------------
Os dois campos vem de `game_data.player` como string ("0"), verbatim em todas
as capturas de `cache/debug/` (2026-09-20 a 09-29). Nenhuma captura tem valor
diferente de zero, entao "incomings = comandos hostis chegando na conta
inteira, o contador da barra do jogo" e leitura do nome e do lugar do campo,
nao medicao. O painel apresenta como "segundo o jogo" e com a idade da leitura;
quem decide defesa continua sendo o `DefenceManager`, por aldeia.

REGRAS
------
- Desarmado ate `arm()`, que so `twb.main()` chama. A suite de testes cria
  wrappers e alimenta respostas; sem a trava, rodar os testes reescreveria o
  arquivo que o painel le (vigesimo primeiro padrao: a guarda nao escreve no
  artefato de producao).
- Grava quando algum valor muda, ou a cada WRITE_EVERY segundos para a idade
  continuar honesta. Com ~800 respostas por ciclo, gravar em toda seria I/O a
  toa.
- Nunca levanta para o chamador: e observabilidade.
"""
import os
import time

from core.filemanager import FileManager

PULSE_FILE = os.path.join("cache", "account_pulse.json")
WRITE_EVERY = 60

FIELDS = ("incomings", "supports", "villages")

_armed = False


def arm():
    global _armed
    _armed = True


def disarm():
    global _armed
    _armed = False


def extract(game_data, received_at=None):
    """
    {"incomings", "supports", "villages", "at", "screen"} do `game_data`, ou
    None se ele nao tiver `player.incomings` legivel.

    `at` e o `time_generated` do servidor (ms -> s) quando existe. Valor
    ilegivel vira None em vez de 0: zero aqui significaria "nenhum ataque",
    que e justamente a afirmacao que nao se pode fabricar.
    """
    try:
        player = (game_data or {}).get("player")
        if not isinstance(player, dict):
            return None
        out = {}
        for key in FIELDS:
            raw = player.get(key)
            try:
                out[key] = int(raw) if raw is not None and str(raw).strip() != "" else None
            except (TypeError, ValueError):
                out[key] = None
        if out["incomings"] is None:
            return None
        generated = game_data.get("time_generated")
        try:
            out["at"] = float(generated) / 1000.0 if generated else None
        except (TypeError, ValueError):
            out["at"] = None
        if out["at"] is None:
            out["at"] = received_at if received_at is not None else time.time()
        out["screen"] = game_data.get("screen")
        return out
    except Exception:
        return None


class AccountPulse:
    def __init__(self, path=None, clock=time.time):
        # None = PULSE_FILE lido na hora, para o teste poder redirecionar.
        self.path = path
        self.clock = clock
        self._last_written = None
        self._last_write_at = 0.0

    def observe(self, game_data):
        """Registra o `game_data` de uma resposta. Devolve True se gravou."""
        try:
            pulse = extract(game_data, received_at=self.clock())
            if pulse is None:
                return False
            if not _armed:
                return False
            now = self.clock()
            changed = (self._last_written is None or any(
                pulse.get(k) != self._last_written.get(k) for k in FIELDS))
            if not changed and now - self._last_write_at < WRITE_EVERY:
                return False
            record = dict(pulse, written_at=now)
            # Quando o numero mudou por ultimo: "3 ataques ha 2 min" e "3
            # ataques ha 5 h" pedem reacoes diferentes.
            if changed or not self._last_written:
                record["changed_at"] = pulse["at"]
            else:
                record["changed_at"] = self._last_written.get("changed_at", pulse["at"])
            FileManager.save_json_file(record, self.path or PULSE_FILE)
            self._last_written = record
            self._last_write_at = now
            return True
        except Exception:
            return False


def read(path=None, now=None):
    """
    O que o painel precisa, ou {"available": False}. Arquivo ausente ou
    ilegivel nao e "zero ataques": e "nao se sabe".
    """
    now = time.time() if now is None else now
    try:
        data = FileManager.load_json_file(path or PULSE_FILE)
    except Exception:
        data = None
    if not isinstance(data, dict) or data.get("incomings") is None:
        return {"available": False}
    at = data.get("at") or data.get("written_at")
    try:
        age = max(0, int(now - float(at))) if at else None
    except (TypeError, ValueError):
        age = None
    return {
        "available": True,
        "incomings": data.get("incomings"),
        "supports": data.get("supports"),
        "villages": data.get("villages"),
        "at": at,
        "age_seconds": age,
        "changed_at": data.get("changed_at"),
        "screen": data.get("screen"),
    }
