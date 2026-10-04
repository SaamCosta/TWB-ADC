"""
Testes de quem recruta nobre e quem so cunha (docs/backend.md 8.48).

  rank_recruiters / nth_nearest / area_targets -- a regua, logica pura
  NobleRecruitGate.decide()                    -- quem entra no ranking
  Village._noble_too_far / run_snob_recruit    -- o que a aldeia faz com isso

As coordenadas sao as reais de 2026-10-04: as 23 aldeias com academia e
`snobs > 0`, e as 53 barbaras elegiveis (100 a 1.100 pontos) dentro da area de
interesse 500-650|270-299 segundo o `map/village.txt` do br143 daquele dia.

Nada aqui toca rede nem cache/: a lista do mundo e um dublê, e as aldeias
trazem coordenada e academia em memoria.

Rodar: python tests/test_noble_recruit_gate.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game.noble_recruit_gate import (
    NobleRecruitGate, area_targets, nth_nearest, rank_recruiters,
)
from game.village import Village


ACADEMIAS = {
    "32056": (574, 317),  # BBM 020
    "34597": (576, 316),  # BBM 016
    "35059": (579, 318),  # BBM 019
    "36294": (569, 312),  # BBM 021
    "37318": (577, 315),  # BBM 015
    "38363": (586, 313),  # BBM 017
    "38997": (580, 309),  # BBM 005
    "39292": (579, 308),  # BBM 004
    "39472": (588, 309),  # BBM 018
    "39975": (583, 312),  # BBM 009
    "40314": (571, 308),  # BBM 007
    "40374": (588, 314),  # BBM 024
    "40618": (569, 304),  # BBM 022
    "41114": (584, 309),  # BBM 008
    "41123": (577, 306),  # BBM 001
    "41140": (585, 304),  # BBM 012
    "41283": (576, 309),  # BBM 006
    "44620": (586, 308),  # BBM 013
    "44674": (587, 307),  # BBM 014
    "44683": (579, 304),  # BBM 003
    "49709": (572, 295),  # BBM 029
    "74689": (578, 306),  # BBM 010
    "74690": (582, 304),  # BBM 011
}

ALVOS_NA_AREA = [
    (523, 277), (524, 286), (525, 287), (525, 288), (528, 270), (529, 289),
    (531, 270), (531, 288), (531, 289), (532, 282), (533, 276), (534, 293),
    (534, 296), (536, 272), (537, 273), (543, 291), (543, 296), (544, 290),
    (545, 272), (548, 274), (549, 283), (550, 274), (550, 277), (550, 281),
    (552, 280), (553, 279), (555, 273), (556, 275), (560, 274), (561, 274),
    (563, 270), (563, 272), (563, 279), (565, 278), (566, 270), (567, 272),
    (568, 271), (570, 279), (574, 271), (577, 270), (583, 270), (583, 271),
    (585, 270), (585, 278), (586, 275), (588, 272), (588, 274), (593, 270),
    (593, 273), (595, 270), (598, 270), (619, 273), (620, 271),
]

AREA = {"enabled": True, "x_min": 500, "x_max": 650, "y_min": 270, "y_max": 299}


# --------------------------------------------------------------------------
# Dublês
# --------------------------------------------------------------------------

class _Logger:
    def __init__(self):
        self.lines = []

    def debug(self, *a, **k): pass

    def info(self, msg, *a, **k):
        self.lines.append(msg % a if a else msg)

    def warning(self, *a, **k): pass
    def error(self, *a, **k): pass


class _Area:
    def __init__(self, loc):
        self.my_location = list(loc) if loc else None


class _Builder:
    def __init__(self, academy):
        self.levels = {"snob": academy}

    def get_level(self, building):
        return self.levels.get(building, 0)


class _V:
    def __init__(self, loc, academy=1):
        self.area = _Area(loc)
        self.builder = _Builder(academy)


class _World:
    """`WorldVillages.in_box` com as entradas na forma de cache/villages."""

    def __init__(self, entries):
        self.entries = entries

    def in_box(self, x_min, x_max, y_min, y_max):
        return {vid: e for vid, e in self.entries.items()
                if x_min <= e["location"][0] <= x_max
                and y_min <= e["location"][1] <= y_max}


def _world(alvos=ALVOS_NA_AREA, extra=None):
    entries = {}
    for i, (x, y) in enumerate(alvos):
        entries["b%d" % i] = {"location": [x, y], "owner": "0", "points": 500}
    entries.update(extra or {})
    return _World(entries)


def _config(recruiters=8, villages=None, area=AREA):
    return {
        "conquest": {"enabled": True, "max_radius": 70, "min_points": 100,
                     "max_points": 1100, "area_of_interest": area,
                     "max_noble_recruiters": recruiters},
        "villages": villages if villages is not None
        else {vid: {"snobs": 4} for vid in ACADEMIAS},
    }


def _gate(cfg=None, world=None, **kw):
    g = NobleRecruitGate(config=cfg or _config(),
                         world_villages=_world() if world is None else world, **kw)
    g.logger = _Logger()
    return g


def _imperio():
    return {vid: _V(loc) for vid, loc in ACADEMIAS.items()}


# --------------------------------------------------------------------------
# A regua
# --------------------------------------------------------------------------

def test_as_oito_mais_perto_com_os_dados_de_hoje():
    """
    O ranking real de 2026-10-04 com N = 8. A BBM 001 e a BBM 010, que
    concentravam os nobres, ficam entre as que recrutam; as seis do sul (015,
    016, 017, 019, 020, 024) ficam de fora.
    """
    recrutam, ranking = rank_recruiters(list(ACADEMIAS.items()), ALVOS_NA_AREA, 8)
    assert recrutam == {"49709", "40618", "41140", "74690", "44683",
                        "41123", "40314", "74689"}
    assert ranking[0][0] == "49709"   # BBM 029, a unica com academia no norte
    assert ranking[-1][0] == "35059"  # BBM 019
    for sul in ("37318", "34597", "38363", "35059", "32056", "40374"):
        assert sul not in recrutam


def test_um_alvo_isolado_perto_nao_faz_da_aldeia_linha_de_frente():
    """
    O caso da BBM 024: uma barbara a 10 campos e mais nada perto. Pelo alvo
    mais proximo ela pareceria a melhor; pelo 3o ela e o que e -- longe.
    """
    alvos = [(588, 304), (560, 270), (561, 270), (562, 270)]
    perto_de_um = (588, 314)
    perto_de_tres = (565, 285)
    assert nth_nearest(perto_de_um, alvos, 1) < nth_nearest(perto_de_tres, alvos, 1)
    assert nth_nearest(perto_de_um, alvos, 3) > nth_nearest(perto_de_tres, alvos, 3)


def test_menos_alvos_que_a_ordem_usa_o_mais_distante():
    assert nth_nearest((0, 0), [(3, 4)], 3) == 5.0
    assert nth_nearest((0, 0), [], 3) is None


def test_empate_decide_pelo_id():
    """Sem desempate fixo a escolha poderia oscilar entre ciclos."""
    recrutam, _ = rank_recruiters([("b", (0, 0)), ("a", (0, 0))], [(5, 0)], 1, n=1)
    assert recrutam == {"a"}


def test_area_de_interesse_e_preferencia_como_no_find_target():
    dentro, fora = (550, 280), (550, 320)
    assert area_targets([dentro, fora], AREA) == [dentro]
    assert area_targets([fora], AREA) == [fora]        # area esgotada libera o resto
    assert area_targets([dentro, fora], {"enabled": False}) == [dentro, fora]


# --------------------------------------------------------------------------
# NobleRecruitGate.decide
# --------------------------------------------------------------------------

def test_decide_marca_quem_recruta_e_quem_cunha():
    plano = _gate().decide(_imperio())
    assert len(plano) == 23
    assert plano["49709"]["recruit"] is True and plano["49709"]["rank"] == 1
    assert plano["35059"]["recruit"] is False and plano["35059"]["rank"] == 23
    assert sum(d["recruit"] for d in plano.values()) == 8


def test_desligado_por_default():
    assert _gate(cfg=_config(recruiters=0)).decide(_imperio()) == {}


def test_valor_ilegivel_desliga_em_vez_de_cortar():
    assert _gate(cfg=_config(recruiters="oito")).decide(_imperio()) == {}


def test_sem_academia_nao_ocupa_vaga():
    """
    O norte tinha `snobs: 4` e academia 0. Se entrasse no ranking, ocuparia as
    vagas mais perto e nao produziria nobre nenhum.
    """
    imperio = _imperio()
    imperio["58039"] = _V((569, 278), academy=0)  # BBM 040, 1,4 campo de um alvo
    cfg = _config()
    cfg["villages"]["58039"] = {"snobs": 4}
    plano = _gate(cfg=cfg).decide(imperio)
    assert "58039" not in plano
    assert plano["49709"]["rank"] == 1


def test_snobs_zero_e_noble_ignore_distance_ficam_fora():
    cfg = _config()
    cfg["villages"]["49709"] = {"snobs": 0}
    cfg["villages"]["35059"] = {"snobs": 4, "noble_ignore_distance": True}
    plano = _gate(cfg=cfg).decide(_imperio())
    assert "49709" not in plano and "35059" not in plano
    # A vaga da 49709 passou para a proxima da fila.
    assert sum(d["recruit"] for d in plano.values()) == 8


def test_poucas_candidatas_ninguem_e_cortado():
    imperio = {vid: _V(ACADEMIAS[vid]) for vid in ("49709", "35059")}
    assert _gate().decide(imperio) == {}


def test_sem_lista_do_mundo_falha_aberta():
    """'Nao sei' nunca desliga nobre: sem alvo conhecido, todo mundo recruta."""
    assert _gate(world=False).decide(_imperio()) == {}
    assert _gate(world=_World({})).decide(_imperio()) == {}


def test_alvo_com_dono_fora_da_faixa_ou_em_conquista_nao_conta():
    """
    Os mesmos filtros de find_target(). Aqui o unico alvo perto do sul e
    invalido de tres formas, e o sul continua longe.
    """
    sul = (579, 318)
    invalidos = {
        "dono": {"location": [579, 320], "owner": "123", "points": 500},
        "grande": {"location": [580, 320], "owner": "0", "points": 5000},
        "ativo": {"location": [578, 320], "owner": "0", "points": 500},
    }
    g = _gate(world=_world(extra=invalidos), active_targets={"ativo"})
    alvos = g._targets([("35059", sul)])
    assert (579, 320) not in alvos and (580, 320) not in alvos and (578, 320) not in alvos


def test_reserva_de_outro_jogador_no_quadro_nao_conta():
    class _Board:
        @staticmethod
        def claimed_by_other(vid, location):
            return {"reserved_by_name": "outro"} if vid == "b0" else None

    g = _gate(reservation_board=_Board())
    alvos = g._targets(list(ACADEMIAS.items()))
    assert ALVOS_NA_AREA[0] not in alvos
    assert len(alvos) == len(ALVOS_NA_AREA) - 1


# --------------------------------------------------------------------------
# Village
# --------------------------------------------------------------------------

class _Snob:
    def __init__(self):
        self.ran = None
        self.is_incomplete = True

    def run(self):
        self.ran = (self.wanted, self.mint_only)


class _Resman:
    def __init__(self):
        self.requested = {"snob": {"wood": 9000}, "building": {"stone": 10}}


def _village(plan, snobs=4, mint=False):
    v = Village(village_id="35059")
    v.config = {"villages": {"35059": {"snobs": snobs, "mint_coins": mint}},
                "conquest": {"max_noble_recruiters": 8}}
    v.logger = _Logger()
    v.builder = _Builder(1)
    v.resman = _Resman()
    v.snobman = _Snob()
    v.noble_recruit_plan = plan
    return v


_LONGE = {"35059": {"recruit": False, "distance": 42.2, "hours": 24.6, "rank": 23, "of": 23}}
_PERTO = {"35059": {"recruit": True, "distance": 18.4, "hours": 10.7, "rank": 1, "of": 23}}


def test_aldeia_longe_so_cunha():
    v = _village(_LONGE)
    v.run_snob_recruit()
    assert v.snobman.ran == (0, True)


def test_aldeia_perto_recruta_como_configurado():
    v = _village(_PERTO)
    v.run_snob_recruit()
    assert v.snobman.ran == (4, False)


def test_sem_plano_recruta_como_configurado():
    v = _village(None)
    v.run_snob_recruit()
    assert v.snobman.ran == (4, False)


def test_ao_passar_a_cunhar_solta_o_pedido_de_recurso_do_nobre():
    """
    O pedido "snob" sobrevive no ResourceManager entre ciclos e vai para
    `required_resources`: sem soltar, o compartilhamento seguiria mandando
    recurso para um nobre que nao vai ser feito. O pedido do builder fica.
    """
    v = _village(_LONGE)
    v.run_snob_recruit()
    assert "snob" not in v.resman.requested
    assert v.resman.requested["building"] == {"stone": 10}
    assert v.snobman.is_incomplete is False


def test_snobs_zero_nao_e_afetado_pelo_plano():
    """Quem ja nao recruta (torre de vigia) segue so a propria config."""
    v = _village(_PERTO, snobs=0, mint=False)
    v.run_snob_recruit()
    assert v.snobman.ran is None


def test_loga_so_na_troca_de_modo():
    v = _village(_LONGE)
    v.run_snob_recruit()
    v.run_snob_recruit()
    assert len([l for l in v.logger.lines if l.startswith("Nobre:")]) == 1
    v.noble_recruit_plan = _PERTO
    v.run_snob_recruit()
    assert len([l for l in v.logger.lines if l.startswith("Nobre:")]) == 2


if __name__ == "__main__":
    falhas = 0
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok   %s" % nome)
            except Exception as exc:
                falhas += 1
                print("FALHA %s: %r" % (nome, exc))
    sys.exit(1 if falhas else 0)
