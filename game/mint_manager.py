"""
Cunhagem (§8.55) -- o que roda da conta inteira, uma instância por processo.

Três coisas, todas pela aba "Cunhagem" do painel:

1. **Campanha de itens** (Bônus de bandeira + Decreto Real, e o Cofre de
   Guerra se marcado). Só começa com a aprovação do painel -- o bot nunca
   gasta item por conta própria. Cada item é conferido pela RELEITURA do
   inventário (a quantidade tem que cair), no mesmo desenho do upgrade de
   bandeira da §8.54: aceitar "veio JSON" como sucesso foi o bug de lá.
2. **Roteamento para o hub**: as outras aldeias mandam o que passa do piso
   para a aldeia de menor custo de moeda (quem envia é a própria aldeia, em
   `ResourceSharingManager.run_mint_route`; aqui só se decide o hub). Ligado
   pela config ou, durante a campanha, sempre. O hub mantém uma sessão de
   cunhagem automática de 8 h, renovada aqui, e cunha o máximo da tela
   (o "(N)" ao lado do campo) a cada renovação.
3. **Cunhagem automática diária**: num horário fixo, antes de o bot entrar no
   horário inativo, inicia a sessão de 8 h em todas as aldeias com academia.

Endpoints, conferidos antes de escrever:

  * item: `POST screen=inventory&ajaxaction=consume` com `item_key` e
    `amount` (`Inventory.dff6db.js_`, `consumeItem`). O diálogo de ativação do
    Bônus de bandeira diz "serão aplicados em sua aldeia atual" e não tem
    seletor: a aldeia é a da URL, por isso o POST sai com `village=<hub>`.
  * cunhagem automática: `POST screen=snob&action=start_auto_minting_session`
    sem corpo (formulário "Ativar" da academia, captura de 04/10).
  * cunhagem em lote: `POST screen=snob&action=coin` com `count=N`.

Não sabido ainda, medido pela própria campanha (fica no diário dela): se o
Decreto soma ou multiplica com a bandeira -- o custo da academia é lido antes e
depois de cada item.
"""
import datetime
import logging
import os
import re
import time

from core import mint_store
from core.filemanager import FileManager
from core.notification import Notification
from game import mint_planner
from game.inventory_manager import InventoryManager, CACHE_PATH as INVENTORY_CACHE
from pages import academy
from pages.inventory import fetch_inventory_payload, amounts_from_payload

logger = logging.getLogger("Mint")

FLAG_BONUS_ID = "3021"
DECREE_ID = "3023"
WAR_CHEST_ID = "3077"
ITEM_LABELS = {
    FLAG_BONUS_ID: "Bônus de bandeira",
    DECREE_ID: "Decreto Real",
    WAR_CHEST_ID: "Cofre de Guerra Pequeno",
}

AUTO_MINT_SECONDS = 8 * 3600
FLAG_BONUS_DEFAULT_SECONDS = 48 * 3600
# Sessão do hub que não deu para confirmar, ou leitura que falhou: tenta de
# novo depois disto, não a cada checkpoint (são dezenas por ciclo).
HUB_RETRY_SECONDS = 15 * 60
ACTIVATION_RETRY_SECONDS = 5 * 60
# Horário diário perdido (bot fora do ar) só é recuperado dentro desta janela;
# depois disso a sessão de 8 h já cairia em pleno horário ativo.
DAILY_MAX_LATE = 3 * 3600

DURATION_RE = re.compile(r"(\d+):(\d{2}):(\d{2})")


def item_keys(amounts, item_id):
    """Chaves (`3021_0`, …) de um item_id, da maior quantidade para a menor."""
    prefix = "%s_" % item_id
    keys = [k for k in amounts if k.startswith(prefix)]
    return sorted(keys, key=lambda k: -amounts.get(k, 0))


def item_duration_seconds(payload, key, default):
    """Duração lida da descrição do item ("Duração da recompensa: 48:00:00")."""
    entry = ((payload or {}).get("data") or {}).get(key) or {}
    for block in entry.get("descriptions") or []:
        text = str((block or {}).get("text") or "")
        if "Dura" in text:
            match = DURATION_RE.search(text)
            if match:
                h, m, s = (int(g) for g in match.groups())
                return h * 3600 + m * 60 + s
    return default


