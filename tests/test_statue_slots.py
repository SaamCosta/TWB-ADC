"""
Testes dos limiares de slot de Paladino (StatuePage, Feature 24 fase 1).

O markup abaixo e recorte do HTML REAL de screen=statue&mode=overview do
br143, buscado com a sessao do bot em 2026-08-16 (aldeia 44683). Nao e
inventado -- o bug que estes testes fecham existia justamente porque o parser
anterior fora escrito contra um texto que o servidor nunca manda.

Duas reducoes, ambas anotadas onde aparecem: o 1o argumento de
initImmutables traz as 12 skills e aqui ficou so a primeira (verbatim), e o
dict de paladinos ficou com um paladino em vez de tres. Todo o resto -- os
limiares, as tres arvores, o bloco premium, o `0` que fecha
receiveKnightsData e o "villages" como STRING -- e byte a byte o que o
servidor respondeu.

Rodar: python tests/test_statue_slots.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pages.statue import StatuePage


# 1a das 12 skills, verbatim (as demais foram cortadas por tamanho). Mantida
# com os escapes \u que o jogo manda: sao eles que exercitam _extract_balanced.
SKILL_1 = (
    '{"id":1,"name":"Investida","image":1,"description":"Durante ataque com o '
    'paladino, os b\\u00e1rbaros receber\\u00e3o um b\\u00f4nus de for\\u00e7a.",'
    '"level_descriptions":{"1":["B\\u00e1rbaro: +5% poder de ataque"],'
    '"2":["B\\u00e1rbaro: +10% poder de ataque"],"3":["B\\u00e1rbaro: +15% poder '
    'de ataque"],"4":["B\\u00e1rbaro: +30% poder de ataque"]},'
    '"effect_magnitudes":{"1":[5],"2":[10],"3":[15],"4":[30]},'
    '"level_min":1,"level_max":4}'
)

# 2o argumento: tier_requirements + as 3 arvores. Verbatim, inteiro.
BRANCHES = (
    '{"tier_requirements":{"1":1,"2":8,"3":16,"4":24},"branches":['
    '{"name":"Ofensiva","node_map":{"1":{"skill_id":1,"parent_id":null,"depth":0,'
    '"child_ids":[2]},"2":{"skill_id":2,"parent_id":1,"depth":1,"child_ids":[3]},'
    '"3":{"skill_id":3,"parent_id":2,"depth":2,"child_ids":[4]},'
    '"4":{"skill_id":4,"parent_id":3,"depth":3,"child_ids":[]}},"root_id":1,'
    '"color":"rgb(122, 0, 0)","color_dark":"rgb(61, 0, 0)",'
    '"color_bright":"rgb(183, 0, 0)",'
    '"image_src":"knight\\/branch\\/background\\/offense.png",'
    '"border_src":"knight\\/branch\\/border\\/red.png"},'
    '{"name":"Aldeia","node_map":{"5":{"skill_id":5,"parent_id":null,"depth":0,'
    '"child_ids":[6]},"6":{"skill_id":6,"parent_id":5,"depth":1,"child_ids":[7]},'
    '"7":{"skill_id":7,"parent_id":6,"depth":2,"child_ids":[8]},'
    '"8":{"skill_id":8,"parent_id":7,"depth":3,"child_ids":[]}},"root_id":5,'
    '"color":"rgb(0, 100, 0)","color_dark":"rgb(0, 50, 0)",'
    '"color_bright":"rgb(0, 150, 0)",'
    '"image_src":"knight\\/branch\\/background\\/city.png",'
    '"border_src":"knight\\/branch\\/border\\/green.png"},'
    '{"name":"Defesa","node_map":{"9":{"skill_id":9,"parent_id":null,"depth":0,'
    '"child_ids":[10]},"10":{"skill_id":10,"parent_id":9,"depth":1,'
    '"child_ids":[11]},"11":{"skill_id":11,"parent_id":10,"depth":2,'
    '"child_ids":[12]},"12":{"skill_id":12,"parent_id":11,"depth":3,'
    '"child_ids":[]}},"root_id":9,"color":"rgb(0, 0, 150)",'
    '"color_dark":"rgb(0, 0, 75)","color_bright":"rgb(0, 0, 225)",'
    '"image_src":"knight\\/branch\\/background\\/defense.png",'
    '"border_src":"knight\\/branch\\/border\\/blue.png"}]}'
)

# 4o argumento, verbatim.
PREMIUM = (
    '{"time_reduction":{"enabled":true,"pp_cost":10,"factor":0.5},'
    '"instant_finish":{"enabled":true,"pp_cost":10,"threshold_minutes":10},'
    '"cost_reduction":{"enabled":true,"pp_cost":30,"factor":0.8},'
    '"refund_factor":0.9}'
)

# Espacamento entre argumentos copiado da resposta real (quebra de linha dupla
# e indentacao), porque e exatamente isso que o walker precisa atravessar.
INIT_IMMUTABLES = (
    "<script>\n\n    $(function() {\n\n        BuildingStatue.initImmutables(\n\n"
    "            %s,\n\n            %s,\n\n            [1,3,5,10,20,35,50,65,80,100],\n\n"
    "            %s\n        );" % (SKILL_1, BRANCHES, PREMIUM)
)

# Um paladino em vez dos tres da conta; a forma da chamada -- array vazio,
# dict, e o literal 0 no fim -- e a real.
KNIGHTS_DATA = (
    'BuildingStatue.receiveKnightsData([], {"554":{"id":554,"name":"Sans\\u00e3o",'
    '"portrait_id":8,"level":19,"xp":{"progress":211959,"goal":357871},'
    '"skill_points":0,"home_village":{"id":44683,"name":"Aldeia"},'
    '"spawn_warn_premium":false}}, 0);'
)


def _game_data(villages='"8"'):
    """
    Linha real de TribalWars.updateGameData, com o player reduzido aos campos
    que importam aqui. `villages` vem como STRING na resposta do jogo -- e o
    detalhe que faz int() ser necessario.
    """
    return (
        'TribalWars.updateGameData({"player":{"id":848535,"villages":%s,'
        '"incomings":"0","supports":"0"},"village":{"id":44683},'
        '"world":"br143","screen":"statue","mode":"overview"});' % villages
    )


def _pagina(villages='"8"'):
    return _game_data(villages) + "\n" + INIT_IMMUTABLES + "\n" + KNIGHTS_DATA


def test_limiares_vem_do_terceiro_argumento_de_init_immutables():
    """Os 10 slots do br143, lidos server-side."""
    assert StatuePage._parse_slot_thresholds(_pagina()) == [
        1, 3, 5, 10, 20, 35, 50, 65, 80, 100
    ]


def test_o_texto_do_parser_antigo_nao_existe_na_resposta():
    """
    Guarda de regressao do bug: o parser anterior procurava "Obtenha N aldeias
    para desbloquear este slot", que so passa a existir depois que o JS do jogo
    monta o template no navegador. Se alguem voltar a parsear texto renderizado,
    este teste explica por que nao funciona.
    """
    assert "Obtenha" not in _pagina()
    assert "desbloquear" not in _pagina()


def test_contagem_de_aldeias_vem_do_game_data_como_inteiro():
    assert StatuePage._parse_village_count(_pagina()) == 8
    assert StatuePage._parse_village_count(_pagina(villages='"37"')) == 37


def test_bloqueados_sao_os_acima_da_contagem_de_aldeias():
    """
    Com 8 aldeias: 1, 3 e 5 abertos (batem com os 3 paladinos da conta em
    2026-08-16), 7 bloqueados -- exatamente os 7 que a tela renderizava.
    """
    texto = _pagina()
    limiares = StatuePage._parse_slot_thresholds(texto)
    bloqueados = StatuePage._locked_slots(limiares, StatuePage._parse_village_count(texto))
    assert bloqueados == [10, 20, 35, 50, 65, 80, 100]
    assert len(limiares) - len(bloqueados) == 3


def test_limiar_igual_a_contagem_conta_como_desbloqueado():
    """Com 10 aldeias o slot de 10 abre -- e limite, nao pode ficar de fora."""
    assert StatuePage._locked_slots([1, 3, 5, 10, 20], 10) == [20]


def test_sem_contagem_de_aldeias_nao_chuta_bloqueio():
    """
    Sem saber quantas aldeias a conta tem, dizer "tudo bloqueado" seria uma
    afirmacao falsa na tela. Vazio deixa a secao oculta, como antes do fix.
    """
    assert StatuePage._locked_slots([1, 3, 5], None) == []
    assert StatuePage._parse_village_count("<html>bot protection</html>") is None


def test_paladinos_continuam_sendo_lidos_pelo_walker_generico():
    """
    _parse_knights passou a usar _call_arguments; o walker tem que parar no
    literal `0` do terceiro argumento sem estragar o segundo.
    """
    knights = StatuePage._parse_knights(_pagina())
    assert list(knights) == ["554"]
    assert knights["554"]["level"] == 19
    assert knights["554"]["name"] == "Sansão"


def test_walker_para_no_argumento_que_nao_e_json():
    args = StatuePage._call_arguments(
        'BuildingStatue.receiveKnightsData([], {"554":{"id":554}}, 0);',
        "BuildingStatue.receiveKnightsData(", 3
    )
    assert len(args) == 2
    assert args[0] == []
    assert args[1] == {"554": {"id": 554}}


def test_markup_ausente_ou_quebrado_devolve_vazio_sem_excecao():
    """Sessao expirada, bot protection ou markup novo nao podem derrubar o ciclo."""
    for lixo in ("", "<html><body>login</body></html>",
                 "BuildingStatue.initImmutables(",
                 "BuildingStatue.initImmutables({\"1\":{},"):
        assert StatuePage._parse_slot_thresholds(lixo) == []
        assert StatuePage._parse_knights(lixo) == {}


def test_json_invalido_no_argumento_nao_propaga():
    quebrado = 'BuildingStatue.initImmutables({"1":{,,,}}, {}, [1,3], {});'
    assert StatuePage._parse_slot_thresholds(quebrado) == []


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
