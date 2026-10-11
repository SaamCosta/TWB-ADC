"""
Apoio agendado no Hunter (docs/backend.md §8.61): um comando de APOIO que
pousa N segundos depois de uma chegada -- tipicamente a do nosso trem de
nobres, para a aldeia recém-conquistada já ter defesa.

Cobre: a sonda pelo botão de apoio (`_probe_duration(kind="support")`), a
trava `arrive_after` de `DefenceManager.support()` (apoio que pousaria ANTES
do nobre defenderia a aldeia contra o próprio trem), a chegada real dos
nobres já enviados (`linked_arrive_after`), a recusa quando um nobre do trem
falhou, o despacho dentro do `_run()` sem misturar apoio no lote de ataque, a
reserva da tropa na origem e o `HunterReader.add_support_after()` do painel.

Nada grava no `cache/hunter/schedules.json` de produção: o Hunter recebe
`_load_schedules`/`_save_schedules` em memória (como em
test_hunter_schedule_queue.py) e o `HunterReader` aponta para um arquivo
temporário.

Rodar: python tests/test_hunter_support.py
"""
import datetime
import json
import os
import sys
import tempfile
import time
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "webmanager"))

from game.defence_manager import DefenceManager
from game.hunter import Hunter

with open(os.path.join(ROOT, "tests", "fixtures", "place_confirm_support_br143.html"),
          encoding="utf-8") as _fh:
    CONFIRM_SUPPORT = _fh.read()  # confirmação real de apoio, data-duration=764

PLACE_FORM = (
    '<input name="template_id" value="">'
    '<input id="target_attack" class="attack btn" name="attack" type="submit" value="Ataque" />'
    '<input id="target_support" class="support btn" name="support" type="submit" value="Apoio" />'
)


def _check(label, got, expected):
    assert got == expected, f"{label}: esperado {expected!r}, veio {got!r}"
    print(f"  ok  {label}: {got!r}")


class _Wrapper:
    last_h = "csrf"

    def __init__(self, confirm=CONFIRM_SUPPORT):
        self.confirm = confirm
        self.posts = []
        self.finals = []

    def get_url(self, url):
        return SimpleNamespace(text=PLACE_FORM)

    def post_url(self, url, data):
        self.posts.append(dict(data))
        return SimpleNamespace(text=self.confirm)

    def get_api_action(self, village_id, action, params, data):
        self.finals.append(data)
        return {"success": True}


def _village(vid="49709", troops=None):
    attack = SimpleNamespace(_resolve_position=lambda target: (531, 289),
                             attack=lambda *a, **k: True)
    units = SimpleNamespace(troops=dict(troops or {"heavy": "561"}), conquest_reserve={})
    return SimpleNamespace(village_id=vid, area=object(), attack=attack, units=units)


def test_sonda_pelo_botao_de_apoio():
    print("test_sonda_pelo_botao_de_apoio")
    hunter = Hunter(wrapper=_Wrapper())
    hunter.villages = {"49709": _village()}
    duration = hunter._probe_duration("49709", "40808", {"heavy": 5}, kind="support")
    post = hunter.wrapper.posts[-1]
    _check("duração da confirmação de apoio", duration, 764)
    _check("só o botão de apoio no POST", ("attack" in post, post.get("support")), (False, "Apoio"))
    hunter = Hunter(wrapper=_Wrapper(confirm="<form id=\"command-data-form\"></form>"))
    hunter.villages = {"49709": _village()}
    _check("confirmação que não é de apoio não vale",
           hunter._probe_duration("49709", "40808", {"heavy": 5}, kind="support"), None)


def test_support_nao_pousa_antes():
    print("test_support_nao_pousa_antes")
    dm = DefenceManager(village_id="49709", wrapper=_Wrapper())
    ok = dm.support("40808", troops={"heavy": 5}, position=(531, 289),
                    arrive_after=time.time() + 800)
    _check("764 s pousaria antes do trem: não sai", ok, False)
    _check("nenhum comando criado", dm.wrapper.finals, [])
    _check("motivo", "antes do nobre" in dm.last_support_error, True)
    dm = DefenceManager(village_id="49709", wrapper=_Wrapper())
    ok = dm.support("40808", troops={"heavy": 5}, position=(531, 289),
                    arrive_after=time.time() + 700)
    _check("pousa depois: sai", bool(ok), True)


def _train(arrival, statuses):
    attacks = []
    for i, (status, sent_delay) in enumerate(statuses):
        atk = {"source_village_id": str(100 + i), "troops": {"snob": 1, "axe": 100},
               "send_time": arrival - 3600, "status": status}
        if status == "sent":
            atk["sent_at"] = arrival - 3600 + sent_delay
        if status == "failed":
            atk["fail_reason"] = "send_time_missed"
        attacks.append(atk)
    return {"target_id": "40808", "arrival_time": arrival, "status": "pending",
            "attacks": attacks}


def test_chegada_real_do_trem():
    print("test_chegada_real_do_trem")
    T = 1_800_000_000
    sched = {"arrive_after": T, "after_sched": "trem"}
    after, refusal = Hunter.linked_arrive_after(sched, {"trem": _train(T, [("sent", 2), ("sent", 3)])})
    _check("o nobre mais atrasado empurra a base", (after, refusal), (T + 3, None))
    after, refusal = Hunter.linked_arrive_after(sched, {"trem": _train(T, [("sent", 1), ("pending", 0)])})
    _check("nobre pendente não recusa", refusal, None)
    after, refusal = Hunter.linked_arrive_after(sched, {"trem": _train(T, [("sent", 1), ("failed", 0)])})
    _check("nobre que falhou recusa o apoio", refusal is not None, True)
    _check("sem trem ligado vale a base", Hunter.linked_arrive_after({"arrive_after": T}, {}), (T, None))


