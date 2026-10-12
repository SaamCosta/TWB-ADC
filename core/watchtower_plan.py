"""
Feature 30, refinamento de 2026-10-12: em que aldeia a torre de vigia nasce.

A regra antiga decidia uma vez, na primeira rodada da aldeia conquistada:
"nenhuma torre a enxerga? vira torre". Isso fazia de uma conquista isolada a
49 campos uma torre que vigiava só a si mesma -- 11.607 de população (quase
meia fazenda 30, docs/backend.md §4.4) para avisar de ataque numa aldeia que
ninguém consegue apoiar a tempo. Foi o caso da BBM 048 (531|289), a 24,6
campos da aldeia própria mais próxima.

Agora a torre nasce de um GRUPO: aldeias que nenhuma torre enxerga (a
`min_spacing` ou mais de toda torre) e que ficam perto umas das outras
(ligação simples a `min_spacing`). Quando um grupo chega a `min_cluster`
aldeias, vira torre a aldeia do MEIO dele -- a de menor distância até o
membro mais longe --, não a última conquistada. A recém-conquistada é o pior
sítio (prédios baixos, fronteira); o comentário de `Village.needs_watchtower`
já dizia isso da primeira torre.

Lógica pura: recebe posições e perfis, não lê disco nem rede.
`Village.needs_watchtower` (herança) e `Village.apply_watchtower_plan`
(passo global do ciclo) chamam este módulo com o que leram de
`cache/managed`, então as duas portas decidem igual.
"""
import math

TOWER_PROFILE = "watchtower"


def _dist(a, b):
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"])


def uncovered(villages, min_spacing):
    """Ids das aldeias que não são torre e ficam a >= min_spacing de toda torre."""
    towers = [v for v in villages.values() if v.get("profile") == TOWER_PROFILE]
    out = []
    for vid, v in villages.items():
        if v.get("profile") == TOWER_PROFILE:
            continue
        if all(_dist(v, t) >= min_spacing for t in towers):
            out.append(vid)
    return out


def clusters(vids, villages, link):
    """Componentes conexos por ligação simples: duas aldeias a < `link` campos
    caem no mesmo grupo, e o grupo cresce em cadeia. Ordem estável por id."""
    pending = sorted(vids)
    groups = []
    while pending:
        group = [pending.pop(0)]
        i = 0
        while i < len(group):
            here = villages[group[i]]
            near = [o for o in pending if _dist(here, villages[o]) < link]
            for o in near:
                pending.remove(o)
            group.extend(near)
            i += 1
        groups.append(sorted(group))
    return groups


def pick_center(group, villages):
    """
    Aldeia do grupo que vira torre: a de menor distância até o membro mais
    longe (centro do grupo). Ofensiva só se o grupo não tiver outra -- torre é
    aldeia de retaguarda com tropa baixa, e promover uma ofensiva desperdiça o
    full que ela está montando. Empate: fazenda mais alta, depois mais pontos,
    depois id.
    """
    candidates = [
        vid for vid in group if villages[vid].get("profile") != "offensive"
    ] or list(group)

    def key(vid):
        v = villages[vid]
        radius = max(_dist(v, villages[o]) for o in group)
        return (round(radius, 3), -(v.get("farm") or 0), -(v.get("points") or 0), vid)

    return min(candidates, key=key)


def plan(villages, min_spacing, min_cluster):
    """
    Torres a criar, em ordem: [(vid, membros_do_grupo)].

    `villages`: {vid: {"x", "y", "profile", "farm", "points"}} de todas
    as aldeias gerenciadas com coordenada conhecida. Sem nenhuma torre não
    planeja nada: a primeira é manual (ver Village.needs_watchtower).

    Iterativo: depois de cada promoção a aldeia passa a contar como torre, os
    membros que ela enxerga saem do jogo, e o que sobrou do grupo pode ainda
    formar outro grupo grande o bastante.
    """
    villages = {vid: dict(v) for vid, v in villages.items()}
    if not any(v.get("profile") == TOWER_PROFILE for v in villages.values()):
        return []
    min_cluster = max(1, int(min_cluster))
    out = []
    while True:
        groups = [
            g for g in clusters(uncovered(villages, min_spacing), villages, min_spacing)
            if len(g) >= min_cluster
        ]
        if not groups:
            return out
        # Maior grupo primeiro; o resto é recalculado na próxima volta.
        group = max(groups, key=len)
        center = pick_center(group, villages)
        villages[center]["profile"] = TOWER_PROFILE
        out.append((center, group))
