"""
Testes de Extractor.own_commands / server_clock -- a tela de comandos do jogo,
que e a fonte do painel "Em voo" (Feature 38, docs/frontend.md 6.1.2 item 1).

FIXTURE VERBATIM: os blocos abaixo sao recorte LITERAL de
`screen=overview_villages&mode=commands&page=-1` do br143, capturado em
2026-09-22 com 65 comandos no ar (cache/debug/commands_page_all.html). Markup
de jogo se copia do servidor, nao se inventa -- e a versao anterior de
loyalty_from_report() falhou exatamente por ter sido escrita contra markup
suposto (CLAUDE.md).

O que os casos adversariais cobrem, e por que cada um existe:

  1. PAGINACAO / CONTADOR MENTIROSO. Medido: sem `page=-1` vieram 25 linhas de
     65, e o `<th>` dizia "Comando (25)". Um parser que lesse o contador como
     total concluiria que tinha tudo. O teste fixa que `declared` e o numero
     do cabecalho e que ele CONFERE com as linhas lidas -- divergencia vira
     warning, que e o unico jeito de a perda aparecer.
  2. ORDEM DE COLUNA DE UNIDADE POR MUNDO. br143 nao tem arqueiro (10
     colunas). O teste roda um cabecalho COM arqueiro (12 colunas) e exige que
     as tropas saiam rotuladas certo -- uma ordem chumbada leria catapulta
     como nobre e o painel anunciaria trem de conquista inexistente.
  3. HORA DE FALHA DISTINGUIVEL. `attack_duration()` devolve 0 quando falha, e
     somar 0 faz o nobre nascer pousado (sexto padrao). Aqui a falha tem de
     ser None, e o teste exige isso explicitamente -- incluindo quando nao ha
     relogio do servidor na pagina.

Rodar: python tests/test_own_commands_extractor.py
"""
import os
import sys
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.extractors import Extractor

_checks = 0
_failures = []


def _check(label, got, want):
    global _checks
    _checks += 1
    if got != want:
        _failures.append("%s: esperado %r, veio %r" % (label, want, got))
        print("  FALHOU %s: esperado %r, veio %r" % (label, want, got))
    else:
        print("  ok %s" % label)


def _check_true(label, got):
    _check(label, bool(got), True)


# --------------------------------------------------------------------------
# Recortes verbatim do br143 (2026-09-22).
# --------------------------------------------------------------------------

# Relogio do servidor, do topo de qualquer tela.
SERVER_CLOCK = (
    '<span id="serverTime">16:14:06</span> '
    '<span id="serverDate">22/09/2026</span>'
)

# Linha simples: ataque de farm, 8 cavalarias leves, chegando hoje.
ROW_FARM = """<tr class="nowrap  row_ax">
	<td>
		<input type="checkbox" name="cancel[]" value="6869354" disabled />        			<span class="own_command" data-icon-hint="Ataque pequeno (1-1000 tropas) " data-command-type="attack" data-command-id="6869354">
            <img  src="https://dsbr.innogamescdn.com/asset/e94cf8a0/graphic/command/attack_small.webp" alt="" />			</span>

        <span class="quickedit" data-id="6869354">
            <span class="quickedit-content">
                <a href="/game.php?village=32056&amp;screen=info_command&amp;id=6869354&amp;type=own">
                    <span class="quickedit-label">
                         Ataque a Aldeia de bárbaros (598|315) K35                    </span>
                </a>
                <a class="rename-icon" href="#" title="Renomear"></a>
            </span>
        </span>

	</td>
	<td>
		<a href="/game.php?village=32056&amp;screen=info_village&amp;id=40374">BBM 024 (588|314) K35</a>
	</td>
	<td>
			hoje às 16:24:23:<span class="grey small">812</span>		</td>
	<td class='unit-item hidden'>0</td><td class='unit-item hidden'>0</td><td class='unit-item hidden'>0</td><td class='unit-item hidden'>0</td><td class='unit-item'>8</td><td class='unit-item hidden'>0</td><td class='unit-item hidden'>0</td><td class='unit-item hidden'>0</td><td class='unit-item hidden'>0</td><td class='unit-item hidden'>0</td></tr>"""