def read_inventory(wrapper, village_id):
    """
    Payload do inventário, ou None se a resposta não tem a forma esperada.

    Exige `inventory` presente (dict, ou a lista vazia que o PHP manda para
    inventário vazio): sem ele `amounts_from_payload` daria 0 para tudo, e a
    releitura depois de um consumo leria "a quantidade caiu" sem ter caído --
    valor de falha disfarçado de resultado (sexto padrão).
    """
    payload = fetch_inventory_payload(wrapper, village_id)
    if payload is None or not isinstance(payload.get("inventory"), (dict, list)):
        return None
    return payload


def consume_error(result):
    """Motivo da recusa na resposta do `consume`, ou None (que NÃO é sucesso)."""
    if result is None:
        return "sem resposta do servidor"
    if not isinstance(result, dict):
        return None
    error = result.get("error")
    inner = result.get("response")
    if not error and isinstance(inner, dict):
        error = inner.get("error")
    if not error:
        return None
    if isinstance(error, list):
        error = "; ".join(str(e) for e in error)
    return str(error)


def daily_due(now, time_str, done_date):
    """
    (devido, data) -- devido se já passou do horário de hoje, há menos de
    DAILY_MAX_LATE, e hoje ainda não foi concluído.
    """
    local = datetime.datetime.fromtimestamp(now)
    try:
        hh, mm = (int(p) for p in str(time_str).split(":"))
    except (TypeError, ValueError):
        return False, None
    sched = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
    today = local.strftime("%Y-%m-%d")
    late = (local - sched).total_seconds()
    return (0 <= late <= DAILY_MAX_LATE and done_date != today), today


def daily_next(now, time_str):
    """Timestamp do próximo horário diário (hoje se ainda não passou)."""
    local = datetime.datetime.fromtimestamp(now)
    try:
        hh, mm = (int(p) for p in str(time_str).split(":"))
    except (TypeError, ValueError):
        return None
    sched = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if sched.timestamp() <= now:
        sched += datetime.timedelta(days=1)
    return sched.timestamp()


