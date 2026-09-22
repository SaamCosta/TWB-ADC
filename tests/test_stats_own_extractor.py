"""
Extractor.stats_own_series -- a serie "Saqueado"/"Coletado" (e as demais de
gasto) que `screen=info_player&mode=stats_own` publica embutida no HTML.

Contexto: docs/backend.md 8.13 (P-STATS-JOGO) e game/player_stats.py
(Feature 37). Os dois blocos abaixo (SAQUEADO_BLOCK, COLETADO_BLOCK) sao
RECORTE VERBATIM de `cache/debug/stats_own.html`, capturado com o WebWrapper
do bot em 2026-09-21 (ver tests/smoke_capture_stats_own.py) -- fixture de
markup do jogo se copia do servidor, nao se inventa (CLAUDE.md). Preservados
byte a byte, inclusive as aspas escapadas (`\\"icon header wood\\"`) e a
indentacao irregular que o jogo gera entre `data.push({` e `label:`.

Rodar: python tests/test_stats_own_extractor.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from core.extractors import Extractor

checks = 0


def check(cond, msg):
    global checks
    checks += 1
    if not cond:
        raise AssertionError(msg)


# Recorte verbatim de cache/debug/stats_own.html (br143, 2026-09-21). Os "7
# dias" e os numeros sao os de uma conta real -- inclusive os tres dias com
# `total: 0` de Coletado, de ANTES de P-COL-01 ligar a coleta (docs/backend.md
# 8.13: a serie mostra 0 em 19/09 e "liga" em 20/09).
SAQUEADO_BLOCK = """data.push({

                            label: 'Saqueado',

                            data: [["1789959600000","147248"],["1789873200000","282771"],["1789786800000","306327"],["1789700400000","587332"],["1789614000000","336886"],["1789527600000","681142"],["1789441200000","679439"]],

                            details: [{"time":"1789959600000","wood":"55165","stone":"44169","iron":"47914","total":"147248","percent":26.24091357043442},{"time":"1789873200000","wood":"109841","stone":"65162","iron":"107768","total":"282771","percent":50.77316718438583},{"time":"1789786800000","wood":"114498","stone":"97877","iron":"93952","total":"306327","percent":100},{"time":"1789700400000","wood":"216198","stone":"174043","iron":"197091","total":"587332","percent":100},{"time":"1789614000000","wood":"129402","stone":"108075","iron":"99409","total":"336886","percent":100},{"time":"1789527600000","wood":"248947","stone":"217488","iron":"214707","total":"681142","percent":85.68998768384596},{"time":"1789441200000","wood":"239747","stone":"213960","iron":"225732","total":"679439","percent":83.53124865532736}],

                            color: 'cyan',

                            createTooltipContents: function(data_index) {

                                var date = new Date(parseInt(this.data[data_index][0]));

                                var details = this.details[data_index];



                                var tooltip_contents =

                                    '<div class="warstats_popup_date">' + date.toLocaleDateString() + '</div>' +

                                    '<div>' + this.label + ': ' + (Math.round(details.percent * 10) / 10) + '%</div>' +

                                    '<div>' +

                                    '<span class=\\"icon header wood\\" title=\\"Madeira\\"> </span>' + number_format(details.wood, '.') +

                                    '<br/> <span class=\\"icon header stone\\" title=\\"Argila\\"> </span>' + number_format(details.stone, '.') +

                                    '<br/> <span class=\\"icon header iron\\" title=\\"Ferro\\"> </span>' + number_format(details.iron, '.') +

                                    '</div>';



                                return tooltip_contents;

                            }

                        });"""

COLETADO_BLOCK = """data.push({

                            label: 'Coletado',

                            data: [["1789959600000","413891"],["1789873200000","274159"],["1789786800000","0"],["1789700400000","0"],["1789614000000","0"],["1789527600000","113749"],["1789441200000","133956"]],

                            details: [{"time":"1789959600000","wood":"137967","stone":"137967","iron":"137957","total":"413891","percent":73.75908642956558},{"time":"1789873200000","wood":"91388","stone":"91388","iron":"91383","total":"274159","percent":49.22683281561417},{"time":"1789786800000","wood":"0","stone":"0","iron":"0","total":"0","percent":0},{"time":"1789700400000","wood":"0","stone":"0","iron":"0","total":"0","percent":0},{"time":"1789614000000","wood":"0","stone":"0","iron":"0","total":"0","percent":0},{"time":"1789527600000","wood":"37914","stone":"37914","iron":"37921","total":"113749","percent":14.310012316154038},{"time":"1789441200000","wood":"44653","stone":"44653","iron":"44650","total":"133956","percent":16.468751344672636}],

                            color: 'green',

                            createTooltipContents: function(data_index) {

                                var date = new Date(parseInt(this.data[data_index][0]));

                                var details = this.details[data_index];



                                var tooltip_contents =

                                    '<div class="warstats_popup_date">' + date.toLocaleDateString() + '</div>' +

                                    '<div>' + this.label + ': ' + (Math.round(details.percent * 10) / 10) + '%</div>' +

                                    '<div>' +

                                    '<span class=\\"icon header wood\\" title=\\"Madeira\\"> </span>' + number_format(details.wood, '.') +

                                    '<br/> <span class=\\"icon header stone\\" title=\\"Argila\\"> </span>' + number_format(details.stone, '.') +

                                    '<br/> <span class=\\"icon header iron\\" title=\\"Ferro\\"> </span>' + number_format(details.iron, '.') +

                                    '</div>';



                                return tooltip_contents;

                            }

                        });"""

PAGE = (
    "<html><body><div>...</div>\n\n<script>\n\n"
    "$(document).ready(function() {\n\n    var data = [];\n\n\n\n"
    + SAQUEADO_BLOCK + "\n\n" + COLETADO_BLOCK
    + "\n\n});\n</script></body></html>"
)


class _FakeResponse:
    def __init__(self, text):
        self.text = text


def test_parses_both_series_from_the_real_page():
    out = Extractor.stats_own_series(PAGE)
    check(out is not None, "deveria achar as duas series")
    check(set(out) == {"Saqueado", "Coletado"}, "so as duas series do fixture: %s" % out)
    check(len(out["Saqueado"]) == 7, "7 dias de Saqueado, veio %d" % len(out["Saqueado"]))
    check(len(out["Coletado"]) == 7, "7 dias de Coletado, veio %d" % len(out["Coletado"]))


def test_ordem_e_a_do_jogo_mais_recente_primeiro():
    out = Extractor.stats_own_series(PAGE)
    stamps = [row["observed_at"] for row in out["Saqueado"]]
    check(stamps == sorted(stamps, reverse=True),
          "o jogo ja manda mais recente primeiro; nao reordenar por baixo")
    check(stamps[0] == 1789959600, "primeiro epoch (s, nao ms): %r" % stamps[0])


def test_valores_do_primeiro_dia_batem_com_o_fixture():
    out = Extractor.stats_own_series(PAGE)
    saq0 = out["Saqueado"][0]
    check(saq0 == {
        "observed_at": 1789959600, "wood": 55165, "stone": 44169,
        "iron": 47914, "total": 147248, "percent": 26.24091357043442,
    }, "Saqueado[0] divergiu do fixture: %r" % saq0)

    col0 = out["Coletado"][0]
    check(col0["total"] == 413891 and col0["wood"] == 137967,
          "Coletado[0] divergiu do fixture: %r" % col0)


def test_zero_e_distinto_de_ausente_coletado_ligou_no_dia_4():
    # Antes de P-COL-01 (docs/backend.md 8.13): tres dias seguidos com
    # Coletado == 0, nao ausentes -- a coleta estava desligada, nao
    # "sem leitura". Confirma que 0 sobrevive ao parse como inteiro, nao vira
    # None nem falsy-skip.
    out = Extractor.stats_own_series(PAGE)
    zerados = [row for row in out["Coletado"] if row["total"] == 0]
    check(len(zerados) == 3, "esperava 3 dias zerados, veio %d" % len(zerados))


def test_total_igual_a_soma_dos_tres_recursos_nas_duas_series():
    # Contrato (c) de frontend.md 6.1.2 item 6, medido em backend.md 8.13.
    # A participacao no dia (percent) nao da para validar so com estes dois
    # blocos -- ela soma com as series de GASTO que este fixture nao inclui
    # (ja medido contra a pagina inteira no smoke, docs/backend.md 8.13).
    out = Extractor.stats_own_series(PAGE)
    for label in ("Saqueado", "Coletado"):
        for row in out[label]:
            check(row["wood"] + row["stone"] + row["iron"] == row["total"],
                  "%s: %r nao fecha soma" % (label, row))


def test_aceita_response_com_atributo_text_e_string_crua():
    via_res = Extractor.stats_own_series(_FakeResponse(PAGE))
    via_str = Extractor.stats_own_series(PAGE)
    check(via_res == via_str, "res.text e string crua deveriam dar o mesmo resultado")


def test_none_quando_pagina_nao_tem_series_reconheciveis():
    # Resposta de login / bot-protection / markup que mudou: 200 sem o
    # padrao esperado. Precisa devolver None, nao {} nem levantar -- o
    # consumidor (game.PlayerStats) distingue "sem serie" de "erro de rede"
    # por isto.
    check(Extractor.stats_own_series("<html>login</html>") is None,
          "pagina sem series devia devolver None")
    check(Extractor.stats_own_series("") is None, "string vazia devia devolver None")


def test_bloco_com_json_quebrado_e_ignorado_sem_derrubar_os_outros():
    quebrado = SAQUEADO_BLOCK.replace('"total":"147248"', '"total":BROKEN')
    pagina = "<script>\n" + quebrado + "\n\n" + COLETADO_BLOCK + "\n</script>"
    out = Extractor.stats_own_series(pagina)
    check(out is not None, "Coletado sozinho ainda deveria parsear")
    check("Saqueado" not in out, "o bloco quebrado nao pode aparecer")
    check("Coletado" in out and len(out["Coletado"]) == 7,
          "o bloco bom nao pode ser afetado pelo quebrado")


# --------------------------------------------------------------------------
# O defeito de pareamento achado na revisao de 2026-09-22
# --------------------------------------------------------------------------

# Bloco com `label:` e SEM `details:` -- e o que o jogo gera para uma serie de
# LINHA (pontos, aldeias, classificacao). Hoje a pagina poe essas antes, via
# `InfoPlayer.Stats.createGraph(...)`, que nao usa `label:`; basta o jogo
# mudar de construcao para o caso abaixo virar a pagina real.
PAGINA_COM_BLOCO_SEM_DETAILS = (
    "data.push({label: 'Pontos'});"
    "data.push({label: 'Saqueado', details: ["
    '{"time":"1000","wood":"1","stone":"1","iron":"1","total":"3","percent":1.0}]});'
    "data.push({label: 'Coletado', details: ["
    '{"time":"1000","wood":"9","stone":"9","iron":"9","total":"27","percent":9.0}]});'
)


def test_bloco_sem_details_nao_rouba_os_numeros_do_bloco_seguinte():
    """
    O bug: um `label:` sem `details:` no proprio bloco fazia o `.*?` do regex
    antigo atravessar a fronteira e casar aquele label com os numeros do bloco
    SEGUINTE -- e o label legitimo desaparecia, porque o match ja o tinha
    consumido. Sem erro e sem log: o card de /empire mostraria coletado como
    se fosse saqueado, invertendo a unica pergunta que ele existe para
    responder.
    """
    out = Extractor.stats_own_series(PAGINA_COM_BLOCO_SEM_DETAILS)
    check(out.get("Saqueado", [{}])[0].get("wood") == 1,
          "Saqueado tem que ficar com os PROPRIOS numeros: %r" % out)
    check(out.get("Coletado", [{}])[0].get("wood") == 9,
          "Coletado tem que ficar com os proprios numeros: %r" % out)
    check("Pontos" not in out,
          "bloco sem details deveria ser pulado, nao herdar numeros alheios")


def test_o_regex_antigo_erra_este_caso_a_guarda_pode_falhar():
    """
    Roda a formulacao ANTIGA contra o mesmo markup e exige que ela erre.

    Sem isto, o teste acima passaria tambem com o parser quebrado no dia em
    que alguem "simplificasse" o recorte por bloco de volta para uma varredura
    do documento inteiro -- guarda que nao pode falhar e o vigesimo primeiro
    padrao do CLAUDE.md de cabeca para baixo. Mesma tecnica de
    tests/test_incoming_commands.py.
    """
    import re
    antigo = re.compile(r"label:\s*'([^']+)'.*?details:\s*(\[\{.*?\}\])", re.S)
    pares = dict(antigo.findall(PAGINA_COM_BLOCO_SEM_DETAILS))
    check("Pontos" in pares,
          "o regex antigo DEVERIA casar 'Pontos' com details alheio -- se nao "
          "casa mais, este teste perdeu o sentido e precisa ser reescrito")
    check("Saqueado" not in pares,
          "o regex antigo DEVERIA perder 'Saqueado' -- idem")


def test_details_com_objeto_aninhado_nao_e_truncado():
    """
    `\\[\\{.*?\\}\\]` para no primeiro `}]`. Com um objeto aninhado dentro de
    cada ponto, isso truncaria a lista (ou invalidaria o JSON) e a serie
    perderia dias em silencio. `balanced_slice` -- que existe neste mesmo
    arquivo justamente por causa dessa armadilha -- atravessa o aninhamento.
    """
    pagina = (
        "data.push({label: 'Saqueado', details: ["
        '{"time":"1000","wood":"1","stone":"1","iron":"1","total":"3",'
        '"percent":1.0,"meta":{"a":{"b":1}}},'
        '{"time":"2000","wood":"5","stone":"5","iron":"5","total":"15",'
        '"percent":2.0}]});'
    )
    out = Extractor.stats_own_series(pagina)
    check(out is not None and len(out["Saqueado"]) == 2,
          "os dois dias deveriam sobreviver ao aninhamento: %r" % out)


def test_linha_com_campo_ausente_e_pulada_sem_derrubar_a_serie():
    minimo = (
        "data.push({label: 'Teste', "
        'details: [{"time":"1000","wood":"1","stone":"1","iron":"1",'
        '"total":"3","percent":1.0},'
        '{"time":"2000","wood":"1","stone":"1","total":"2","percent":1.0}]'
        "});"
    )
    out = Extractor.stats_own_series(minimo)
    check(out is not None and "Teste" in out, "serie deveria aparecer")
    check(len(out["Teste"]) == 1,
          "a linha sem 'iron' deveria ser pulada, sobrando 1 de 2: %r" % out["Teste"])


for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
    fn()

print("OK: %d checagens em %s" % (checks, os.path.basename(__file__)))