# ⚠️ Linha de NOBRE. Repare no SEGUNDO <span class="own_command">, com
# data-icon-hint="Com nobre" e icone snob.webp, repetindo data-command-type e
# data-command-id. Foi essa duplicacao que fez a contagem crua dar 69
# atributos para 65 linhas; como os dois valores sao IDENTICOS, o .search()
# por linha pega o certo -- e o icone vira a segunda leitura de "tem nobre".
ROW_NOBLE = """<tr class="nowrap  row_ax">
	<td>
		<input type="checkbox" name="cancel[]" value="1526336960" disabled />        			<span class="own_command" data-icon-hint="Ataque pequeno (1-1000 tropas) " data-command-type="attack" data-command-id="1526336960">
            <img  src="https://dsbr.innogamescdn.com/asset/e94cf8a0/graphic/command/attack_small.webp" alt="" />			</span>
        			<span class="own_command" data-icon-hint="Com nobre " data-command-type="attack" data-command-id="1526336960">
            <img  src="https://dsbr.innogamescdn.com/asset/e94cf8a0/graphic/command/snob.webp" alt="" />			</span>

        <span class="quickedit" data-id="1526336960">
            <span class="quickedit-content">
                <a href="/game.php?village=32056&amp;screen=info_command&amp;id=1526336960&amp;type=own">
                    <span class="quickedit-label">
                         Ataque a Aldeia-bonus (582|289) K25                    </span>
                </a>
                <a class="rename-icon" href="#" title="Renomear"></a>
            </span>
        </span>

	</td>
	<td>
		<a href="/game.php?village=32056&amp;screen=info_village&amp;id=74690">BBM 011 (582|304) K35</a>
	</td>
	<td>
			hoje às 21:23:50:<span class="grey small">177</span>		</td>
	<td class='unit-item'>428</td><td class='unit-item'>416</td><td class='unit-item hidden'>0</td><td class='unit-item hidden'>0</td><td class='unit-item'>48</td><td class='unit-item'>36</td><td class='unit-item hidden'>0</td><td class='unit-item hidden'>0</td><td class='unit-item hidden'>0</td><td class='unit-item'>1</td></tr>"""

# Retirada de apoio, chegando em OUTRO DIA ("em 25.09."). E a unica linha da
# captura que nao usa "hoje" -- e por isso a unica prova de que o caminho de
# data explicita funciona.
ROW_WITHDRAW = """<tr class="nowrap  row_ax">
	<td>
		<input type="checkbox" name="cancel[]" value="1730531308" disabled />        			<span class="own_command" data-icon-hint="Apoio retirado " data-command-type="back" data-command-id="1730531308">
            <img  src="https://dsbr.innogamescdn.com/asset/e94cf8a0/graphic/command/back.webp" alt="" />			</span>

        <span class="quickedit" data-id="1730531308">
            <span class="quickedit-content">
                <a href="/game.php?village=32056&amp;screen=info_command&amp;id=1730531308&amp;type=own">
                    <span class="quickedit-label">
                         Retirada de Mad Max 14.21 Pavuna II (742|561) K57                    </span>
                </a>
                <a class="rename-icon" href="#" title="Renomear"></a>
            </span>
        </span>

	</td>
	<td>
		<a href="/game.php?village=32056&amp;screen=info_village&amp;id=39292">BBM 004 (579|308) K35</a>
	</td>
	<td>
			em 25.09. às 00:26:36:<span class="grey small">000</span>		</td>
	<td class='unit-item hidden'>0</td><td class='unit-item'>1000</td><td class='unit-item hidden'>0</td><td class='unit-item hidden'>0</td><td class='unit-item hidden'>0</td><td class='unit-item hidden'>0</td><td class='unit-item hidden'>0</td><td class='unit-item hidden'>0</td><td class='unit-item hidden'>0</td><td class='unit-item hidden'>0</td></tr>"""