def _support_sched(arrival, send_time, after_sched=None):
    return {"target_id": "40808", "label": "apoio", "arrival_time": arrival,
            "arrive_after": arrival - 5, "after_sched": after_sched, "status": "pending",
            "attacks": [{"source_village_id": "49709", "troops": {"heavy": 300},
                         "kind": "support", "send_time": send_time, "status": "pending"}]}


def _hunter_with(schedules, wrapper):
    hunter = Hunter(wrapper=wrapper)
    hunter.villages = {"49709": _village()}
    hunter._load_schedules = lambda: schedules
    hunter._save_schedules = lambda *_a: None
    hunter._schedule_deleted = lambda key: False
    return hunter


def test_run_despacha_apoio():
    print("test_run_despacha_apoio")
    now = time.time()
    # Chegada base daqui a 764 s (a duração do fixture) + 5 s depois.
    arrival = now + 0.2 + 764 + 5
    schedules = {"apoio": _support_sched(arrival, now + 0.2)}
    wrapper = _Wrapper()
    hunter = _hunter_with(schedules, wrapper)
    hunter._run({"hunter": {"enabled": True}})
    atk = schedules["apoio"]["attacks"][0]
    _check("enviado", atk["status"], "sent")
    _check("um comando criado", len(wrapper.finals), 1)
    _check("POST de apoio, não de ataque", "attack" in wrapper.posts[-1], False)
    _check("tropa descontada da origem", hunter.villages["49709"].units.troops["heavy"], "261")
    _check("schedule fechado", schedules["apoio"]["status"], "complete")


def test_run_recusa_com_nobre_falho():
    print("test_run_recusa_com_nobre_falho")
    now = time.time()
    arrival = now + 0.2 + 764 + 5
    schedules = {"trem": _train(arrival - 5, [("failed", 0)]),
                 "apoio": _support_sched(arrival, now + 0.2, after_sched="trem")}
    schedules["trem"]["status"] = "failed"
    wrapper = _Wrapper()
    hunter = _hunter_with(schedules, wrapper)
    hunter._run({"hunter": {"enabled": True}})
    atk = schedules["apoio"]["attacks"][0]
    _check("apoio não sai", atk["status"], "failed")
    _check("nem chega na praça", wrapper.posts, [])
    _check("motivo gravado", "falhou" in atk["fail_reason"], True)


def test_reserva_na_origem():
    print("test_reserva_na_origem")
    hunter = Hunter(wrapper=None)
    village = _village()
    village.units.conquest_reserve = {"apoio_agendado:velho": {"heavy": 1}, "outro": {"axe": 9}}
    hunter.villages = {"49709": village}
    schedules = {"apoio": _support_sched(time.time() + 9999, None)}
    hunter.sync_support_reserves(schedules)
    _check("reserva do pendente", village.units.conquest_reserve.get("apoio_agendado:apoio"),
           {"heavy": 300})
    _check("reserva de apoio que sumiu solta", "apoio_agendado:velho" in village.units.conquest_reserve, False)
    _check("reserva alheia intacta", village.units.conquest_reserve.get("outro"), {"axe": 9})
    schedules["apoio"]["attacks"][0]["status"] = "sent"
    hunter.sync_support_reserves(schedules)
    _check("enviado solta", "apoio_agendado:apoio" in village.units.conquest_reserve, False)


def test_painel_agenda_apoio():
    print("test_painel_agenda_apoio")
    from utils import HunterReader
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "schedules.json")
    original = HunterReader._cache_path
    HunterReader._cache_path = staticmethod(lambda: path)
    try:
        base = datetime.datetime.now().replace(microsecond=0) + datetime.timedelta(hours=3)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"trem": {"target_id": "40808", "arrival_time": base.timestamp(),
                                "status": "pending", "attacks": []}}, fh)
        ok, msg = HunterReader.add_support_after("49709", {"heavy": 300, "axe": 50}, 5,
                                                  after_sched="trem")
        _check("gravado", ok, True)
        data = json.load(open(path, encoding="utf-8"))
        sched = next(v for k, v in data.items() if k != "trem")
        _check("chegada = base + 5 s", sched["arrival_time"] - base.timestamp(), 5.0)
        _check("não pousa antes da base", sched["arrive_after"], base.timestamp())
        _check("ligado ao trem", sched["after_sched"], "trem")
        _check("bárbaro fora do apoio", sched["attacks"][0]["troops"], {"heavy": 300})
        _check("tipo", sched["attacks"][0]["kind"], "support")
        ok, msg = HunterReader.add_support_after("49709", {"heavy": 300}, 5, after_sched="trem")
        _check("duplicado recusado", ok, False)
        ok, _ = HunterReader.add_support_after(
            "49709", {"heavy": 1}, 3, target_id="40808",
            base_arrival_str=base.strftime(HunterReader.DATETIME_FMT))
        _check("chegada digitada", ok, True)
        ok, _ = HunterReader.add_support_after("49709", {"heavy": 1}, 0, after_sched="trem")
        _check("0 s recusado", ok, False)
    finally:
        HunterReader._cache_path = original


if __name__ == "__main__":
    test_sonda_pelo_botao_de_apoio()
    test_support_nao_pousa_antes()
    test_chegada_real_do_trem()
    test_run_despacha_apoio()
    test_run_recusa_com_nobre_falho()
    test_reserva_na_origem()
    test_painel_agenda_apoio()
    print("\nOK - todos os testes do apoio agendado passaram")
