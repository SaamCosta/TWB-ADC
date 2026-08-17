"""
Feature 25 (fase 1) — leitura periódica do inventário, sem nenhuma ativação
de item (a política de "qual boost usar e quando" é a fase 2 e ainda não tem
desenho — ver docs/backlog.md Feature 25).

Roda uma vez por ciclo completo do bot (não por aldeia — o inventário é do
jogador, compartilhado por toda a conta), a partir da primeira aldeia
gerenciada disponível. Persiste em cache/inventory/status.json para o
webmanager ler — mesmo padrão de game/statue_manager.py (Feature 24 fase 1).

Opt-in via config["inventory"]["enabled"] (default false): são duas
requisições HTTP novas por ciclo a uma tela que o bot nunca acessou, então
fica desligada até o usuário habilitar explicitamente.
"""
import logging
import time

from core.filemanager import FileManager
from pages.inventory import InventoryPage

logger = logging.getLogger("InventoryManager")

CACHE_PATH = "cache/inventory/status.json"


class InventoryManager:
    @staticmethod
    def run(wrapper, config, found_villages):
        """
        wrapper: WebWrapper compartilhado do bot (TWB.wrapper)
        config: config completo do bot
        found_villages: lista de village_id gerenciados e presentes neste ciclo
        """
        cfg = config.get("inventory", {})
        if not cfg.get("enabled", False):
            return
        if not found_villages:
            return

        village_id = found_villages[0]
        try:
            page = InventoryPage(wrapper, village_id)
        except RuntimeError as e:
            # Timeout/sessão expirada/markup novo — não-fatal, igual ao
            # StatueManager: loga e tenta de novo no próximo ciclo.
            logger.warning("InventoryManager: %s", e)
            return
        except Exception as e:
            logger.error(
                "InventoryManager: erro inesperado lendo screen=inventory: %s", e
            )
            return

        items = page.items
        data = {
            "fetched_at": int(time.time()),
            "village_used": village_id,
            "item_types": page.item_types,
            "item_categories": page.item_categories,
            "items": items,
            "total_distinct": len(items),
            "total_amount": sum(item["amount"] for item in items),
        }
        FileManager.save_json_file(data, CACHE_PATH)
        logger.debug(
            "InventoryManager: %d item(ns) distinto(s), %d unidade(s) no total",
            data["total_distinct"], data["total_amount"]
        )
        if not page.enums_available:
            # Os itens continuam legíveis, só sem rótulo de tipo/categoria.
            logger.warning(
                "InventoryManager: enums de screen=inventory ausentes "
                "(Inventory.item_types/item_categories) — tipos e categorias "
                "vão aparecer como número em /inventory"
            )
