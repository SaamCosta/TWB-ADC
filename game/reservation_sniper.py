"""
P-RESERVA-TIMER -- reservar um alvo da fila manual no minuto em que a reserva
de outro jogador vence (docs/backend.md 8.28).

Pedido do usuario em 2026-09-23: a 74694 (583|308) estava reservada por um
aliado ate "hoje as 17:31". Aldeia em disputa, dessas que outro membro da tribo
pega no minuto seguinte. A fila manual (8.27) ja espera a reserva sumir, mas
fila nao e reserva: o bot so reservava ao AGENDAR um trem, e isso exige 4 nobres
livres e nenhuma outra conquista ativa. Este modulo segura a vaga no quadro
assim que ela abre, e o trem vem depois.

COMO O HORARIO E OBTIDO
-----------------------
O quadro publica a validade em texto relativo, em tres formas (medidas nas 441
linhas de cache/debug/reservations_all.html, 2026-09-21): "hoje às 13:39"
(11), "amanhã às 07:45" (62) e "em 24.09. às 18:02" (368). Relativo AO MOMENTO
DA LEITURA, por isso `parse_expires` recebe a hora em que o quadro foi lido, e
nao a hora atual. Precisao de minuto: nao se sabe se a reserva some no
comeco ou no fim do minuto, e e por isso que existe o laco de tentativas.

QUANDO RODA
-----------
No mesmo gancho cooperativo do Hunter (`hunter_service_callback`): o farm o
chama antes de cada alvo e a aldeia entre as fases, entao durante o ciclo ele
e visitado a cada poucas dezenas de segundos. Faltando ate `LEAD` segundos, o
tick dorme ate o horario, do mesmo jeito que o Hunter faz com `send_time`. Fora
do ciclo, `twb.py` encurta o sono para acordar a tempo (`nearest_time`).

ORCAMENTO DE REQUISICOES
------------------------
Cada tentativa custa uma releitura do quadro (~700 KB) e, se estiver livre, um
POST e mais uma releitura. Uma tentativa por minuto, no maximo
`MAX_ATTEMPTS`: o captcha do jogo e por taxa da CONTA, e o bot esta farmando
ao mesmo tempo.
"""
import datetime
import logging
import re
import time

from core.filemanager import FileManager

_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})")
_DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.")


def parse_expires(text, read_at):
    """
    Epoch da validade de uma reserva, ou None se o texto nao for reconhecido.

    `read_at` e o epoch em que o quadro foi LIDO -- "hoje" e "amanha" sao
    relativos a ele. Na forma com data sem ano, a data que ja passou ha mais
    de um dia e do ano seguinte (virada de dezembro para janeiro).

    Nao ancora em "às": o arquivo de captura chega com o acento corrompido
    dependendo de quem leu, e a hora e a data bastam.
    """
    if not text:
        return None
    m_time = _TIME_RE.search(text)
    if not m_time:
        return None
    hour, minute = int(m_time.group(1)), int(m_time.group(2))
    base = datetime.datetime.fromtimestamp(read_at)
    lowered = text.lower()

    m_date = _DATE_RE.search(text)
    if m_date:
        day, month = int(m_date.group(1)), int(m_date.group(2))
        try:
            when = base.replace(month=month, day=day, hour=hour, minute=minute,
                                second=0, microsecond=0)
        except ValueError:
            return None
        if when < base - datetime.timedelta(days=1):
            try:
                when = when.replace(year=when.year + 1)
            except ValueError:
                return None
        return when.timestamp()

    if "hoje" in lowered:
        offset = 0
    elif "amanh" in lowered:
        offset = 1
    else:
        return None
    when = (base + datetime.timedelta(days=offset)).replace(
        hour=hour, minute=minute, second=0, microsecond=0)
    return when.timestamp()


