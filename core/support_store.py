"""
Estado do apoio a membros da tribo (docs/backend.md §8.39), dividido em dois
arquivos com donos diferentes:

- `cache/support/request.json` -- o pedido lido (tópico do fórum ou texto
  colado). Só o webmanager escreve.
- `cache/support/plan.json` -- as linhas do plano (origem -> destino ->
  tropas) e o status de cada uma. DOIS escritores: o painel propõe, aprova e
  cancela; o bot marca envio. Toda gravação passa por `file_lock` e relê o
  disco antes de gravar (A26-12: nunca gravar a cópia lida antes de uma
  espera).

Ciclo de vida de uma linha:

    proposed -> approved -> dispatching -> sent | failed
             `-> cancelled   (approved também pode ser cancelada)

`dispatching` é gravado ANTES de o bot tocar na praça. Se o processo cair
entre o envio e a gravação do resultado, a linha fica em `dispatching` e NÃO é
tentada de novo -- o painel mostra "resultado desconhecido, confira no jogo".
Reenviar às cegas é o trem duplicado da §6.1 com outra roupa: melhor uma
pergunta ao usuário do que o dobro de tropa na conta de outro jogador.
"""
import logging
import math
import time
import uuid

from core.file_lock import file_lock
from core.exceptions import InvalidJSONException
from core.filemanager import FileManager

REQUEST_PATH = "cache/support/request.json"
PLAN_PATH = "cache/support/plan.json"

# Fatia padrão das unidades da coleta que pode ir de apoio (usuário,
# 2026-09-29: "a coleta é prioridade", com taxa de ~0,2). Vale também para
# linha aprovada antes de a fatia ser gravada em cada linha -- sem isso ela
# era lida como 0% e toda lança/espada/pesada falhava.
DEFAULT_GATHER_SHARE = 0.2

# Aprovação vale 24 h. Um plano aprovado e esquecido não pode sair dias depois
# com tropa calculada sobre um estado que já não existe.
APPROVAL_TTL = 24 * 3600

logger = logging.getLogger("TribeSupport")


def _read(path):
    """Dict do arquivo; {} se não existe; None se ilegível (não sobrescrever)."""
    try:
        data = FileManager.load_json_file(path)
    except InvalidJSONException:
        return None
    return data if isinstance(data, dict) else ({} if data is None else None)


def load_request():
    return _read(REQUEST_PATH) or {}


def save_request(data):
    FileManager.create_directory(FileManager.get_path("cache/support"))
    FileManager.save_json_file(data, REQUEST_PATH, ensure_ascii=False)


def load_plan():
    data = _read(PLAN_PATH) or {}
    data.setdefault("lines", [])
    return data


def update_plan(mutator):
    """
    Relê `plan.json` sob a trava, aplica `mutator(data)` e grava. Devolve o
    retorno do mutator, ou None se o arquivo estava ilegível -- nesse caso
    NADA é gravado, para não apagar um plano que só não pôde ser lido.
    """
    FileManager.create_directory(FileManager.get_path("cache/support"))
    with file_lock(FileManager.get_path(PLAN_PATH)):
        data = _read(PLAN_PATH)
        if data is None:
            logger.warning("%s ilegível -- plano não alterado", PLAN_PATH)
            return None
        data.setdefault("lines", [])
        result = mutator(data)
        data["updated_at"] = int(time.time())
        FileManager.save_json_file(data, PLAN_PATH, ensure_ascii=False)
        return result


def new_line_id():
    return uuid.uuid4().hex[:12]


def replace_proposed(lines, request_key, ranking=None, options=None, now=None):
    """Troca as linhas `proposed` pelas novas; o resto (histórico) fica."""
    now = int(now or time.time())

    def mutate(data):
        kept = [l for l in data["lines"] if l.get("status") != "proposed"]
        fresh = []
        for line in lines:
            fresh.append(dict(line, id=new_line_id(), status="proposed",
                              request_key=request_key, created_at=now))
        data["lines"] = kept + fresh
        data["ranking"] = ranking or []
        data["options"] = options or {}
        data["request_key"] = request_key
        data["planned_at"] = now
        return len(fresh)

    return update_plan(mutate)


def set_status(ids, new_status, allowed_from, now=None, **fields):
    """Muda o status das linhas `ids` que estão em `allowed_from`."""
    now = int(now or time.time())
    ids = set(ids or [])

    def mutate(data):
        changed = 0
        for line in data["lines"]:
            if line.get("id") in ids and line.get("status") in allowed_from:
                line["status"] = new_status
                line[new_status + "_at"] = now
                line.update(fields)
                changed += 1
        return changed

    return update_plan(mutate) or 0


