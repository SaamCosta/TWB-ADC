import json
import logging
import os
import sys

from game.attack import AttackCache
from game.reports import ReportCache


class VillageManager:
    @staticmethod
    def farm_manager(verbose=False, clean_reports=False):
        logger = logging.getLogger("FarmManager")
        with open("config.json", "r") as f:
            config = json.load(f)

        if verbose:
            logger.info("Villages: %d", len(config["villages"]))
        attacks = AttackCache.cache_grab()
        reports = ReportCache.cache_grab()

        if verbose:
            logger.info("Reports: %d", len(reports))
            logger.info("Farms: %d", len(attacks))
        t = {"wood": 0, "iron": 0, "stone": 0}
        for farm in attacks:
            data = attacks[farm]

            num_attack = []
            loot = {"wood": 0, "iron": 0, "stone": 0}
            total_loss_count = 0
            total_sent_count = 0
            for rep in reports:
                report = reports[rep]
                if report.get("dest") == farm and report.get("type") == "attack":
                    # P2-26: units_losses so e gravado quando o relatorio tem
                    # as duas tabelas de unidades (game/reports.py). O try/
                    # except abaixo cobria so o bloco de loot, entao um
                    # relatorio parcial derrubava o farm_manager inteiro --
                    # que roda direto no loop principal do twb.py.
                    extra = report.get("extra") or {}
                    units_sent = extra.get("units_sent") or {}
                    units_losses = extra.get("units_losses") or {}
                    for unit in units_sent:
                        total_sent_count += units_sent[unit]
                    for unit in units_losses:
                        total_loss_count += units_losses[unit]
                    try:
                        res = extra["loot"]
                        for r in res:
                            loot[r] = loot[r] + int(res[r])
                            t[r] = t[r] + int(res[r])
                        num_attack.append(report)
                    except:
                        pass
            percentage_lost = 0

            if total_sent_count > 0:
                percentage_lost = total_loss_count / total_sent_count * 100

            perf = ""
            if data.get("high_profile"):
                perf = "High Profile "
            if "low_profile" in data and data["low_profile"]:
                perf = "Low Profile "
            if verbose:
                logger.info(
                    "%sFarm village %s attacked %d times - Total loot: %s - Total units lost: %d (%.2f)",
                    perf, farm, len(num_attack), str(loot), total_loss_count, percentage_lost
                )

            # Bugfix (achado construindo a Feature 17 -- mapa de calor de
            # farm no /empire): "attack_count" era gravado em
            # cache/attacks/{id}.json apenas como valor herdado do cache
            # anterior (game/attack.py::AttackManager.attacked(),
            # "attack_count": existing.get("attack_count", 0)) e nunca era
            # efetivamente atualizado em lugar nenhum -- ficava para sempre
            # em 0. A
            # contagem real só existia aqui, calculada na hora a partir de
            # cache/reports e usada só para o log acima. Isso também deixava
            # a coluna "Ataques" de /farmscores sempre zerada. Persistindo
            # aqui corrige as duas telas de uma vez.
            # P1-8: farm_score era LIDO em game/attack.py::get_targets() e nas
            # telas do webmanager, mas nunca era ESCRITO em lugar nenhum do
            # projeto -- o comentario "preserve score fields calculated by
            # farm_manager" preservava um campo que ninguem calculava. Com o
            # score sempre no default 9999, `distance / max(score, 1)` virava
            # `distance / 9999` para todo alvo e a "ordenacao por eficiencia de
            # saque" da Feature 5 era, na pratica, ordenacao por distancia
            # pura. /farmscores classificava tudo como "new" para sempre.
            #
            # Metrica: saque medio por ataque. Maior = melhor, que e a
            # semantica que get_targets() ja assume (score no denominador) e
            # que /farmscores ja usa (ordena por -score, e trata None/9999
            # como "ainda sem historico").
            changed = False
            if data.get("attack_count") != len(num_attack):
                # Bugfix (achado construindo a Feature 17 -- mapa de calor de
                # farm no /empire): "attack_count" era gravado em
                # cache/attacks/{id}.json apenas como valor herdado do cache
                # anterior (game/attack.py::AttackManager.attacked(),
                # "attack_count": existing.get("attack_count", 0)) e nunca era
                # efetivamente atualizado em lugar nenhum -- ficava para
                # sempre em 0. A contagem real só existia aqui, calculada na
                # hora a partir de cache/reports e usada só para o log acima.
                # Isso também deixava a coluna "Ataques" de /farmscores sempre
                # zerada. Persistindo aqui corrige as duas telas de uma vez.
                data["attack_count"] = len(num_attack)
                changed = True

            if len(num_attack):
                total = 0
                for k in loot:
                    total += loot[k]

                new_score = int(total / len(num_attack))
                if data.get("farm_score") != new_score:
                    data["farm_score"] = new_score
                    changed = True

                if len(num_attack) > 3:
                    if total / len(num_attack) < 100 and (
                            "low_profile" not in data or not data["low_profile"]
                    ):
                        if verbose:
                            logger.info(
                                "Farm %s has very low resources (%d avg total), extending farm time",
                                farm, total / len(num_attack)
                            )
                        data["low_profile"] = True
                        changed = True
                    elif total / len(num_attack) > 500 and (
                            "high_profile" not in data or not data["high_profile"]
                    ):
                        if verbose:
                            logger.info(
                                "Farm %s has very high resources (%d avg total), setting to high profile",
                                farm, total / len(num_attack)
                            )
                        data["high_profile"] = True
                        changed = True

            if percentage_lost > 20 and not data.get("low_profile"):
                logger.warning(f"Dangerous {percentage_lost} percentage lost units! Extending farm time")
                data["low_profile"] = True
                data["high_profile"] = False
                changed = True
            if percentage_lost > 50 and len(num_attack) > 10:
                logger.critical("Farm seems too dangerous/ unprofitable to farm. Setting safe to false!")
                data["safe"] = False
                changed = True

            # Uma escrita por farm por ciclo, em vez de ate quatro: os blocos
            # acima mutam o mesmo dict `data`, entao cada set_cache anterior
            # regravava o arquivo inteiro de novo.
            if changed:
                AttackCache.set_cache(farm, data)

        if verbose:
            logger.info("Total loot: %s" % t)

        # P2-33: a poda existia mas twb.py nunca passava clean_reports, entao
        # cache/reports crescia sem limite -- e farm_manager cruza cada farm
        # com cada relatorio a cada ciclo, entao o custo por ciclo cresce
        # junto. Agora vem de bot.max_cached_reports (default 1000, acima do
        # volume atual: so entra em acao quando o diretorio realmente
        # dispara). 0/None desliga.
        if clean_reports and os.path.exists("./cache/reports/"):
            list_of_files = sorted(
                ["./cache/reports/" + f for f in os.listdir("./cache/reports/")],
                key=os.path.getctime
            )

            removed = 0
            while len(list_of_files) > clean_reports:
                oldest_file = list_of_files.pop(0)
                try:
                    os.remove(os.path.abspath(oldest_file))
                    removed += 1
                except OSError as e:
                    logger.warning("Could not delete old report %s: %s", oldest_file, e)
            if removed:
                logger.info(
                    "Pruned %d old reports (limit %d, %d remaining)",
                    removed, clean_reports, len(list_of_files)
                )


if __name__ == "__main__":
    logging.basicConfig(stream=sys.stdout)
    VillageManager.farm_manager(verbose=True)
