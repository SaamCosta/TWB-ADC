"""
Feature 9 — Transferência automática de recursos entre aldeias

Reformulada em 2026-08-11. A versão anterior tinha uma regra só: doadora era
quem passasse de `threshold_pct` da **própria** capacidade, receptora era quem
tivesse `required_resources` pendente. Percentual da própria capacidade é o
sinal certo para "vou transbordar" e o sinal errado para "tenho sobra": uma
aldeia com armazém 30 (500.000) e 42.000 de ferro está a 8% da capacidade e
mesmo assim é rica em termos absolutos -- 42.000 de ferro é cinco armazéns
inteiros de uma aldeia recém-conquistada. Na prática as duas aldeias maiores
da conta nunca podiam doar (precisariam de 8x mais recurso do que tinham) e o
sistema não movia nada.

Agora são duas regras com intenções diferentes, avaliadas na mesma passada:

  1. **Resgate de transbordo** — o armazém vai estourar e a produção começaria
     a ser jogada fora. Medido em percentual da própria capacidade, que aqui é
     exatamente o sinal correto. Não olha necessidade de ninguém.
  2. **Abastecimento por necessidade** — sobra em termos absolutos, acima de um
     piso de reserva própria (`need_donor_floor`). Olha quem está de fato
     travado (`required_resources`).

Ordem de precedência: necessidade primeiro, transbordo depois. Mandar o
excedente para quem precisa resolve os dois problemas de uma vez; só o que
sobra depois disso é despejado na aldeia com mais espaço livre ("banco").
O volume de transbordo é isento do `need_donor_floor` -- aquele recurso ia ser
perdido de qualquer forma, então doá-lo nunca é pior que mantê-lo.
"""
import logging
import os
import time

from core.extractors import Extractor
from core.filemanager import FileManager

logger = logging.getLogger("ResourceSharing")

RESOURCES = ["wood", "stone", "iron"]

# Feature 20: histórico de transferências para o webmanager (processo
# separado, só enxerga o que for persistido em cache/). Mantém só as N
# entradas mais recentes para não crescer sem limite.
HISTORY_PATH = "cache/resource_sharing/history.json"
HISTORY_MAX_ENTRIES = 300

# Cada mercador carrega 1000 recursos no total (qualquer mistura entre
# madeira/argila/ferro). Confirmado no world config público do br143 em
# 2026-08-11: <MerchantBonus>0</MerchantBonus>, ou seja, sem bônus de carga.
# Configurável porque mundos com bônus existem, e o mesmo valor já é assumido
# no caminho premium (`PremiumExchange.optimize_n(..., size=1000)`).
DEFAULT_MERCHANT_CAPACITY = 1000