# Cabecalho verbatim do br143 -- MUNDO SEM ARQUEIRO, 10 colunas de unidade.
HEADER_NO_ARCHER = """<table id="commands_table" class="vis overview_table" width="100%">
<tr>
	<th>Comando (@COUNT@)</th>
	<th><a href="/game.php?order=start_name">Aldeia de origem</a></th>
	<th><a href="/game.php?order=command_date_arrival">Chegada</a></th>
	<th><a href="/game.php?order=spear"><img src="https://dsbr.innogamescdn.com/asset/e94cf8a0/graphic/unit/unit_spear.webp" title="Lanceiro" /></a></th>
	<th><a href="/game.php?order=sword"><img src="https://dsbr.innogamescdn.com/asset/e94cf8a0/graphic/unit/unit_sword.webp" title="Espadachim" /></a></th>
	<th><a href="/game.php?order=axe"><img src="https://dsbr.innogamescdn.com/asset/e94cf8a0/graphic/unit/unit_axe.webp" title="Bárbaro" /></a></th>
	<th><a href="/game.php?order=spy"><img src="https://dsbr.innogamescdn.com/asset/e94cf8a0/graphic/unit/unit_spy.webp" title="Explorador" /></a></th>
	<th><a href="/game.php?order=light"><img src="https://dsbr.innogamescdn.com/asset/e94cf8a0/graphic/unit/unit_light.webp" title="Cavalaria leve" /></a></th>
	<th><a href="/game.php?order=heavy"><img src="https://dsbr.innogamescdn.com/asset/e94cf8a0/graphic/unit/unit_heavy.webp" title="Cavalaria pesada" /></a></th>
	<th><a href="/game.php?order=ram"><img src="https://dsbr.innogamescdn.com/asset/e94cf8a0/graphic/unit/unit_ram.webp" title="Aríete" /></a></th>
	<th><a href="/game.php?order=catapult"><img src="https://dsbr.innogamescdn.com/asset/e94cf8a0/graphic/unit/unit_catapult.webp" title="Catapulta" /></a></th>
	<th><a href="/game.php?order=knight"><img src="https://dsbr.innogamescdn.com/asset/e94cf8a0/graphic/unit/unit_knight.webp" title="Paladino" /></a></th>
	<th><a href="/game.php?order=snob"><img src="https://dsbr.innogamescdn.com/asset/e94cf8a0/graphic/unit/unit_snob.webp" title="Nobre" /></a></th>
</tr>"""


def _page(rows, count=None, header=None):
    header = header or HEADER_NO_ARCHER
    header = header.replace(
        "@COUNT@", str(len(rows) if count is None else count))
    return SERVER_CLOCK + header + "".join(rows) + "</table>"


# --------------------------------------------------------------------------
print("\n== relogio do servidor ==")
clock, err = Extractor.server_clock(SERVER_CLOCK)
_check("data e hora do servidor", clock, datetime.datetime(2026, 9, 22, 16, 14, 6))
_check("sem erro", err, None)

clock, err = Extractor.server_clock("<html>sem relogio</html>")
_check("pagina sem relogio -> None", clock, None)
_check_true("pagina sem relogio -> motivo", err)


print("\n== linha de farm (verbatim) ==")
out = Extractor.own_commands(_page([ROW_FARM]))
_check("um comando", len(out["commands"]), 1)
_check("sem warnings", out["warnings"], [])
c = out["commands"][0]
_check("id", c["command_id"], "6869354")
_check("tipo", c["command_type"], "attack")
_check("origem id", c["origin_village_id"], "40374")
_check("origem rotulo", c["origin_label"], "BBM 024 (588|314) K35")
_check("origem coords", c["origin_coords"], "588|314")
_check("alvo coords", c["target_coords"], "598|315")
_check("tropas", c["units"], {"light": 8})
_check("sem nobre", c["has_snob"], False)
_check("chegada absoluta",
       datetime.datetime.fromtimestamp(c["arrival_ts"]),
       datetime.datetime(2026, 9, 22, 16, 24, 23))
_check("texto cru da chegada preservado",
       c["arrival_text"].startswith("hoje"), True)
_check("sem erro de chegada", c["arrival_error"], None)


print("\n== linha de nobre: DOIS sinais concordam ==")
out = Extractor.own_commands(_page([ROW_NOBLE]))
c = out["commands"][0]
_check("sem warnings (coluna e icone concordam)", out["warnings"], [])
_check("tipo lido do PRIMEIRO atributo, que e igual ao segundo",
       c["command_type"], "attack")
