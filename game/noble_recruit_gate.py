"""
Quem recruta nobre e quem so cunha moeda (docs/backend.md 8.48).

O PROBLEMA
----------
Todo nobre anda a 35 min/campo no br143, e a chegada comum de um trem e a da
origem mais lenta. Medido em 2026-10-04: a area de interesse fica no norte da
conta, e as aldeias que tem academia vao de 18 campos (BBM 029, ~11 h) a 42
(BBM 019, ~25 h) do 3o alvo elegivel mais proximo. Nobre recrutado no sul ou
fica parado (o planejador prefere origens perto do alvo desde a mesma data) ou
entra num trem que voa um dia inteiro com a lealdade regenerando no alvo.

POR QUE "CUNHA" E NAO "PARA"
----------------------------
A moeda de ouro e da conta inteira; o nobre e da aldeia. Uma aldeia longe dos
alvos que cunha continua aumentando quantos nobres as aldeias perto podem
recrutar -- so nao gasta populacao e recurso num nobre que nao vai servir. O
modo ja existia (`snobs: 0` + `mint_coins: true`, o perfil de torre de vigia);
aqui ele passa a ser escolhido sozinho para quem esta longe.

POR QUE UMA REGUA RELATIVA (AS N MAIS PERTO) E NAO UM TETO EM HORAS
-------------------------------------------------------------------
Na mesma medicao, o norte -- o lado perto dos alvos -- nao tinha academia:
BBM 030 a 040 estavam com academia 0. Os produtores reais formam um contínuo de
11 a 25 h, sem degrau. Um teto fixo ou nao cortava ninguem ou zerava a
producao, e envelhece sozinho conforme a conta cresce (14o padrao do
CLAUDE.md). "As N aldeias com academia mais perto dos alvos" se ajusta: quando
uma aldeia do norte ganha academia, ela entra no ranking e empurra a mais
distante para fora.

POR QUE O 3o ALVO E NAO O MAIS PROXIMO
--------------------------------------
Uma aldeia conquistada sai da lista. A BBM 024 tinha UMA barbara a 10 campos e
nenhuma outra a menos de 35: pela mais proxima ela pareceria da linha de
frente, e depois do primeiro trem deixaria de ser. O k-esimo mede se ha
alvo para mais de uma conquista.

FALHA ABERTA
------------
Sem lista do mundo, sem alvo elegivel, ou aldeia sem coordenada: a aldeia
recruta como a config manda. Recrutar e o comportamento de antes, entao "nao
sei" nunca desliga nobre de ninguem.
"""
import logging

from core.filemanager import FileManager
from core.world_config import WorldConfig
from game.attack import field_distance, village_location
from game.reservations import manual_exclusion

logger = logging.getLogger("NobleRecruitGate")

# Ordem do alvo usada para medir a distancia de uma aldeia ate os alvos
# (ver "POR QUE O 3o ALVO" acima).
TARGET_RANK = 3


def nth_nearest(origin, targets, n=TARGET_RANK):
    """
    Distancia de `origin` ate o n-esimo alvo mais proximo, ou None sem alvo.

    Com menos de `n` alvos usa o mais distante deles: a aldeia continua
    comparavel com as outras, que veem os mesmos poucos alvos.
    """
    if not targets:
        return None
    dists = sorted(field_distance(origin, t) for t in targets)
    return dists[min(n, len(dists)) - 1]


def rank_recruiters(candidates, targets, recruiters, n=TARGET_RANK):
    """
    `(recrutam, ranking)`.

    `candidates` e [(vid, (x, y))] das aldeias que poderiam recrutar.
    `ranking` e [(vid, distancia)] da mais perto para a mais longe; as
    primeiras `recruiters` recrutam. Empate decide pelo id, para a escolha nao
    oscilar entre ciclos sem nada ter mudado.
    """
    ranking = []
    for vid, location in candidates:
        distance = nth_nearest(location, targets, n)
        if distance is not None:
            ranking.append((vid, distance))
    ranking.sort(key=lambda item: (item[1], item[0]))
    return {vid for vid, _ in ranking[:recruiters]}, ranking


def area_targets(targets, area):
    """
    Os alvos dentro de `conquest.area_of_interest`, ou todos quando a area esta
    desligada ou vazia -- a mesma particao de
    `ConquestManager._prefer_area_of_interest()`, que e onde os trens vao.
    """
    if not (area or {}).get("enabled", False):
        return targets
    try:
        x_min, x_max = int(area["x_min"]), int(area["x_max"])
        y_min, y_max = int(area["y_min"]), int(area["y_max"])
    except (KeyError, TypeError, ValueError):
        return targets
    inside = [t for t in targets if x_min <= t[0] <= x_max and y_min <= t[1] <= y_max]
    return inside or targets


