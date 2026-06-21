"""
Feature 9 — Transferência automática de recursos entre aldeias
Lê o cache de todas as aldeias gerenciadas, identifica doadoras e receptoras,
e envia recursos via mercado interno (send_res) sem necessidade de troca.
"""
import logging
import os
import time

from core.filemanager import FileManager

logger = logging.getLogger("ResourceSharing")

RESOURCES = ["wood", "stone", "iron"]


class ResourceSharingManager:
    """
    Gerencia transferência direta de recursos entre aldeias do próprio jogador.

    Fluxo por ciclo:
      1. Lê cache/managed/*.json de todas as aldeias gerenciadas
      2. Classifica cada aldeia como doadora / receptora / neutra por recurso
      3. Ordena receptoras por prioridade (new_villages primeiro)
      4. Para cada par doadora→receptora viável, chama resman.send_resources()
    """

    def __init__(self, wrapper, current_village_id, config):
        self.wrapper = wrapper
        self.current_village_id = str(current_village_id)
        self.config = config
        self.sharing_cfg = config.get("resource_sharing", {})

    # ------------------------------------------------------------------
    # Ponto de entrada principal
    # ------------------------------------------------------------------

    def run(self, current_resman):
        """
        Executa o ciclo de compartilhamento a partir da aldeia atual.
        Só envia se a aldeia atual for doadora de algum recurso.
        """
        if not self.sharing_cfg.get("enabled", False):
            return

        threshold_pct = self.sharing_cfg.get("threshold_pct", 80) / 100.0
        priority_mode = self.sharing_cfg.get("priority", "new_villages")

        # Mapa completo de todas as aldeias gerenciadas (via cache)
        village_states = self._load_all_village_states()

        if len(village_states) < 2:
            logger.debug("ResourceSharing: menos de 2 aldeias no cache, nada a fazer")
            return

        current_state = village_states.get(self.current_village_id)
        if not current_state:
            logger.debug("ResourceSharing: estado da aldeia atual não encontrado no cache")
            return

        storage = current_resman.storage
        if not storage:
            return

        # Verifica se esta aldeia tem excesso em algum recurso
        surplus = self._calculate_surplus(current_resman, storage, threshold_pct)
        if not surplus:
            logger.debug("ResourceSharing: aldeia %s sem excedente, nada a enviar", self.current_village_id)
            return

        # Identifica receptoras e ordena por prioridade
        receivers = self._find_receivers(village_states, priority_mode)
        if not receivers:
            logger.debug("ResourceSharing: nenhuma aldeia receptora encontrada")
            return

        # Verifica mercadores disponíveis antes de tentar enviar
        merchants_available = self._get_available_merchants()
        if merchants_available < 1:
            logger.info("ResourceSharing: sem mercadores disponíveis em %s", self.current_village_id)
            return

        sent_count = 0
        for receiver_id, receiver_state in receivers:
            if sent_count >= merchants_available:
                break

            needed = self._get_needed_resources(receiver_state)
            if not needed:
                continue

            to_send = {}
            for res in needed:
                if res in surplus and surplus[res] > 0:
                    # Envia o mínimo entre o excedente disponível e o que a receptora precisa
                    amount = min(surplus[res], needed[res])
                    # Arredonda para múltiplo de 10 (evita envios irrisórios)
                    amount = (amount // 10) * 10
                    if amount >= 100:
                        to_send[res] = amount

            if not to_send:
                continue

            success = current_resman.send_resources(
                target_village_id=receiver_id,
                resources=to_send,
            )

            if success:
                logger.info(
                    "ResourceSharing: enviado %s de %s → %s",
                    to_send, self.current_village_id, receiver_id
                )
                # Desconta do excedente local para evitar envios duplos no mesmo ciclo
                for res, amt in to_send.items():
                    surplus[res] = max(0, surplus[res] - amt)
                sent_count += 1
            else:
                logger.warning(
                    "ResourceSharing: falha ao enviar de %s → %s",
                    self.current_village_id, receiver_id
                )

    # ------------------------------------------------------------------
    # Helpers internos
    # ------------------------------------------------------------------

    def _load_all_village_states(self):
        """
        Lê todos os arquivos cache/managed/*.json e retorna um dict
        keyed por village_id.
        """
        states = {}
        managed_ids = set(self.config.get("villages", {}).keys())

        try:
            files = FileManager.list_directory("cache/managed", ends_with=".json")
        except Exception:
            return states

        for fname in files:
            vid = fname.replace(".json", "")
            if vid not in managed_ids:
                continue
            data = FileManager.load_json_file(f"cache/managed/{fname}")
            if data:
                states[vid] = data

        return states

    def _calculate_surplus(self, resman, storage, threshold_pct):
        """
        Retorna dict com o excedente disponível por recurso.
        Excedente = actual - threshold - requested (para não roubar recursos
        que já estão reservados para construção/recrutamento).
        """
        surplus = {}
        threshold = int(storage * threshold_pct)

        for res in RESOURCES:
            actual = resman.actual.get(res, 0)
            if actual <= threshold:
                continue
            # Desconta o que já está reservado internamente
            reserved = resman.in_need_amount(res)
            available = actual - reserved
            excess = available - threshold
            if excess > 0:
                surplus[res] = excess

        return surplus

    def _find_receivers(self, village_states, priority_mode):
        """
        Retorna lista ordenada de (village_id, state) das aldeias receptoras.
        Receptora = tem required_resources com algum valor > 0.
        Prioridade 'new_villages': aldeias com last_run mais recente primeiro
        (proxy para aldeias novas que ainda estão em desenvolvimento).
        """
        receivers = []

        for vid, state in village_states.items():
            if vid == self.current_village_id:
                continue

            required = state.get("required_resources", {})
            # Verifica se há alguma necessidade pendente
            has_need = False
            for source_needs in required.values():
                if isinstance(source_needs, dict):
                    if any(v > 0 for v in source_needs.values()):
                        has_need = True
                        break

            if has_need:
                receivers.append((vid, state))

        if not receivers:
            return []

        # Ordenação por prioridade
        if priority_mode == "new_villages":
            # Aldeias com last_run mais recente (recém-conquistadas têm last_run menor
            # pois rodaram menos ciclos — ordena ASC para priorizá-las)
            receivers.sort(key=lambda x: x[1].get("last_run", 0))
        else:
            # Modo padrão: mais necessidade total primeiro
            def total_need(state):
                total = 0
                for source_needs in state.get("required_resources", {}).values():
                    if isinstance(source_needs, dict):
                        total += sum(v for v in source_needs.values() if v > 0)
                return total
            receivers.sort(key=lambda x: total_need(x[1]), reverse=True)

        return receivers

    def _get_needed_resources(self, state):
        """
        Agrega todas as necessidades pendentes de uma aldeia em um único dict.
        """
        needed = {}
        required = state.get("required_resources", {})

        for source_needs in required.values():
            if not isinstance(source_needs, dict):
                continue
            for res, amount in source_needs.items():
                if res in RESOURCES and amount > 0:
                    needed[res] = needed.get(res, 0) + amount

        return needed

    def _get_available_merchants(self):
        """
        Consulta a tela de mercado da aldeia atual para saber quantos
        mercadores estão disponíveis para envio.
        """
        try:
            url = f"game.php?village={self.current_village_id}&screen=market&mode=send_res"
            res = self.wrapper.get_url(url=url)
            if not res:
                return 0
            # O jogo exibe algo como: market_merchant_available_count">N<
            import re
            match = re.search(r'market_merchant_available_count["\s>]+(\d+)', res.text)
            if match:
                return int(match.group(1))
            # Fallback: se não achou o padrão, assume 1 para tentar
            logger.debug("ResourceSharing: não foi possível ler mercadores disponíveis, assumindo 1")
            return 1
        except Exception as e:
            logger.warning("ResourceSharing: erro ao verificar mercadores: %s", e)
            return 0