class ResourceSharingManager:
    """
    Gerencia transferência direta de recursos entre aldeias do próprio jogador.

    Roda a partir da aldeia atual (a "doadora" candidata) e só decide envios
    que saem dela. As outras aldeias entram apenas como receptoras, lidas de
    `cache/managed/*.json` -- ou seja, com até um ciclo de atraso, o que é
    aceitável para recurso (o erro é da ordem da produção de um ciclo) mas
    não seria para tropa.

    Fluxo por ciclo:
      1. Calcula quanto esta aldeia pode doar por recurso (as duas regras)
      2. Lê quantos mercadores existem -> orçamento de carga do ciclo
      3. Distribui primeiro para quem está travado, depois o transbordo restante
         para a aldeia com mais espaço livre
      4. Envia via resman.send_resources()
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
        Só envia se a aldeia atual tiver algo a doar por alguma das duas regras.
        """
        cfg = self.sharing_cfg
        if not cfg.get("enabled", False):
            return

        village_states = self._load_all_village_states()
        if len(village_states) < 2:
            logger.debug("ResourceSharing: menos de 2 aldeias no cache, nada a fazer")
            return

        if self.current_village_id not in village_states:
            logger.debug("ResourceSharing: estado da aldeia atual não encontrado no cache")
            return

        storage = current_resman.storage
        if not storage:
            return

        giveable, overflow = self._calculate_giveable(current_resman, storage, cfg)
        if not giveable:
            logger.debug(
                "ResourceSharing: aldeia %s não tem nada a doar por nenhuma das "
                "duas regras", self.current_village_id
            )
            return

        # Orçamento de carga do ciclo inteiro. O bug da versão anterior era
        # contar *transferências* (sent_count += 1) como se cada envio custasse
        # um mercador; custa um mercador a cada ~1000 recursos, então um envio
        # de 4.000 de madeira consome 4 de uma vez.
        carry_budget, merchants = self._get_carry_budget(cfg)
        if merchants < 1:
            logger.info("ResourceSharing: sem mercadores disponíveis em %s", self.current_village_id)
            self._log_event(
                source=self.current_village_id, target=None, resources=None,
                success=False, reason="no_merchants",
            )
            return

        plan = self._build_plan(village_states, giveable, overflow, cfg, carry_budget)
        if not plan:
            logger.debug(
                "ResourceSharing: aldeia %s tem excedente (%s) mas nenhuma "
                "receptora elegível neste ciclo", self.current_village_id, giveable
            )
            return

        for target_id, to_send, kind in plan:
            success = current_resman.send_resources(
                target_village_id=target_id,
                resources=to_send,
            )

            if success:
                logger.info(
                    "ResourceSharing: enviado %s de %s → %s (regra: %s)",
                    to_send, self.current_village_id, target_id, kind
                )
                self._log_event(
                    source=self.current_village_id, target=target_id, resources=to_send,
                    success=True, reason=None, kind=kind,
                )
            else:
                logger.warning(
                    "ResourceSharing: falha ao enviar de %s → %s (regra: %s)",
                    self.current_village_id, target_id, kind
                )
                self._log_event(
                    source=self.current_village_id, target=target_id, resources=to_send,
                    success=False, reason="send_failed", kind=kind,
                )
                # Um envio recusado normalmente significa que a premissa do
                # plano (mercadores, estoque) não vale mais -- seguir para o
                # próximo alvo com o mesmo plano só gastaria requisições.
                break

    # ------------------------------------------------------------------
    # Regra 1 + Regra 2: quanto esta aldeia pode doar
    # ------------------------------------------------------------------

    def _calculate_giveable(self, resman, storage, cfg):
        """
        Retorna (giveable, overflow), ambos dicts recurso -> quantidade:

          overflow[res] -- volume que precisa sair para o armazém não estourar
                           (regra 1). Isento do piso de reserva: esse recurso
                           seria perdido de qualquer jeito.
          giveable[res] -- o máximo entre o transbordo e a sobra absoluta acima
                           de `need_donor_floor` (regra 2). É o teto do que pode
                           sair da aldeia neste ciclo.

        `resman.in_need_amount(res)` é descontado nas duas regras: é o que esta
        aldeia já reservou para a própria fila de construção/recrutamento.
        """
        trigger_pct = self._pct(cfg.get("overflow_trigger_pct", 85))
        target_pct = self._pct(cfg.get("overflow_target_pct", 60))
        donor_floor = int(cfg.get("need_donor_floor", 20000))
        overflow_enabled = cfg.get("overflow_enabled", True)
        need_enabled = cfg.get("need_enabled", True)

        # Um alvo acima do gatilho não esvaziaria nada: trata como "descer até
        # o gatilho" em vez de silenciosamente não fazer nada.
        if target_pct >= trigger_pct:
            target_pct = trigger_pct

        giveable = {}
        overflow = {}

        for res in RESOURCES:
            actual = int(resman.actual.get(res, 0) or 0)
            reserved = int(resman.in_need_amount(res) or 0)
            free = max(0, actual - reserved)

            over = 0
            if overflow_enabled and actual >= int(storage * trigger_pct):
                over = min(free, max(0, actual - int(storage * target_pct)))

            surplus = 0
            if need_enabled and free > donor_floor:
                surplus = free - donor_floor

            total = max(over, surplus)
            if total > 0:
                giveable[res] = total
                overflow[res] = over

        return giveable, overflow

    # ------------------------------------------------------------------
    # Montagem do plano de envios
    # ------------------------------------------------------------------

    def _build_plan(self, village_states, giveable, overflow, cfg, carry_budget):
        """
        Devolve uma lista de (target_village_id, {res: amount}, kind) já
        limitada pelo orçamento de carga, pelo espaço livre de cada receptora e
        por `max_sends_per_cycle`.

        Nada aqui faz requisição -- o plano inteiro é montado a partir do cache
        e só depois executado, para que o orçamento de mercadores seja
        respeitado globalmente e não por envio.
        """
        min_send = int(cfg.get("min_send_amount", 500))
        fill_max_pct = self._pct(cfg.get("receiver_fill_max_pct", 90))
        max_sends = int(cfg.get("max_sends_per_cycle", 3))

        remaining = dict(giveable)
        overflow_left = dict(overflow)
        carry_left = carry_budget
        plan = []

        receivers = self._eligible_receivers(village_states)

        # --- Etapa 1: quem está travado -------------------------------
        # Vem primeiro de propósito: mandar o excedente para quem precisa
        # resolve necessidade e transbordo de uma vez só.
        if cfg.get("need_enabled", True):
            ranked = self._rank_by_priority(receivers, cfg.get("priority", "new_villages"))
            for vid, state in ranked:
                if len(plan) >= max_sends or carry_left < min_send:
                    break
                to_send = self._fit_send(
                    state, remaining, carry_left, min_send, fill_max_pct,
                    cap_fn=lambda res: self._deficit(state, res),
                )
                if to_send:
                    plan.append((vid, to_send, "need"))
                    carry_left -= self._consume(to_send, remaining, overflow_left)

        # --- Etapa 2: despejar o transbordo restante no "banco" -------
        # Só o que ainda é transbordo depois da etapa 1: sobra acima do
        # `need_donor_floor` sem ninguém precisando dela fica em casa, onde é
        # útil, em vez de virar tráfego de mercador.
        if cfg.get("overflow_enabled", True):
            dumpable = {res: amt for res, amt in overflow_left.items() if amt >= min_send}
            if dumpable:
                already_planned = {vid for vid, _, _ in plan}
                for vid, state in self._rank_by_free_space(receivers, dumpable, fill_max_pct):
                    if len(plan) >= max_sends or carry_left < min_send:
                        break
                    # `_headroom` sai do cache, que não conhece o envio que a
                    # etapa 1 acabou de planejar para esta mesma aldeia -- somar
                    # um segundo envio em cima transbordaria a receptora. Pular
                    # é mais simples (e mais fácil de revisar) do que rastrear
                    # o comprometido por aldeia, e custa no máximo adiar um
                    # despejo de transbordo para o ciclo seguinte.
                    if vid in already_planned:
                        continue
                    to_send = self._fit_send(
                        state, dumpable, carry_left, min_send, fill_max_pct,
                        cap_fn=lambda res: dumpable.get(res, 0),
                    )
                    if to_send:
                        plan.append((vid, to_send, "overflow"))
                        carry_left -= self._consume(to_send, remaining, overflow_left, dumpable)

        return plan

    def _fit_send(self, state, pool, carry_left, min_send, fill_max_pct, cap_fn):
        """
        Monta o dict {res: amount} de um envio para uma receptora, limitado
        simultaneamente por: o que a doadora pode dar (`pool`), o teto da regra
        em questão (`cap_fn`), o espaço livre da receptora e o que ainda cabe
        nos mercadores do ciclo (`carry_left`).
        """
        to_send = {}
        used = 0
        for res in RESOURCES:
            available = pool.get(res, 0)
            if available < min_send:
                continue
            cap = cap_fn(res)
            if cap <= 0:
                continue
            headroom = self._headroom(state, res, fill_max_pct)
            if headroom <= 0:
                continue
            amount = min(available, cap, headroom, carry_left - used)
            # Múltiplo de 10 evita envios de valor irrisório/quebrado.
            amount = (amount // 10) * 10
            if amount >= min_send:
                to_send[res] = amount
                used += amount
        return to_send

    @staticmethod
    def _consume(to_send, *pools):
        """
        Desconta o enviado de cada pool passado e devolve o total de recursos,
        que é o que efetivamente sai do orçamento de mercadores.
        """
        total = 0
        for res, amt in to_send.items():
            total += amt
            for pool in pools:
                if res in pool:
                    pool[res] = max(0, pool[res] - amt)
        return total

    # ------------------------------------------------------------------
    # Leitura das receptoras
    # ------------------------------------------------------------------

    def _eligible_receivers(self, village_states):
        """
        Aldeias que podem receber recurso nossa neste ciclo. Devolve uma lista
        de (village_id, state).

        Exclusões, todas por motivo concreto:
          - a própria aldeia atual (não dá para enviar para si mesma);
          - sem mercado construído: o jogo exige mercado nas **duas** pontas, e
            a versão anterior só checava o da origem;
          - sem `storage` no cache: capacidade desconhecida significa que não dá
            para calcular espaço livre, e enviar às cegas transborda a receptora.
            Chave nova (2026-08-11) -- toda aldeia passa a ter depois de um ciclo
            completo, então isso só silencia o primeiro ciclo após a atualização;
          - sob ataque: recurso entregue numa aldeia prestes a ser saqueada é
            recurso entregue ao atacante.
        """
        receivers = []
        for vid, state in village_states.items():
            if vid == self.current_village_id:
                continue
            if not (state.get("buidling_levels") or {}).get("market"):
                logger.debug("ResourceSharing: %s sem mercado, não pode receber", vid)
                continue
            if not state.get("storage"):
                logger.debug(
                    "ResourceSharing: %s ainda sem capacidade de armazém no cache, "
                    "pulando até o próximo ciclo dela", vid
                )
                continue
            if state.get("under_attack"):
                logger.debug("ResourceSharing: %s sob ataque, não vou abastecer", vid)
                continue
            receivers.append((vid, state))
        return receivers

    @staticmethod
    def _deficit(state, res):
        """
        Quanto falta para a receptora destravar o que ela registrou em
        `required_resources`, já descontando o que ela tem em mãos.

        `ResourceManager.request()` grava o montante **total** da ação (não o
        que falta) e `check_state()` zera a entrada quando o estoque alcança
        esse montante -- então somar as entradas e subtrair o estoque atual é o
        déficit real. A versão anterior somava sem descontar o estoque e podia
        mandar recurso que a aldeia já tinha.
        """
        required = state.get("required_resources") or {}
        needed = 0
        for source_needs in required.values():
            if isinstance(source_needs, dict):
                amount = source_needs.get(res, 0)
                if isinstance(amount, (int, float)) and amount > 0:
                    needed += int(amount)
        if needed <= 0:
            return 0
        have = int((state.get("resources") or {}).get(res, 0) or 0)
        return max(0, needed - have)

    @staticmethod
    def _headroom(state, res, fill_max_pct):
        """
        Espaço utilizável da receptora para um recurso. `fill_max_pct` deixa uma
        margem abaixo da capacidade real porque o recurso leva tempo de viagem e
        a produção dela continua correndo nesse meio tempo -- encher até 100% no
        papel significa transbordar na chegada.
        """
        storage = int(state.get("storage") or 0)
        if storage <= 0:
            return 0
        current = int((state.get("resources") or {}).get(res, 0) or 0)
        return max(0, int(storage * fill_max_pct) - current)

    def _rank_by_priority(self, receivers, priority_mode):
        """
        Ordena as receptoras da etapa de necessidade.

        'new_villages': menor pontuação primeiro. P2-27: antes ordenava por
        `last_run` ASC com o comentário "recém-conquistadas rodaram menos
        ciclos", mas `last_run` é reescrito a cada ciclo para toda aldeia
        (village.py::set_cache_vars) -- ordenava ruído. Pontos são o sinal real
        de aldeia nova disponível no mesmo cache.
        """
        needy = [
            (vid, state) for vid, state in receivers
            if any(self._deficit(state, res) > 0 for res in RESOURCES)
        ]
        if priority_mode == "new_villages":
            def newness(entry):
                state = entry[1]
                points = state.get("points")
                if points is None:
                    points = (state.get("buidling_levels") or {}).get("main", 0)
                try:
                    return int(points)
                except (TypeError, ValueError):
                    return 0
            needy.sort(key=newness)
        else:
            def total_need(entry):
                return sum(self._deficit(entry[1], res) for res in RESOURCES)
            needy.sort(key=total_need, reverse=True)
        return needy

    def _rank_by_free_space(self, receivers, dumpable, fill_max_pct):
        """
        Ordena as receptoras da etapa de transbordo: quem tem mais espaço livre
        absoluto para os recursos que sobraram vem primeiro. É essa regra que
        elege a aldeia de armazém grande como "banco" -- exatamente o papel que
        o percentual da capacidade própria nunca conseguiria expressar.
        """
        def free_space(entry):
            state = entry[1]
            return sum(self._headroom(state, res, fill_max_pct) for res in dumpable)
        ranked = [entry for entry in receivers if free_space(entry) > 0]
        ranked.sort(key=free_space, reverse=True)
        return ranked

    # ------------------------------------------------------------------
    # Helpers internos
    # ------------------------------------------------------------------

    @staticmethod
    def _pct(value):
        """Converte um percentual de config (0-100) para fração, com guarda."""
        try:
            pct = float(value) / 100.0
        except (TypeError, ValueError):
            return 0.0
        return min(1.0, max(0.0, pct))

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

    def _log_event(self, source, target, resources, success, reason, kind=None):
        """
        Feature 20: acrescenta uma entrada ao histórico persistido em
        HISTORY_PATH, para o webmanager (processo separado) poder mostrar
        quanto foi transferido, quando, por qual das duas regras, e falhas.
        Best-effort — nunca deve derrubar o ciclo do bot por erro de I/O.
        """
        try:
            # twb.py::start() já cria cache/resource_sharing na inicialização
            # normal do bot, mas recriar aqui é defensivo/idempotente caso
            # este método seja chamado fora desse fluxo (ex: testes).
            FileManager.create_directory(FileManager.get_path(os.path.dirname(HISTORY_PATH)))
            history = FileManager.load_json_file(HISTORY_PATH) or []
            if not isinstance(history, list):
                history = []
            history.append({
                "timestamp": int(time.time()),
                "source": source,
                "target": target,
                "resources": resources,
                "success": bool(success),
                "reason": reason,
                "kind": kind,
            })
            if len(history) > HISTORY_MAX_ENTRIES:
                history = history[-HISTORY_MAX_ENTRIES:]
            FileManager.save_json_file(history, HISTORY_PATH)
        except Exception as e:
            logger.warning("ResourceSharing: falha ao gravar histórico: %s", e)

    @staticmethod
    def _dump_once(path, content):
        """
        Salva `content` em `path` só se o arquivo ainda não existir -- amostra
        de diagnóstico, não log. Escrever a cada ciclo encheria o disco sem
        acrescentar informação, já que o markup é sempre o mesmo.
        Best-effort: nunca derruba o ciclo por erro de I/O.
        """
        try:
            full = FileManager.get_path(path)
            if os.path.exists(full):
                return
            FileManager.create_directory(FileManager.get_path(os.path.dirname(path)))
            with open(full, "w", encoding="utf-8") as fh:
                fh.write(content)
            logger.info("ResourceSharing: amostra de markup salva em %s", full)
        except Exception as e:
            logger.debug("ResourceSharing: falha ao salvar amostra: %s", e)

    def _get_carry_budget(self, cfg):
        """
        Devolve (carga_disponível, mercadores) para o ciclo desta aldeia.

        A carga sai do próprio jogo sempre que possível. O markup real do br143
        (confirmado em 2026-08-11) traz os três números juntos:

            market_merchant_available_count  13
            market_merchant_total_count      13
            market_merchant_max_transport    13000

        `max_transport / total` é a capacidade real por mercador, então mundos
        com bônus de mercador funcionam sem tocar em `merchant_capacity` -- a
        config vira só o fallback de quando a página não puder ser lida.

        Nota sobre a tela: `mode=traders` ("Estado do comerciante") é usada aqui
        porque existe e não exige um `target` na URL, e o orçamento precisa ser
        conhecido *antes* de escolher os alvos do plano. A anterior,
        `mode=send_res`, nunca existiu -- o jogo devolvia "Modo inválido", e era
        essa a causa de o contador nunca ser encontrado (o regex sempre esteve
        certo). Ver ResourceManager.send_resources.
        """
        fallback_capacity = int(
            cfg.get("merchant_capacity", DEFAULT_MERCHANT_CAPACITY) or DEFAULT_MERCHANT_CAPACITY
        )
        try:
            url = f"game.php?village={self.current_village_id}&screen=market&mode=traders"
            res = self.wrapper.get_url(url=url)
            if not res:
                return 0, 0

            data = Extractor.merchant_data(res)
            if not data:
                # Assume 1 mercador para não travar o sistema inteiro por causa
                # de markup inesperado. WARNING e não DEBUG de propósito: um
                # envio dimensionado para 1 mercador quando existem 13 é
                # desperdício silencioso, e a amostra abaixo é o que permite
                # corrigir com o markup na mão em vez de por tentativa e erro.
                logger.warning(
                    "ResourceSharing: não foi possível ler os mercadores disponíveis "
                    "em %s (markup inesperado), assumindo 1", self.current_village_id
                )
                self._dump_once("cache/resource_sharing/market_traders.html", res.text)
                return fallback_capacity, 1

            available = data["available"]
            per_merchant = fallback_capacity
            if data["total"] and data["max_transport"]:
                per_merchant = max(1, data["max_transport"] // data["total"])

            logger.debug(
                "ResourceSharing: %s tem %s de %s mercadores livres, carga %s",
                self.current_village_id, available, data["total"],
                available * per_merchant
            )
            return available * per_merchant, available
        except Exception as e:
            logger.warning("ResourceSharing: erro ao verificar mercadores: %s", e)
            return 0, 0
