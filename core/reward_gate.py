"""
P-MISSAO-POPUP (docs/backend.md §8.44): o GET do popup de recompensas de
missao so quando o jogo diz que ha recompensa.

`Village.get_quest_rewards()` baixava `screen=new_quests&ajax=quest_popup` em
toda aldeia, todo ciclo. Medido em `cache/cycles/` (50 ciclos, ate 2026-10-02):
946 GETs para 5 resgates. Cada GET custa o sono entre requisicoes, ~12 s.

Toda tela HTML ja traz `RewardSystem.setUnlockableRewardsCount(N)`
(`Extractor.unlocked_rewards_count`). O wrapper anota N por aldeia, de toda
resposta (`observe`), e o popup so e baixado quando:
  - nao ha N desta aldeia, ou ele tem mais de `MAX_AGE` segundos;
  - N > 0;
  - ou e hora da conferencia (`VERIFY_EVERY`): mesmo com N = 0, um GET de
    verdade, para medir em campo se o contador e confiavel.

A conferencia e a rede de protecao. O significado de N foi lido no JS do jogo,
mas nenhuma captura em disco tinha N > 0, entao nada ali discriminava as
hipoteses. Se uma conferencia achar recompensa pronta com N = 0, o gate se
desliga ate o fim do processo (WARNING) e o bot volta ao GET em toda aldeia.
O pior caso fica limitado a uma recompensa resgatada ate `VERIFY_EVERY` mais
tarde, e o campo produz a evidencia que faltava.

Nada aqui levanta para o chamador: wrapper sem gate (mock de teste) faz o GET
como antes.
"""
import logging
import time

from core.extractors import Extractor

logger = logging.getLogger("RewardGate")


class RewardGate:
    # Idade maxima do N desta aldeia. Entre o `init` da aldeia (visao geral,
    # HTML) e a fase de missoes ha a defesa, alguns segundos a poucos minutos.
    MAX_AGE = 600
    # Uma conferencia por janela, para o imperio inteiro. Com ciclo de ~4 h,
    # e uma ou duas por ciclo contra ~39 GETs antes.
    VERIFY_EVERY = 3 * 3600

    def __init__(self, clock=time.time):
        self._clock = clock
        # {village_id: (N, quando)}. Em __init__ (primeiro padrao).
        self.seen = {}
        self.last_verify = None
        self.disabled = False

    def observe(self, village_id, text):
        """Anota N desta resposta, se houver. Nunca levanta."""
        try:
            count = Extractor.unlocked_rewards_count(text)
            if count is not None and village_id:
                self.seen[str(village_id)] = (count, self._clock())
        except Exception:
            pass

    def decide(self, village_id):
        """
        (buscar, motivo). `motivo` vai no log e no teste:
        `gate_desligado`, `sem_contador`, `contador_velho`, `contador_positivo`,
        `conferencia` -> buscar; `contador_zero` -> nao buscar.
        """
        if self.disabled:
            return True, "gate_desligado"
        entry = self.seen.get(str(village_id))
        if entry is None:
            return True, "sem_contador"
        count, when = entry
        now = self._clock()
        if now - when > self.MAX_AGE:
            return True, "contador_velho"
        if count > 0:
            return True, "contador_positivo"
        if self.last_verify is None or now - self.last_verify >= self.VERIFY_EVERY:
            self.last_verify = now
            return True, "conferencia"
        return False, "contador_zero"

    def check(self, village_id, reason, found):
        """
        Confere o que o popup trouxe (`found` = recompensas prontas) contra N.
        So a conferencia com N = 0 e recompensa achada desliga o gate: e o unico
        caso em que pular o GET teria perdido alguma coisa.
        """
        entry = self.seen.get(str(village_id))
        count = entry[0] if entry else None
        if reason == "conferencia":
            if found:
                self.disabled = True
                logger.warning(
                    "Recompensas: o contador do jogo dizia 0 na aldeia %s e o "
                    "popup tinha %d pronta(s) -- gate desligado ate reiniciar, "
                    "voltando ao GET em toda aldeia", village_id, found
                )
            else:
                logger.info(
                    "Recompensas: conferencia na aldeia %s -- contador 0 e popup "
                    "sem recompensa pronta, o gate segue", village_id
                )
        elif reason == "contador_positivo" and not found:
            # Nao custa nada a mais que o comportamento antigo (o GET ja
            # aconteceria); fica registrado porque contradiz a leitura do JS.
            logger.info(
                "Recompensas: contador %s na aldeia %s e nenhuma pronta no popup",
                count, village_id
            )
