"""
Testes do registro do motivo de exclusao de alvo de farm.

  FarmExclusionLog                       -- buffer, teto por fase, snapshot
  AttackManager._record_attack_failure() -- traduz o desfecho falsy do attack()
  AttackManager._record_scout_attempt()  -- separa "explorou" de "nao tinha espiao"
  AttackManager.run()                    -- fora do teto e ciclo interrompido

O que isto protege, em ordem de importancia:

1. **"Nao sei" nao pode virar "o jogo recusou".** `attack()` devolve False
   igual para alvo sem coordenada, timeout de rede e recusa do servidor, e so
   no ultimo caso `last_refusal` fica preenchido. Se o painel apresentar os
   tres como recusa, ele reintroduz exatamente o problema que esta feature
   existe para resolver -- e com a agravante de parecer diagnostico.

2. **Ausencia de linha nao pode significar duas coisas.** Um alvo que o teto de
   `max_farms` cortou e um alvo que o laco nem alcancou (porque acabou a tropa)
   apareceriam identicos: sem registro nenhum. O vigesimo sexto padrao do
   CLAUDE.md descreve a falha -- lista curta e indistinguivel de lista
   completa -- e aqui ela teria a forma "o painel nao diz nada sobre 300
   alvos".

3. **O teto de entradas corta so a fase de selecao.** As entradas de tentativa
   sao poucas e sao as unicas com valor diagnostico; um teto global as
   perderia primeiro, porque elas sao registradas depois.

Rodar: python tests/test_farm_exclusions.py
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game.attack import AttackManager
from game.farm_exclusions import (
    FarmExclusionLog,
    MAX_SELECAO,
    REASONS,
    FASE_SELECAO,
    FASE_TENTATIVA,
)


class _Silent:
    def __getattr__(self, _):
        return lambda *a, **k: None


def _man():
    """AttackManager so com o que os metodos de registro tocam."""
    man = AttackManager.__new__(AttackManager)
    man.village_id = "1"
    man.logger = _Silent()
    man.scout_farm_amount = 5
    man.last_refusal = None
    man.last_attack_failure = None
    man.exclusions = FarmExclusionLog(None).begin()
    return man


# --------------------------------------------------------------------------
# Vocabulario
# --------------------------------------------------------------------------

def test_todo_codigo_tem_fase_rotulo_e_ajuda():
    for code, meta in REASONS.items():
        assert meta["phase"] in (FASE_SELECAO, FASE_TENTATIVA), code
        assert meta["label"], code
        assert meta["detail_help"], code
        assert "knob" in meta, code


def test_codigos_usados_pelo_manager_existem_no_vocabulario():
    """
    O registrador aceita codigo desconhecido de proposito (nao pode derrubar o
    farm), entao nada explodiria se o manager escrevesse um codigo com erro de
    digitacao -- o painel so mostraria o codigo cru para sempre. Esta lista e a
    guarda: os codigos que o AttackManager escreve sao literais no fonte.
    """
    fonte = open(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "game", "attack.py"),
        encoding="utf-8",
    ).read()
    usados = [c for c in REASONS if '"%s"' % c in fonte]
    # Os que o manager de fato escreve hoje. "atacado" entra por attacked().
    esperados = {
        "dono_jogador", "pontos_acima_max", "pontos_abaixo_min",
        "pontos_maiores_que_os_meus", "bloqueado_pelo_jogo",
        "janela_noturna_jogador", "longe_demais", "fora_do_teto",
        "ciclo_encerrado_sem_tropa", "sem_tropa_em_casa", "espiao_enviado",
        "sem_espiao", "aguardando_relatorio_espiao", "relatorio_viu_tropa",
        "inseguro_sem_relatorio", "intervalo_entre_ataques",
        "recusado_pelo_jogo", "paz_forcada", "sem_coordenada", "falha_de_rede",
    }
    assert esperados.issubset(set(usados)), esperados - set(usados)


# --------------------------------------------------------------------------
# FarmExclusionLog
# --------------------------------------------------------------------------

def test_begin_descarta_o_ciclo_anterior():
    log = FarmExclusionLog("1").begin()
    log.record("9", "longe_demais")
    log.begin()
    assert log.entries == {}
    assert log.summary == {}
    assert log.truncated is False


def test_summary_conta_todas_as_ocorrencias_mesmo_truncadas():
    """
    A contagem tem que sobreviver ao teto, senao truncar mentiria sobre o
    tamanho do problema -- e o total e justamente o que responde "por que so
    3 alvos hoje?".
    """
    log = FarmExclusionLog("1").begin()
    for i in range(MAX_SELECAO + 50):
        log.record(str(i), "longe_demais")
    assert log.summary["longe_demais"] == MAX_SELECAO + 50
    assert len(log.entries) == MAX_SELECAO
    assert log.truncated is True


def test_teto_nao_corta_a_fase_de_tentativa():
    log = FarmExclusionLog("1").begin()
    for i in range(MAX_SELECAO + 50):
        log.record("sel%d" % i, "longe_demais")
    log.record("alvo", "recusado_pelo_jogo", "mensagem do jogo")
    assert log.entries["alvo"]["code"] == "recusado_pelo_jogo"
    assert log.entries["alvo"]["phase"] == FASE_TENTATIVA


def test_desfecho_positivo_sobrescreve_recusa_do_mesmo_ciclo():
    """
    O laco tenta pacotes em escada: o grande pode ser recusado e o pequeno
    passar. Se a recusa ficasse, o painel diria que um alvo atacado nao foi.
    """
    log = FarmExclusionLog("1").begin()
    log.record("9", "recusado_pelo_jogo", "pacote grande")
    log.attacked("9", "pacote pequeno")
    assert log.entries["9"]["code"] == "atacado"


def test_codigo_desconhecido_e_aceito_e_contado():
    log = FarmExclusionLog("1").begin()
    log.record("9", "codigo_que_ninguem_declarou")
    assert log.summary["codigo_que_ninguem_declarou"] == 1
    # Sem metadado, degrada para tentativa -- a fase conservadora, que nao
    # participa do corte por teto.
    assert log.entries["9"]["phase"] == FASE_TENTATIVA


def test_entrada_carrega_observed_at():
    log = FarmExclusionLog("1").begin()
    log.record("9", "longe_demais")
    assert isinstance(log.entries["9"]["observed_at"], int)


def test_alvo_sem_id_ou_sem_codigo_e_ignorado():
    log = FarmExclusionLog("1").begin()
    log.record(None, "longe_demais")
    log.record("9", None)
    assert log.entries == {}


def test_flush_sem_village_id_nao_grava():
    assert FarmExclusionLog(None).begin().flush() is False


def test_flush_grava_snapshot_legivel():
    raiz = tempfile.mkdtemp()
    try:
        from core.filemanager import FileManager
        original = FileManager.get_root
        FileManager.get_root = staticmethod(lambda: raiz)
        try:
            log = FarmExclusionLog("77").begin()
            log.record("9", "longe_demais", "80.0 campos, raio 50")
            log.attacked("10", "pacote {'light': 15}")
            assert log.flush() is True
            caminho = os.path.join(raiz, "cache", "farm_exclusions", "77.json")
            with open(caminho, encoding="utf-8") as fh:
                dados = json.load(fh)
        finally:
            FileManager.get_root = original
    finally:
        shutil.rmtree(raiz, ignore_errors=True)

    assert dados["village_id"] == "77"
    assert dados["truncated"] is False
    assert dados["summary"] == {"longe_demais": 1, "atacado": 1}
    assert dados["targets"]["9"]["detail"] == "80.0 campos, raio 50"
    assert isinstance(dados["observed_at"], int)


# --------------------------------------------------------------------------
# _record_attack_failure -- a parte que nao pode inventar causa
# --------------------------------------------------------------------------

def test_recusa_do_jogo_guarda_o_texto_do_servidor():
    man = _man()
    man.last_attack_failure = "recusado_pelo_jogo"
    man.last_refusal = "Não existem unidades suficientes"
    man._record_attack_failure("9", "pacote X")
    entrada = man.exclusions.entries["9"]
    assert entrada["code"] == "recusado_pelo_jogo"
    assert "unidades suficientes" in entrada["detail"]


def test_timeout_nao_vira_recusa():
    """
    O caso que motiva o teste: `attack()` devolve False igual nos dois, e sem
    `last_attack_failure` o unico sinal seria `last_refusal` estar vazio --
    que tambem acontece numa recusa sem error_box legivel.
    """
    man = _man()
    man.last_attack_failure = "falha_de_rede"
    man._record_attack_failure("9", "pacote X")
    assert man.exclusions.entries["9"]["code"] == "falha_de_rede"


def test_alvo_sem_coordenada_tem_codigo_proprio():
    man = _man()
    man.last_attack_failure = "sem_coordenada"
    man._record_attack_failure("9", "pacote X")
    assert man.exclusions.entries["9"]["code"] == "sem_coordenada"


def test_falha_sem_codigo_degrada_dizendo_que_e_desconhecida():
    """
    Caminho novo que ninguem instrumentou. O registro nao pode afirmar recusa;
    tem que ser legivel como "nao sei".
    """
    man = _man()
    man.last_attack_failure = None
    man.last_refusal = None
    man._record_attack_failure("9", "pacote X")
    entrada = man.exclusions.entries["9"]
    assert entrada["code"] == "falha_de_rede"
    assert "desconhecido" in entrada["detail"]


# --------------------------------------------------------------------------
# _record_scout_attempt
# --------------------------------------------------------------------------

def test_explorador_que_saiu_e_explorador_que_nao_saiu_sao_codigos_diferentes():
    enviado = _man()
    enviado._record_scout_attempt("9", True, "alvo sem historico")
    assert enviado.exclusions.entries["9"]["code"] == "espiao_enviado"

    faltou = _man()
    faltou._record_scout_attempt("9", False, "alvo sem historico")
    entrada = faltou.exclusions.entries["9"]
    assert entrada["code"] == "sem_espiao"
    assert "5 espioes" in entrada["detail"]


# --------------------------------------------------------------------------
# run() -- os dois motivos que so existem no laco
# --------------------------------------------------------------------------

def _man_run(targets, max_farms, packs_por_alvo):
    man = AttackManager.__new__(AttackManager)
    man.village_id = "1"
    man.logger = _Silent()
    man.troopmanager = type("T", (), {"can_attack": True, "troops": {"axe": "10"}})()
    man.max_farms = max_farms
    man.targets = []
    man.hunter_service_callback = None
    man.exclusions = FarmExclusionLog(None).begin()
    man.get_targets = lambda: setattr(man, "targets", targets)
    man._ordered_templates = lambda vid: packs_por_alvo
    return man


def test_alvos_alem_do_teto_ganham_motivo():
    alvos = [[{"id": str(i)}, i, i] for i in range(5)]
    man = _man_run(alvos, max_farms=2, packs_por_alvo=[])
    man.run()
    assert man.exclusions.entries["2"]["code"] == "fora_do_teto"
    assert man.exclusions.summary["fora_do_teto"] == 3
    # Os dois primeiros foram avaliados: sem pacote, nao ha o que registrar,
    # mas tambem nao podem aparecer como cortados pelo teto.
    assert "0" not in man.exclusions.entries


def test_alvos_depois_do_break_nao_sao_confundidos_com_avaliados():
    alvos = [[{"id": str(i)}, i, i] for i in range(4)]
    man = _man_run(alvos, max_farms=4, packs_por_alvo=[{"light": 1}])
    # send_farm sempre devolve -1: nem o menor pacote cabe -> run() faz break
    # no primeiro alvo.
    man.send_farm = lambda target, template: -1
    man.run()
    assert man.exclusions.summary["ciclo_encerrado_sem_tropa"] == 3
    assert man.exclusions.entries["3"]["code"] == "ciclo_encerrado_sem_tropa"
    assert "0" not in man.exclusions.entries


# --------------------------------------------------------------------------
# FarmExclusionReader (webmanager) -- o lado que a pagina le
# --------------------------------------------------------------------------

def _ler(conteudo):
    """Roda o leitor contra um arquivo temporario, sem tocar em cache/."""
    from webmanager.utils import FarmExclusionReader

    pasta = tempfile.mkdtemp()
    try:
        caminho = os.path.join(pasta, "1.json")
        with open(caminho, "w", encoding="utf-8") as fh:
            fh.write(conteudo)
        original = FarmExclusionReader._path
        FarmExclusionReader._path = staticmethod(lambda vid: caminho)
        try:
            return FarmExclusionReader.load("1")
        finally:
            FarmExclusionReader._path = original
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


def test_arquivo_ausente_nao_e_nenhuma_exclusao():
    """
    A distincao que a pagina precisa fazer: "o bot avaliou e nao excluiu nada"
    contra "o bot nao rodou farm aqui". Sem `available`, as duas renderizariam
    a mesma lista vazia.
    """
    from webmanager.utils import FarmExclusionReader

    assert FarmExclusionReader.load("id_que_nao_existe_999999")["available"] is False
    assert FarmExclusionReader.load(None)["available"] is False


def test_json_parcial_e_tratado_como_ausente():
    """
    `FileManager.save_json_file` degrada para escrita in-place sob contencao,
    entao JSON truncado e possivel. Nao pode virar 500 nem lista vazia muda.
    """
    assert _ler('{"village_id": "1", "targ')["available"] is False


def test_separa_tentativa_de_selecao_e_poe_atacado_por_ultimo():
    dados = _ler(json.dumps({
        "village_id": "1", "observed_at": 1700000000, "truncated": False,
        "summary": {"longe_demais": 2, "atacado": 1, "recusado_pelo_jogo": 1},
        "targets": {
            "5": {"code": "longe_demais", "phase": "selecao",
                  "detail": "80.0 campos", "observed_at": 1700000000},
            "6": {"code": "atacado", "phase": "tentativa",
                  "detail": None, "observed_at": 1700000000},
            "7": {"code": "recusado_pelo_jogo", "phase": "tentativa",
                  "detail": "mensagem", "observed_at": 1700000000},
        },
    }))
    assert dados["available"] is True
    assert [r["target_id"] for r in dados["attempts"]] == ["7", "6"]
    assert [r["target_id"] for r in dados["selection_sample"]] == ["5"]
    assert dados["attacked_count"] == 1
    assert dados["total"] == 4
    assert dados["observed_at_fmt"] != "—"


def test_rotulo_vem_do_vocabulario_do_bot():
    dados = _ler(json.dumps({
        "village_id": "1", "summary": {"longe_demais": 1},
        "targets": {"5": {"code": "longe_demais", "phase": "selecao"}},
    }))
    assert dados["summary"][0]["label"] == REASONS["longe_demais"]["label"]
    assert dados["summary"][0]["knob"] == REASONS["longe_demais"]["knob"]


def test_codigo_desconhecido_aparece_cru_em_vez_de_sumir():
    """
    O painel pode ser mais velho que o bot. Engolir o codigo esconderia
    exatamente a exclusao nova que ninguem esta esperando.
    """
    dados = _ler(json.dumps({
        "village_id": "1", "summary": {"motivo_do_futuro": 1},
        "targets": {"5": {"code": "motivo_do_futuro", "phase": "tentativa"}},
    }))
    assert dados["summary"][0]["label"] == "motivo_do_futuro"
    assert dados["attempts"][0]["code"] == "motivo_do_futuro"


def test_truncado_viaja_ate_a_pagina():
    dados = _ler(json.dumps({
        "village_id": "1", "truncated": True, "max_selecao": 400,
        "summary": {"longe_demais": 900}, "targets": {},
    }))
    assert dados["truncated"] is True
    assert dados["max_selecao"] == 400
    # O resumo conta tudo mesmo com a lista cortada.
    assert dados["total"] == 900


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
