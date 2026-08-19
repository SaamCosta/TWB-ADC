"""
Report management
"""
import json
import logging
import re
from datetime import datetime

from core.extractors import Extractor
from core.filemanager import FileManager

# Bugfix (2026-08-07): o jogo passou a renderizar a data do relatorio
# localizada em pt-BR ("ago. 07, 2026  05:14:58<span class=\"small grey\">"),
# em vez do formato antigo "07.08.26 05:14:58<span class=\"small grey\">"
# que o regex original esperava. Isso fazia extra["when"] nunca ser
# preenchido (confirmado: 0 de ~190 relatorios em cache/reports tinham o
# campo), quebrando silenciosamente PvpConquestManager._find_scout_report
# (alvo ficava travado para sempre em "pending_scout"), a estimativa de
# lealdade real via relatorio (game/attack.py::_get_real_loyalty) e o
# "drenar recursos" do farm (game/reports.py::has_resources_left). Ver
# docs/backlog.md para o registro completo do diagnostico.
PT_MONTH_ABBR = {
    "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
    "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12,
}


class ReportManager:
    """
    Class to "efficiently" manage reports
    """
    wrapper = None
    village_id = None
    game_state = None
    logger = None
    last_reports = {}

    def __init__(self, wrapper=None, village_id=None):
        self.wrapper = wrapper
        self.village_id = village_id
        # Mutavel por instancia (ver CLAUDE.md): read() reatribui, mas
        # last_reports[...] = res tambem e escrito direto em dois pontos.
        self.last_reports = {}

    def has_resources_left(self, vid):
        possible_reports = []
        for repid in self.last_reports:
            entry = self.last_reports[repid]
            if vid == entry.get("dest") and (entry.get("extra") or {}).get("when", None):
                possible_reports.append(entry)
        if len(possible_reports) == 0:
            return False, {}

        def highest_when(attack):
            return datetime.fromtimestamp(int(attack["extra"]["when"]))

        entry = max(possible_reports, key=highest_when)
        self.logger.debug("This is the newest? %s", datetime.fromtimestamp(int(entry["extra"]["when"])))
        if entry["extra"].get("resources", None):
            return True, entry["extra"]["resources"]
        return False, {}

    def last_seen_value(self, vid):
        """
        Melhor estimativa do que este alvo rende, tirada do relatorio mais
        recente dele **que carregue algum numero**, seja qual for o tipo:

          exploracao -> `resources`, o estoque que o explorador viu parado
          ataque     -> `loot`, o que trouxemos (um piso, porque e limitado
                        pela capacidade do pacote enviado)

        Zero quando nao existe relatorio utilizavel.

        Existe separado de `has_resources_left()` de proposito. Aquele olha
        **so o relatorio mais novo** e devolve False se ele nao tiver
        `resources` -- o que passa a ser o caso permanente depois do primeiro
        farm, ja que dali em diante o mais novo e sempre um relatorio de
        ataque. Medido em 2026-08-19 rodando ao vivo: 11 dos 119 alvos caiam
        nesse buraco e recebiam o menor pacote possivel, entre eles um com
        10.292 de recurso visto na exploracao levando 640 de capacidade.
        `has_resources_left` continua intocado porque alimenta o calculo de
        tempo de revisita em can_attack(), onde a semantica de "o ultimo
        evento foi uma exploracao que viu recurso" e a desejada.
        """
        best_when = None
        best_value = 0
        for entry in self.last_reports.values():
            if entry.get("dest") != vid:
                continue
            extra = entry.get("extra") or {}
            when = extra.get("when")
            if not when:
                continue
            payload = extra.get("resources") or extra.get("loot")
            if not payload:
                continue
            try:
                when = int(when)
                value = sum(int(v) for v in payload.values())
            except (TypeError, ValueError):
                continue
            if best_when is None or when > best_when:
                best_when, best_value = when, value
        return best_value

    def safe_to_engage(self, vid):
        # P2-25: attack_report() so popula units_sent/defence_units quando a
        # tabela correspondente existe no HTML e o regex casa. Relatorio
        # parcial (ou gravado por versao antiga do bot) nao pode derrubar o
        # farm inteiro com KeyError -- ausente significa "sem informacao".
        for repid in self.last_reports:
            entry = self.last_reports[repid]
            if vid == entry.get("dest"):
                extra = entry.get("extra") or {}
                losses = entry.get("losses") or {}
                if entry.get("type") == "attack" and losses == {}:
                    return 1
                if (
                        entry.get("type") == "scout"
                        and losses == {}
                        and (
                        extra.get("defence_units", {}) == {}
                        or extra.get("defence_units")
                        == extra.get("defence_losses")
                )
                ):
                    return 1

                units_sent = extra.get("units_sent") or {}
                if losses != {} and self.logger:
                    self.logger.debug(
                        "safe_to_engage %s: units sent %s, units lost %s",
                        vid, units_sent, losses
                    )

                for sent_type in units_sent:
                    amount = units_sent[sent_type]
                    if sent_type in losses:
                        if amount == losses[sent_type]:
                            return 0
                        elif losses[sent_type] <= 1:
                            return 1

                if losses != {}:
                    return 0
        return -1

    def read(self, page=0, full_run=False):
        if not self.logger:
            self.logger = logging.getLogger("Reports")

        if len(self.last_reports) == 0:
            self.logger.info("First run, re-reading cache entries")
            self.last_reports = ReportCache.cache_grab()
            self.logger.info("Got %d reports from cache", len(self.last_reports))

        offset = page * 12
        url = f"game.php?village={self.village_id}&screen=report&mode=all"
        if page > 0:
            url += f"&from={offset}"

        result = self.wrapper.get_url(url)

        # Guard: network timeout returns None
        if result is None:
            self.logger.warning("Reports: request timed out for page %d, skipping report read", page)
            return

        self.game_state = Extractor.game_state(result)
        new = 0

        ids = Extractor.report_table(result)
        for report_id in ids:
            if report_id in self.last_reports:
                continue
            new += 1
            url = f"game.php?village={self.village_id}&screen=report&mode=all&group_id=0&view={report_id}"
            data = self.wrapper.get_url(url)

            # Guard: individual report request may also timeout
            if data is None:
                self.logger.warning("Reports: timed out fetching report %s, skipping", report_id)
                continue

            get_type = re.search(r'class="report_(\w+)', data.text)
            if get_type:
                report_type = get_type.group(1)
                if report_type == "ReportAttack":
                    self.attack_report(data.text, report_id)
                    continue
                else:
                    res = self.put(report_id, report_type=report_type)
                    self.last_reports[report_id] = res

        if new == 12 or full_run and page < 20:
            page += 1
            self.logger.debug(
                "%d new reports where added, also checking page %d", new, page
            )
            return self.read(page, full_run=full_run)

    def re_unit(self, inp):
        output = {}
        for row in inp:
            k, v = row
            if int(v) > 0:
                output[k] = int(v)
        return output

    def re_building(self, inp):
        output = {}
        for row in inp:
            k = row["id"]
            v = row["level"]
            if int(v) > 0:
                output[k] = int(v)
        return output

    def attack_report(self, report, report_id):
        from_village = None
        from_player = None
        to_village = None
        to_player = None
        extra = {}
        losses = {}

        # Formato atual (pt-BR): "ago. 07, 2026  05:14:58<span class=\"small grey\">"
        attacked = re.search(
            r'([A-Za-zç]{3})\.\s+(\d{1,2}),\s+(\d{4})\s+(\d{1,2}):(\d{2}):(\d{2})<span class=\"small grey\">',
            report,
        )
        if attacked:
            mon_abbr, day, year, hh, mm, ss = attacked.groups()
            month = PT_MONTH_ABBR.get(mon_abbr.lower())
            if month:
                extra["when"] = int(datetime(
                    int(year), month, int(day), int(hh), int(mm), int(ss)
                ).timestamp())
            else:
                self.logger.warning(
                    "Report %s: unrecognized month abbreviation '%s' in battle date",
                    report_id, mon_abbr,
                )
        else:
            # Formato antigo (fallback, caso o jogo volte a este formato num
            # skin/idioma diferente): "07.08.26 05:14:58<span class=...">
            attacked_legacy = re.search(
                r'(\d{2}\.\d{2}\.\d{2} \d{2}\:\d{2}\:\d{2})<span class=\"small grey\">', report
            )
            if attacked_legacy:
                extra["when"] = int(
                    datetime.strptime(attacked_legacy.group(1), "%d.%m.%y %H:%M:%S").timestamp()
                )

        attacker = re.search(r'(?s)(<table id="attack_info_att".+?</table>)', report)
        if attacker:
            attacker_data = re.search(
                r'data-player="(\d+)" data-id="(\d+)"', attacker.group(1)
            )
            if attacker_data:
                from_player = attacker_data.group(1)
                from_village = attacker_data.group(2)
                units = re.search(
                    r'(?s)<table id="attack_info_att_units"(.+?)</table>',
                    attacker.group(1),
                )
                if units:
                    sent_units = re.findall("(?s)<tr>(.+?)</tr>", units.group(1))
                    extra["units_sent"] = self.re_unit(
                        Extractor.units_in_total(sent_units[0])
                    )
                    if len(sent_units) == 2:
                        extra["units_losses"] = self.re_unit(
                            Extractor.units_in_total(sent_units[1])
                        )
                        if from_player == self.game_state["player"]["id"]:
                            losses = extra["units_losses"]

        defender = re.search(r'(?s)(<table id="attack_info_def".+?</table>)', report)
        if defender:
            defender_data = re.search(
                r'data-player="(\d+)" data-id="(\d+)"', defender.group(1)
            )
            if defender_data:
                to_player = defender_data.group(1)
                to_village = defender_data.group(2)
                units = re.search(
                    r'(?s)<table id="attack_info_def_units"(.+?)</table>',
                    defender.group(1),
                )
                if units:
                    def_units = re.findall("(?s)<tr>(.+?)</tr>", units.group(1))
                    extra["defence_units"] = self.re_unit(
                        Extractor.units_in_total(def_units[0])
                    )
                    if len(def_units) == 2:
                        extra["defence_losses"] = self.re_unit(
                            Extractor.units_in_total(def_units[1])
                        )
                        if to_player == self.game_state["player"]["id"]:
                            losses = extra["defence_losses"]

        results = re.search(r'(?s)(<table id="attack_results".+?</table>)', report)
        report = report.replace('<span class="grey">.</span>', "")
        if results:
            loot = {}
            for loot_entry in re.findall(
                    r'<span class="icon header (wood|stone|iron)".+?</span>(\d+)', report
            ):
                loot[loot_entry[0]] = loot_entry[1]
            extra["loot"] = loot
            self.logger.info("attack report %s -> %s", from_village, to_village)

        scout_results = re.search(
            r'(?s)(<table id="attack_spy_resources".+?</table>)', report
        )
        if scout_results:
            self.logger.info("scout report %s -> %s", from_village, to_village)
            scout_buildings = re.search(
                r'(?s)<input id="attack_spy_building_data" type="hidden" value="(.+?)"',
                report,
            )
            if scout_buildings:
                raw = scout_buildings.group(1).replace("&quot;", '"')
                extra["buildings"] = self.re_building(json.loads(raw))
            found_res = {}
            for loot_entry in re.findall(
                    r'<span class="icon header (wood|stone|iron)".+?</span>(\d+)', scout_results.group(1)
            ):
                found_res[loot_entry[0]] = loot_entry[1]
            extra["resources"] = found_res
            units_away = re.search(
                r'(?s)(<table id="attack_spy_away".+?</table>)', report
            )
            if units_away:
                data_away = self.re_unit(Extractor.units_in_total(units_away.group(1)))
                extra["units_away"] = data_away

        # Feature 8: extrair lealdade real de relatórios de noble
        if results and extra.get("units_sent", {}).get("snob"):
            loyalty = Extractor.loyalty_from_report(report)
            if loyalty is not None:
                extra["loyalty_after"] = loyalty
                self.logger.info(
                    "Noble report %s -> %s: loyalty after = %.1f",
                    from_village, to_village, loyalty
                )

        attack_type = "scout" if scout_results and not results else "attack"
        res = self.put(
            report_id, attack_type, from_village, to_village, data=extra, losses=losses
        )
        self.last_reports[report_id] = res
        return True

    def put(self, report_id, report_type, origin_village=None, dest_village=None, losses={}, data={}):
        output = {
            "type": report_type,
            "origin": origin_village,
            "dest": dest_village,
            "losses": losses,
            "extra": data,
        }
        ReportCache.set_cache(report_id, output)
        self.logger.info(
            "Processed %s report with id %s", report_type, str(report_id)
        )
        return output


class ReportCache:
    @staticmethod
    def get_cache(report_id):
        return FileManager.load_json_file(f"cache/reports/{report_id}.json")

    @staticmethod
    def set_cache(report_id, entry):
        FileManager.save_json_file(entry, f"cache/reports/{report_id}.json")

    @staticmethod
    def cache_grab():
        output = {}
        for existing in FileManager.list_directory("cache/reports", ends_with=".json"):
            output[existing.replace(".json", "")] = FileManager.load_json_file(f"cache/reports/{existing}")
        return output
