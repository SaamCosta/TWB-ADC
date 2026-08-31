"""
Feature 21 -- ReportReader do webmanager.

Cobre o que o polimento de 2026-08-31 acrescentou: veredito agregado por
aldeia-alvo (a logica que o AttackManager de fato usa), resolucao de nome de
aldeia, filtro de tipo dinamico e paginacao.

Sem rede e sem estado de jogo: os dois unicos pontos que tocam disco
(`_all_reports` e `_village_labels`) sao substituidos por fixtures. Roda
sozinho, sem pytest:  python tests/test_report_reader.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from webmanager.utils import ReportReader

checks = 0


def check(cond, msg):
    global checks
    checks += 1
    if not cond:
        raise AssertionError(msg)


def _attack(dest, losses=None, sent=None, when=0, origin="41123"):
    return {
        "type": "attack", "origin": origin, "dest": dest,
        "losses": losses or {},
        "extra": {"when": when, "units_sent": sent or {"light": 15},
                  "loot": {"wood": 100, "stone": 100, "iron": 100}},
    }


def _scout(dest, def_units=None, def_losses=None, when=0):
    return {
        "type": "scout", "origin": "41123", "dest": dest, "losses": {},
        "extra": {"when": when, "defence_units": def_units or {},
                  "defence_losses": def_losses or {}},
    }


class _Patch:
    """Troca as duas funcoes de disco por fixtures, e restaura no fim."""

    def __init__(self, reports, labels=None):
        self.reports, self.labels = reports, labels or {}

    def __enter__(self):
        self._old_r = ReportReader._all_reports
        self._old_l = ReportReader._village_labels
        ReportReader._all_reports = staticmethod(lambda: self.reports)
        ReportReader._village_labels = staticmethod(lambda: self.labels)
        return self

    def __exit__(self, *a):
        ReportReader._all_reports = self._old_r
        ReportReader._village_labels = self._old_l


# --- veredito agregado (espelha ReportManager.safe_to_engage) ---------------

def test_safe_to_engage_espelha_o_bot():
    # ataque sem perdas -> seguro
    check(ReportReader._safe_to_engage([_attack("900")]) == 1, "sem perdas deveria ser 1")
    # ataque com perda total da unidade enviada -> inseguro
    check(
        ReportReader._safe_to_engage([_attack("900", losses={"light": 15})]) == 0,
        "perda total deveria ser 0",
    )
    # perda de 1 unidade -> o bot considera seguro (ramo losses[t] <= 1)
    check(
        ReportReader._safe_to_engage([_attack("900", losses={"light": 1})]) == 1,
        "perda de 1 deveria ser 1, como no bot",
    )
    # scout sem defesa -> seguro
    check(ReportReader._safe_to_engage([_scout("900")]) == 1, "scout limpo deveria ser 1")
    # scout com defesa viva -> nao dispara nenhum return e cai para -1
    check(
        ReportReader._safe_to_engage([_scout("900", def_units={"spear": 50})]) == -1,
        "scout com defesa nao decide, deveria cair para -1",
    )
    # nenhum relatorio -> desconhecido
    check(ReportReader._safe_to_engage([]) == -1, "vazio deveria ser -1")


def test_primeiro_relatorio_decide_nao_o_mais_recente():
    """
    Guarda da nota de ordenacao: o bot itera na ordem de os.listdir e retorna
    no PRIMEIRO relatorio que decide -- nao no mais recente. Este teste fixa
    esse comportamento (real, medido) para que uma futura "correcao" para
    ordem cronologica seja uma decisao consciente e nao um acidente.
    """
    antigo_seguro = _attack("900", when=1000)
    novo_perigoso = _attack("900", losses={"light": 15}, when=9000)
    check(
        ReportReader._safe_to_engage([antigo_seguro, novo_perigoso]) == 1,
        "primeiro da lista deveria decidir (1), mesmo sendo o mais antigo",
    )
    check(
        ReportReader._safe_to_engage([novo_perigoso, antigo_seguro]) == 0,
        "invertendo a ordem o veredito muda -- e o que torna a ordem relevante",
    )


def test_aggregate_marca_divergencia():
    reports = {
        "100": _attack("900", when=1000),                        # antigo, seguro
        "200": _attack("900", losses={"light": 15}, when=9000),   # recente, perigoso
    }
    with _Patch(reports, {"900": {"name": "Bárbara", "coords": "512|487",
                                  "own": False, "label": "Bárbara (512|487)"}}):
        rows = ReportReader.aggregate_by_target()
    check(len(rows) == 1, "deveria agregar num alvo so")
    row = rows[0]
    check(row["verdict"] == 1, "ordem do bot (alfabetica: 100 antes de 200) da seguro")
    check(row["verdict_newest"] == 0, "pelo mais recente daria inseguro")
    check(row["disagrees"] is True, "a divergencia precisa ficar visivel")
    check(row["report_count"] == 2, "contagem de relatorios errada")
    check(row["target_label"] == "Bárbara (512|487)", "nome do alvo nao resolvido")


def test_aggregate_sem_divergencia_nao_alarma():
    reports = {"100": _attack("900", when=1000), "200": _attack("900", when=9000)}
    with _Patch(reports):
        rows = ReportReader.aggregate_by_target()
    check(rows[0]["disagrees"] is False, "sem divergencia nao deveria alarmar")
    check(rows[0]["target_label"] == "#900", "sem cache de aldeia deveria cair no id cru")


def test_relatorio_sem_dest_e_ignorado():
    reports = {"100": _attack(None), "200": _attack("900")}
    with _Patch(reports):
        rows = ReportReader.aggregate_by_target()
    check(len(rows) == 1, "relatorio sem dest nao pode virar linha de alvo")


# --- filtro de tipo dinamico ------------------------------------------------

def test_types_present_inclui_tipo_fora_da_lista_fixa():
    reports = {
        "1": _attack("900"), "2": _attack("901"), "3": _scout("900"),
        "4": {"type": "ReportFoundCrew", "dest": "902", "losses": {}, "extra": {}},
    }
    with _Patch(reports):
        types = ReportReader.types_present()
    values = [t["value"] for t in types]
    check("ReportFoundCrew" in values, "tipo real fora da lista fixa ficou de fora")
    check(values[0] == "attack", "deveria ordenar por frequencia desc (attack=2)")
    by_value = {t["value"]: t for t in types}
    check(by_value["attack"]["count"] == 2, "contagem de attack errada")
    check(by_value["attack"]["label"] == "Ataque", "rotulo conhecido deveria ser traduzido")
    check(by_value["ReportFoundCrew"]["label"] == "ReportFoundCrew",
          "tipo desconhecido deveria cair no proprio valor")


# --- paginacao e stats ------------------------------------------------------

def test_paginacao_fatia_sem_perder_stats():
    reports = {str(i): _attack("900", when=i) for i in range(1, 251)}
    with _Patch(reports):
        page0, stats, pag = ReportReader.load(page=0, per_page=100)
        page2, _, pag2 = ReportReader.load(page=2, per_page=100)
    check(len(page0) == 100, "primeira pagina deveria ter 100")
    check(len(page2) == 50, "ultima pagina deveria ter o resto (50)")
    check(pag["pages"] == 3 and pag["total"] == 250, "contagem de paginas errada")
    check(stats["total"] == 250, "stats devem cobrir o conjunto filtrado inteiro, nao a pagina")
    check(pag["has_next"] is True and pag["has_prev"] is False, "flags da primeira pagina")
    check(pag2["has_next"] is False and pag2["has_prev"] is True, "flags da ultima pagina")
    # ordenacao: mais recente primeiro
    check(page0[0]["when"] == 250, "deveria ordenar por 'when' desc")


def test_pagina_fora_do_intervalo_e_presa_no_limite():
    reports = {str(i): _attack("900", when=i) for i in range(1, 11)}
    with _Patch(reports):
        entries, _, pag = ReportReader.load(page=99, per_page=100)
    check(pag["page"] == 0, "pagina alem do fim deveria ser presa na ultima valida")
    check(len(entries) == 10, "e ainda devolver os registros")


def test_filtro_de_dest_restringe_stats():
    reports = {"1": _attack("900"), "2": _attack("901"), "3": _attack("901")}
    with _Patch(reports):
        entries, stats, _ = ReportReader.load(dest_filter="901")
    check(len(entries) == 2, "filtro de dest nao aplicou")
    check(stats["total"] == 2, "stats devem respeitar o filtro (o comentario antigo dizia o contrario)")


# --- rotulo de aldeia -------------------------------------------------------

def test_entry_label_barbara_vem_com_name_zero():
    """
    O jogo manda `name` = 0 (int) para aldeia sem nome proprio e o Map guarda
    verbatim. Medido no cache real: 184/734 aldeias, todas com owner "0".
    Sem esta regra, 99 de 100 linhas da tabela mostravam apenas "#id".
    """
    barb = {"id": "26401", "name": 0, "location": [572, 338], "owner": "0"}
    out = ReportReader._entry_label("26401", barb, False)
    check(out["label"] == "Bárbara (572|338)", "barbara deveria virar rotulo legivel, veio %r" % out["label"])
    check(out["own"] is False, "barbara nao e aldeia propria")

    # name 0 mas dono real: nao inventar "Bárbara"
    orfa = {"id": "999", "name": 0, "location": [1, 2], "owner": "920023448"}
    check(ReportReader._entry_label("999", orfa, False)["label"] == "#999 (1|2)",
          "aldeia de jogador sem nome nao pode virar Bárbara")

    # aldeia de jogador com nome
    jog = {"id": "102550", "name": "zOno", "location": [556, 307], "owner": "920023448"}
    check(ReportReader._entry_label("102550", jog, False)["label"] == "zOno (556|307)",
          "nome de jogador deveria passar direto")


def test_entry_label_le_o_formato_de_managed():
    """cache/managed guarda name/x/y no topo e repete o mapa em `public`."""
    managed = {"name": "BBM 016", "x": 576, "y": 316,
               "public": {"id": "34597", "name": "BBM 016", "location": [576, 316]}}
    out = ReportReader._entry_label("34597", managed, True)
    check(out["label"] == "BBM 016 (576|316)", "managed nao resolveu, veio %r" % out["label"])
    check(out["own"] is True, "aldeia gerenciada deveria vir marcada como propria")

    # so o bloco public preenchido (cache gravado por versao antiga)
    so_public = {"public": {"name": "BBM 001", "location": [512, 487]}}
    check(ReportReader._entry_label("41123", so_public, True)["label"] == "BBM 001 (512|487)",
          "deveria cair para o bloco public")


def test_label_for():
    labels = {"900": {"name": "BBM 001", "coords": "512|487", "own": True,
                      "label": "BBM 001 (512|487)"}}
    check(ReportReader._label_for("900", labels) == ("BBM 001 (512|487)", True),
          "aldeia propria deveria resolver com flag own")
    check(ReportReader._label_for("999", labels) == ("#999", False),
          "aldeia desconhecida deveria virar #id")
    check(ReportReader._label_for(None, labels) == ("—", False),
          "dest ausente deveria virar travessao")


TESTS = [
    test_safe_to_engage_espelha_o_bot,
    test_primeiro_relatorio_decide_nao_o_mais_recente,
    test_aggregate_marca_divergencia,
    test_aggregate_sem_divergencia_nao_alarma,
    test_relatorio_sem_dest_e_ignorado,
    test_types_present_inclui_tipo_fora_da_lista_fixa,
    test_paginacao_fatia_sem_perder_stats,
    test_pagina_fora_do_intervalo_e_presa_no_limite,
    test_filtro_de_dest_restringe_stats,
    test_entry_label_barbara_vem_com_name_zero,
    test_entry_label_le_o_formato_de_managed,
    test_label_for,
]

if __name__ == "__main__":
    for t in TESTS:
        t()
        print("ok  %s" % t.__name__)
    print("\n%d checks em %d testes" % (checks, len(TESTS)))
