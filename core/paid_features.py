"""
Recursos pagos da conta (premium, gerente de conta, assistente de saque) lidos
ao vivo do `game_data` de QUALQUER resposta, e a troca de modo quando um deles
liga ou vence (docs/backend.md §8.67).

POR QUE EXISTE
--------------
O bot e feito para conta gratuita, com o pago como camada ativavel por
deteccao (§9, itens 26-28). Ceder uma fase ao gerente so e seguro se o bot
souber, na hora, que o gerente ainda esta ativo: ele vence (08/10/2026 01:16) e
volta (18/10/2026), e uma fase cedida a um gerente vencido para de ser feita
por qualquer um. A deteccao anterior (`world.premium_account`, Feature 22) lia
a visao geral UMA vez e gravava no config para sempre: em 18/10, com o premium
ativo, o `config.json` dizia `false`.

O jogo publica o estado em todo `game_data`, verbatim em 18/10 (com os tres
ativos): `{"Premium": {"possible": true, "active": true}, "AccountManager":
{"possible": true, "active": true}, "FarmAssistent": {"possible": true,
"active": true}}`. O bot ja parseia esse `game_data` em toda resposta
(`WebWrapper._remember_game_data`), entao detectar custa zero requisicao, e o
vencimento aparece na primeira resposta depois dele.

REGRAS
------
- **Bloco ausente ou malformado nao e "desligado"**: e falta de leitura, e nao
  muda o estado. So `active` booleano conta. Sem isso, uma tela sem `features`
  derrubaria o modo premium no meio do ciclo e o religaria na seguinte
  (decimo quinto padrao: o detector precisa da mesma ancora que o parser).
- `active(nome)` devolve True, False ou **None** (nunca visto neste processo).
  Quem cede fase trata None como gratuito: na duvida, o bot faz.
- Transicao (inclusive contra o estado gravado antes de um restart: o premium
  pode vencer com o bot parado) loga e avisa no Telegram.
- Desarmado ate `arm()`, que so `twb.main()` chama: sem a trava, a suite
  gravaria `cache/paid_features.json` e leria o estado real da conta
  (vigesimo primeiro padrao).
- Nunca levanta para o chamador.
"""
import logging
import os
import time

from core.filemanager import FileManager

STATE_FILE = os.path.join("cache", "paid_features.json")

NAMES = ("Premium", "AccountManager", "FarmAssistent")
LABELS = {
    "Premium": "Conta premium",
    "AccountManager": "Gerente de conta",
    "FarmAssistent": "Assistente de saque",
}
HISTORY_MAX = 50
# Regrava sem transicao a cada tanto, para o `seen_at` do arquivo nao envelhecer.
WRITE_EVERY = 600

logger = logging.getLogger("PaidFeatures")

_armed = False


def arm():
    global _armed
    _armed = True


def disarm():
    global _armed
    _armed = False


def extract(game_data):
    """{nome: bool} dos recursos com `active` booleano no `game_data`; {} se
    nenhum. Nome sem bloco legivel fica de fora: nao e "desligado"."""
    out = {}
    try:
        features = (game_data or {}).get("features")
        if not isinstance(features, dict):
            return out
        for name in NAMES:
            block = features.get(name)
            if isinstance(block, dict) and isinstance(block.get("active"), bool):
                out[name] = block["active"]
    except Exception:
        return {}
    return out


