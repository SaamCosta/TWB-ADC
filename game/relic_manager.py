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
"""
import glob
import json
import logging
import os
import time

from core import relics as R
from core.extractors import Extractor
from core.filemanager import FileManager
from core.village_label import village_label

CACHE_PATH = "cache/relics.json"
OVERVIEW_MAX_AGE = 6 * 3600
FOUND_MAX_AGE = 6 * 3600
# Quadro que diverge pede releitura, mas no máximo uma a cada meia hora: o
# jogador pode estar trocando relíquias agora, e cada troca dele diverge.
BOARD_REREAD_MIN_INTERVAL = 1800


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
        self.state = FileManager.load_json_file(CACHE_PATH) or None

    @property
    def enabled(self):
        return (self.config.get("relics") or {}).get("enabled", True)

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

    def _board_msgs(self, vid, board):
        relics = [r for r in self.state.get("relics") or [] if r.get("state") == "equipped"]
        computed = {r["id"]: r.get("covers") or [] for r in relics}
        return R.board_check(vid, board, relics, computed, self.state.get("villages") or {})

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
                     found=prev.get("found") or {}, found_at=prev.get("found_at") or 0)
        if self._found_needed(prev, server_now, now):
            gets += self._read_found(village_id, state, now)
        state["gets"] = gets
        self.state = state
        self._recheck_boards()
        self._save()
        self._log_summary(state)
        return True

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
