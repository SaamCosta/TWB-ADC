"""
Defesa automática das aldeias próprias (docs/backend.md §8.60).

Detectou ataque > interrompe > olha a aldeia atacada > estuda o ataque >
monta o plano > manda apoio se for preciso. A lógica de decisão é pura e mora
em `core/own_defense.py`; aqui fica só o que fala com o jogo.

GATILHO (sem requisição): `player.incomings` vem no `game_data` de toda
resposta e o `AccountPulse` do wrapper guarda a última leitura. O `tick()`
roda no checkpoint cooperativo do bot -- o mesmo do Hunter, chamado antes de
cada alvo de farm e de cada fase -- e no sono entre ciclos. Ele só vai ao jogo
quando o número mudou (ataque novo, ou um que pousou: a lealdade pode ter
caído) ou quando passou `rescan_minutes` com ataque pendente.

VARREDURA (requisições, nesta ordem):
  1. `overview_villages` -- a tela grátis lista TODAS as aldeias, inclusive a
     recém-conquistada que ainda não está no config.json, com o ícone
     "Sob ataque (N)" (`Extractor.own_villages_overview`). 1 GET.
  2. visão geral de cada aldeia atacada: comandos com hora de chegada,
     lealdade, bônus do Sinal da Aflição. 1 GET por aldeia.
  3. `info_command` de cada ataque ainda sem origem conhecida, para a
     distância. 1 GET por ataque, uma vez só (a origem não muda; fica em
     cache no state.json).
  4. praça da aldeia atacada (`place&mode=units`), para a defesa que já está
     lá dentro (linha Total). 1 GET por aldeia que precisa de apoio.
  5. por envio: praça + confirmação + envio (`DefenceManager.support`, com
     `arrive_by`, `clamp_to_available` e `trim`). 3 requisições; 1 só quando o
     corte desiste antes do POST.

TETO (2026-10-18, `core/own_defense.py` "QUANTO BASTA"): sem blindagem, para
de mandar quando a defesa na aldeia mais o apoio próprio a caminho matam o
maior ataque possível com nobre. Com blindagem (`cache/defense/shield.json`,
escrito pelo painel), sem teto e com piso `shield_min_send_pop` por envio.

Estado em `cache/defense/state.json` -- só o bot escreve; o painel lê.
Pedido manual do painel ("defender mesmo sem ameaça de nobre") chega por
`cache/defense/force.json`, e a blindagem por `cache/defense/shield.json`;
os dois só o painel escreve e o bot só lê.
"""
import logging
import os
import time

from core import own_defense
from core.extractors import FRIENDLY_COMMAND_TYPES, Extractor
from core.filemanager import FileManager
from core.notification import Notification
from core.village_label import village_label
from core.world_config import WorldConfig
from game.defence_manager import DefenceManager
from game.simulator import Simulator

STATE_PATH = "cache/defense/state.json"
FORCE_PATH = "cache/defense/force.json"
SHIELD_PATH = "cache/defense/shield.json"
HISTORY_MAX = 300

DEFAULTS = {
    "enabled": True,
    "rescan_minutes": 10,
    # Uma origem que acabou de ser tentada para um alvo não é tentada de novo
    # antes disto: a praça já disse o que tinha em casa.
    "retry_minutes": 30,
    "max_origin_lookups": 20,
    "units": list(own_defense.DEFAULT_OPTIONS["units"]),
    "reserve_pct": own_defense.DEFAULT_OPTIONS["reserve_pct"],
    "arrival_margin_sec": own_defense.DEFAULT_OPTIONS["arrival_margin_sec"],
    "min_package_pop": own_defense.DEFAULT_OPTIONS["min_package_pop"],
    "max_pop_per_target": own_defense.DEFAULT_OPTIONS["max_pop_per_target"],
    "exclude_attacked_sources": own_defense.DEFAULT_OPTIONS["exclude_attacked_sources"],
    "nuke_pop": own_defense.DEFAULT_OPTIONS["nuke_pop"],
    "attacker_luck_pct": own_defense.DEFAULT_OPTIONS["attacker_luck_pct"],
    "shield_min_send_pop": own_defense.DEFAULT_OPTIONS["shield_min_send_pop"],
}