class MintManager:
    def __init__(self, wrapper):
        self.wrapper = wrapper
        self.config = {}
        self.found_villages = []
        self.states = {}
        self.route = None
        self.ranking = []
        self.state = mint_store.load_state()
        self._busy = False
        self._samples_saved = set()
        # Ativação que não pôde seguir (tela não leu): a próxima tentativa
        # espera ACTIVATION_RETRY_SECONDS, senão o sono encurtado para "agora"
        # viraria um ciclo por minuto a noite inteira.
        self._activation_attempt_at = 0

    # ------------------------------------------------------------ config

    def cfg(self):
        return (self.config or {}).get("minting") or {}

    def _managed_states(self):
        managed = set(((self.config or {}).get("villages") or {}).keys())
        states = {}
        try:
            files = FileManager.list_directory("cache/managed", ends_with=".json")
        except Exception:
            return states
        for fname in files:
            vid = fname[:-5]
            if vid in managed:
                data = FileManager.load_json_file("cache/managed/%s" % fname)
                if isinstance(data, dict):
                    states[vid] = data
        return states

    # ------------------------------------------------------------ ciclo

    def begin_cycle(self, config, found_villages, service=None):
        """Início de ciclo: relê config e caches, decide o hub e faz o devido."""
        self.config = config
        self.found_villages = [str(v) for v in found_villages]
        self.refresh_route()
        self.tick(service=service)

    def refresh_route(self):
        """Decide o hub do ciclo: o da campanha ativa, ou o melhor do ranking."""
        now = time.time()
        cfg = self.cfg()
        self.states = mint_planner.with_measured(
            self._managed_states(), self.state.get("coin_costs") or {}
        )
        hub, self.ranking = mint_planner.choose_hub(
            self.states, (self.config or {}).get("villages") or {}, now,
            override=cfg.get("hub_village"),
        )
        campaign = mint_store.load_campaign()
        floor = int(cfg.get("donor_floor", 20000) or 0)
        fill_max = float(cfg.get("routing_fill_max_pct", 95) or 95) / 100.0
        if campaign.get("status") == "active" and campaign.get("hub"):
            self.route = {
                "hub": str(campaign["hub"]),
                "hub_name": campaign.get("hub_name"),
                "floor": int(campaign.get("floor", floor) or 0),
                "fill_max_pct": fill_max,
                "campaign": True,
                "flag_lock": "campanha de cunhagem ativa (Bônus de bandeira)",
                "pause_spending": bool(cfg.get("campaign_pause_hub_spending", True)),
            }
        elif cfg.get("routing_enabled") and hub:
            name = (self.states.get(hub) or {}).get("name") or hub
            self.route = {
                "hub": hub,
                "hub_name": name,
                "floor": floor,
                "fill_max_pct": fill_max,
                "campaign": False,
                "flag_lock": None,
                "pause_spending": False,
            }
        else:
            self.route = None

    def route_for(self, village_id):
        """O que a aldeia faz no roteamento: None, ou a rota com `role`."""
        if not self.route:
            return None
        role = "hub" if str(village_id) == self.route["hub"] else "donor"
        return dict(self.route, role=role)

    def tick(self, service=None):
        """
        Chamado no início do ciclo, nos checkpoints das aldeias (junto do
        Hunter) e antes do sono. Só faz requisição quando algo venceu.
        `service` é o callback do Hunter, chamado entre requisições longas.
        """
        if self._busy or not self.config or not self.found_villages:
            return
        self._busy = True
        try:
            now = time.time()
            self._tick_campaign(now, service)
            self._tick_hub(time.time())
            self._tick_daily(time.time(), service)
            self._tick_inventory(time.time())
        except Exception as e:
            logger.exception("Cunhagem: erro no tick (o bot segue): %s", e)
        finally:
            self._busy = False

    def next_due(self):
        """Próximo instante em que o tick tem algo a fazer, para encurtar o sono."""
        now = time.time()
        cfg = self.cfg()
        candidates = []
        campaign = mint_store.load_campaign()
        if campaign.get("status") in ("approved", "activating"):
            candidates.append(max(now, self._activation_attempt_at + ACTIVATION_RETRY_SECONDS))
        if campaign.get("status") == "active" and campaign.get("ends_at"):
            candidates.append(float(campaign["ends_at"]))
        hub_state = self.state.get("hub") or {}
        if self.route and cfg.get("hub_auto_mint", True):
            candidates.append(float(hub_state.get("next_at") or now))
        if cfg.get("daily_auto_mint_enabled"):
            due, _ = daily_due(now, cfg.get("daily_auto_mint_time", "22:30"),
                               (self.state.get("daily") or {}).get("complete_date"))
            nxt = now if due else daily_next(now, cfg.get("daily_auto_mint_time", "22:30"))
            if nxt:
                candidates.append(nxt)
        return min(candidates) if candidates else None

    # ------------------------------------------------------------ campanha

    def _tick_campaign(self, now, service):
        campaign = mint_store.load_campaign()
        status = campaign.get("status")
        if status == "approved":
            if now - int(campaign.get("approved_at") or 0) > mint_store.APPROVAL_TTL:
                self._fail("aprovação expirou sem o bot conseguir ativar (6 h)")
                return
            self._activate(campaign, service)
        elif status == "activating":
            self._activate(campaign, service)
        elif status == "active" and now >= float(campaign.get("ends_at") or 0):
            def mutate(data):
                if data.get("status") != "active":
                    return False
                data["status"] = "done"
                data["ended_at"] = int(now)
                mint_store.add_event(data, "Campanha encerrada: o Bônus de bandeira venceu", now=now)
                return True
            if mint_store.update_campaign(mutate):
                logger.info("Cunhagem: campanha encerrada, travas e roteamento soltos")
                Notification.send("Cunhagem: campanha na %s encerrada" % campaign.get("hub_name"))
                self.refresh_route()

    def _event(self, message, **fields):
        logger.info("Cunhagem: %s", message)

        def mutate(data):
            mint_store.add_event(data, message, **fields)
        mint_store.update_campaign(mutate)

    def _fail(self, reason):
        logger.warning("Cunhagem: campanha falhou: %s", reason)

        def mutate(data):
            if data.get("status") not in mint_store.OPEN_STATUSES:
                return
            data["status"] = "failed"
            data["failed_reason"] = reason
            mint_store.add_event(data, "Falhou: %s" % reason)
        mint_store.update_campaign(mutate)
        Notification.send("Cunhagem: campanha falhou -- %s" % reason)

    def _activate(self, campaign, service):
        if time.time() - self._activation_attempt_at < ACTIVATION_RETRY_SECONDS:
            return
        self._activation_attempt_at = time.time()
        hub = str(campaign.get("hub"))
        if hub not in self.found_villages:
            self._fail("a aldeia %s não está entre as aldeias da conta neste ciclo" % hub)
            return
        payload = read_inventory(self.wrapper, hub)
        if payload is None:
            self._event("Inventário não respondeu; tento de novo no próximo checkpoint")
            return
        amounts = amounts_from_payload(payload)

        if campaign.get("status") == "approved":
            # Sexto padrão: a aprovação foi decidida sobre o cache; a bandeira
            # se confere AGORA, na tela, porque o bônus dobra a bandeira que
            # estiver equipada -- seja ela qual for.
            res = self.wrapper.get_url("game.php?village=%s&screen=flags" % hub)
            flag = academy.current_flag(res.text if res is not None else None)
            if flag is None:
                self._event("Tela de bandeiras não leu; tento de novo no próximo checkpoint")
                return
            if not flag or flag[0] != mint_planner.COIN_FLAG_TYPE:
                self._fail(
                    "a %s está com a bandeira %s, não a de cunhagem -- o bônus dobraria outra coisa"
                    % (campaign.get("hub_name"), "tipo %s nível %s" % flag if flag else "nenhuma")
                )
                return
            items = campaign.get("items") or {}
            plan = []
            flag_keys = item_keys(amounts, FLAG_BONUS_ID)
            if not flag_keys or not amounts.get(flag_keys[0]):
                self._fail("não há Bônus de bandeira no inventário")
                return
            plan.append({"key": flag_keys[0], "item_id": FLAG_BONUS_ID, "count": 1})
            for item_id, wanted in ((DECREE_ID, int(items.get("decree") or 0)),
                                    (WAR_CHEST_ID, int(items.get("war_chest") or 0))):
                keys = item_keys(amounts, item_id)
                if wanted > 0 and keys:
                    have = amounts.get(keys[0], 0)
                    if have < wanted:
                        self._event("Só há %d de %s (pedido: %d)" % (have, ITEM_LABELS[item_id], wanted))
                    if have:
                        plan.append({"key": keys[0], "item_id": item_id, "count": min(have, wanted)})
                elif wanted > 0:
                    self._event("Não há %s no inventário; segue sem ele" % ITEM_LABELS[item_id])
            before = {step["key"]: amounts.get(step["key"], 0) for step in plan}

            def mutate(data):
                if data.get("status") != "approved":
                    return False
                data["status"] = "activating"
                data["plan"] = plan
                data["inventory_before"] = before
                data["flag_at_start"] = list(flag)
                mint_store.add_event(
                    data, "Ativando na %s (bandeira tipo %d nível %d)" % (data.get("hub_name"), flag[0], flag[1])
                )
                return True
            if not mint_store.update_campaign(mutate):
                return
            Notification.send("Cunhagem: ativando a campanha na %s" % campaign.get("hub_name"))
            self._measure(hub, "antes dos itens")
            campaign = mint_store.load_campaign()

        before = campaign.get("inventory_before") or {}
        started_at = campaign.get("started_at")
        flag_seconds = campaign.get("flag_seconds")
        for step in campaign.get("plan") or []:
            key, item_id, count = step["key"], step["item_id"], int(step["count"])
            label = ITEM_LABELS.get(item_id, key)
            done = before.get(key, 0) - amounts.get(key, 0)
            while done < count:
                if callable(service):
                    service()
                result = self.wrapper.get_api_action(
                    hub, action="consume",
                    params={"screen": "inventory", "h": self.wrapper.last_h},
                    data={"item_key": key, "amount": "1"},
                )
                error = consume_error(result)
                time.sleep(2)
                payload = read_inventory(self.wrapper, hub)
                if payload is None:
                    # Resultado desconhecido: NÃO tenta de novo agora. A
                    # retomada relê e calcula pela diferença.
                    self._event("Releitura do inventário falhou depois de usar %s; confiro no próximo checkpoint" % label)
                    return
                amounts = amounts_from_payload(payload)
                now_done = before.get(key, 0) - amounts.get(key, 0)
                if now_done <= done:
                    detail = error or ("o jogo respondeu sem erro, mas a quantidade não caiu (resposta: %.200s)" % (result,))
                    if item_id == FLAG_BONUS_ID:
                        self._fail("o Bônus de bandeira não foi ativado: %s" % detail)
                        return
                    self._event("%s não foi ativado: %s" % (label, detail))
                    break
                done = now_done
                expire = (payload.get("expire") or {})
                self._event(
                    "%s ativado (%d de %d)" % (label, done, count),
                    expire=expire if isinstance(expire, dict) else None,
                )
                if item_id == FLAG_BONUS_ID and not started_at:
                    started_at = int(time.time())
                    flag_seconds = item_duration_seconds(payload, key, FLAG_BONUS_DEFAULT_SECONDS)

                    def mark(data, s=started_at, f=flag_seconds):
                        data["started_at"] = s
                        data["flag_seconds"] = f
                    mint_store.update_campaign(mark)
                if item_id != WAR_CHEST_ID:
                    self._measure(hub, "depois de %s %d" % (label, done))

        started_at = started_at or int(time.time())
        flag_seconds = flag_seconds or FLAG_BONUS_DEFAULT_SECONDS

        def activate(data):
            if data.get("status") != "activating":
                return False
            data["status"] = "active"
            data["started_at"] = started_at
            data["ends_at"] = started_at + int(flag_seconds)
            mint_store.add_event(data, "Campanha ativa até %s" % time.strftime(
                "%d/%m %H:%M", time.localtime(started_at + int(flag_seconds))))
            return True
        if mint_store.update_campaign(activate):
            Notification.send("Cunhagem: campanha ativa na %s por %d h" % (
                campaign.get("hub_name"), int(flag_seconds) // 3600))
            # A sessão do hub começa já, com o desconto novo.
            self.state.setdefault("hub", {})["next_at"] = 0
            self.refresh_route()

    def _measure(self, vid, label):
        """Lê o custo da moeda na academia e grava (diário da campanha + state)."""
        res = self.wrapper.get_url("game.php?village=%s&screen=snob" % vid)
        cost = academy.coin_cost(res.text if res is not None else None)
        if not cost:
            return None
        self._record_cost(vid, cost)

        def mutate(data):
            data.setdefault("measurements", []).append(
                {"t": int(time.time()), "label": label, "cost": cost})
            mint_store.add_event(data, "Custo da moeda %s: %s / %s / %s" % (
                label, cost["wood"], cost["stone"], cost["iron"]))
        mint_store.update_campaign(mutate)
        return res

    def _record_cost(self, vid, cost):
        entry = dict(cost)
        entry["read_at"] = int(time.time())
        self.state.setdefault("coin_costs", {})[str(vid)] = entry
        mint_store.save_state(self.state)

    # ------------------------------------------------------------ hub

    def _tick_hub(self, now):
        if not self.route or not self.cfg().get("hub_auto_mint", True):
            return
        hub = self.route["hub"]
        if hub not in self.found_villages:
            return
        hub_state = self.state.setdefault("hub", {})
        if hub_state.get("vid") == hub and now < float(hub_state.get("next_at") or 0):
            return

        res = self.wrapper.get_url("game.php?village=%s&screen=snob" % hub)
        html = res.text if res is not None else None
        hub_state.update(vid=hub, next_at=now + HUB_RETRY_SECONDS)
        cost = academy.coin_cost(html)
        if not cost:
            logger.warning("Cunhagem: academia do hub %s não leu; tento em 15 min", hub)
            mint_store.save_state(self.state)
            return
        self._record_cost(hub, cost)

        minted = self._mint_max(hub, html)
        if minted:
            html = self.wrapper.last_response.text if self.wrapper.last_response is not None else html

        state = academy.auto_minting_state(html)
        if state == "can_start":
            ok, note = self._start_auto_mint(hub)
            if ok:
                hub_state.update(next_at=now + AUTO_MINT_SECONDS + 60, started_at=int(now))
                logger.info("Cunhagem: sessão automática de 8 h iniciada no hub %s (%s)", hub, note)
            else:
                logger.warning("Cunhagem: sessão automática do hub %s não iniciou: %s", hub, note)
        elif state == "no_start_button":
            # Provavelmente já em andamento (markup não capturado ainda):
            # reconfere em 30 min em vez de supor 8 h.
            hub_state.update(next_at=now + 1800)
            self._save_sample("snob_no_start_button", html)
        mint_store.save_state(self.state)

    def _mint_max(self, vid, html):
        """Cunha o "(N)" da academia de uma vez. Devolve quantas mandou."""
        n = academy.max_mintable(html)
        if not n:
            return 0
        res = self.wrapper.post_url(
            "game.php?village=%s&screen=snob&action=coin&h=%s" % (vid, self.wrapper.last_h),
            data={"count": str(n), "coin_mint_count": str(n), "h": self.wrapper.last_h},
        )
        if res is None:
            logger.warning("Cunhagem: cunhagem de %d moeda(s) em %s sem resposta", n, vid)
            return 0
        logger.info("Cunhagem: %d moeda(s) cunhada(s) de uma vez em %s", n, vid)
        return n

    def _start_auto_mint(self, vid):
        """(ok, nota) -- inicia a sessão de 8 h e confere na tela que voltou."""
        if not self.wrapper.last_h:
            self.wrapper.get_url("game.php?village=%s&screen=snob" % vid)
        res = self.wrapper.post_url(
            "game.php?village=%s&screen=snob&action=start_auto_minting_session&h=%s"
            % (vid, self.wrapper.last_h),
            data={"h": self.wrapper.last_h},
        )
        if res is None:
            return False, "sem resposta"
        state = academy.auto_minting_state(res.text)
        if state == "no_start_button":
            self._save_sample("auto_mint_started", res.text)
            return True, "botão Ativar sumiu da tela"
        if state == "can_start":
            self._save_sample("auto_mint_still_can_start", res.text)
            return False, "o botão Ativar continua na tela"
        self._save_sample("auto_mint_unexpected", res.text)
        return False, "a resposta não é a tela da academia"

    def _save_sample(self, kind, html):
        """Primeira resposta de cada tipo, com o token h redigido (repo público)."""
        if kind in self._samples_saved or not html:
            return
        self._samples_saved.add(kind)
        try:
            path = FileManager.get_path("cache/mint/samples")
            FileManager.create_directory(path)
            full = os.path.join(path, "%s.html" % kind)
            if os.path.exists(full):
                return
            text = re.sub(r"([?&](?:amp;)?h=)\w+", r"\1REDACTED", html)
            text = re.sub(r"(csrf_token\s*=\s*')\w+", r"\1REDACTED", text)
            with open(full, "w", encoding="utf-8") as fh:
                fh.write(text)
        except Exception as e:
            logger.debug("Cunhagem: amostra %s não salva: %s", kind, e)

    # ------------------------------------------------------------ diária

    def daily_targets(self):
        """Aldeias com academia, fora da exclusão, menos o hub com sessão própria."""
        cfg = self.cfg()
        exclude = {str(v) for v in (cfg.get("daily_auto_mint_exclude") or [])}
        hub = self.route["hub"] if (self.route and cfg.get("hub_auto_mint", True)) else None
        out = []
        for vid in self.found_villages:
            if vid in exclude or vid == hub:
                continue
            if mint_planner.has_academy(self.states.get(vid)):
                out.append(vid)
        return out

    def _tick_daily(self, now, service):
        cfg = self.cfg()
        if not cfg.get("daily_auto_mint_enabled"):
            return
        daily = self.state.setdefault("daily", {})
        due, today = daily_due(now, cfg.get("daily_auto_mint_time", "22:30"), daily.get("complete_date"))
        if not due:
            return
        if daily.get("date") != today:
            daily.clear()
            daily.update({"date": today, "done": [], "failed": {}, "started_at": int(now)})
        spacing = max(0, int(cfg.get("daily_auto_mint_spacing_sec", 15) or 0))
        targets = [v for v in self.daily_targets() if v not in daily["done"]]
        logger.info("Cunhagem diária: iniciando a sessão automática em %d aldeia(s)", len(targets))
        for i, vid in enumerate(targets):
            if callable(service):
                service()
            if i:
                # Espaçado de propósito: ~25 POSTs em sequência são uma rajada
                # bem acima dos ~3,7 req/min do bot, e captcha trava a conta.
                time.sleep(spacing)
            ok, note = self._start_auto_mint(vid)
            if ok:
                daily["done"].append(vid)
                daily["failed"].pop(vid, None)
            else:
                daily["failed"][vid] = note
                logger.warning("Cunhagem diária: %s não iniciou: %s", vid, note)
            mint_store.save_state(self.state)
        daily["complete_date"] = today
        daily["finished_at"] = int(time.time())
        mint_store.save_state(self.state)
        logger.info(
            "Cunhagem diária: %d iniciada(s), %d falha(s)",
            len(daily["done"]), len(daily["failed"]),
        )

    # ------------------------------------------------------------ inventário

    def _tick_inventory(self, now):
        """Mantém o inventário do painel fresco (2 requisições a cada N horas)."""
        hours = float(self.cfg().get("inventory_refresh_hours", 6) or 0)
        if hours <= 0:
            return
        try:
            cached = FileManager.load_json_file(INVENTORY_CACHE)
        except Exception:
            cached = None
        fetched = int((cached or {}).get("fetched_at") or 0)
        if now - fetched < hours * 3600:
            return
        InventoryManager.fetch_and_save(self.wrapper, self.found_villages[0])