_check("id nao duplicou", c["command_id"], "1526336960")
_check("has_snob", c["has_snob"], True)
_check("coluna de nobre", c["units"].get("snob"), 1)
_check("tropas completas", c["units"],
       {"spear": 428, "sword": 416, "light": 48, "heavy": 36, "snob": 1})


print("\n== chegada em outro dia ('em 25.09.') ==")
out = Extractor.own_commands(_page([ROW_WITHDRAW]))
c = out["commands"][0]
_check("tipo retirada", c["command_type"], "back")
_check("hint", c["icon_hint"], "Apoio retirado")
_check("chegada em 25/09",
       datetime.datetime.fromtimestamp(c["arrival_ts"]),
       datetime.datetime(2026, 9, 25, 0, 26, 36))
_check("tropas", c["units"], {"sword": 1000})


print("\n== 1. o contador do cabecalho e guarda, nao total ==")
# Medido no br143: a pagina default trouxe 25 de 65 e o cabecalho dizia 25.
# Logo o contador NAO detecta truncamento -- ele so detecta o parser perdendo
# linha. Este teste fixa esse uso e nada alem dele.
out = Extractor.own_commands(_page([ROW_FARM, ROW_NOBLE]))
_check("declared bate com as linhas", out["declared"], 2)
_check("sem warning quando bate", out["warnings"], [])

out = Extractor.own_commands(_page([ROW_FARM, ROW_NOBLE], count=7))
_check("declared divergente e denunciado", len(out["warnings"]), 1)
_check_true("warning cita os dois numeros",
            "7" in out["warnings"][0] and "2" in out["warnings"][0])


print("\n== 2. mundo COM arqueiro: 12 colunas, nada de ordem chumbada ==")
# Se a ordem fosse chumbada na do br143 (10 colunas), os 3 nobres abaixo
# seriam lidos como outra unidade e o painel mentiria sobre trem de conquista.
HEADER_ARCHER = HEADER_NO_ARCHER.replace(
    '<th><a href="/game.php?order=spy">',
    '<th><a href="/game.php?order=archer"><img src="https://x/graphic/unit/unit_archer.webp" title="Arqueiro" /></a></th>\n'
    '<th><a href="/game.php?order=spy">'
).replace(
    '<th><a href="/game.php?order=heavy">',
    '<th><a href="/game.php?order=marcher"><img src="https://x/graphic/unit/unit_marcher.webp" title="Arqueiro a cavalo" /></a></th>\n'
    '<th><a href="/game.php?order=heavy">'
)
ROW_ARCHER_WORLD = (
    '<tr class="nowrap row_ax"><td>'
    '<span class="own_command" data-icon-hint="Ataque" data-command-type="attack" data-command-id="999">'
    '<img src="https://x/graphic/command/attack_small.webp" /></span>'
    # Leva nobre, entao leva TAMBEM o icone -- foi assim nas 4 linhas de nobre
    # da captura real, e omiti-lo aqui faria a fixture mentir sobre o jogo.
    '<span class="own_command" data-icon-hint="Com nobre " data-command-type="attack" data-command-id="999">'
    '<img src="https://x/graphic/command/snob.webp" /></span>'
    '<span class="quickedit-label">Ataque a Aldeia de bárbaros (500|500) K55</span>'
    '</td><td><a href="/game.php?screen=info_village&amp;id=111">ORIG (400|400) K44</a></td>'
    '<td>hoje às 18:00:00:<span class="grey small">000</span></td>'
    # spear sword axe ARCHER spy light MARCHER heavy ram catapult knight snob
    "<td class='unit-item'>1</td><td class='unit-item'>2</td>"
    "<td class='unit-item'>3</td><td class='unit-item'>4</td>"
    "<td class='unit-item'>5</td><td class='unit-item'>6</td>"
    "<td class='unit-item'>7</td><td class='unit-item'>8</td>"
    "<td class='unit-item'>9</td><td class='unit-item'>10</td>"
    "<td class='unit-item'>11</td><td class='unit-item'>3</td></tr>"
)
out = Extractor.own_commands(_page([ROW_ARCHER_WORLD], header=HEADER_ARCHER))
c = out["commands"][0]
_check("sem warnings no mundo com arqueiro", out["warnings"], [])
_check("arqueiro rotulado certo", c["units"].get("archer"), 4)
_check("arqueiro a cavalo rotulado certo", c["units"].get("marcher"), 7)
_check("nobre rotulado certo (3, nao catapulta)", c["units"].get("snob"), 3)
_check("catapulta rotulada certo", c["units"].get("catapult"), 10)
_check("has_snob", c["has_snob"], True)