class NobleRecruitGate:
    """
    Construido uma vez por ciclo em twb.py, antes do laco de aldeias.
    `decide()` devolve {vid: decisao} e as aldeias so leem.
    """

    def __init__(self, config, world_villages=None, reservation_board=None,
                 active_targets=None):
        self.config = config or {}
        self.world_villages = world_villages
        self.reservation_board = reservation_board
        self.active_targets = set(active_targets or ())
        self.logger = logger

    # ------------------------------------------------------------------

    def recruiters(self):
        """`conquest.max_noble_recruiters` como inteiro >= 0 (0 = desligado)."""
        raw = self.config.get("conquest", {}).get("max_noble_recruiters", 0)
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            self.logger.warning(
                "Conquest: conquest.max_noble_recruiters=%r nao e um inteiro -- "
                "todas as aldeias recrutam como a config manda", raw
            )
            return 0

    def decide(self, villages):
        """
        {vid: {"recruit": bool, "distance": campos, "hours": h ou None,
               "rank": posicao, "of": total}}

        So entram aldeias com `snobs > 0`, academia construida e
        `noble_ignore_distance` desligado. As demais ficam fora do dict e
        seguem a config, que e o comportamento de antes.
        """
        limit = self.recruiters()
        if not limit or not self.config.get("conquest", {}).get("enabled", False):
            return {}

        candidates = []
        for vid in sorted(villages):
            village_cfg = (self.config.get("villages") or {}).get(vid) or {}
            if not (village_cfg.get("snobs") or 0):
                continue
            if village_cfg.get("noble_ignore_distance", False):
                continue
            if self._academy_level(vid, villages[vid]) <= 0:
                continue
            location = village_location(vid, villages[vid])
            if location:
                candidates.append((vid, location))

        if len(candidates) <= limit:
            return {}

        targets = self._targets(candidates)
        if not targets:
            self.logger.info(
                "Conquest: nenhum alvo barbaro elegivel conhecido -- todas as "
                "aldeias recrutam nobre como a config manda"
            )
            return {}

        recruit, ranking = rank_recruiters(candidates, targets, limit)
        speed = self._noble_minutes_per_field()
        decisions = {}
        for position, (vid, distance) in enumerate(ranking, start=1):
            decisions[vid] = {
                "recruit": vid in recruit,
                "distance": round(distance, 1),
                "hours": round(distance * speed / 60.0, 1) if speed else None,
                "rank": position,
                "of": len(ranking),
            }
        self.logger.info(
            "Conquest: recrutam nobre as %d aldeias mais perto do %do alvo (%s); "
            "as outras %d so cunham moeda",
            len(recruit), TARGET_RANK,
            ", ".join("%s %.1f campos" % (vid, d) for vid, d in ranking[:limit]),
            len(ranking) - len(recruit)
        )
        return decisions

    # ------------------------------------------------------------------

    def _targets(self, candidates):
        """
        [(x, y)] das barbaras que a conquista poderia escolher, recortadas pela
        caixa que o alcance do nobre permite em volta das candidatas.

        Os mesmos filtros de `find_target()` que nao dependem de quem manda:
        dono, faixa de pontos, `excluded_targets`, reserva de outro jogador no
        quadro da tribo e conquista ja em andamento.
        """
        if not self.world_villages:
            return []
        cfg = self.config.get("conquest", {})
        radius = int(self._noble_radius(cfg))
        xs = [loc[0] for _, loc in candidates]
        ys = [loc[1] for _, loc in candidates]
        try:
            box = self.world_villages.in_box(
                min(xs) - radius, max(xs) + radius,
                min(ys) - radius, max(ys) + radius,
            )
        except Exception as exc:  # lista do mundo e rede + disco
            self.logger.warning("Conquest: lista do mundo indisponivel (%s)", exc)
            return []

        min_pts = cfg.get("min_points", 100)
        max_pts = cfg.get("max_points", 3000)
        targets = []
        for vid, entry in box.items():
            if str(entry.get("owner", "0")) != "0":
                continue
            if not (min_pts <= int(entry.get("points") or 0) <= max_pts):
                continue
            if vid in self.active_targets:
                continue
            location = entry.get("location")
            if not location or len(location) != 2:
                continue
            if manual_exclusion(self.config, vid, location):
                continue
            board = self.reservation_board
            if board and board.claimed_by_other(vid, location):
                continue
            targets.append((int(location[0]), int(location[1])))
        return area_targets(targets, cfg.get("area_of_interest"))

    def _noble_radius(self, cfg):
        """`max_radius` limitado pelo alcance do nobre no mundo, como `_effective_radius`."""
        configured = cfg.get("max_radius", 20)
        server_cfg = self.config.get("server", {})
        world_limit = WorldConfig.noble_max_distance(
            WorldConfig.get(server=server_cfg.get("server"),
                            endpoint=server_cfg.get("endpoint"))
        )
        return min(configured, world_limit) if world_limit else configured

    def _noble_minutes_per_field(self):
        """Minutos por campo do nobre, so para o log. None quando nao se sabe."""
        server_cfg = self.config.get("server", {})
        speeds = WorldConfig.unit_speeds(server_cfg.get("server"), server_cfg.get("endpoint"))
        return (speeds or {}).get("snob")

    @staticmethod
    def _academy_level(vid, village):
        """
        Nivel da academia, do builder deste processo ou de `cache/managed`.

        No primeiro ciclo depois de iniciar, nenhuma aldeia rodou ainda e o
        builder esta vazio; o cache gravado pelo ciclo anterior cobre isso.
        A chave e `buidling_levels`, com o erro de digitacao que o arquivo tem.
        """
        builder = getattr(village, "builder", None)
        levels = getattr(builder, "levels", None)
        if not levels:
            cached = FileManager.load_json_file(f"cache/managed/{vid}.json") or {}
            levels = cached.get("buidling_levels") or {}
        try:
            return int(levels.get("snob", 0) or 0)
        except (TypeError, ValueError):
            return 0