class PaidFeatures:
    def __init__(self, path=None, clock=time.time, notify=None):
        # None = STATE_FILE, e so quando armado (o teste passa `path`).
        self.path = path
        self.clock = clock
        # notify(texto); None = Notification.send, importado na hora para o
        # import deste modulo nao puxar telegram.
        self.notify = notify
        self.state = {}      # nome -> {"active", "since", "seen_at"}
        self.history = []
        self._loaded = False
        self._last_write_at = None

    # -- leitura -----------------------------------------------------------

    def active(self, name):
        """True/False pelo ultimo `game_data` visto neste processo; None se
        nunca visto. O valor do arquivo (de antes de um restart) nao conta:
        e so referencia para detectar a transicao."""
        entry = self.state.get(name)
        if not entry or entry.get("from_file"):
            return None
        return entry.get("active")

    def summary(self):
        """'Conta premium ativo, Gerente de conta ativo, ...' para log."""
        parts = []
        for name in NAMES:
            value = self.active(name)
            word = "ativo" if value is True else "inativo" if value is False else "nao lido"
            parts.append("%s %s" % (LABELS[name], word))
        return ", ".join(parts)

    # -- observacao --------------------------------------------------------

    def observe(self, game_data):
        """Registra o `game_data` de uma resposta. Devolve a lista de
        transicoes [(nome, ativo_agora, de_onde)] desta observacao."""
        try:
            seen = extract(game_data)
            if not seen:
                return []
            self._load_once()
            now = self.clock()
            transitions = []
            for name, value in seen.items():
                entry = self.state.get(name)
                if entry is None or entry.get("active") is not value:
                    # `restart`: o valor anterior veio do arquivo, nao desta
                    # execucao -- mudou com o bot parado (ou e a primeira vez).
                    origin = "restart" if entry and entry.get("from_file") else (
                        "first" if entry is None else "live")
                    self.state[name] = {"active": value, "since": now, "seen_at": now}
                    if origin != "first":
                        transitions.append((name, value, origin))
                    elif value:
                        # Primeira leitura da historia: so loga, sem Telegram.
                        logger.info("%s: ativo", LABELS[name])
                else:
                    entry["seen_at"] = now
                    entry.pop("from_file", None)
            for name, value, origin in transitions:
                self.history.append({"name": name, "active": value, "at": now,
                                     "origin": origin})
                self._announce(name, value, origin)
            self.history = self.history[-HISTORY_MAX:]
            if (transitions or self._last_write_at is None
                    or now - self._last_write_at >= WRITE_EVERY):
                self._save()
            return transitions
        except Exception:
            return []

    def _announce(self, name, value, origin):
        if value:
            text = "%s ATIVADO: o bot entra no modo pago para ele." % LABELS[name]
        else:
            text = ("%s DESATIVADO (venceu ou foi cancelado): o bot volta a "
                    "fazer sozinho o que tinha cedido." % LABELS[name])
        if origin == "restart":
            text += " Mudou com o bot parado."
        logger.warning(text)
        try:
            if self.notify is not None:
                self.notify(text)
            else:
                from core.notification import Notification
                Notification.send(text)
        except Exception:
            pass

    # -- persistencia ------------------------------------------------------

    def _file(self):
        if self.path:
            return self.path
        return STATE_FILE if _armed else None

    def _load_once(self):
        if self._loaded:
            return
        self._loaded = True
        path = self._file()
        if not path:
            return
        try:
            data = FileManager.load_json_file(path)
        except Exception:
            data = None
        if not isinstance(data, dict):
            return
        for name, entry in (data.get("features") or {}).items():
            if name in NAMES and isinstance(entry, dict) and isinstance(entry.get("active"), bool):
                self.state[name] = dict(entry, from_file=True)
        history = data.get("history")
        if isinstance(history, list):
            self.history = history[-HISTORY_MAX:]

    def _save(self):
        path = self._file()
        if not path:
            return
        try:
            features = {name: {k: v for k, v in entry.items() if k != "from_file"}
                        for name, entry in self.state.items()}
            FileManager.save_json_file({"features": features, "history": self.history,
                                        "written_at": self.clock()}, path)
            self._last_write_at = self.clock()
        except Exception:
            pass


def read(path=None):
    """O que o painel precisa: {nome: {"active", "since", "seen_at"}} e o
    historico, ou {"available": False}."""
    try:
        data = FileManager.load_json_file(path or STATE_FILE)
    except Exception:
        data = None
    if not isinstance(data, dict) or not isinstance(data.get("features"), dict):
        return {"available": False}
    return {"available": True, "features": data["features"],
            "history": data.get("history") or [], "written_at": data.get("written_at")}
