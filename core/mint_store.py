"""
Estado da cunhagem (§8.55), em dois arquivos com donos diferentes:

- `cache/mint/campaign.json` -- a campanha de itens (Bônus de bandeira +
  Decreto Real). DOIS escritores: o painel aprova e cancela; o bot ativa,
  acompanha e encerra. Toda gravação passa por `file_lock` e relê o disco
  antes de gravar (A26-12).
- `cache/mint/state.json` -- contabilidade do bot (última cunhagem automática
  diária, sessão do hub, último custo medido). Um escritor só: o bot.

Ciclo de vida da campanha:

    approved -> activating -> active -> done
             `-> cancelled              `-> failed (em qualquer passo)

`activating` é gravado ANTES do primeiro item ser gasto, com o inventário de
antes (`inventory_before`). Se o processo cair no meio, a retomada NÃO reenvia
às cegas: relê o inventário e só gasta o que a diferença diz que ainda falta.
Item de inventário não volta -- gastar dois Bônus de bandeira por causa de uma
resposta perdida é o trem duplicado da §6.1 com outra roupa.
"""
import logging
import os
import time

from core.exceptions import InvalidJSONException
from core.file_lock import file_lock
from core.filemanager import FileManager

CAMPAIGN_PATH = "cache/mint/campaign.json"
STATE_PATH = "cache/mint/state.json"

OPEN_STATUSES = ("approved", "activating", "active")

# Aprovação vale 6 h. Uma campanha aprovada e esquecida não pode disparar dias
# depois numa aldeia que pode nem ter mais a bandeira certa.
APPROVAL_TTL = 6 * 3600

EVENTS_MAX = 80

logger = logging.getLogger("Mint")


def _read(path):
    """Dict do arquivo; {} se não existe; None se ilegível (não sobrescrever)."""
    try:
        data = FileManager.load_json_file(path)
    except InvalidJSONException:
        return None
    return data if isinstance(data, dict) else ({} if data is None else None)


def _ensure_dir(path):
    # Diretório do caminho em uso, não "cache/mint" fixo: os testes apontam
    # CAMPAIGN_PATH/STATE_PATH para um diretório temporário.
    FileManager.create_directory(os.path.dirname(FileManager.get_path(path)))


def load_campaign():
    return _read(CAMPAIGN_PATH) or {}


def update_campaign(mutator):
    """
    Relê sob a trava, aplica `mutator(data)` e grava. Devolve o retorno do
    mutator, ou None se o arquivo estava ilegível -- nada é gravado nesse caso.
    """
    _ensure_dir(CAMPAIGN_PATH)
    with file_lock(FileManager.get_path(CAMPAIGN_PATH)):
        data = _read(CAMPAIGN_PATH)
        if data is None:
            logger.warning("%s ilegível -- campanha não alterada", CAMPAIGN_PATH)
            return None
        result = mutator(data)
        data["updated_at"] = int(time.time())
        FileManager.save_json_file(data, CAMPAIGN_PATH, ensure_ascii=False)
        return result


def add_event(data, message, now=None, **fields):
    """Acrescenta ao diário da campanha (dentro de um mutator)."""
    entry = {"t": int(now or time.time()), "msg": message}
    entry.update(fields)
    events = data.setdefault("events", [])
    events.append(entry)
    del events[:-EVENTS_MAX]


def approve(hub, hub_name, decrees, war_chest, floor, now=None):
    """
    Grava a aprovação do painel. Recusa (ValueError) se já existe campanha
    aberta: duas campanhas ao mesmo tempo gastariam o dobro de itens.
    """
    now = int(now or time.time())

    def mutate(data):
        if data.get("status") in OPEN_STATUSES and not _expired_approval(data, now):
            raise ValueError(
                "já existe uma campanha %s (aldeia %s)" % (data.get("status"), data.get("hub_name"))
            )
        data.clear()
        data.update({
            "status": "approved",
            "hub": str(hub),
            "hub_name": hub_name,
            "items": {"flag_bonus": 1, "decree": int(decrees), "war_chest": int(bool(war_chest))},
            "floor": int(floor),
            "approved_at": now,
            "events": [],
            "measurements": [],
        })
        add_event(data, "Campanha aprovada no painel", now=now)
        return True

    return update_campaign(mutate)


def _expired_approval(data, now):
    return data.get("status") == "approved" and now - int(data.get("approved_at") or 0) > APPROVAL_TTL


def cancel(now=None):
    """Cancela uma campanha ainda não ativada. Devolve True se cancelou."""
    now = int(now or time.time())

    def mutate(data):
        if data.get("status") != "approved":
            return False
        data["status"] = "cancelled"
        add_event(data, "Cancelada no painel antes de qualquer item ser gasto", now=now)
        return True

    return bool(update_campaign(mutate))


def finish_early(now=None):
    """Encerra uma campanha ativa: solta travas e roteamento. Itens não voltam."""
    now = int(now or time.time())

    def mutate(data):
        if data.get("status") != "active":
            return False
        data["status"] = "done"
        data["ended_at"] = now
        add_event(data, "Encerrada no painel antes do fim (itens já gastos não voltam)", now=now)
        return True

    return bool(update_campaign(mutate))


def load_state():
    return _read(STATE_PATH) or {}


def save_state(state):
    _ensure_dir(STATE_PATH)
    FileManager.save_json_file(state, STATE_PATH, ensure_ascii=False)