class ReservationSniper:
    """
    Arma um horario por alvo da fila manual que esta reservado por outra
    pessoa, e tenta reservar para a conta quando ele chega.
    """

    # Segundos antes do horario em que o tick aceita dormir ate ele. Mesma
    # ordem de grandeza do `Hunter.window` (120): dormir bloqueia o ciclo.
    LEAD = 90
    # A validade tem precisao de minuto; tentar 2 s depois do minuto virar.
    GRACE = 2
    RETRY_INTERVAL = 60
    MAX_ATTEMPTS = 8

    def __init__(self, wrapper, config, board, writer, world_villages=None):
        self.wrapper = wrapper
        self.config = config
        self.board = board
        self.writer = writer
        self.world_villages = world_villages
        self.fallback_village_id = None
        self.logger = logging.getLogger("ReservationTimer")
        # Mutaveis em __init__ (1o padrao do CLAUDE.md).
        self.armed = {}
        self.now = time.time
        self.sleep = time.sleep

    @property
    def enabled(self):
        cfg = self.config.get("conquest", {})
        return bool(cfg.get("snipe_expiring_reservations", False)) and bool(
            self.writer and self.writer.enabled
        )

    # ------------------------------------------------------------------
    # Armar
    # ------------------------------------------------------------------

    @staticmethod
    def _manual_queue():
        """{target_id: data} dos alvos com status "manual" em cache/conquest."""
        out = {}
        for fname in FileManager.list_directory("cache/conquest", ends_with=".json"):
            data = FileManager.load_json_file(f"cache/conquest/{fname}")
            if data and data.get("status") == "manual":
                out[fname.replace(".json", "")] = data
        return out

    @staticmethod
    def _location(target_id, data):
        loc = data.get("target_location")
        if not loc:
            cached = FileManager.load_json_file(f"cache/villages/{target_id}.json") or {}
            loc = cached.get("location")
        if loc and len(loc) == 2:
            return [int(loc[0]), int(loc[1])]
        return None

    def arm(self):
        """
        Recalcula os horarios a partir do quadro ja lido. Nao faz requisicao.

        Sem leitura valida do quadro nada muda: o que ja estava armado
        continua, porque o quadro velho ainda e a melhor informacao que existe
        (ciclo noturno nao rele o quadro -- nenhuma aldeia ativa).
        """
        if not self.enabled or not self.board or not self.board.is_readable():
            return
        queue = self._manual_queue()

        for target_id in list(self.armed):
            if target_id not in queue:
                self.logger.info(
                    "Reserva-timer: alvo %s saiu da fila manual -- desarmado",
                    target_id)
                del self.armed[target_id]

        for target_id, data in queue.items():
            location = self._location(target_id, data)
            if not location:
                continue
            claim = self.board.claimed_by_other(target_id, location)
            if not claim:
                continue
            expires_at = parse_expires(claim.get("expires_text"),
                                       self.board.fetched_at)
            if expires_at is None:
                self.logger.warning(
                    "Reserva-timer: nao entendi a validade %r da reserva de %s "
                    "sobre %s -- alvo nao armado",
                    claim.get("expires_text"), claim.get("reserved_by_name"),
                    target_id)
                continue
            current = self.armed.get(target_id)
            if current and current["expires_at"] == expires_at:
                continue
            self.armed[target_id] = {
                "location": location,
                "expires_at": expires_at,
                "reserved_by": claim.get("reserved_by_name"),
                "attempts": 0,
                "last_attempt": 0.0,
            }
            self.logger.info(
                "Reserva-timer: alvo %s (%d|%d) armado para %s -- reserva de %s "
                "vence entao", target_id, location[0], location[1],
                datetime.datetime.fromtimestamp(expires_at).strftime("%d/%m %H:%M"),
                claim.get("reserved_by_name"))

    def nearest_time(self):
        """Epoch da proxima tentativa de qualquer alvo armado, ou None."""
        if not self.armed:
            return None
        return min(self._next_at(entry) for entry in self.armed.values())

    def _next_at(self, entry):
        return max(entry["expires_at"] + self.GRACE,
                   entry["last_attempt"] + self.RETRY_INTERVAL)

    # ------------------------------------------------------------------
    # Disparar
    # ------------------------------------------------------------------

    def tick(self):
        """Chamado nos checkpoints do ciclo e antes/depois do sono."""
        if not self.armed or not self.enabled:
            return
        for target_id in sorted(self.armed, key=lambda t: self._next_at(self.armed[t])):
            entry = self.armed.get(target_id)
            if not entry:
                continue
            wait = self._next_at(entry) - self.now()
            if wait > self.LEAD:
                continue
            if wait > 0:
                self.logger.info(
                    "Reserva-timer: alvo %s -- dormindo %.0fs ate a reserva de "
                    "%s vencer", target_id, wait, entry["reserved_by"])
                self.sleep(wait)
            self._attempt(target_id, entry)

    def _attempt(self, target_id, entry):
        entry["attempts"] += 1
        entry["last_attempt"] = self.now()
        location = entry["location"]
        late = entry["last_attempt"] - entry["expires_at"]

        village_id = self.board.read_village_id or self.fallback_village_id
        readable = self.board.refresh(village_id, force=True) if village_id else False
        if not readable:
            self._give_up_if_exhausted(target_id, entry, "sem leitura do quadro")
            return

        other = self.board.claimed_by_other(target_id, location)
        if other:
            expires_at = parse_expires(other.get("expires_text"), self.board.fetched_at)
            if expires_at and expires_at > entry["expires_at"] + 60:
                self.logger.info(
                    "Reserva-timer: %s renovou a reserva de %s ate %s -- "
                    "rearmado", other.get("reserved_by_name"), target_id,
                    other.get("expires_text"))
                entry.update(expires_at=expires_at, attempts=0, last_attempt=0.0,
                             reserved_by=other.get("reserved_by_name"))
                return
            self._give_up_if_exhausted(
                target_id, entry,
                "reserva de %s ainda no quadro" % other.get("reserved_by_name"))
            return

        if self.board.claimed_by_me(target_id, location):
            self.logger.info(
                "Reserva-timer: alvo %s ja esta reservado por esta conta -- "
                "desarmado", target_id)
            del self.armed[target_id]
            return

        owner = self._owner(target_id)
        if owner != "0":
            self.logger.warning(
                "Reserva-timer: alvo %s tem dono agora (%s) -- desarmado, sem "
                "reservar", target_id, owner)
            del self.armed[target_id]
            return

        claim = self.writer.claim_target(target_id, location, budget_exempt=True)
        if not claim:
            self._give_up_if_exhausted(target_id, entry, "reserva recusada")
            return

        self.logger.info(
            "Reserva-timer: alvo %s (%d|%d) reservado %.0fs depois do "
            "vencimento da reserva de %s (tentativa %d)", target_id,
            location[0], location[1], late, entry["reserved_by"],
            entry["attempts"])
        self._record_claim(target_id, claim)
        del self.armed[target_id]

    def _give_up_if_exhausted(self, target_id, entry, why):
        if entry["attempts"] < self.MAX_ATTEMPTS:
            self.logger.info(
                "Reserva-timer: alvo %s, tentativa %d/%d sem sucesso (%s)",
                target_id, entry["attempts"], self.MAX_ATTEMPTS, why)
            return
        self.logger.warning(
            "Reserva-timer: desistindo do alvo %s depois de %d tentativas (%s). "
            "Ele segue na fila manual; o trem ainda reserva ao ser agendado",
            target_id, entry["attempts"], why)
        del self.armed[target_id]

    def _owner(self, target_id):
        """
        "0" se barbara pelas duas fontes, senao o dono. Mesma regra de
        `ConquestManager._get_manual_target`: basta uma fonte dizer dono.
        """
        cached = FileManager.load_json_file(f"cache/villages/{target_id}.json") or {}
        owner = str(cached.get("owner", "0"))
        if owner != "0" or not self.world_villages:
            return owner
        try:
            row = self.world_villages.rows().get(str(target_id))
        except Exception:  # noqa: BLE001 -- fonte extra, nao essencial
            return "0"
        return str(row[2]) if row else "0"

    @staticmethod
    def _record_claim(target_id, claim):
        """
        Mesmo campo que `BarbarianTrainPlanner._claim_target_on_board` grava,
        para o resto do sistema ver a vaga como do bot e com procedencia.
        """
        path = f"cache/conquest/{target_id}.json"
        data = FileManager.load_json_file(path) or {}
        data.pop("waiting_reservation", None)
        data["target_claim"] = {
            "reservation_id": claim.get("reservation_id"),
            "created_at": int(time.time()),
            "expires_text": claim.get("expires_text"),
            "source": "reservation_timer",
        }
        FileManager.save_json_file(data, path)