def settings(config):
    out = dict(DEFAULTS)
    out.update((config or {}).get("own_defense") or {})
    return out


def load_state():
    try:
        data = FileManager.load_json_file(STATE_PATH)
    except Exception:
        data = None
    return data if isinstance(data, dict) else {}


FORCE_TTL = 24 * 3600


def load_force(now=None):
    """
    {vid: timestamp do pedido} -- pedidos do painel ainda válidos. Vencem em
    FORCE_TTL: "defender mesmo sem ameaça" esquecido não pode puxar tropa
    para a mesma aldeia dias depois.
    """
    try:
        data = FileManager.load_json_file(FORCE_PATH)
    except Exception:
        data = None
    if not isinstance(data, dict):
        return {}
    now = time.time() if now is None else now
    out = {}
    for vid, at in data.items():
        try:
            if now - float(at) <= FORCE_TTL:
                out[str(vid)] = at
        except (TypeError, ValueError):
            continue
    return out


def load_shield():
    """
    {vid: timestamp} -- aldeias com blindagem ligada no painel. Não vence
    sozinha: em guerra a blindagem dura o que a guerra durar, e o painel
    mostra a lista para desligar.
    """
    try:
        data = FileManager.load_json_file(SHIELD_PATH)
    except Exception:
        data = None
    return {str(k): v for k, v in data.items()} if isinstance(data, dict) else {}


