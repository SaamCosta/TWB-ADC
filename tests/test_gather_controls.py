"""Scavenging selection and the webmanager's account-wide configuration.

Runs without pytest:
    python tests/test_gather_controls.py
"""
import json
import logging
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from core.extractors import Extractor
from core.filemanager import FileManager
from game.troopmanager import TroopManager
from twb import TWB
from webmanager.server import app
from webmanager.utils import DataReader


checks = 0


def check(condition, message):
    global checks
    checks += 1
    if not condition:
        raise AssertionError(message)


OPTIONS = {
    "1": {"is_locked": False, "scavenging_squad": None},
    "2": {"is_locked": False, "scavenging_squad": None},
    "3": {"is_locked": True, "scavenging_squad": None},
    "4": {"is_locked": True, "scavenging_squad": None},
}

check(TroopManager.effective_gather_selection(OPTIONS, 4) == 2,
      "o teto 4 deve se ajustar ao maior nivel realmente desbloqueado")
check(TroopManager.effective_gather_selection(OPTIONS, 1) == 1,
      "o teto manual menor continua sendo respeitado")
check(TroopManager.effective_gather_selection({"1": {"is_locked": True}}, 4) == 0,
      "sem opcao desbloqueada o manager deve se abster")
check(TroopManager.effective_gather_selection({"x": {}, "2": {}}, 4) == 0,
      "linha malformada ou sem estado de lock nao prova disponibilidade")
check(TroopManager.effective_gather_selection([], 4) == 0,
      "container de opcoes malformado deve degradar para abstencao")
check(TroopManager.gather_option_keys({"x": {}, "1": {}, "4": {}, "2": {}}, 3) == ["2", "1"],
      "ids invalidos e opcoes acima do teto devem ser ignorados")
check(TroopManager.gather_option_keys({1: {}, "1": {}, "2": {}}, 2) == ["2", 1, "1"],
      "ids numericamente iguais nao podem falhar ao ordenar tipos mistos")

# Regression for the upstream-discovered memory/session bug: Village objects
# are distinct, but every one must point at the account's one live wrapper.
bot = TWB()
shared_wrapper = object()
bot.wrapper = shared_wrapper
first_village = bot._new_village("101")
second_village = bot._new_village("202")
check(first_village is not second_village,
      "cada aldeia deve continuar tendo um objeto de estado proprio")
check(first_village.wrapper is shared_wrapper and second_village.wrapper is shared_wrapper,
      "aldeias nao podem clonar a sessao HTTP compartilhada")


class FakeWrapper:
    def __init__(self):
        self.last_h = "csrf"
        self.sent = []

    def get_url(self, url):
        return object()

    def get_api_action(self, **kwargs):
        self.sent.append(kwargs["data"]["squad_requests[0][option_id]"])
        return {"ok": True}


# Regression: option 4 locked and option 3 already running must not prevent
# basic mode from falling through to option 2.  Once option 2 receives the
# whole army, basic mode must stop rather than reuse those troops on option 1.
runtime_options = {
    "1": {"is_locked": False, "scavenging_squad": None},
    "2": {"is_locked": False, "scavenging_squad": None},
    "3": {"is_locked": False, "scavenging_squad": {"return_time": 1}},
    "4": {"is_locked": True, "scavenging_squad": None},
}
original_village_data = Extractor.village_data
original_units = Extractor.units_in_village
Extractor.village_data = staticmethod(lambda _result: {"options": runtime_options})
Extractor.units_in_village = staticmethod(lambda _result: [("spear", "10")])
try:
    manager = TroopManager.__new__(TroopManager)
    manager.wrapper = FakeWrapper()
    manager.village_id = "101"
    manager.logger = logging.getLogger("test.gather")
    manager.can_gather = True
    manager.total_troops = {"spear": 10}
    manager.conquest_reserve = {}
    manager.gather(selection=4, disabled_units=[], advanced_gather=False)
    check(manager.wrapper.sent == ["2"],
          "modo basico deve pular 4/3, enviar uma vez na 2 e parar: %r" % manager.wrapper.sent)
finally:
    Extractor.village_data = staticmethod(original_village_data)
    Extractor.units_in_village = staticmethod(original_units)


