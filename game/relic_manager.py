"""
Relíquias, Fase 1 (§8.75): o bot passa a SABER o estado das relíquias.
Só leitura: nenhum POST, nenhuma relíquia é movida (isso é a Fase 3).

Uma instância por processo (`twb.py`), como `PlayerStats`: o estado é da
conta. Roda no início do ciclo e, durante o laço de aldeias, quando o
`ReportManager` abre um relatório `ReportRelic*` ou quando o quadro de bônus
de uma aldeia não bate com o cálculo. Sempre atrás do `_hunter_gate` (§8.58).

Custo por execução (taxa da conta, memória nunca-usar-priority-mode):
  1. `screen=relic_system` — sempre: o inventário inteiro num `<script>`.
  2. `screen=relic_system&mode=overview` — só quando as relíquias ATIVAS
     mudaram, quando o número de aldeias da conta mudou (vaga nova) ou a
     leitura tem mais de `OVERVIEW_MAX_AGE`. Achado novo vai para o
     inventário e não muda nada desta tela.
  3. `screen=report&mode=other` — só quando chegou relatório de relíquia,
     virou o dia do servidor, o dia de hoje ficou incompleto ou a leitura
     tem mais de `FOUND_MAX_AGE`. ⚠️ Não usar `cache/reports` para contar:
     ele tem buracos (`ReportManager.MAX_PAGES`, §8.74).
Ciclo normal: 1 GET. Relíquia achada: 2.

Estado em `cache/relics.json` (só o bot escreve; o painel lê).

Fase 2 (§8.77): no fim de cada leitura, o planejador (`core/relic_planner.py`)
calcula em dry-run onde as relíquias valeriam mais e grava em `plan`, com 0 GET
a mais. Nada é equipado nem removido (Fase 3). Duas medições alimentam o plano
de graça, com respostas que o bot já tinha: a produção/h de cada aldeia
(`village_prod`, do `game_data` do `village_init`) e o custo nominal de cada
unidade (`unit_costs`, da tela de recrutamento de aldeia sem desconto).

Fase 3 (§8.78): com `relics.manage` ligado, `act()` executa UM passo do plano
por leitura, com os freios de `core/relic_executor.py` (histerese, mesmo plano
em leituras seguidas, teto por dia do servidor, nada se desfaz em 24 h).
Custo de uma ação: 1 GET de `screen=relic_system` NA anfitriã (reconferência:
o `loyalty_locked` é da aldeia da URL) + 1 POST (equipar) ou 2 (mover =
`remove_relic` na origem + `equip_relic` no destino). A resposta do POST é o
estado novo quando traz `relics`; senão, a confirmação é 1 GET. Toda resposta
passa por `Extractor.ajax_error()` (A26-09).

Fase 4 (§8.79): com `relics.fuse` (e `manage`) ligados, a fusão do método 1
(principal + 2 do mesmo tipo e qualidade) sai quando nenhum equipar/mover
saiu nesta leitura, pelos freios de `core/relic_fusion.py`. Custo: 1 GET de
`screen=relic_system` (reconferência: o usuário também funde) + 1 POST
`upgrade_relic`. Nenhum POST sai fora de `relic_fusion.ALLOWED_POSTS`: as ações
pagas (`premium_upgrade_relic`, `reroll_relic`, `reduce_cooldown`) são recusadas
antes da rede, e componente (`material_qualities[]`) nunca é mandado. A primeira
resposta crua de cada ação vai para `cache/debug/relics/` (fora do git).
"""
import glob
import json
import logging
import os
import time

from core import relic_executor as E
from core import relic_fusion as F
from core import relic_planner as P
from core import relics as R
from core.extractors import Extractor
from core.filemanager import FileManager
from core.notification import Notification
from core.village_label import village_label
from core.world_config import WorldConfig

CACHE_PATH = "cache/relics.json"
OVERVIEW_MAX_AGE = 6 * 3600
FOUND_MAX_AGE = 6 * 3600
# Quadro que diverge pede releitura, mas no máximo uma a cada meia hora: o
# jogador pode estar trocando relíquias agora, e cada troca dele diverge.
BOARD_REREAD_MIN_INTERVAL = 1800
# A ação só sai sobre um plano feito de uma leitura deste instante (6º padrão):
# `act()` roda logo depois de `run()`, e plano mais velho que isto não age.
ACT_MAX_STATE_AGE = 600
# Primeira resposta crua de cada ação (fixture futura, anonimizada antes de ir
# para tests/): `cache/` está no .gitignore.
DEBUG_DIR = "cache/debug/relics"


