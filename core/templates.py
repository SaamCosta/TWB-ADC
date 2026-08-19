"""
Manages template files
"""
from core.exceptions import InvalidUnitTemplateException
from core.filemanager import FileManager

# Unidade -> edificio que a recruta. Esta era uma copia morta em
# TroopManager.unit_building (definida, nunca lida) -- e a ausencia de
# qualquer consumidor foi o que deixou o bloco "workshop" de
# templates/troops/offensive.txt sumir em silencio por meses. Passa a ser a
# fonte unica: TroopManager importa daqui.
UNIT_BUILDING = {
    "spear": "barracks",
    "sword": "barracks",
    "axe": "barracks",
    "archer": "barracks",
    "spy": "stable",
    "light": "stable",
    "marcher": "stable",
    "heavy": "stable",
    "ram": "garage",
    "catapult": "garage",
}

# Capacidade de saque por unidade. Conferido identico em br142 (com arqueiro)
# e br143 (sem), via interface.php?func=get_unit_info -- carga nao varia por
# mundo, entao pode ser constante.
UNIT_CARRY = {
    "spear": 25,
    "sword": 15,
    "axe": 10,
    "archer": 10,
    "spy": 0,
    "light": 80,
    "marcher": 50,
    "heavy": 50,
    "ram": 0,
    "catapult": 0,
}

# Edificios que aparecem como chave dentro de "build".
RECRUIT_BUILDINGS = set(UNIT_BUILDING.values())

# Nomes de edificio validos no campo "building" de um estagio. Sao os mesmos
# que os templates de builder usam, porque get_template_action() compara
# contra BuildingManager.levels, alimentado por aqueles arquivos.
GAME_BUILDINGS = {
    "barracks", "farm", "garage", "iron", "main", "market", "smith", "snob",
    "stable", "statue", "stone", "storage", "wall", "watchtower", "wood",
}

# "farm" descreve pacotes de ataque, nao recrutamento, entao aceita tambem
# unidades que nao saem de um edificio de tropa.
FARM_UNITS = set(UNIT_BUILDING) | {"knight", "snob"}

STAGE_KEYS = {"building", "level", "build", "farm", "upgrades"}
REQUIRED_KEYS = {"building", "level", "build", "farm"}


def _check_unit_map(units, where, problems, allowed, building=None):
    """
    Valida um dict {unidade: quantidade}. `building`, quando dado, exige que
    a unidade seja recrutavel naquele edificio.
    """
    if not isinstance(units, dict):
        problems.append(f"{where}: esperava um objeto {{unidade: quantidade}}, veio {type(units).__name__}")
        return
    for unit, amount in units.items():
        if unit not in allowed:
            problems.append(f"{where}: unidade desconhecida {unit!r}")
            continue
        if building and UNIT_BUILDING[unit] != building:
            problems.append(
                f"{where}: {unit!r} nao sai de {building!r}, e recrutada em "
                f"{UNIT_BUILDING[unit]!r}"
            )
        if not isinstance(amount, int) or isinstance(amount, bool):
            problems.append(f"{where}.{unit}: quantidade deve ser inteiro, veio {amount!r}")


def validate_troop_template(entries, name="<template>"):
    """
    Confere um template de tropa contra o vocabulario que o bot realmente
    entende, e devolve a lista de problemas (vazia = valido).

    Existe porque todo consumidor de template ignora em silencio o que nao
    reconhece: village.py::run_unit_upgrades pula chave de edificio
    desconhecida com log de debug, e get_template_action() so olha "upgrades".
    Um erro de digitacao produzia um bot que rodava limpo e nao recrutava
    nada -- so visivel semanas depois, olhando a contagem de tropa.
    """
    problems = []
    if not isinstance(entries, list):
        return [f"{name}: o template deve ser uma lista de estagios ([...]), veio {type(entries).__name__}"]

    for i, entry in enumerate(entries):
        at = f"{name}[{i}]"
        if not isinstance(entry, dict):
            problems.append(f"{at}: estagio deve ser um objeto, veio {type(entry).__name__}")
            continue

        for key in sorted(set(entry) - STAGE_KEYS):
            hint = ""
            if key in RECRUIT_BUILDINGS:
                hint = f" -- {key!r} e edificio de recrutamento, deveria estar dentro de \"build\""
            elif key == "research":
                hint = " -- pesquisa se declara em \"upgrades\""
            problems.append(f"{at}: chave desconhecida {key!r}{hint}")

        for key in sorted(REQUIRED_KEYS - set(entry)):
            problems.append(f"{at}: falta a chave obrigatoria {key!r}")

        building = entry.get("building")
        if building is not None and building not in GAME_BUILDINGS:
            problems.append(f"{at}.building: edificio desconhecido {building!r}")

        level = entry.get("level")
        if level is not None and (not isinstance(level, int) or isinstance(level, bool)):
            problems.append(f"{at}.level: deve ser inteiro, veio {level!r}")

        build = entry.get("build")
        if build is not None:
            if not isinstance(build, dict):
                problems.append(f"{at}.build: esperava um objeto {{edificio: {{unidade: qtd}}}}")
            else:
                for bname, units in build.items():
                    if bname not in RECRUIT_BUILDINGS:
                        known = "/".join(sorted(RECRUIT_BUILDINGS))
                        problems.append(
                            f"{at}.build: {bname!r} nao recruta tropa (validos: {known})"
                        )
                        continue
                    _check_unit_map(units, f"{at}.build.{bname}", problems,
                                    allowed=UNIT_BUILDING, building=bname)

        upgrades = entry.get("upgrades")
        if upgrades is not None:
            _check_unit_map(upgrades, f"{at}.upgrades", problems, allowed=UNIT_BUILDING)

        farm = entry.get("farm")
        if farm is not None:
            packs = farm if isinstance(farm, list) else [farm]
            if not isinstance(farm, (list, dict)):
                problems.append(f"{at}.farm: esperava um objeto ou lista de objetos")
            else:
                for j, pack in enumerate(packs):
                    label = f"{at}.farm[{j}]" if isinstance(farm, list) else f"{at}.farm"
                    _check_unit_map(pack, label, problems, allowed=FARM_UNITS)

    return problems


class TemplateManager:
    """
    Template manager file
    """
    @staticmethod
    def get_template(category, template="basic", output_json=False):
        """
        Reads a specific text file with arguments
        TODO: switch to improved FileManager
        """
        path = f"templates/{category}/{template}.txt"
        if output_json:
            data = FileManager.load_json_file(path)
            if category == "troops":
                problems = validate_troop_template(data, name=f"{template}.txt")
                if problems:
                    raise InvalidUnitTemplateException(
                        "Template de tropa invalido (%d problema(s)):\n  - %s"
                        % (len(problems), "\n  - ".join(problems))
                    )
            return data
        return FileManager.read_file(path).strip().split()