# Bulk configuration: all villages change in a single atomic FileManager save,
# unrelated fields survive, and disabling never rewinds the chosen ceiling.
tmp = tempfile.mkdtemp(prefix="twb_gather_controls_")
original_root = FileManager.get_root
original_save = FileManager.save_json_file
save_calls = []
FileManager.get_root = staticmethod(lambda: tmp)


def counted_save(data, path, **kwargs):
    save_calls.append(path)
    return original_save(data, path, **kwargs)


FileManager.save_json_file = staticmethod(counted_save)
try:
    fixture = {
        "build": {"version": "test"},
        "villages": {
            "101": {"managed": True, "gather_enabled": False, "gather_selection": 1, "profile": "offensive"},
            "202": {"managed": False, "gather_enabled": False, "gather_selection": 2, "profile": "defensive"},
        },
    }
    with open(os.path.join(tmp, "config.json"), "w", encoding="utf-8") as handle:
        json.dump(fixture, handle)

    summary = DataReader.gather_bulk_set(True, use_all_unlocked=False)
    saved = FileManager.load_json_file("config.json")
    check(summary == {"total": 2, "managed": 1, "enabled": 2, "all_options": 0},
          "resumo da ativacao simples incorreto: %r" % summary)
    check(saved["villages"]["101"]["gather_selection"] == 1
          and saved["villages"]["202"]["gather_selection"] == 2,
          "ativar nao pode mudar silenciosamente os tetos atuais")
    check(saved["villages"]["101"]["profile"] == "offensive",
          "campos alheios a coleta precisam sobreviver")
    check(save_calls == ["config.json"],
          "a conta inteira deve ser persistida em uma unica escrita: %r" % save_calls)

    save_calls.clear()
    summary = DataReader.gather_bulk_set(True, use_all_unlocked=True)
    saved = FileManager.load_json_file("config.json")
    check(summary["all_options"] == 2
          and all(v["gather_selection"] == 4 for v in saved["villages"].values()),
          "modo todas desbloqueadas deve gravar o teto 4 em todas")
    check(save_calls == ["config.json"], "segunda alteracao em massa tambem deve ter uma escrita")

    # The HTTP contract validates the action and delegates to the same one-save
    # path.  The receipt explicitly distinguishes persistence from game effect.
    save_calls.clear()
    client = app.test_client()
    response = client.post("/app/gather/bulk", json={"action": "enable"})
    body = response.get_json()
    check(response.status_code == 200 and body["persisted"] is True,
          "rota em massa deve confirmar a persistencia")
    check(body["effect"] == "pending_next_cycle" and save_calls == ["config.json"],
          "recibo deve manter efeito pendente e uma unica escrita: %r" % body)
    check(client.post("/app/gather/bulk", json={"action": "invented"}).status_code == 400,
          "acao desconhecida deve ser recusada sem alterar config")
    check(save_calls == ["config.json"],
          "acao invalida nao pode persistir nada")

    DataReader.gather_bulk_set(False)
    saved = FileManager.load_json_file("config.json")
    check(not any(v["gather_enabled"] for v in saved["villages"].values()),
          "desativar deve cobrir todas as aldeias")
    check(all(v["gather_selection"] == 4 for v in saved["villages"].values()),
          "desativar nao deve apagar a preferencia de nivel")
    malformed = {"villages": {"x": {"gather_selection": "?"}}}
    check(DataReader.gather_config_summary(malformed)["all_options"] == 0,
          "resumo nao pode derrubar a pagina por valor legado malformado")
    check(DataReader.gather_config_summary([])["total"] == 0,
          "resumo deve degradar com raiz de config malformada")

    with open(os.path.join(tmp, "config.json"), "w", encoding="utf-8") as handle:
        handle.write("{json interrompido")
    response = client.post("/app/gather/bulk", json={"action": "enable"})
    check(response.status_code == 409,
          "config JSON corrompida deve virar conflito explicito, nao HTTP 500")
finally:
    FileManager.save_json_file = staticmethod(original_save)
    FileManager.get_root = staticmethod(original_root)
    shutil.rmtree(tmp)


print("OK - %d checks" % checks)