# GUARDA: a ordem do br143 aplicada a um mundo com arqueiro erraria. Se alguem
# trocar a leitura do cabecalho por uma lista fixa, este teste falha.
# Com 10 nomes para 12 celulas o zip TRUNCA, entao o erro nao e so de rotulo:
# as duas ultimas colunas somem e `snob` recebe o valor da 10a celula.
BR143_ORDER = ["spear", "sword", "axe", "spy", "light", "heavy", "ram",
               "catapult", "knight", "snob"]
cells = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 3]
hardcoded = dict(zip(BR143_ORDER, cells))
_check("a ordem chumbada leria 'snob' como 10 (errado)", hardcoded["snob"], 10)
_check_true("...e portanto diverge do valor real (3)",
            hardcoded["snob"] != c["units"]["snob"])
_check("a ordem chumbada perderia o arqueiro inteiro",
       "archer" in hardcoded, False)


print("\n== os dois sinais de nobre discordando viram warning ==")
# Nao e hipotetico o suficiente para ser ignorado: se o jogo mudar o icone ou
# a coluna, preciso saber -- "tem nobre no ar" e o fato mais caro de errar
# aqui. Nenhum dos dois lados vence calado.
ROW_DISAGREE = ROW_NOBLE.replace(
    '<img  src="https://dsbr.innogamescdn.com/asset/e94cf8a0/graphic/command/snob.webp" alt="" />',
    '<img  src="https://dsbr.innogamescdn.com/asset/e94cf8a0/graphic/command/other.webp" alt="" />')
out = Extractor.own_commands(_page([ROW_DISAGREE]))
_check("discordancia denunciada", len(out["warnings"]), 1)
_check_true("warning nomeia o comando", "1526336960" in out["warnings"][0])
_check("e o nobre continua visivel (coluna diz que tem)",
       out["commands"][0]["has_snob"], True)


print("\n== 3. falha de chegada e None, nunca 0 ==")
ROW_BAD_TIME = ROW_FARM.replace("hoje às 16:24:23", "quando der")
out = Extractor.own_commands(_page([ROW_BAD_TIME]))
c = out["commands"][0]
_check("arrival_ts e None", c["arrival_ts"], None)
_check_true("arrival_ts NAO e 0 (o erro do attack_duration)",
            c["arrival_ts"] is None and c["arrival_ts"] != 0)
_check_true("motivo registrado", c["arrival_error"])
_check("o resto da linha sobreviveu", c["units"], {"light": 8})

# Sem relogio do servidor nao da para resolver "hoje" -- e o fallback para o
# relogio local seria errado em mundo de outro fuso.
out = Extractor.own_commands(_page([ROW_FARM]).replace(SERVER_CLOCK, ""))
c = out["commands"][0]
_check("sem relogio -> arrival_ts None", c["arrival_ts"], None)
_check("sem relogio -> server_time None", out["server_time"], None)
_check_true("sem relogio -> warning", any("relogio" in w for w in out["warnings"]))


print("\n== degradacao: None x lista vazia sao coisas diferentes ==")
_check("html vazio -> None", Extractor.own_commands(""), None)
_check("pagina de login -> None",
       Extractor.own_commands("<html><body>login</body></html>"), None)
vazio = Extractor.own_commands(_page([], count=0))
_check("tabela sem linhas -> lista vazia, NAO None", vazio["commands"], [])
_check_true("...e a resposta existe", vazio is not None)


print("\n== colunas de tropa que nao casam: descarta, nao desloca ==")
ROW_SHORT = ROW_FARM.replace(
    "<td class='unit-item hidden'>0</td><td class='unit-item hidden'>0</td></tr>", "</tr>")