def _coords_from_disk(own_ids):
    """
    {vid: (x, y)} das aldeias da conta: `cache/managed` primeiro (gravado por
    toda aldeia que roda), `cache/villages` (mapa) para quem ainda não rodou.
    Restrito a `own_ids` quando dado: `cache/managed` guarda aldeia perdida.
    """
    wanted = {str(v) for v in own_ids} if own_ids else None
    out = {}
    for path in glob.glob(os.path.join(FileManager.get_path("cache/managed"), "*.json")):
        vid = os.path.basename(path)[:-5]
        if wanted is not None and vid not in wanted:
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if data.get("x") and data.get("y"):
                out[vid] = (int(data["x"]), int(data["y"]))
        except (OSError, ValueError, TypeError):
            continue
    for vid in sorted((wanted or set()) - set(out)):
        data = FileManager.load_json_file("cache/villages/%s.json" % vid) or {}
        loc = data.get("location")
        if isinstance(loc, (list, tuple)) and len(loc) == 2:
            out[vid] = (int(loc[0]), int(loc[1]))
    return out


class RelicManager:
    def __init__(self, wrapper=None, config=None):
        self.wrapper = wrapper
        self.config = config or {}
        self.logger = logging.getLogger("Relics")
        # Mutáveis em __init__ (1º padrão).
        self.pending = None
        self._found_dirty = True
        self._board_mismatch = {}
        self._last_board_reread = 0.0
        self._last_plan_summary = None
        self.state = FileManager.load_json_file(CACHE_PATH) or None
        self._coords = None
        self._last_exec_summary = None
        self._last_fusion_summary = None
        self._read_village = None

    @property
    def enabled(self):
        return (self.config.get("relics") or {}).get("enabled", True)

    @property
    def manage(self):
        """Fase 3: o bot equipa/move de verdade. Sem a leitura (`enabled`), nada."""
        return self.enabled and E.settings(self.config)["manage"]

    @property
    def fuse(self):
        """Fase 4: o bot funde. Exige `manage`: sem equipar a resultante, a fusão não rende."""
        return self.manage and E.settings(self.config)["fuse"]

    # -- gatilhos -------------------------------------------------------------

    def note_report(self, report_type, report_id=None):
        """Chamado pelo `ReportManager` para todo relatório aberto que não é ataque."""
        if not report_type or not str(report_type).startswith("ReportRelic"):
            return
        self._found_dirty = True
        self.pending = "relatório %s (%s)" % (report_type, report_id)

    def check_board(self, vid, board, read_at=None):
        """
        Confere o quadro de bônus que `Village.village_init()` acabou de ler
        com o estado em memória. Divergência com estado mais velho que meia
        hora pede releitura (o jogador pode ter mexido: log é ação do bot, não
        estado do mundo); com estado recente, é WARNING.
        """
        if board is None or not self.state or not self.enabled:
            return None
        read_at = read_at or time.time()
        msgs = self._board_msgs(vid, board)
        boards = self.state.setdefault("boards", {})
        # A mesma divergência de novo (ex.: um atributo que o quadro escreve
        # de outro jeito, como "ataque e defesa" -- não medido) não vira um
        # WARNING por aldeia por ciclo: só a mudança é avisada.
        repeated = bool(msgs) and (boards.get(str(vid)) or {}).get("msgs") == msgs
        boards[str(vid)] = {"read_at": int(read_at), "ok": not msgs, "msgs": msgs}
        if not msgs:
            self._board_mismatch.pop(str(vid), None)
            self._save()
            return msgs
        state_age = read_at - (self.state.get("fetched_at") or 0)
        if (not repeated and state_age > BOARD_REREAD_MIN_INTERVAL
                and time.time() - self._last_board_reread > BOARD_REREAD_MIN_INTERVAL):
            self._board_mismatch[str(vid)] = board
            self.pending = "quadro de %s diverge" % village_label(vid)
            self.logger.info(
                "Relics: quadro de bônus de %s não bate com o estado lido há %.0f min, "
                "relendo: %s", village_label(vid), state_age / 60.0, "; ".join(msgs))
        else:
            (self.logger.debug if repeated else self.logger.warning)(
                "Relics: quadro de bônus de %s não bate com o cálculo (estado lido há "
                "%.0f min): %s", village_label(vid), state_age / 60.0, "; ".join(msgs))
        self._save()
        return msgs

    def note_village_prod(self, vid, game_data, read_at=None):
        """
        Produção/h da aldeia (`*_prod` do `game_data`, por segundo e já com
        todos os bônus), da resposta que o `village_init` já tinha. Só
        conferência: o planejador valora produção pela fórmula do nível da
        mina, e a razão lida/fórmula mostra se a conta aditiva fecha (§8.77).
        """
        if not self.state or not self.enabled:
            return
        village = (game_data or {}).get("village") or {}
        try:
            prod = {r: round(float(village["%s_prod" % r]) * 3600.0, 1) for r in P.RESOURCES}
        except (KeyError, TypeError, ValueError):
            return
        self.state.setdefault("village_prod", {})[str(vid)] = {
            "prod_h": prod, "read_at": int(read_at or time.time())}

    def note_unit_costs(self, vid, building, recruit_data):
        """
        Custo das unidades lido na tela de recrutamento (`unit_managers.units`),
        guardado como custo NOMINAL só quando a aldeia não tem desconto de
        relíquia naquele prédio: o planejador valora desconto sobre o preço
        cheio. Chamado pelo `TroopManager.recruit` (0 GET).
        """
        if not self.state or not self.enabled or not recruit_data:
            return
        key = "%s nos custos de recrutamento" % P.BUILDING_NAMES.get(building, "?")
        if ((self.state.get("villages") or {}).get(str(vid)) or {}).get(key):
            return
        costs = self.state.setdefault("unit_costs", {})
        changed = False
        for unit, entry in recruit_data.items():
            try:
                cost = {r: int(entry[r]) for r in P.RESOURCES}
            except (KeyError, TypeError, ValueError):
                continue
            if {r: (costs.get(unit) or {}).get(r) for r in P.RESOURCES} != cost:
                changed = True
            costs[unit] = dict(cost, vid=str(vid), at=int(time.time()))
        if changed:
            self._save()
            self.logger.info("Relics: custo de unidade lido em %s (%s): %s", village_label(vid),
                             building, ", ".join("%s %s" % (u, "/".join(str(costs[u][r]) for r in P.RESOURCES))
                                                 for u in sorted(recruit_data) if u in costs))

    def _board_msgs(self, vid, board):
        relics = [r for r in self.state.get("relics") or [] if r.get("state") == "equipped"]
        inactive = [r for r in self.state.get("relics") or [] if r.get("state") == "inactive"]
        computed = {r["id"]: r.get("covers") or [] for r in relics}
        return R.board_check(vid, board, relics, computed, self.state.get("villages") or {},
                             inactive=inactive)

    # -- leitura --------------------------------------------------------------

    def run(self, village_id, own_ids=None, reason="início do ciclo"):
        """
        Lê o estado das relíquias. `village_id` é só o endereço dos GETs (a
        resposta é da conta). Devolve True quando gravou estado novo. Leitura
        ruim não apaga o estado anterior.
        """
        if not self.enabled or self.wrapper is None or not village_id:
            return False
        self.pending = None
        self._read_village = str(village_id)
        base = "game.php?village=%s&screen=relic_system" % village_id
        res = self.wrapper.get_url(base)
        if res is None:
            self.logger.warning("Relics: sem resposta de relic_system (%s)", reason)
            return False
        inventory = Extractor.relic_inventory(res)
        if inventory is None:
            self.logger.warning(
                "Relics: relic_system sem RelicSystem.Inventory.init legível -- "
                "login/bot-protection, ou o markup mudou")
            return False
        now = time.time()
        server_now, _ = Extractor.server_clock(res)
        prev = self.state or {}
        gets = 1

        own_count = len(own_ids) if own_ids else None
        overview, overview_at = prev.get("overview"), prev.get("overview_at") or 0
        signature = sorted([r["id"], r["village_id"], bool(r.get("inactive_sec"))]
                           for r in inventory["relics"] if r.get("village_id"))
        if (overview is None or signature != prev.get("signature")
                or own_count != prev.get("own_villages")
                or now - overview_at > OVERVIEW_MAX_AGE):
            page = self.wrapper.get_url(base + "&mode=overview")
            gets += 1
            parsed = Extractor.relic_overview(page) if page is not None else None
            if parsed is None:
                self.logger.warning(
                    "Relics: visão geral das relíquias não veio ou não tem relic_slots; "
                    "vagas e conferência ficam da leitura anterior")
            else:
                overview, overview_at = parsed, now

        coords = _coords_from_disk(own_ids)
        own = {str(v) for v in own_ids} if own_ids else None
        for vid, xy in ((overview or {}).get("coords") or {}).items():
            if own is None or vid in own:
                coords.setdefault(vid, tuple(xy))
        state = R.build_state(inventory, overview, coords, now,
                              server_time=int(server_now.timestamp()) if server_now else None)
        state.update(overview=overview, overview_at=int(overview_at), signature=signature,
                     own_villages=own_count, reason=reason,
                     boards=prev.get("boards") or {},
                     found=prev.get("found") or {}, found_at=prev.get("found_at") or 0,
                     village_prod=prev.get("village_prod") or {},
                     unit_costs=prev.get("unit_costs") or {},
                     exec=prev.get("exec") or {})
        if self._found_needed(prev, server_now, now):
            gets += self._read_found(village_id, state, now)
        state["gets"] = gets
        self.state = state
        self._recheck_boards()
        self._plan(coords, now)
        E.update_streaks(self.state["exec"], self.state.get("plan"), self.state["fetched_at"])
        self._coords = coords
        self._save()
        self._log_summary(state)
        self._log_plan(state.get("plan"))
        return True

    def _plan(self, coords, now):
        """Fase 2: o plano em dry-run, só de disco. Falha aqui não perde a leitura."""
        try:
            server_cfg = self.config.get("server") or {}
            # `WorldConfig.get()`, e não o arquivo do cache: num processo novo
            # o cache pode ser de uma versão sem `speed`/`base_production`, e
            # quem o relia era outro componente, segundos DEPOIS deste plano
            # (§8.78/§8.79). `get()` refaz o cache velho na hora (1 GET no
            # interface.php público, não no jogo) e degrada para o cache ou
            # para o neutro se a rede falhar.
            world = WorldConfig.get(server_cfg.get("server"), server_cfg.get("endpoint"))
            regen = (self.config.get("conquest") or {}).get("loyalty_regen_per_hour", 1) or 1
            self.state["plan"] = P.plan_from_disk(
                self.state, coords, root=FileManager.get_root(), now=now,
                speed=P.world_speed(world), regen=float(regen),
                base_production=P.world_base_production(world),
                labels={vid: village_label(vid) for vid in coords})
            self.state["plan"]["dry_run"] = not self.manage
        except Exception as exc:  # o plano é dry-run: nunca derruba a leitura
            self.logger.warning("Relics: o planejador falhou: %r", exc)
            self.state["plan"] = {"error": repr(exc), "computed_at": int(now)}

    def _log_plan(self, plan):
        if not plan or plan.get("error"):
            return
        self.logger.info("Relics: plano (%s): %s; "
                         "valor das relíquias hoje %.0f/h, depois %.0f/h",
                         "relics.manage ligado" if self.manage else "dry-run, relics.manage desligado",
                         plan.get("summary"), plan.get("value_now", 0), plan.get("value_after", 0))
        self._log_fusions(plan)
        # O detalhe só quando o plano muda: a leitura roda todo ciclo.
        if plan.get("summary") == self._last_plan_summary:
            return
        self._last_plan_summary = plan.get("summary")
        sources = plan.get("sources") or {}
        if not sources.get("schedules_read", True):
            self.logger.warning("Relics: cache/hunter/schedules.json ilegível: o plano conta 0 nobre "
                                "por falta de leitura, não por medição")
        for relic in plan.get("relics") or []:
            if relic.get("state") == "inventory" and not relic.get("target_host"):
                best = (relic.get("best_hosts") or [{}])[0]
                self.logger.info("Relics: %s fica parada: melhor anfitriã %s vale %.0f/h",
                                 relic["name"], best.get("label", "nenhuma"), best.get("value", 0))
        if plan.get("missing"):
            self.logger.info("Relics: plano sem dado de %d aldeia(s): %s", len(plan["missing"]),
                             "; ".join("%s: %s" % (village_label(v), ", ".join(m))
                                       for v, m in sorted(plan["missing"].items())))

    def _log_fusions(self, plan):
        """§8.79: as fusões possíveis e por que saem ou não; só quando mudam."""
        cfg = E.settings(self.config)
        ex = (self.state or {}).get("exec") or {}
        now = time.time()
        rows = F.evaluate(plan, ex, cfg, now, E.server_day(self.state, now))
        info = plan.get("fusion_info") or {}
        summary = "; ".join("%s (%s): %s" % (
            f.get("text"), "+%.0f/h" % f["gain_h"] if f.get("gain_h") is not None else "sem valor",
            why or ("sai" if self.fuse else "sairia, relics.fuse desligado")) for f, why in rows)
        if info.get("materials"):
            summary += "; componentes no inventário (o bot não os usa: formato não medido): %s" % (
                json.dumps(info["materials"], ensure_ascii=False))
        if info.get("error"):
            summary += "; a avaliação das fusões falhou: %s" % info["error"]
        if info.get("table"):
            summary += "; tabela de qualidade divergente: %s" % info["table"]
        if summary == self._last_fusion_summary:
            return
        self._last_fusion_summary = summary
        self.logger.info("Relics: fusões (%s): %s",
                         "relics.fuse ligado" if self.fuse else "dry-run",
                         summary or "nenhuma possível (menos de 3 paradas livres da mesma qualidade)")

    # -- Fase 3: ação ---------------------------------------------------------

    def _exec_view(self, now=None):
        """(plano, estado de execução, config da Fase 3, agora, dia do servidor)."""
        now = now or time.time()
        state = self.state or {}
        ex = self.state.setdefault("exec", {}) if self.state is not None else {}
        return (state.get("plan") or {}, ex, E.settings(self.config), now,
                E.server_day(state, now))

    def candidate(self, now=None):
        """O passo que `act()` executaria agora, ou None. Puro: 0 GET."""
        if not self.manage or not self.state:
            return None
        plan, ex, cfg, now, day = self._exec_view(now)
        if (plan.get("error") or plan.get("stale")
                or now - (self.state.get("fetched_at") or 0) > ACT_MAX_STATE_AGE):
            return None
        return E.choose(plan, ex, cfg, now, day)

    def confirm_due(self, now=None):
        """
        Pede a releitura que confirma um passo visto só uma vez, quando a
        leitura tem mais de `confirm_after_min`: sem isto, a 2ª leitura só
        viria no ciclo seguinte (horas). 1 GET, entre aldeias.
        """
        if not self.manage or not self.state or self.pending:
            return False
        plan, ex, cfg, now, day = self._exec_view(now)
        if now - (self.state.get("fetched_at") or 0) < cfg["confirm_after_min"] * 60:
            return False
        if plan.get("stale"):
            self.pending = "replanejar depois de uma ação"
            return True
        waiting = E.awaiting_confirmation(plan, ex, cfg, now, day)
        if not waiting and self.fuse:
            waiting = F.awaiting_confirmation(plan, ex, cfg, now, day)
        if not waiting:
            return False
        self.pending = "confirmar o plano (%s)" % waiting[0].get("text")
        return True

    def fusion_candidate(self, now=None):
        """A fusão que `act()` faria agora (só quando nenhum equipar/mover sai), ou None. 0 GET."""
        if not self.fuse or not self.state:
            return None
        plan, ex, cfg, now, day = self._exec_view(now)
        if (plan.get("error") or plan.get("stale")
                or now - (self.state.get("fetched_at") or 0) > ACT_MAX_STATE_AGE):
            return None
        return F.choose(plan, ex, cfg, now, day)

    def act(self):
        """
        Executa no máximo UM passo do plano (equipar parada antes de mover, e
        fundir só sem nenhum dos dois). Devolve True quando o bot mudou alguma
        relíquia.
        """
        if not self.manage or self.wrapper is None or not self.state:
            return False
        plan, ex, cfg, now, day = self._exec_view()
        self._log_exec(plan, ex, cfg, now, day)
        move = self.candidate(now)
        if move is None:
            return self._act_fuse(now, day)
        rid = str(move["relic_ids"][0])
        host = str(move["to"][rid])
        origin = move["from"].get(rid)
        page = self.wrapper.get_url("game.php?village=%s&screen=relic_system" % host)
        fresh = Extractor.relic_inventory(page) if page is not None else None
        why, kind = E.precheck(move, fresh, low_loyalty=plan.get("low_loyalty"))
        if why:
            E.note_skip(ex, move, why, kind, now)
            if kind == "diverge":
                # O jogador pode ter mexido (9º padrão): não age, relê.
                self.pending = "estado diverge do plano"
            self.logger.info("Relics: não vou %s: %s%s", move.get("text"), why,
                             "; relendo o inventário" if kind == "diverge" else "")
            self._save()
            return False
        self._apply_inventory(fresh)

        if move["action"] == "move":
            res = self._post("remove_relic", origin, {})
            err = Extractor.ajax_error(res)
            after = None if err else self._confirmed(res, origin)
            if err or after is None or self._relic_host(after, rid) is not None:
                detail = ("o jogo recusou remover: %s" % err if err else
                          "a remoção não se confirmou (resposta: %.200s)" % (res,))
                return self._fail(move, detail, now, day, changed=False)
            self._apply_inventory(after)
            if not after.get("can_equip"):
                detail = ("removida de %s, mas o jogo diz que não há vaga para equipar; "
                          "ela ficou no inventário" % village_label(origin))
                return self._fail(move, detail, now, day, changed=True)

        res = self._post("equip_relic", host, {"relic_id": rid})
        err = Extractor.ajax_error(res)
        after = None if err else self._confirmed(res, host)
        if err or after is None or self._relic_host(after, rid) != host:
            detail = ("o jogo recusou equipar: %s" % err if err else
                      "o equipar não se confirmou (resposta: %.200s)" % (res,))
            if move["action"] == "move":
                detail = "removida de %s, mas %s; ela ficou no inventário" % (
                    village_label(origin), detail)
            return self._fail(move, detail, now, day, changed=move["action"] == "move")
        self._apply_inventory(after)
        # A hora gravada é a do resultado, não a da decisão (o GET e os POSTs
        # levam ~20 s com o atraso do wrapper).
        E.record(ex, move, True, "feito", time.time(), day)
        self._save()
        self.logger.info("Relics: %s (+%.0f/h; hoje %s)", self._done_text(move),
                         move.get("gain_alone_h") or 0, self._today_text(ex, cfg, day))
        Notification.send("Relíquias: %s (+%.0f/h)" % (
            self._done_text(move), move.get("gain_alone_h") or 0))
        return True

    def _act_fuse(self, now, day):
        """
        Fase 4 (§8.79): uma fusão do método 1. 1 GET (o inventário relido: o
        usuário também funde) + 1 POST `upgrade_relic`. Devolve True quando o
        inventário mudou.
        """
        fusion = self.fusion_candidate(now)
        if fusion is None:
            return False
        ex = self.state.setdefault("exec", {})
        vid = self._read_village
        page = self.wrapper.get_url("game.php?village=%s&screen=relic_system" % vid) if vid else None
        fresh = Extractor.relic_inventory(page) if page is not None else None
        why, kind = F.precheck(fusion, fresh)
        if why:
            E.note_skip(ex, fusion, why, kind, now)
            if kind == "diverge":
                self.pending = "inventário diverge do plano de fusão"
            self.logger.info("Relics: não vou %s: %s%s", fusion.get("text"), why,
                             "; relendo o inventário" if kind == "diverge" else "")
            self._save()
            return False
        self._apply_inventory(fresh)
        res = self._post("upgrade_relic", vid, {"relic_ids[]": list(fusion["relic_ids"])})
        err = Extractor.ajax_error(res)
        after = None if err else self._confirmed(res, vid)
        if err or after is None:
            detail = ("o jogo recusou fundir: %s" % err if err else
                      "a fusão não se confirmou (resposta: %.200s)" % (res,))
            return self._fail(fusion, detail, now, day, changed=False)
        verdict, detail = F.check_result(fusion, after)
        if verdict == "none":
            return self._fail(fusion, "a fusão não se confirmou: %s" % detail, now, day, changed=False)
        self._apply_inventory(after)
        if verdict == "changed":
            return self._fail(fusion, detail, now, day, changed=True)
        E.record(ex, fusion, True, "feito" if detail == "como previsto" else detail, time.time(), day)
        self._save()
        result = next((r for r in after.get("relics") or []
                       if str(r.get("id")) == str(fusion["relic_ids"][0])), {})
        text = "fundidas %s em %s (%s; POST em %s)" % (
            ", ".join(fusion.get("names") or []), result.get("name"), detail, village_label(vid))
        self.logger.info("Relics: %s (+%.0f/h; hoje %s)", text, fusion.get("gain_h") or 0,
                         self._today_text(ex, E.settings(self.config), day))
        Notification.send("Relíquias: %s (+%.0f/h)" % (text, fusion.get("gain_h") or 0))
        return True

    def _post(self, action, vid, data):
        """
        `TribalWars.post("relic_system", {ajaxaction}, data)` na aldeia `vid`.
        Só as ações gratuitas de `relic_fusion.ALLOWED_POSTS` saem; qualquer
        outra (as pagas, inclusive por engano) vira uma recusa local no formato
        `{"error": [...]}` sem tocar a rede, e o chamador a trata como recusa.
        """
        data = dict(data or {})
        if action not in F.ALLOWED_POSTS or any(k.startswith("material_qualities") for k in data) \
                or (action == "upgrade_relic"
                    and len(set(data.get("relic_ids[]") or [])) != F.FUSION_SIZE):
            self.logger.error("Relics: POST %s recusado pelo próprio bot (%r): só %s, e a fusão só "
                              "com 3 relíquias e sem componente", action, data,
                              ", ".join(F.ALLOWED_POSTS))
            return {"error": ["ação %s recusada pelo bot: nunca PP" % action]}
        res = self.wrapper.get_api_action(
            vid, action=action,
            params={"screen": "relic_system", "h": self.wrapper.last_h}, data=data)
        self._save_first_raw(action, res)
        return res

    def _save_first_raw(self, action, res):
        """A primeira resposta crua de cada ação, para virar fixture (fora do git)."""
        path = FileManager.get_path(os.path.join(DEBUG_DIR, "action_%s.json" % action))
        if res is None or os.path.exists(path):
            return
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                if isinstance(res, (dict, list)):
                    json.dump(res, fh, ensure_ascii=False, indent=1)
                else:
                    fh.write(getattr(res, "text", None) or str(res))
        except OSError as exc:
            self.logger.warning("Relics: não gravei a resposta crua de %s: %s", action, exc)

    def _confirmed(self, res, vid):
        """
        O inventário depois da ação: o da própria resposta, quando ela traz
        `relics` (sem GET); senão 1 GET de `relic_system` na aldeia `vid`.
        """
        ex = self.state.setdefault("exec", {})
        parsed = Extractor.relic_action_response(res)
        if parsed is not None:
            ex["response_has_relics"] = True
            return parsed
        ex["response_has_relics"] = False
        self.logger.info("Relics: a resposta da ação não trouxe o inventário (%.200s); "
                         "confirmando com 1 GET", (res,))
        page = self.wrapper.get_url("game.php?village=%s&screen=relic_system" % vid)
        return Extractor.relic_inventory(page) if page is not None else None

    @staticmethod
    def _relic_host(inventory, rid):
        """Onde a relíquia `rid` está no inventário (None = parada; "?" = não está lá)."""
        for relic in (inventory or {}).get("relics") or []:
            if str(relic.get("id")) == str(rid):
                return str(relic["village_id"]) if relic.get("village_id") else None
        return "?"

    def _apply_inventory(self, inventory):
        """
        Estado novo a partir de um inventário (relido na anfitriã ou vindo na
        resposta da ação), sem GET: a visão geral, o contador de achados e o
        resto ficam da leitura anterior. O plano NÃO é refeito aqui: a próxima
        ação espera a próxima leitura (uma ação por leitura).
        """
        prev = self.state or {}
        merged = dict(inventory)
        for key in ("loyalty_locked", "is_new_system", "materials", "premium_enabled"):
            merged.setdefault(key, prev.get(key))
        now = time.time()
        server_time = prev.get("server_time")
        if server_time and prev.get("fetched_at"):
            server_time = int(server_time + (now - prev["fetched_at"]))
        state = R.build_state(merged, prev.get("overview"), self._coords or {}, now,
                              server_time=server_time)
        for key in ("overview", "overview_at", "signature", "own_villages", "reason", "boards",
                    "found", "found_at", "village_prod", "unit_costs", "exec", "plan", "gets"):
            if key in prev:
                state[key] = prev[key]
        # O plano foi feito sobre o estado anterior: nenhuma ação sai dele até a
        # próxima leitura (`candidate`), que `confirm_due` pede.
        if state.get("plan"):
            state["plan"] = dict(state["plan"], stale=True)
        # A vaga ocupada/livre da visão geral fica velha depois de uma ação;
        # `can_equip` (da resposta) é a verdade sobre haver vaga.
        self.state = state

    def _fail(self, move, detail, now, day, changed):
        """Ação que não fechou. `changed`: o bot já tinha mudado algo (remoção feita)."""
        ex = self.state.setdefault("exec", {})
        E.record(ex, move, changed, detail, time.time(), day)
        E.note_skip(ex, move, detail, "recusa", now)
        self.pending = "depois de uma ação que não fechou"
        self._save()
        self.logger.warning("Relics: %s não fechou: %s", move.get("text"), detail)
        if changed:
            Notification.send("Relíquias: %s não fechou: %s" % (move.get("text"), detail))
        return changed

    @staticmethod
    def _done_text(move):
        rid = str(move["relic_ids"][0])
        name = (move.get("names") or [rid])[0]
        if move["action"] == "move":
            return "movida %s de %s para %s" % (name, village_label(move["from"][rid]),
                                               village_label(move["to"][rid]))
        return "equipada %s em %s" % (name, village_label(move["to"][rid]))

    @staticmethod
    def _today_text(ex, cfg, day):
        moves, equips = E.day_counts(ex, day) if day else (0, 0)
        return "%d/%d mover, %d/%d equipar, %d/%d fundir" % (
            moves, cfg["max_moves_per_day"], equips, cfg["max_equips_per_day"],
            F.fusions_today(ex, day), cfg["max_fusions_per_day"])

    def _log_exec(self, plan, ex, cfg, now, day):
        """Por que cada passo do plano sai ou não sai; o detalhe só quando muda."""
        rows = E.evaluate(plan, ex, cfg, now, day)
        if cfg["fuse"]:
            rows += F.evaluate(plan, ex, cfg, now, day)
        summary = "; ".join("%s: %s" % (m.get("text"), why or "sai agora") for m, why in rows)
        if not rows or summary == self._last_exec_summary:
            return
        self._last_exec_summary = summary
        self.logger.info("Relics: execução (hoje %s): %s", self._today_text(ex, cfg, day), summary)

    def _found_needed(self, prev, server_now, now):
        if self._found_dirty or not prev.get("found"):
            return True
        today = server_now.date().isoformat() if server_now else None
        entry = (prev.get("found") or {}).get(today) if today else None
        return entry is None or not entry.get("complete") or now - (prev.get("found_at") or 0) > FOUND_MAX_AGE

    def _read_found(self, village_id, state, now):
        page = self.wrapper.get_url(
            "game.php?village=%s&screen=report&mode=other" % village_id)
        if page is None:
            self.logger.warning("Relics: sem resposta da lista de relatórios (mode=other)")
            return 1
        server_now, _ = Extractor.server_clock(page)
        rows = Extractor.report_list_rows(page)
        if server_now is None or not rows:
            # Categoria vazia é possível, mas sem relógio do servidor a página
            # não é a lista: login/captcha.
            self.logger.warning(
                "Relics: lista de relatórios sem linhas ou sem relógio do servidor; "
                "contador de achados fica da leitura anterior")
            return 1
        fresh = R.found_by_day(rows, server_now)
        state["found"] = R.merge_found(state.get("found"), fresh, today=server_now.date())
        state["found_at"] = int(now)
        self._found_dirty = False
        return 1

    def _recheck_boards(self):
        if not self._board_mismatch:
            return
        self._last_board_reread = time.time()
        for vid, board in sorted(self._board_mismatch.items()):
            msgs = self._board_msgs(vid, board)
            self.state.setdefault("boards", {})[vid] = {
                "read_at": int(time.time()), "ok": not msgs, "msgs": msgs}
            if msgs:
                self.logger.warning(
                    "Relics: quadro de bônus de %s segue sem bater depois de reler: %s",
                    village_label(vid), "; ".join(msgs))
            else:
                self.logger.info(
                    "Relics: quadro de %s bate com o estado relido (as relíquias tinham "
                    "mudado desde a leitura anterior; o bot não mexeu)", village_label(vid))
        self._board_mismatch = {}

    def _save(self):
        if self.state is None:
            return
        try:
            FileManager.save_json_file(self.state, CACHE_PATH, ensure_ascii=False)
        except OSError as exc:
            self.logger.warning("Relics: não gravei %s: %s", CACHE_PATH, exc)

    def _log_summary(self, state):
        slots = state.get("slots") or {}
        counts = state.get("counts") or {}
        tot = state.get("totals") or {}
        nxt = slots.get("next_thresholds") or []
        parked = [r for r in state["relics"] if r["state"] == "inventory"]
        inactive = [r for r in state["relics"] if r["state"] == "inactive"]
        covered = sorted(state.get("villages") or {})
        found = state.get("found") or {}
        today = max(found) if found else None
        self.logger.info(
            "Relics (%s, %d GET): vagas %s/%s%s; %d equipadas, %d inativas, %d paradas%s; "
            "%d aldeias cobertas; %.1f%% do bônus das relíquias descartado pelo teto "
            "(%g de %g pontos); achadas %s",
            state.get("reason"), state.get("gets", 0),
            slots.get("used", "?"), slots.get("total", "?"),
            " (próximas com %s aldeias)" % ", ".join(str(n) for n in nxt) if nxt else "",
            counts.get("equipped", 0), counts.get("inactive", 0), len(parked),
            " (%s)" % ", ".join("%s" % r["name"] for r in parked) if parked else "",
            len(covered), 100.0 * tot.get("discarded_share", 0.0),
            tot.get("discarded_pct", 0.0), tot.get("relic_pct", 0.0),
            "hoje %d/%d%s" % (found[today]["found"], R.DAILY_FOUND_CAP,
                              "" if found[today].get("complete") else " (dia incompleto)")
            if today else "não lidas",
        )
        self.logger.info("Relics: cobertas %s", ", ".join(village_label(v) for v in covered) or "nenhuma")
        for relic in inactive:
            self.logger.info("Relics: %s inativa em %s por mais %.1f h",
                             relic["name"], village_label(relic["village_id"]),
                             (relic.get("inactive_sec") or 0) / 3600.0)
        check = state.get("coverage_check") or {}
        for div in check.get("divergences") or []:
            self.logger.warning(
                "Relics: cobertura diverge do jogo -- %s%s%s", div["text"],
                " (relíquia na %s)" % village_label(div["host_id"]) if div.get("host_id") else "",
                ": %s" % village_label(div["vid"]) if div.get("vid") else "")
        if check.get("unplaced"):
            self.logger.info("Relics: sem coordenada para conferir: %s",
                             ", ".join(village_label(v) for v in check["unplaced"]))
        if not check.get("divergences") and state.get("overview"):
            self.logger.info("Relics: cobertura calculada bate com a visão geral do jogo")
