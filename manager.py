import json
import logging
import os
import sys

from core.templates import UNIT_CARRY
from game.attack import AttackCache
from game.reports import ReportCache

# Um relatorio conta como "lotou" a partir daqui. Nao e 100% exato porque o
# jogo arredonda a divisao do saque entre os tres recursos, entao um ataque
# cheio pode voltar com 1 ou 2 a menos que a capacidade.
FULL_LOOT_RATIO = 0.995


def _pack_capacity(units_sent):
    """
    Capacidade de saque do que foi enviado num relatorio. Devolve 0 quando nao
    da para saber -- o chamador trata 0 como "nao medivel" e ignora o ataque,
    em vez de contar como lotacao 0% e enviesar o alvo para low_profile.
    """
    total = 0
    for unit, qty in (units_sent or {}).items():
        try:
            total += UNIT_CARRY.get(unit, 0) * int(qty)
        except (TypeError, ValueError):
            continue
    return total


class VillageManager:
    @staticmethod
    def farm_manager(verbose=False, clean_reports=False):
        logger = logging.getLogger("FarmManager")
        with open("config.json", "r") as f:
            config = json.load(f)

        farm_cfg = config.get("farms", {})
        high_fill = float(farm_cfg.get("high_profile_fill_rate", 0.75) or 0.75)
        low_util = float(farm_cfg.get("low_profile_utilization", 0.35) or 0.35)
        min_attacks = int(farm_cfg.get("profile_min_attacks", 4) or 4)

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
            # Lotacao e aproveitamento, por ataque, para classificar o alvo sem
            # depender do tamanho do pacote -- ver o bloco de perfil abaixo.
            filled = 0
            measurable = 0
            utilization_sum = 0.0
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
                        this_loot = 0
                        for r in res:
                            loot[r] = loot[r] + int(res[r])
                            t[r] = t[r] + int(res[r])
                            this_loot += int(res[r])
                        num_attack.append(report)
                        capacity = _pack_capacity(units_sent)
                        if capacity > 0:
                            measurable += 1
                            utilization_sum += this_loot / capacity
                            if this_loot >= capacity * FULL_LOOT_RATIO:
                                filled += 1
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

                # Perfil do alvo: decide o tempo de revisita em
                # AttackManager._should_attack (high = 30 min, default = 1 h,
                # low = 2 h).
                #
                # A metrica era o saque MEDIO ABSOLUTO (>500 alto, <100 baixo),
                # e tinha dois defeitos medidos em 2026-08-31 sobre 693 ataques
                # reais:
                #
                # 1. Ela e CENSURADA pelo tamanho do pacote. O saque nao pode
                #    passar da capacidade enviada, entao "saque medio" mede o
                #    nosso pacote tanto quanto o alvo. Alvos que lotam 640 toda
                #    vez e alvos que lotam 12.000 toda vez dizem a MESMA coisa
                #    ("tem mais do que eu carrego"), e o limiar absoluto so
                #    enxergava o segundo.
                # 2. Por isso ela EXPIRA sozinha quando a escada de pacotes
                #    muda -- foi o que aconteceu apos 7c85a22: com os pacotes
                #    maiores, 35 de 62 alvos (56%) viraram "high profile", e um
                #    rotulo que vale para a maioria nao prioriza nada.
                #
                # A lotacao e adimensional e responde direto a pergunta que o
                # flag existe para responder ("vale voltar cedo?"): se o pacote
                # volta cheio, o alvo tem mais do que consigo levar. Como nao
                # depende da capacidade, nao expira quando os pacotes mudarem
                # de novo (decimo quarto padrao do CLAUDE.md).
                #
                # O aproveitamento cobre o outro lado: um alvo pode quase nunca
                # lotar e ainda assim devolver 55% de um pacote grande, e esse
                # nao e pobre. So e low_profile quem devolve pouco em relacao
                # ao que foi mandado.
                #
                # Os dois flags sao recalculados do zero a cada ciclo e sao
                # mutuamente exclusivos. Antes eram so LIGADOS, nunca
                # desligados: 6 alvos estavam com os dois ao mesmo tempo e,
                # como _should_attack testa low por ultimo, o alvo 41318 (que
                # lota 25% e rende 4.517 por viagem) era tratado como pobre e
                # revisitado a cada 2 h.
                # `percentage_lost > 20` mais abaixo e uma regra de SEGURANCA
                # (o alvo mata tropa), nao de riqueza, e por isso tem a ultima
                # palavra. Ela e antecipada aqui para o caso do alvo que mata
                # tropa E lota o pacote: sem isto os dois blocos brigariam todo
                # ciclo, cada um desfazendo o outro e regravando o cache.
                if len(num_attack) >= min_attacks and measurable and percentage_lost <= 20:
                    fill_rate = filled / measurable
                    utilization = utilization_sum / measurable
                    want_high = fill_rate >= high_fill
                    want_low = (not want_high) and utilization <= low_util

                    if bool(data.get("high_profile")) != want_high:
                        if verbose and want_high:
                            logger.info(
                                "Farm %s lota o pacote em %.0f%% dos ataques, "
                                "marcando high profile", farm, fill_rate * 100
                            )
                        elif verbose:
                            logger.info(
                                "Farm %s caiu para %.0f%% de lotacao, saindo de "
                                "high profile", farm, fill_rate * 100
                            )
                        data["high_profile"] = want_high
                        changed = True

                    if bool(data.get("low_profile")) != want_low:
                        if verbose and want_low:
                            logger.info(
                                "Farm %s devolve %.0f%% da capacidade enviada, "
                                "marcando low profile", farm, utilization * 100
                            )
                        elif verbose:
                            logger.info(
                                "Farm %s subiu para %.0f%% de aproveitamento, "
                                "saindo de low profile", farm, utilization * 100
                            )
                        data["low_profile"] = want_low
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