out = Extractor.own_commands(_page([ROW_SHORT]))
c = out["commands"][0]
_check("tropas descartadas em vez de deslocadas", c["units"], {})
_check_true("descarte denunciado", any("tropa" in w for w in out["warnings"]))
_check("a linha continua existindo", c["command_id"], "6869354")
# O icone ainda e lido -- e por isso que has_snob nao depende so da coluna.
out = Extractor.own_commands(_page([ROW_NOBLE.replace(
    "<td class='unit-item'>1</td></tr>", "</tr>")]))
_check("nobre ainda visivel pelo icone com a coluna quebrada",
       out["commands"][0]["has_snob"], True)

# --------------------------------------------------------------------------
# RETORNO COM NOBRE (2026-09-23). Recorte literal da mesma tela, capturado as
# 20:1x com `WebWrapper.get_url`: um dos tres nobres do trem da 50833 que
# baixaram a lealdade sem conquistar e voltam para casa. O jogo marca a linha
# com o mesmo segundo <span class="own_command">, mas o icone e
# `command/return_snob.*` (hint "Com nobre (retornando)"). O regex antigo so
# casava `command/snob.*`: a coluna dizia nobre, o icone dizia que nao, e o
# InFlight logava um WARNING por retorno -- alarme falso (15o padrao).
# --------------------------------------------------------------------------
ROW_RETURN_SNOB = """<tr class="nowrap  selected  row_ax">
	<td>
		<input type="checkbox" name="cancel[]" value="279844355" disabled />        			<span class="own_command" data-icon-hint="Ataque pequeno (1-1000 tropas) (retornando) " data-command-type="return" data-command-id="279844355">
            <img  src="https://dsbr.innogamescdn.com/asset/e94cf8a0/graphic/command/return_attack_small.webp" alt="" />			</span>
        			<span class="own_command" data-icon-hint="Com nobre (retornando) " data-command-type="return" data-command-id="279844355">
            <img  src="https://dsbr.innogamescdn.com/asset/e94cf8a0/graphic/command/return_snob.webp" alt="" />			</span>
        
        <span class="quickedit" data-id="279844355">
            <span class="quickedit-content">
                <a href="/game.php?village=41123&amp;screen=info_command&amp;id=279844355&amp;type=own">
                    <span class="quickedit-label">
                         Retorno de BBM 033 (575|291) K25                    </span>
                </a>
                <a class="rename-icon" href="#" title="Renomear"></a>
            </span>
        </span>

	</td>
	<td>
		<a href="/game.php?village=41123&amp;screen=info_village&amp;id=41123">BBM 001 (577|306) K35</a>
	</td>
	<td>
			amanhã às 03:04:45:<span class="grey small">000</span>		</td>
	<td class='unit-item'>10</td><td class='unit-item hidden'>0</td><td class='unit-item'>634</td><td class='unit-item hidden'>0</td><td class='unit-item'>278</td><td class='unit-item hidden'>0</td><td class='unit-item'>14</td><td class='unit-item'>4</td><td class='unit-item hidden'>0</td><td class='unit-item'>1</td></tr>"""
out = Extractor.own_commands(_page([ROW_RETURN_SNOB]))
c = out["commands"][0]
_check("retorno: tipo", c["command_type"], "return")
_check("retorno: coluna de nobre", c["units"].get("snob"), 1)
_check("retorno: has_snob", c["has_snob"], True)
_check("retorno com nobre nao gera aviso de discordancia",
       [w for w in out["warnings"] if "coluna de nobre" in w], [])
# O retorno sem nobre continua sem nobre pelos dois lados.
sem_nobre = ROW_RETURN_SNOB.replace(
    "<td class='unit-item'>1</td></tr>", "<td class='unit-item'>0</td></tr>"
).replace("command/return_snob.webp", "command/return_attack_small.webp")
out = Extractor.own_commands(_page([sem_nobre]))
_check("retorno sem nobre: has_snob", out["commands"][0]["has_snob"], False)
_check("retorno sem nobre: sem aviso",
       [w for w in out["warnings"] if "coluna de nobre" in w], [])


print("\n" + "=" * 70)
if _failures:
    print("FALHAS (%d de %d):" % (len(_failures), _checks))
    for f in _failures:
        print("  - " + f)
    sys.exit(1)
print("OK - %d checagens de own_commands passaram" % _checks)