def approve(ids, now=None):
    return set_status(ids, "approved", ("proposed",), now=now)


def cancel(ids, now=None):
    return set_status(ids, "cancelled", ("proposed", "approved"), now=now)


def claim_lines(village_id, now=None, blocked_reason=None, only_ids=None, waiting=None):
    """
    Linhas aprovadas cuja origem é `village_id`, marcadas `dispatching` e
    devolvidas (cópias) para o bot enviar.

    - aprovação com mais de APPROVAL_TTL vira `failed` sem ser tentada;
    - com `blocked_reason` (ex.: ataque chegando na origem), nada é
      reclamado: as linhas continuam aprovadas, com a nota do motivo, e o
      bot tenta de novo no próximo ciclo da aldeia até a aprovação vencer;
    - `only_ids`: só estas podem ser reclamadas; `waiting` ({id: motivo}):
      estas ficam aprovadas com a nota (tropa da coleta ainda fora).
    """
    waiting = waiting or {}
    now = int(now or time.time())
    village_id = str(village_id)

    def mutate(data):
        claimed = []
        for line in data["lines"]:
            if line.get("status") != "approved" or str(line.get("source_vid")) != village_id:
                continue
            if now - int(line.get("approved_at") or 0) > APPROVAL_TTL:
                line["status"] = "failed"
                line["failed_at"] = now
                line["error"] = "aprovação venceu (%d h) sem envio" % (APPROVAL_TTL // 3600)
                continue
            if blocked_reason:
                line["note"] = "adiado: %s" % blocked_reason
                line["note_at"] = now
                continue
            if line.get("id") in waiting:
                line["note"] = waiting[line["id"]]
                line["note_at"] = now
                continue
            if only_ids is not None and line.get("id") not in only_ids:
                continue
            line["status"] = "dispatching"
            line["dispatching_at"] = now
            line.pop("note", None)
            claimed.append(dict(line))
        return claimed

    return update_plan(mutate) or []


def finish_line(line_id, ok, now=None, **fields):
    """Resultado do envio de uma linha `dispatching`: `sent` ou `failed`."""
    now = int(now or time.time())
    status = "sent" if ok else "failed"

    def mutate(data):
        for line in data["lines"]:
            if line.get("id") == line_id and line.get("status") == "dispatching":
                line["status"] = status
                line[status + "_at"] = now
                line.update(fields)
                return True
        return False

    return bool(update_plan(mutate))


def line_readiness(troops, home, total, reserve_pct, gathering, gather_share, gather_units):
    """
    ("send" | "wait" | "fail", motivo) para uma linha aprovada, na hora de agir.

    - Unidade da coleta numa aldeia que coleta: o limite é `gather_share` do
      TOTAL. Acima dele, falha (a coleta tem prioridade sobre o resto). Dentro
      dele mas fora de casa (coletando), ESPERA: a linha continua aprovada e
      a coleta deixa essa fatia em casa quando a tropa voltar.
    - Qualquer outra unidade: precisa estar em casa, deixando `reserve_pct`.
    """
    wait, fail = [], []
    for unit, qty in (troops or {}).items():
        qty = int(qty)
        have = int((home or {}).get(unit) or 0)
        owned = int((total or {}).get(unit) or 0)
        if gathering and unit in gather_units:
            cap = int(math.floor(owned * float(gather_share or 0)))
            if qty > cap:
                fail.append("%s: plano %d acima da fatia da coleta (%d%% de %d = %d)"
                            % (unit, qty, round(float(gather_share or 0) * 100), owned, cap))
            elif have < qty:
                wait.append("%s: %d em casa, %d coletando" % (unit, have, owned - have))
        else:
            keep = int(math.ceil(have * float(reserve_pct or 0)))
            if have - qty < keep:
                fail.append("%s: em casa %d, plano %d, reserva %d" % (unit, have, qty, keep))
    if fail:
        return "fail", "; ".join(fail)
    if wait:
        return "wait", "aguardando a coleta voltar (%s)" % "; ".join(wait)
    return "send", None


def home_check(home, troops, reserve_pct):
    """
    None se dá para mandar `troops` deixando `reserve_pct` em casa; senão o
    motivo. Conferido na HORA do envio, com a tropa lida neste ciclo -- o
    plano foi feito sobre o cache/managed, que pode ter horas (sexto padrão).
    """
    short = []
    for unit, qty in (troops or {}).items():
        have = int((home or {}).get(unit) or 0)
        keep = int(math.ceil(have * float(reserve_pct or 0)))
        if have - int(qty) < keep:
            short.append("%s: em casa %d, plano %d, reserva %d" % (unit, have, int(qty), keep))
    return "; ".join(short) if short else None
