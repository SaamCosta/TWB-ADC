"""
Testes do caminho de alvo MANUAL da conquista barbara (Feature 15).

  AttackManager._resolve_position()      -- de onde sai a coordenada do alvo
  ConquestManager._note_failed_claim()   -- saida da fila para alvo intratavel

Por que existem: o caminho manual estava completo de ponta a ponta e NUNCA
tinha sido exercitado -- em 16/09/2026 os 21 arquivos de cache/conquest
estavam todos em "conquered" e um grep nos logs por "manually queued" nao
devolvia uma linha. Dois defeitos so apareceram lendo o codigo:

1. `attack()` exigia o alvo em `self.map.map_pos`, que e o scan de mapa DAQUELA
   aldeia naquele ciclo. O webmanager valida o alvo contra `cache/villages`,
   que e compartilhado -- entao um alvo legitimo era recusado em silencio se a
   aldeia que o reivindicou nao o tivesse no proprio prefetch. Com
   `farms.map_sector_radius = 0` (o valor em campo) esse prefetch e pequeno e
   erratico, ver o comentario em map.py:56.

2. `find_target()` devolve alvo manual antes de tudo e sem condicao, entao um
   alvo que nunca consegue ser enviado congelava a selecao automatica da conta
   INTEIRA, para sempre, com `attack 1/4 failed` como unico sinal.

Nada aqui toca o cache real: `FileManager.load_json_file` e os dois metodos de
`ConquestCache` sao substituidos por fixtures em memoria. O bot escreve em
cache/conquest enquanto roda, e um teste que faz setup destrutivo num artefato
de producao e o vigesimo primeiro padrao do CLAUDE.md.

Rodar: python tests/test_conquest_manual_target.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import game.attack as attack_mod
from game.attack import AttackManager, ConquestManager


class _Logger:
    def debug(self, *a, **k): pass
    def info(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def error(self, *a, **k): pass


class _Map:
    def __init__(self, map_pos):
        self.map_pos = map_pos


def _attacker(map_pos, villages_cache):
    """AttackManager cru, com as duas fontes de coordenada controladas."""
    man = AttackManager.__new__(AttackManager)
    man.village_id = "41123"
    man.logger = _Logger()
    man.map = _Map(map_pos)

    class _FM:
        @staticmethod
        def load_json_file(path, **kwargs):
            return villages_cache.get(path)

    attack_mod.FileManager = _FM
    return man


# --------------------------------------------------------------------------
# _resolve_position
# --------------------------------------------------------------------------

def test_scan_local_ganha_do_cache():
    """
    O farm depende disto: ele itera sobre map.villages, entao o alvo sempre
    veio do scan e nao pode passar a pagar uma leitura de disco por ataque.
    """
    man = _attacker(
        map_pos={"49709": [572, 295]},
        villages_cache={"cache/villages/49709.json": {"location": [1, 1]}},
    )
    assert man._resolve_position("49709") == [572, 295]


def test_cache_compartilhado_salva_alvo_fora_do_scan():
    """
    O bug: este caso devolvia False em silencio e o trem de nobres nunca saia.
    """
    man = _attacker(
        map_pos={},
        villages_cache={"cache/villages/49709.json": {
            "location": [572, 295], "owner": "0", "points": 856,
        }},
    )
    assert man._resolve_position("49709") == (572, 295)


def test_coordenada_de_texto_vira_inteiro():
    """
    O round-trip por JSON nao garante int -- e x/y vao direto para o POST.
    """
    man = _attacker(
        map_pos={},
        villages_cache={"cache/villages/49709.json": {"location": ["572", "295"]}},
    )
    assert man._resolve_position("49709") == (572, 295)


def test_sem_coordenada_em_lugar_nenhum_recusa():
    """
    O gate do P2-38 continua valendo: sem coordenada nao se gasta o GET da
    praca (que carrega o sleep de delay_factor).
    """
    man = _attacker(map_pos={}, villages_cache={})
    assert man._resolve_position("49709") is None


def test_cache_sem_a_chave_location_recusa():
    """Arquivo existe mas truncado/de outro formato -- nao inventar coordenada."""
    man = _attacker(
        map_pos={},
        villages_cache={"cache/villages/49709.json": {"owner": "0"}},
    )
    assert man._resolve_position("49709") is None


# --------------------------------------------------------------------------
# _note_failed_claim
# --------------------------------------------------------------------------

def _conquest(store):
    """ConquestManager cru com ConquestCache em memoria."""
    man = ConquestManager.__new__(ConquestManager)
    man.village_id = "41123"
    man.logger = _Logger()

    class _Cache:
        @staticmethod
        def get(target_id):
            return store.get(target_id)

        @staticmethod
        def set(target_id, entry):
            store[target_id] = entry

        nobles_in_flight = staticmethod(attack_mod.ConquestCache.nobles_in_flight)

    attack_mod.ConquestCache = _Cache
    return man


def test_primeira_falha_so_conta():
    store = {"49709": {"status": "manual", "queued_at": 1}}
    _conquest(store)._note_failed_claim("49709")
    assert store["49709"]["status"] == "manual"
    assert store["49709"]["failed_claims"] == 1


def test_terceira_falha_tira_da_fila():
    """
    A saida que faltava. Sem ela a selecao automatica da conta inteira fica
    parada enquanto o registro existir.
    """
    store = {"49709": {"status": "manual", "failed_claims": 2}}
    _conquest(store)._note_failed_claim("49709")
    assert store["49709"]["status"] == "invalid"
    assert "3 tentativas" in store["49709"]["invalid_reason"]


def test_alvo_automatico_nao_e_tocado():
    """
    _note_failed_claim so fala sobre a fila manual. Um registro train_sent que
    falhou nao pode virar "invalid" -- ha nobres reais associados a ele.
    """
    store = {"49709": {"status": "train_sent", "hits_done": 4}}
    _conquest(store)._note_failed_claim("49709")
    assert store["49709"] == {"status": "train_sent", "hits_done": 4}


def test_nobre_em_voo_nao_conta_como_falha():
    """
    _send_train devolve False quando o _noble_flight_guard segura o envio, e
    isso e o sistema funcionando. Contar como falha invalidaria justamente o
    alvo que esta dando certo -- e a trava de nobre em voo existe por causa das
    527 tropas perdidas em 2026-08-12.
    """
    futuro = 4102444800  # 2100-01-01, bem depois de qualquer execucao
    store = {"49709": {"status": "manual", "noble_arrivals": [futuro]}}
    _conquest(store)._note_failed_claim("49709")
    assert "failed_claims" not in store["49709"]


def test_chegada_desconhecida_tambem_segura():
    """
    None em noble_arrivals = "nobre enviado, chegada desconhecida" (inf em
    nobles_in_flight). Tambem e nobre no ar, entao tambem nao e falha do alvo.
    """
    store = {"49709": {"status": "manual", "noble_arrivals": [None]}}
    _conquest(store)._note_failed_claim("49709")
    assert "failed_claims" not in store["49709"]


def test_registro_inexistente_nao_quebra():
    store = {}
    _conquest(store)._note_failed_claim("99999")
    assert store == {}


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
