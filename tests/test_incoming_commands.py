"""
Testes de Extractor.incoming_commands -- as linhas de comando recebido na
visao geral de uma aldeia, que alimentam a priorizacao por urgencia da
Feature 16 (DefenceManager._is_urgent).

Por que este teste existe: o regex original procurava `data-command-id` no
proprio `<tr>`. Nao casava nada. O atributo mora em spans aninhados seis
niveis abaixo, e o `<tr>` se identifica pela CLASSE `no_ignored_command`. O
padrao antigo tinha sido inferido de outras telas e nunca conferido contra um
ataque real -- docs/backlog.md registrava isso como limitacao conhecida, e em
2026-08-22 a limitacao se confirmou em campo com quatro nobres a caminho da
BBM 008.

O custo da falha era invisivel e invertia a feature: lista vazia faz
_is_urgent() devolver True ("assume urgente"), entao o bot evacuava em TODO
ataque, inclusive num fake com 100h de viagem. A Feature 16 existia
exatamente para nao fazer isso. Vale a nota do sexto padrao do CLAUDE.md: um
parser que devolve lista vazia falha em silencio, e ninguem percebe por meses.

O fixture REAL e VERBATIM do br143, capturado em 2026-08-22 as 07:34 (hora do
servidor) da resposta crua de `game.php?village=41114&screen=overview`, com
quatro ataques chegando as 13:13:09. Apenas os valores de `href`/`src` foram
substituidos por URL_REMOVIDA (continham o token de sessao); todo o resto,
incluindo espacos em branco, o `<td >` com espaco sobrando e o acento de
"barbaros", esta como o servidor mandou.

Rodar: python tests/test_incoming_commands.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.extractors import Extractor

# --- verbatim: br143, village=41114&screen=overview, 2026-08-22 ------------
REAL_ROW = (
    '<tr class="command-row no_ignored_command">\n'
    '                    <td>\n'
    '                                                <span class="quickedit" data-id="421560489">\n'
    '                            <span class="quickedit-content">\n'
    '                                <a href="URL_REMOVIDA">\n'
    '                                    <span class="icon-container">\n'
    '                                        <span class=" tooltip" data-command-id="421560489" title="Ataque">\n'
    '\t<img  src="URL_REMOVIDA" alt="" />\n'
    '</span><span class=" tooltip" data-command-id="421560489" title="">\n'
    '\t<img  src="URL_REMOVIDA" alt="" />\n'
    '</span>\n'
    '                                    </span>\n'
    '\n'
    '                                    <span class="quickedit-label">\n'
    '                                         0014 | Aldeia de bárbaros\n'
    '                                    </span>\n'
    '                                                                    </a>\n'
    '                                                                <a class="rename-icon" href="URL_REMOVIDA" title="Renomear"></a>\n'
    '                                                            </span>\n'
    '                        </span>\n'
    '                    </td>\n'
    '                                                                                                    <td>hoje às 13:13:09:<span class="grey small">598</span></td>\n'
    '                                                                <td >\n'
    '                        <span class="widget-command-timer" data-endtime="1787415189">5:27:17</span>\n'
    '                                            </td>\n'
    '                                            <td>\n'
    '                                                            <a class="small" href="URL_REMOVIDA"><img src="URL_REMOVIDA" alt="Peça apoio contra esse ataque" title="Peça apoio contra esse ataque" class="" /></a>\n'
    '                                                    </td>\n'
    '                                    </tr>'
)

# Chegada real do fixture: 1787415189 == 2026-08-22 13:13:09.
ENDTIME = 1787415189


class _FrozenTime:
    """Congela time.time() para o ETA do fixture ser deterministico."""

    def __init__(self, now):
        self.now = now

    def __enter__(self):
        self._real = time.time
        time.time = lambda: self.now

    def __exit__(self, *exc):
        time.time = self._real


def _check(label, got, expected):
    assert got == expected, f"{label}: esperado {expected!r}, veio {got!r}"
    print(f"  ok  {label}: {got!r}")


def test_real_markup_parses():
    """O caso que o regex antigo perdia: uma linha real do servidor."""
    print("test_real_markup_parses")
    with _FrozenTime(ENDTIME - 20343):  # 07:34:06, o momento da captura
        got = Extractor.incoming_commands(REAL_ROW)
    _check("linhas encontradas", len(got), 1)
    _check("command_id", got[0]["command_id"], "421560489")
    _check("eta_seconds", got[0]["eta_seconds"], 20343)
    _check("origin", got[0]["origin"], "0014 | Aldeia de bárbaros")
    # A linha nao traz o dono da aldeia, so o nome dela. Se algum dia trouxer,
    # este assert quebra e a mudanca fica visivel em vez de passar batida.
    _check("attacker (ausente nesta tela)", got[0]["attacker"], None)


def test_old_regex_would_have_missed_it():
    """
    Prova que o bug era real, e nao uma reescrita gratuita: o padrao antigo
    exigia data-command-id dentro do proprio <tr>.
    """
    print("test_old_regex_would_have_missed_it")
    import re

    old = re.findall(r'<tr[^>]*data-command-id="(\d+)"[^>]*>(.*?)</tr>', REAL_ROW, re.S)
    _check("linhas que o regex antigo achava", len(old), 0)


def test_urgency_gate_uses_real_eta():
    """
    O ponto da feature: 5h39 de ETA nao pode ser tratado como urgente com o
    limiar padrao de 30 min. Antes da correcao a lista vinha vazia e o
    DefenceManager assumia urgente -- evacuando por um ataque distante.
    """
    print("test_urgency_gate_uses_real_eta")
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from game.defence_manager import DefenceManager

    dm = DefenceManager(village_id="41114", wrapper=None)
    with _FrozenTime(ENDTIME - 20343):
        dm._parse_incoming_urgency(REAL_ROW)
    _check("incoming_eta", dm.incoming_eta, 20343)
    _check("incoming_origin", dm.incoming_origin, "0014 | Aldeia de bárbaros")
    _check("urgente com limiar 1800s", dm._is_urgent(dm.incoming_eta), False)
    _check("urgente a 10 min do impacto", dm._is_urgent(600), True)
    # Sem parsing, o fallback seguro continua valendo (evacua).
    _check("urgente quando ETA desconhecido", dm._is_urgent(None), True)


def test_eta_fallbacks():
    """
    data-duration e o texto renderizado do contador. O texto so serve porque
    o servidor manda ele preenchido no HTML cru -- conferido na captura de
    2026-08-22. Nao repetir aqui o erro do StatuePage, que regexava texto que
    so existia depois do JS rodar.
    """
    print("test_eta_fallbacks")
    duration_row = (
        '<tr class="command-row no_ignored_command">'
        '<span class="quickedit" data-id="777"></span>'
        '<span class="widget-command-timer" data-duration="900">0:15:00</span>'
        '</tr>'
    )
    got = Extractor.incoming_commands(duration_row)
    _check("eta via data-duration", got[0]["eta_seconds"], 900)

    text_only_row = (
        '<tr class="command-row no_ignored_command">'
        '<span class="quickedit" data-id="888"></span>'
        '<span class="widget-command-timer">5:27:17</span>'
        '</tr>'
    )
    got = Extractor.incoming_commands(text_only_row)
    _check("eta via texto do contador", got[0]["eta_seconds"], 5 * 3600 + 27 * 60 + 17)


def test_soonest_wins_with_four_commands():
    """
    O trem de nobres real tinha quatro linhas. O DefenceManager decide pelo
    mais proximo, entao a ordem nao pode importar.
    """
    print("test_soonest_wins_with_four_commands")
    rows = "".join(
        '<tr class="command-row no_ignored_command">'
        f'<span class="quickedit" data-id="{i}"></span>'
        f'<span class="widget-command-timer" data-duration="{d}"></span>'
        '</tr>'
        for i, d in [(1, 20343), (2, 900), (3, 7200), (4, 60)]
    )
    got = Extractor.incoming_commands(rows)
    _check("quatro linhas", len(got), 4)
    soonest = min(got, key=lambda c: c["eta_seconds"])
    _check("mais proximo", soonest["eta_seconds"], 60)
    _check("id do mais proximo", soonest["command_id"], "4")


def test_no_commands_and_garbage():
    """Ausencia de comando e lista vazia -- e nao excecao."""
    print("test_no_commands_and_garbage")
    _check("pagina sem comandos", Extractor.incoming_commands("<html></html>"), [])
    _check("string vazia", Extractor.incoming_commands(""), [])
    # Uma classe parecida nao pode casar: `\b` nao cria fronteira entre
    # underscore e letra, entao "algo_no_ignored_command" fica de fora.
    _check(
        "classe parecida nao casa",
        Extractor.incoming_commands(
            '<tr class="algo_no_ignored_command">'
            '<span class="widget-command-timer" data-duration="10"></span></tr>'
        ),
        [],
    )
    # Linha marcada mas sem nenhuma fonte de ETA: nao inventa numero, some da
    # lista, e o chamador cai no fallback "urgente".
    _check(
        "linha sem ETA e descartada",
        Extractor.incoming_commands(
            '<tr class="command-row no_ignored_command">'
            '<span class="quickedit" data-id="5"></span></tr>'
        ),
        [],
    )


def test_js_comment_alone_is_not_a_row():
    """
    Achado do smoke contra o servidor em 2026-08-22, depois de os testes ja
    passarem: a string `no_ignored_command` aparece 5 vezes na pagina com 4
    ataques. A quinta e um comentario de JS do proprio jogo --

        //hide bar if all attacks are ignored
        if ($('.no_ignored_command').length == ...

    -- que o jogo serve sempre que o widget renderiza, inclusive quando o
    jogador ignorou todos os comandos e nao existe <tr> nenhum. Sem esta
    distincao, esse caso normal seria logado como "markup mudou", e o alerta
    viraria ruido (decimo quinto padrao do CLAUDE.md).

    Nas outras 8 aldeias, sem ataque, a string aparece 0 vezes -- ou seja, o
    marcador de "sob ataque" do DefenceManager nao dispara sozinho.
    """
    print("test_js_comment_alone_is_not_a_row")
    from core.extractors import INCOMING_ROW_RE
    from game.defence_manager import DefenceManager

    js_only = (
        "<script>\n//hide bar if all attacks are ignored\n"
        "if ($('.no_ignored_command').length == 0) { $('#bar').hide(); }\n</script>"
    )
    _check("marcador solto presente", "no_ignored_command" in js_only, True)
    _check("linhas casadas", len(INCOMING_ROW_RE.findall(js_only)), 0)
    _check("comandos", Extractor.incoming_commands(js_only), [])

    dm = DefenceManager(village_id="41114")
    dm._parse_incoming_urgency(js_only)
    _check("rows_seen (JS puro)", dm.incoming_rows_seen, 0)
    # E o contraste: linha de verdade sem ETA legivel -> rows_seen > 0, que e
    # o que faz o log virar WARNING de markup quebrado.
    dm._parse_incoming_urgency(
        '<tr class="command-row no_ignored_command">'
        '<span class="quickedit" data-id="9"></span></tr>'
    )
    _check("rows_seen (linha sem ETA)", dm.incoming_rows_seen, 1)
    _check("eta continua desconhecido", dm.incoming_eta, None)


def test_endtime_in_the_past_is_clamped():
    """Comando que ja pousou nao pode virar ETA negativo."""
    print("test_endtime_in_the_past_is_clamped")
    with _FrozenTime(ENDTIME + 5000):
        got = Extractor.incoming_commands(REAL_ROW)
    _check("eta nunca negativo", got[0]["eta_seconds"], 0)
    # E zero e urgente, que e a leitura certa para algo que ja chegou.
    from game.defence_manager import DefenceManager

    _check("zero e urgente", DefenceManager(village_id="x")._is_urgent(0), True)


if __name__ == "__main__":
    test_real_markup_parses()
    test_old_regex_would_have_missed_it()
    test_urgency_gate_uses_real_eta()
    test_eta_fallbacks()
    test_soonest_wins_with_four_commands()
    test_no_commands_and_garbage()
    test_js_comment_alone_is_not_a_row()
    test_endtime_in_the_past_is_clamped()
    print("\nOK - todos os testes de incoming_commands passaram")
