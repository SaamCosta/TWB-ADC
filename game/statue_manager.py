"""
Feature 24 (fase 1) — leitura periódica do estado do(s) Paladino(s), sem
nenhuma automação ativa (treino por XP e re-especialização ficam para uma
fase futura, que precisa de mais desenho — ver docs/backlog.md Feature 24).

Roda uma vez por ciclo completo do bot (não por aldeia — o roster de
Paladinos é compartilhado por toda a conta), pedindo screen=statue&mode=overview
a partir de qualquer aldeia gerenciada disponível. Persiste o resultado em
cache/statue/status.json para o webmanager ler — mesmo padrão já usado por
cache/resource_sharing/history.json (Feature 20).

Opt-in via config["statue"]["enabled"] (default false): diferente das
Features 19-21 (que só passaram a persistir estado que managers já
existentes calculavam), esta feature faz uma requisição HTTP nova por ciclo
a uma tela que o bot nunca acessou antes — por segurança, fica desligada até
o usuário habilitar explicitamente.
"""
import logging
import time

from core.filemanager import FileManager
from pages.statue import StatuePage

logger = logging.getLogger("StatueManager")

CACHE_PATH = "cache/statue/status.json"


class StatueManager:
    @staticmethod
    def run(wrapper, config, found_villages):
        """
        wrapper: WebWrapper compartilhado do bot (TWB.wrapper)
        config: config completo do bot
        found_villages: lista de village_id gerenciados e presentes neste ciclo
        """
        cfg = config.get("statue", {})
        if not cfg.get("enabled", False):
            return
        if not found_villages:
            return

        village_id = found_villages[0]
        try:
            page = StatuePage(wrapper, village_id)
        except RuntimeError as e:
            # Timeout/sessão expirada — mesmo tratamento não-fatal usado por
            # OverviewPage: loga e tenta de novo no próximo ciclo.
            logger.warning("StatueManager: %s", e)
            return
        except Exception as e:
            logger.error("StatueManager: erro inesperado lendo screen=statue: %s", e)
            return

        data = {
            "fetched_at": int(time.time()),
            "village_used": village_id,
            "statue_level": page.statue_level,
            "knights": page.knights,
            "locked_slot_thresholds": page.locked_slot_thresholds,
        }
        FileManager.save_json_file(data, CACHE_PATH)
        logger.debug(
            "StatueManager: %d paladino(s) lido(s), %d slot(s) bloqueado(s)",
            len(page.knights), len(page.locked_slot_thresholds)
        )
