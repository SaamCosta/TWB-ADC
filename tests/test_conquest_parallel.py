"""
Trens barbaros em paralelo (docs/backend.md 8.43, `P-CONQ-PARALELO`).

O que motivou, medido em 2026-10-03 15:32: o trem contra a 53691 agendado as
10:57 (pouso 04/10 09:48, 4 nobres: 74689 x2, 37318 x1, 41123 x1) e, em casa,
8 nobres nos snapshots (41123: 4, 74689: 3, 37318: 1). Quatro deles livres, e o
planejador logando "ja existe conquista barbara em andamento" a cada ciclo.

Cobre:
- o teto `conquest.max_parallel_trains` (default 1 = comportamento antigo) e a
  leitura tolerante do valor;
- um trem novo nao conta os nobres que outro trem agendado segura;
- a reserva `barb_train:*` reconstruida do Hunter depois de um reinicio -- o
  caso que, sem ela, poria o mesmo nobre em dois trens;
- so comando `pending` reserva; arquivo vazio ou schedule ausente nao solta.

Reusa os dubles de `tests/test_conquest_planner.py` (nada toca cache/ nem a
rede). Rodar: python tests/test_conquest_parallel.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import test_conquest_planner as base  # noqa: E402
from test_conquest_planner import _Village, _planner  # noqa: E402

CFG3 = {"conquest": {"enabled": True, "max_parallel_trains": 3},
        "hunter": {"enabled": True}}

# Trem agendado contra a 53691, do jeito que o planejador grava.
SCHEDULED = {"53691": {"status": "train_scheduled", "hunter_schedule_key": "k53691",
                       "reserved_by": "41123"}}


def _schedules(attacks):
    return {"k53691": {"target_id": "53691", "status": "pending",
                       "arrival_time": 2000000000, "attacks": attacks}}


def _atk(vid, status="pending", axe=100):
    return {"source_village_id": vid, "status": status,
            "troops": {"snob": 1, "axe": axe}}


# --------------------------------------------------------------------------
# Teto
# --------------------------------------------------------------------------

def test_default_continua_um_trem_por_vez():
    """Sem a chave, nada muda para quem nao pediu trens paralelos."""
    p, calls = _planner(active={"53691": {"status": "train_scheduled"}})
    assert p.run() is None
    assert calls["schedules"] == []


def test_teto_tres_com_um_ativo_agenda_outro():
    p, calls = _planner(active={"53691": {"status": "train_scheduled"}}, cfg=CFG3)
    assert p.run() == "49709"
    assert len(calls["schedules"]) == 1


def test_teto_cheio_nao_agenda():
    active = {t: {"status": "train_sent"} for t in ("1", "2", "3")}
    p, calls = _planner(active=active, cfg=CFG3)
    assert p.run() is None
    assert calls["schedules"] == []


def test_um_trem_novo_por_ciclo():
    """
    Mesmo com vaga e nobre para dois, sai um: a escrita do quadro da tribo e
    uma por ciclo, e o segundo trem ficaria sem reserva anunciada.
    """
    villages = {"41123": _Village("41123", {"snob": 8, "axe": 8000}, [577, 306])}
    p, calls = _planner(villages=villages, cfg=CFG3)
    assert p.run() == "49709"
    assert len(calls["schedules"]) == 1


def test_valor_do_teto_tolerante():
    p, _ = _planner()
    assert p._max_parallel_trains({}) == 1
    assert p._max_parallel_trains({"max_parallel_trains": "3"}) == 3
    assert p._max_parallel_trains({"max_parallel_trains": 2.9}) == 2
    for torto in (0, -1, "tres", None, [3]):
        assert p._max_parallel_trains({"max_parallel_trains": torto}) == 1, torto


# --------------------------------------------------------------------------
# Nobres de um trem agendado nao entram em outro
# --------------------------------------------------------------------------

def _caso_de_campo():
    """8 nobres em casa, 4 deles esperando o send_time do trem da 53691."""
    return {
        "41123": _Village("41123", {"snob": 4, "axe": 4000}, [577, 306]),
        "74689": _Village("74689", {"snob": 3, "axe": 3000}, [578, 306]),
        "37318": _Village("37318", {"snob": 1, "axe": 1000}, [575, 300]),
    }


def _attacks_53691():
    return [_atk("74689"), _atk("74689"), _atk("37318"), _atk("41123")]


def test_depois_de_reinicio_a_reserva_volta_do_hunter():
    """
    O bot reinicia quase todo dia (sessao vencida) e a reserva `barb_train:*`
    vive na memoria. Sem reconstruir, os 8 nobres pareceriam livres e o trem
    novo levaria os 4 que o Hunter vai despachar contra a 53691.
    """
    villages = _caso_de_campo()  # conquest_reserve vazio: acabou de reiniciar
    p, calls = _planner(villages=villages, store=dict(SCHEDULED),
                        schedules=_schedules(_attacks_53691()),
                        active=dict(SCHEDULED), cfg=CFG3)
    assert p.run() == "49709"
    (sched,) = calls["schedules"]
    por_origem = {}
    for atk in sched["attacks"]:
        vid = atk["source_village_id"]
        por_origem[vid] = por_origem.get(vid, 0) + 1
    # 41123: 4 - 1 do trem da 53691 = 3; 74689: 3 - 2 = 1; 37318: 1 - 1 = 0.
    assert por_origem == {"41123": 3, "74689": 1}, por_origem
    assert villages["74689"].units.conquest_reserve["barb_train:53691"] == {
        "snob": 2, "axe": 200}
    assert villages["37318"].units.conquest_reserve["barb_train:53691"] == {
        "snob": 1, "axe": 100}


def test_sem_nobre_sobrando_nao_monta_segundo_trem():
    """
    So 2 nobres alem dos 4 do trem agendado: nao ha segundo trem. Sem a
    reconstrucao, 6 pareceriam livres e o trem sairia com nobre emprestado.
    """
    villages = {
        "41123": _Village("41123", {"snob": 5, "axe": 4000}, [577, 306]),
        "74689": _Village("74689", {"snob": 1, "axe": 3000}, [578, 306]),
    }
    attacks = [_atk("41123"), _atk("41123"), _atk("41123"), _atk("74689")]
    p, calls = _planner(villages=villages, store=dict(SCHEDULED),
                        schedules=_schedules(attacks),
                        active=dict(SCHEDULED), cfg=CFG3)
    assert p.run() is None
    assert calls["schedules"] == []


def test_reserva_em_memoria_conta_contra_o_trem_novo():
    """Sem reinicio: a reserva que o _schedule() pos ja desconta."""
    villages = _caso_de_campo()
    villages["41123"].units.conquest_reserve["barb_train:53691"] = {"snob": 4}
    p, _ = _planner(villages=villages, cfg=CFG3)
    assert ("41123", 4) not in p._noble_sources()
    assert sum(q for _v, q in p._noble_sources()) == 4


# --------------------------------------------------------------------------
# _sync_scheduled_reserves
# --------------------------------------------------------------------------

def test_so_comando_pendente_reserva():
    """O comando `sent` ja levou a tropa; reserva-la descontaria duas vezes."""
    villages = _caso_de_campo()
    attacks = [_atk("41123", "sent"), _atk("41123", "pending", axe=50),
               _atk("74689", "sent")]
    villages["74689"].units.conquest_reserve["barb_train:53691"] = {"snob": 1, "axe": 100}
    p, _ = _planner(villages=villages, store=dict(SCHEDULED),
                    schedules=_schedules(attacks))
    p._sync_scheduled_reserves()
    assert villages["41123"].units.conquest_reserve["barb_train:53691"] == {
        "snob": 1, "axe": 50}
    # A 74689 ja mandou tudo: a reserva dela sai antes da promocao.
    assert "barb_train:53691" not in villages["74689"].units.conquest_reserve


def test_arquivo_vazio_nao_solta_nada():
    """Perder o arquivo nao e "todos os comandos ja sairam"."""
    villages = _caso_de_campo()
    villages["41123"].units.conquest_reserve["barb_train:53691"] = {"snob": 1}
    p, _ = _planner(villages=villages, store=dict(SCHEDULED), schedules={})
    p._sync_scheduled_reserves()
    assert villages["41123"].units.conquest_reserve["barb_train:53691"] == {"snob": 1}


def test_schedule_do_alvo_ausente_nao_mexe():
    villages = _caso_de_campo()
    villages["41123"].units.conquest_reserve["barb_train:53691"] = {"snob": 1}
    outro = {"kOutro": {"attacks": [_atk("41123")]}}
    p, _ = _planner(villages=villages, store=dict(SCHEDULED), schedules=outro)
    p._sync_scheduled_reserves()
    assert villages["41123"].units.conquest_reserve["barb_train:53691"] == {"snob": 1}


def test_trem_ja_promovido_nao_ganha_reserva():
    """Depois de `train_sent` a tropa voou; o schedule antigo nao reserva nada."""
    villages = _caso_de_campo()
    store = {"53691": dict(SCHEDULED["53691"], status="train_sent")}
    p, _ = _planner(villages=villages, store=store,
                    schedules=_schedules(_attacks_53691()))
    p._sync_scheduled_reserves()
    assert all(not v.units.conquest_reserve for v in villages.values())


def test_reserva_de_outro_dono_fica():
    villages = _caso_de_campo()
    villages["41123"].units.conquest_reserve["pvp:900"] = {"snob": 1}
    p, _ = _planner(villages=villages, store=dict(SCHEDULED),
                    schedules=_schedules(_attacks_53691()))
    p._sync_scheduled_reserves()
    assert villages["41123"].units.conquest_reserve["pvp:900"] == {"snob": 1}


def test_aldeia_sem_units_e_pulada():
    """Aldeia ainda nao primada neste processo: fica para o proximo ciclo."""
    villages = _caso_de_campo()
    villages["37318"].units = None
    p, _ = _planner(villages=villages, store=dict(SCHEDULED),
                    schedules=_schedules(_attacks_53691()))
    p._sync_scheduled_reserves()
    assert villages["41123"].units.conquest_reserve["barb_train:53691"] == {
        "snob": 1, "axe": 100}


def test_config_de_exemplo_tem_a_chave_com_default_um():
    import json
    raiz = os.path.dirname(HERE)
    with open(os.path.join(raiz, "config.example.json"), encoding="utf-8") as f:
        conquest = json.load(f)["conquest"]
    assert conquest["max_parallel_trains"] == 1


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
    _ = base  # os dubles do modulo base ficam instalados; nada a desfazer
    sys.exit(1 if falhas else 0)