class OwnDefenseManager:
    def __init__(self, wrapper, clock=time.time):
        self.wrapper = wrapper
        self.clock = clock
        self.logger = logging.getLogger("OwnDefense")
        self.last_scan_at = 0.0
        self.last_incomings = None
        self._busy = False
        state = load_state()
        # Persistidos: origem de comando não muda, e a tentativa recente de
        # uma origem vale também depois de um restart.
        self.origins = dict(state.get("origins") or {})
        self.attempts = dict(state.get("attempts") or {})
        self.history = list(state.get("history") or [])
        self._force_seen = None
        # (aldeia, prazo) já avisados no Telegram sem envio -- a revarredura
        # de 10 em 10 min não pode repetir o mesmo aviso.
        self._notified = set()
        self.simulate = Simulator().simulate
        self._archers = False

    # -- gatilho -----------------------------------------------------------

    def _pulse_incomings(self):
        pulse = getattr(getattr(self.wrapper, "account_pulse", None), "last", None)
        return (pulse or {}).get("incomings")

    def _hunter_close(self):
        """Hunter vai mandar comando em menos de `hunter_silence_seconds`."""
        nxt = getattr(self.wrapper, "hunter_next_send", None)
        if not nxt or getattr(self.wrapper, "hunter_active", False):
            return False
        left = nxt - self.clock()
        return 0 < left <= getattr(self.wrapper, "hunter_silence_seconds", 300)

    def due(self, config):
        """(deve_varrer, motivo)."""
        cfg = settings(config)
        if not cfg.get("enabled"):
            return False, None
        force = load_force()
        force_key = tuple(sorted(force.items()))
        if force and force_key != self._force_seen:
            return True, "pedido do painel"
        incomings = self._pulse_incomings()
        if incomings is None:
            return False, None
        if incomings != self.last_incomings:
            if not incomings and not self.last_incomings:
                self.last_incomings = incomings
                return False, None
            return True, "ataques chegando: %s -> %s" % (self.last_incomings, incomings)
        if incomings and self.clock() - self.last_scan_at >= float(cfg["rescan_minutes"]) * 60:
            return True, "revarredura com %d ataque(s) chegando" % incomings
        return False, None

    def tick(self, config, force=False):
        """Checkpoint. Barato quando não há nada: só lê o pulso em memória."""
        if self._busy:
            return
        should, reason = self.due(config)
        if not (should or force):
            return
        if self._hunter_close():
            return
        self._busy = True
        try:
            self.scan(config, reason or "forçado")
        except Exception as exc:
            # Defesa é prioridade, mas não pode derrubar o ciclo.
            self.logger.exception("OwnDefense: varredura falhou (%s)", exc)
        finally:
            self._busy = False

    # -- varredura ---------------------------------------------------------

    def _any_village(self, config):
        villages = list(((config or {}).get("villages") or {}).keys())
        return villages[0] if villages else None

    def _world(self, config):
        server = (config.get("server") or {}).get("server")
        endpoint = (config.get("server") or {}).get("endpoint")
        world = WorldConfig.get(server, endpoint) or {}
        speeds = WorldConfig.unit_speeds(server, endpoint) or {}
        # Mundo com arqueiro ganha a composição de arqueiro a cavalo no teto.
        self._archers = bool(WorldConfig.feature_enabled(world, "archer", False))
        return speeds, WorldConfig.noble_max_distance(world), WorldConfig.loyalty_drop_range(world)

    def _sources(self, config, attacked_ids):
        out = []
        base = FileManager.get_path("cache/managed")
        for vid in ((config or {}).get("villages") or {}):
            path = os.path.join(base, "%s.json" % vid)
            try:
                data = FileManager.load_json_file("cache/managed/%s.json" % vid) \
                    if os.path.exists(path) else None
            except Exception:
                data = None
            if not isinstance(data, dict) or data.get("x") is None:
                continue
            troops = {}
            for unit, qty in (data.get("troops") or {}).items():
                try:
                    troops[unit] = int(qty)
                except (TypeError, ValueError):
                    pass
            out.append({"vid": str(vid), "name": data.get("name") or str(vid),
                        "x": int(data["x"]), "y": int(data["y"]), "troops": troops,
                        "under_attack": str(vid) in attacked_ids})
        return out

    def scan(self, config, reason):
        cfg = settings(config)
        now = self.clock()
        self.last_scan_at = now
        self.last_incomings = self._pulse_incomings()
        anchor = self._any_village(config)
        if not anchor:
            return
        self.logger.info("OwnDefense: varrendo a conta (%s)", reason)
        page = self.wrapper.get_url(
            "game.php?village=%s&screen=overview_villages&mode=prod&page=-1" % anchor)
        villages = Extractor.own_villages_overview(page) if page is not None else None
        if villages is None:
            self.logger.warning("OwnDefense: visão geral das aldeias ilegível (rede, sessão "
                                "ou captcha) -- sem varredura")
            return
        # Lista curta é indistinguível de lista completa (26º padrão): o
        # `player.villages` do game_data diz quantas aldeias a conta tem.
        expected = ((getattr(getattr(self.wrapper, "account_pulse", None), "last", None)
                     or {}).get("villages"))
        if expected and len(villages) < int(expected):
            self.logger.warning("OwnDefense: visão geral trouxe %d de %s aldeias -- aldeia "
                                "atacada pode ter ficado de fora", len(villages), expected)
        force = load_force()
        self._force_seen = tuple(sorted(force.items()))
        attacked = [v for v in villages if v["incomings"] > 0 or v["vid"] in force]
        attacked_ids = {v["vid"] for v in villages if v["incomings"] > 0}
        speeds, max_dist, drop_range = self._world(config)
        report = []
        for village in attacked:
            try:
                report.append(self._defend(config, cfg, village, attacked_ids, speeds,
                                           max_dist, drop_range, village["vid"] in force))
            except Exception as exc:
                self.logger.exception("OwnDefense: %s falhou (%s)",
                                      village_label(village["vid"]), exc)
                report.append({"vid": village["vid"], "name": village["name"],
                               "error": str(exc)})
        self._save(villages, report, reason)

    def _village_page(self, vid):
        page = self.wrapper.get_url("game.php?village=%s&screen=overview" % vid)
        if page is None:
            return None
        # Conta grátis pede uma aldeia que não é dela -> o jogo devolve outra.
        state = Extractor.game_state(page)
        village = (state or {}).get("village") or {} if isinstance(state, dict) else {}
        if not village or str(village.get("id")) != str(vid):
            return None
        return page

    def _origin(self, attack, budget):
        cid = attack.get("command_id")
        if not cid:
            return None, budget
        if cid in self.origins:
            return self.origins[cid], budget
        if budget <= 0:
            return None, budget
        anchor = attack.get("_village")
        page = self.wrapper.get_url(
            "game.php?village=%s&screen=info_command&id=%s&type=other" % (anchor, cid))
        origin = Extractor.command_origin(page) if page is not None else None
        if origin:
            origin["seen_at"] = int(self.clock())
            self.origins[cid] = origin
        return origin, budget - 1

    def _defend(self, config, cfg, village, attacked_ids, speeds, max_dist, drop_range, forced):
        vid = village["vid"]
        page = self._village_page(vid)
        if page is None:
            return {"vid": vid, "name": village["name"], "error": "visão geral da aldeia ilegível"}
        loyalty = Extractor.village_loyalty(page)
        bonus = Extractor.incoming_support_speed_bonus(page)
        commands = Extractor.incoming_commands(page)
        attacks = [c for c in commands if c.get("command_type") not in FRIENDLY_COMMAND_TYPES]
        now = self.clock()
        for attack in attacks:
            # Linha sem data-endtime só trouxe o contador relativo.
            if not attack.get("arrival_at") and attack.get("eta_seconds") is not None:
                attack["arrival_at"] = int(now + attack["eta_seconds"])
        if village.get("incomings") and len(attacks) < village["incomings"]:
            # A visão geral diz "Sob ataque (N)" e a aldeia mostrou menos:
            # markup novo, não ausência de ameaça (15º padrão).
            self.logger.warning("OwnDefense: %s tem %d ataque(s) na visão geral e %d lido(s) "
                                "na aldeia -- markup do widget mudou?", village_label(vid),
                                village["incomings"], len(attacks))
            if not attacks:
                return {"vid": vid, "name": village["name"],
                        "error": "%d ataque(s) na visão geral e nenhum lido na aldeia"
                                 % village["incomings"]}
        budget = int(cfg["max_origin_lookups"])
        for attack in attacks:
            # `origin` do widget é o RÓTULO (texto livre); a origem de verdade
            # vem do info_command e toma o lugar dele.
            attack["origin_label"] = attack.get("origin")
            attack["_village"] = vid
            attack["origin"], budget = self._origin(attack, budget)
            attack.pop("_village", None)
        target = dict(village, loyalty=loyalty)
        verdict = own_defense.assess(target, attacks, speeds, max_dist, drop_range, now)
        shield = vid in load_shield()
        result = {"vid": vid, "name": village["name"], "x": village["x"], "y": village["y"],
                  "loyalty": loyalty, "bonus_pct": bonus, "forced": forced, "shield": shield,
                  "assessment": verdict, "sent": [], "plan": None, "defense": None}
        deadline = verdict["deadline_at"]
        if not verdict["protect"] and forced:
            upcoming = [a for a in verdict["attacks"] if a.get("arrival_at")]
            if upcoming:
                deadline = upcoming[0]["arrival_at"]
                verdict["reason"] = "pedido do painel: proteger até o primeiro ataque"
        if not (verdict["protect"] or forced) or not deadline:
            self.logger.info("OwnDefense: %s sem necessidade de apoio -- %s",
                             village_label(vid), verdict.get("reason"))
            return result
        margin = int(cfg["arrival_margin_sec"] or 0)
        defense = self._defense_state(cfg, vid, page, deadline, now)
        result["defense"] = self._defense_report(defense)
        result["deadline_at"] = deadline
        if defense["holds"] and not shield:
            self.logger.info(
                "OwnDefense: %s já segura o maior ataque com nobre (%d pop de ofensiva, "
                "muralha %s): %d pop na aldeia%s e %d pop a caminho -- nada a enviar",
                village_label(vid), defense["nuke_pop"], defense["wall"], defense["home_pop"],
                "" if defense["home_read"] else " (praça ilegível)", defense["inflight_pop"])
            return result
        retry = float(cfg["retry_minutes"]) * 60
        skip = {}
        for key, at in self.attempts.items():
            t_vid, s_vid = key.split(":", 1)
            if t_vid == vid and now - float(at) < retry:
                skip[s_vid] = "tentada há %d min" % ((now - float(at)) // 60)
        floor = int((cfg["shield_min_send_pop"] if shield else cfg["min_package_pop"]) or 0)
        plan = own_defense.plan_defense(
            target, deadline, self._sources(config, attacked_ids), speeds, now,
            bonus_pct=bonus, options=dict(cfg, min_package_pop=floor), skip_sources=skip,
            threat_arrivals=verdict.get("threat_arrivals") or [deadline])
        result["plan"] = {k: plan[k] for k in ("lines", "skipped", "total_troops", "total_pop")}
        self.logger.warning(
            "OwnDefense: %s precisa de apoio (%s); janela até %s; %s; %d origem(ns) candidata(s)",
            village_label(vid), verdict.get("reason"),
            time.strftime("%H:%M:%S", time.localtime(deadline)),
            ("BLINDAGEM: sem teto, envio mínimo de %d pop" % floor) if shield else
            ("teto: matar %d pop de ofensiva com nobre (atacantes vivos hoje: %s)"
             % (defense["nuke_pop"], defense["survivors"])),
            len(plan["lines"]))
        current = dict(defense["total"])
        for line in plan["lines"]:
            if not shield and own_defense.assess_defense(
                    current, defense["wall"], self.simulate, defense["nukes"],
                    defense["luck_pct"])["holds"]:
                self.logger.info("OwnDefense: %s -- defesa suficiente, as outras origens ficam",
                                 village_label(vid))
                break
            trim = self._trimmer(shield, floor, current, defense)
            sent = self._send(vid, village, line, deadline - margin, trim)
            result["sent"].append(sent)
            if sent["ok"]:
                current = own_defense._add(current, sent["troops"])
        after = own_defense.assess_defense(current, defense["wall"], self.simulate,
                                           defense["nukes"], defense["luck_pct"])
        result["defense"].update(after_holds=after["holds"], after_survivors=after["survivors"],
                                 after_pop=own_defense._pop(current))
        ok = [s for s in result["sent"] if s["ok"]]
        quiet_key = (vid, deadline)
        if not ok and (plan["lines"] or skip or quiet_key in self._notified):
            return result
        self._notified.add(quiet_key)
        Notification.send(
            "Defesa: %s (lealdade %s) -- %s. %s" % (
                village_label(vid), loyalty if loyalty is not None else "?",
                verdict.get("reason"),
                ("%d apoio(s) enviado(s)%s: %s" % (
                    len(ok), " [blindagem]" if shield else "",
                    ", ".join("%s %s" % (village_label(s["source_vid"]), s["troops"]) for s in ok)))
                if ok else "nenhuma aldeia própria chega antes do prazo."))
        return result

    def _defense_state(self, cfg, vid, page, deadline, now):
        """
        O que defende a aldeia no fim da janela e se isso basta. Na aldeia:
        a linha Total da praça (a tropa dela mais o apoio já pousado). A
        caminho: o apoio que ESTE bot mandou (histórico) e que pousa dentro
        da janela -- apoio mandado à mão só conta depois de pousar, e a tropa
        da própria aldeia fora de casa (farm, coleta) não conta: as duas
        faltas erram para o lado de mandar mais.
        """
        state = Extractor.game_state(page) if page is not None else None
        village = (state.get("village") or {}) if isinstance(state, dict) else {}
        try:
            wall = int((village.get("buildings") or {}).get("wall") or 0)
        except (TypeError, ValueError, AttributeError):
            wall = 0
        place = self.wrapper.get_url(
            "game.php?village=%s&screen=place&mode=units&display=units" % vid)
        home = Extractor.units_home_total(place) if place is not None else None
        if home is None:
            self.logger.warning("OwnDefense: praça de %s ilegível -- a defesa já na aldeia "
                                "conta como zero", village_label(vid))
        inflight = {}
        for entry in self.history:
            arrival = entry.get("arrival_at")
            if (entry.get("ok") and str(entry.get("target_vid")) == str(vid) and arrival
                    and now < arrival <= deadline):
                inflight = own_defense._add(inflight, entry.get("troops"))
        luck = int(cfg.get("attacker_luck_pct") or 0)
        nuke_pop = int(cfg.get("nuke_pop") or 0) or own_defense.max_noble_nuke_pop()
        nukes = own_defense.noble_nukes(nuke_pop, archers=self._archers)
        # O simulador não conhece milícia; unidade fora da tabela dele cai fora.
        total = {u: q for u, q in own_defense._add(home or {}, inflight).items()
                 if u in Simulator.pool}
        verdict = own_defense.assess_defense(total, wall, self.simulate, nukes, luck)
        return {"wall": wall, "home": home or {}, "home_read": home is not None,
                "home_pop": own_defense._pop(home or {}), "inflight": inflight,
                "inflight_pop": own_defense._pop(inflight), "total": total,
                "nuke_pop": nuke_pop, "nukes": nukes, "luck_pct": luck,
                "holds": verdict["holds"], "survivors": verdict["survivors"]}

    @staticmethod
    def _defense_report(defense):
        """O que o painel mostra (sem as composições inteiras)."""
        return {k: defense[k] for k in ("wall", "home", "home_read", "home_pop", "inflight",
                                        "inflight_pop", "nuke_pop", "luck_pct", "holds",
                                        "survivors")}

    def _trimmer(self, shield, floor, current, defense):
        """O `trim` do `support()`: corta ao necessário e confere o piso."""
        def trim(available):
            package = dict(available)
            if not shield:
                package = own_defense.fit_package(
                    package, current, defense["wall"], self.simulate, defense["nukes"],
                    defense["luck_pct"])
            # Explorador não segura nobre: como no plano, sozinho não vira envio.
            if package and all(u in own_defense.RIDE_ALONG_UNITS for u in package):
                return {}, "em casa só explorador agora (%s)" % package
            pop = own_defense._pop(package)
            if pop < floor:
                return {}, "pacote de %d pop em casa, abaixo do mínimo de %d%s (%s)" % (
                    pop, floor, " da blindagem" if shield else "", package)
            return package, None
        return trim

    def _send(self, target_vid, village, line, arrive_by, trim=None):
        src = line["source_vid"]
        now = self.clock()
        self.attempts["%s:%s" % (target_vid, src)] = int(now)
        dm = DefenceManager(village_id=src, wrapper=self.wrapper)
        ok = False
        try:
            ok = bool(dm.support(target_vid, troops=dict(line["troops"]),
                                 position=(int(village["x"]), int(village["y"])),
                                 arrive_by=arrive_by, clamp_to_available=True, trim=trim))
        except Exception as exc:
            dm.last_support_error = "exceção no envio: %s (confira no jogo)" % exc
        entry = {
            "at": int(now), "target_vid": target_vid, "source_vid": src,
            "troops": dm.last_support_troops if ok else line["troops"],
            "planned": line["troops"], "ok": ok, "error": None if ok else dm.last_support_error,
            "arrival_at": dm.last_support_arrival, "deadline_at": int(arrive_by),
        }
        self.history.append(entry)
        self.history = self.history[-HISTORY_MAX:]
        if ok:
            self.logger.warning("OwnDefense: %s -> %s apoio enviado: %s, chega %s",
                                village_label(src), village_label(target_vid), entry["troops"],
                                time.strftime("%H:%M:%S", time.localtime(entry["arrival_at"]))
                                if entry["arrival_at"] else "?")
        else:
            self.logger.info("OwnDefense: %s -> %s não enviado: %s", village_label(src),
                             village_label(target_vid), entry["error"])
        return entry

    def _save(self, villages, report, reason):
        now = int(self.clock())
        # Origem de comando que já pousou há mais de 2 dias não serve a ninguém.
        self.origins = {k: v for k, v in self.origins.items()
                        if now - int((v or {}).get("seen_at") or now) < 2 * 86400}
        self.attempts = {k: v for k, v in self.attempts.items() if now - float(v) < 86400}
        state = {
            "scanned_at": now, "reason": reason, "incomings": self.last_incomings,
            "villages_seen": len(villages), "attacked": report,
            "origins": self.origins, "attempts": self.attempts, "history": self.history,
        }
        try:
            FileManager.create_directory(FileManager.get_path("cache/defense"))
            FileManager.save_json_file(state, STATE_PATH, ensure_ascii=False)
        except Exception as exc:
            self.logger.warning("OwnDefense: não gravei %s (%s)", STATE_PATH, exc)
