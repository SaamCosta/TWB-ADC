"""
Testes do parser de inventario (InventoryPage, Feature 25 fase 1).

Todo o markup abaixo e recorte VERBATIM das duas respostas reais do br143,
buscadas com a sessao do bot em 2026-08-16 (aldeia 41123):

  * SCRIPT       -- o <script> inteiro de screen=inventory, byte a byte.
  * INV_*/DATA_* -- entradas de "inventory" e "data" de
                    screen=inventory&ajax=get_inventory, byte a byte.

Uma unica reducao, anotada onde aparece: o campo "tooltip" (ultimo de cada
entrada de "data", ~500 caracteres de HTML que o bot descarta) foi trocado
por um marcador. Todo o resto -- os escapes \\u, as barras escapadas \\/, o
"instance_id" que vem int num item e string no outro, o "amount" como string
-- e exatamente o que o servidor respondeu.

Isso importa mais aqui do que de costume: o levantamento de campo que
originou esta feature catalogou os itens a partir de `window.Inventory.item_data`,
um objeto que so existe no NAVEGADOR. Ver test_o_objeto_do_navegador_nao_chega_na_resposta.

Rodar: python tests/test_inventory.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pages.inventory import InventoryPage


# <script> verbatim de screen=inventory. Repare no que NAO esta aqui: nem
# item_data, nem um unico item -- so os enums e o init.
SCRIPT = (
    '<script>\n    $(function(){\n        Inventory.item_types = {"1":"Funci'
    'onalidade","2":"Consum\\u00edvel","3":"Passivo","4":"Ativ\\u00e1vel"};\n'
    '        Inventory.item_categories = {"7":"Cosm\\u00e9ticos","5":"Itens '
    'de aldeia","6":"Itens de recrutamento","8":"Itens de rel\\u00edquia","4"'
    ':"Itens de unidade","3":"Itens do evento","2":"Pacotes de recurso","1":'
    '"Premium"};\n        Inventory.item_tags = {"rarity":["Nenhum","Comum",'
    '"Incomum","Raro","Lend\\u00e1rio"],"use_type":["Nenhum","Consum\\u00edve'
    'l","Presente\\u00e1vel"]};\n        Inventory.init(0);\n    });\n</script>'
)

INV_3016 = (
    '{"player_id":"5955651","item_id":"3016","instance_id":"0","item_key"'
    ':"3016_0","amount":"4","instance_data":null,"new":"0"}'
)

INV_201_11 = (
    '{"player_id":"5955651","item_id":"201","instance_id":"11","item_key"'
    ':"201_11","amount":"1","instance_data":"{\\"skill_id\\":8}","new":"0"}'
)

# "tooltip" cortado (era o ultimo campo). O resto e verbatim.
DATA_3016 = (
    '{"item_id":3016,"instance_id":0,"name":"B\\u00f4nus de ataque","admin'
    '_name":"B\\u00f4nus de ataque (5%) 1 day","image":"https:\\/\\/dsbr.inn'
    'ogamescdn.com\\/asset\\/fa57a0ef\\/graphic\\/items\\/3016.webp","image_in'
    'fo":{"hash":"55b47","width":92,"height":92,"has_retina":true,"has_we'
    'bp":true,"src":"items\\/3016.png"},"type":2,"category":4,"color":null'
    ',"actions":[{"name":"Usar","link":"javascript:Inventory.openItemDial'
    'og(\'%item_key%\', \'activate_reward\')","allow_sitter":true}],"links":['
    '],"tags":[{"type":"use_type","tag":1}],"descriptions":[{"text":"B\\u0'
    '0e1rbaro: +5% poder de ataque<br \\/>Cavalaria leve: +5% poder de ata'
    'que","color":null,"image":null},{"text":"Dura\\u00e7\\u00e3o: 24:00:00'
    '","color":"green","image":null},{"text":"Efeito: Em todas as aldeias'
    '","color":"green","image":null}],"new_count":"0","tooltip":"<cortado'
    ' neste fixture>"}'
)

DATA_3095 = (
    '{"item_id":3095,"instance_id":0,"name":"Refor\\u00e7o Defensivo","adm'
    'in_name":"Refor\\u00e7o Defensivo (7%)","image":"https:\\/\\/dsbr.innog'
    'amescdn.com\\/asset\\/fa57a0ef\\/graphic\\/items\\/3095.webp","image_info'
    '":{"hash":"95314","width":92,"height":92,"has_retina":true,"has_webp'
    '":true,"src":"items\\/3095.png"},"type":2,"category":6,"color":null,"'
    'actions":[{"name":"Usar","link":"javascript:Inventory.openItemDialog'
    '(\'%item_key%\', \'use\')","allow_sitter":true}],"links":[],"tags":[{"ty'
    'pe":"use_type","tag":1}],"descriptions":[{"text":"Adiciona 7% do seu'
    ' espa\\u00e7o livre em unidades \\u00e0 sua aldeia atual.","color":nul'
    'l,"image":null},{"text":"<img src=\\"https:\\/\\/dsbr.innogamescdn.com\\/'
    'asset\\/fa57a0ef\\/graphic\\/unit\\/unit_spear.webp\\" title=\\"\\" alt=\\"\\"'
    ' class=\\"\\" \\/> Lanceiro (~3.5%)<br\\/><img src=\\"https:\\/\\/dsbr.inno'
    'gamescdn.com\\/asset\\/fa57a0ef\\/graphic\\/unit\\/unit_sword.webp\\" titl'
    'e=\\"\\" alt=\\"\\" class=\\"\\" \\/> Espadachim (~3.5%)","color":null,"ima'
    'ge":null},{"text":"Hora de chegada: Entre 20 e 24 horas.","color":"g'
    'reen","image":null},{"text":"Efeito: Em uma aldeia","color":"green",'
    '"image":null}],"new_count":"0","tooltip":"<cortado neste fixture>"}'
)

DATA_201_11 = (
    '{"item_id":201,"instance_id":"11","name":"Livro de habilidade: Persu'
    'as\\u00e3o","admin_name":"Livro de habilidade: Persuas\\u00e3o","image'
    '":"https:\\/\\/dsbr.innogamescdn.com\\/asset\\/fa57a0ef\\/graphic\\/items\\/'
    'knight_skill_8.webp","image_info":{"hash":"6d3ff","width":92,"height'
    '":92,"has_retina":true,"has_webp":true,"src":"items\\/knight_skill_8.'
    'png"},"type":2,"category":4,"color":null,"actions":[{"name":"Usar","'
    'link":"javascript:Inventory.openItemDialog(\'%item_key%\', \'study\')","'
    'allow_sitter":true},{"name":"Reutilizar","link":"javascript:Inventor'
    'y.openItemDialog(\'%item_key%\', \'reroll\')","allow_sitter":true}],"lin'
    'ks":[],"tags":[{"type":"use_type","tag":1}],"descriptions":[{"text":'
    '"Os seus paladinos podem usar livros para melhorar suas habilidades.'
    ' Este livro cont\\u00e9m o conhecimento sobre Persuas\\u00e3o:","color'
    '":null,"image":null},{"text":"Melhora a efic\\u00e1cia de ataques com'
    ' nobres a partir da aldeia onde o paladino estiver parado. (O paladi'
    'no deve estar na aldeia de onde partir o ataque quando o ataque cheg'
    'ar \\u00e0 aldeia de destino e n\\u00e3o acompanhando o ex\\u00e9rcito '
    'atacante).","color":null,"image":null}],"new_count":"0","tooltip":"<'
    'cortado neste fixture>"}'
)


def _payload(expire="[]"):
    """Mesma forma da resposta real: inventory + data + expire."""
    return json.loads(
        '{"inventory":{"3016_0":%s,"201_11":%s,"3095_0":'
        '{"player_id":"5955651","item_id":"3095","instance_id":"0",'
        '"item_key":"3095_0","amount":"1","instance_data":null,"new":"0"}},'
        '"data":{"3016_0":%s,"201_11":%s,"3095_0":%s},"expire":%s}'
        % (INV_3016, INV_201_11, DATA_3016, DATA_201_11, DATA_3095, expire)
    )


class _FakeResponse:
    def __init__(self, text):
        self.text = text


# Sentinela: `payload=None` e um caso de TESTE valido (rede falhou), entao
# nao pode significar tambem "usa o payload bom".
_PADRAO = object()


class _FakeWrapper:
    """
    Dubla os dois metodos reais de WebWrapper que a pagina usa, com os
    mesmos contratos de falha: get_action devolve None em erro de rede, e
    get_api_data devolve None OU o proprio Response quando .json() falha.
    """

    def __init__(self, screen=SCRIPT, payload=_PADRAO):
        self._screen = screen
        self._payload = _payload() if payload is _PADRAO else payload
        self.calls = []

    def get_action(self, village_id, action):
        self.calls.append(("get_action", village_id, action))
        return None if self._screen is None else _FakeResponse(self._screen)

    def get_api_data(self, village_id, action, params=None):
        self.calls.append(("get_api_data", village_id, action, params))
        return self._payload


def _page(**kwargs):
    return InventoryPage(_FakeWrapper(**kwargs), "41123")


def _by_key(page, key):
    return next(i for i in page.items if i["item_key"] == key)


def test_o_objeto_do_navegador_nao_chega_na_resposta():
    """
    Guarda de regressao da premissa desta feature. O levantamento de campo
    catalogou os itens de `Inventory.item_data`, que so existe depois que o JS
    monta a tela -- a resposta HTTP nao tem nem o objeto nem um unico item.
    Um parser escrito contra ele devolveria vazio em todo ciclo, em silencio,
    igual ao _parse_locked_slots() da Feature 24.
    """
    assert "item_data" not in SCRIPT
    assert "3016_0" not in SCRIPT
    # ... e mesmo assim os itens sao lidos, porque vem do ajax get_inventory.
    assert len(_page().items) == 3


def test_enums_vem_do_script_da_tela():
    page = _page()
    assert page.item_types["2"] == "Consumível"
    assert page.item_categories["4"] == "Itens de unidade"
    assert page.item_categories["6"] == "Itens de recrutamento"
    assert page.item_tags["use_type"] == ["Nenhum", "Consumível", "Presenteável"]
    assert page.enums_available is True


def test_quantidade_vem_como_string_e_vira_int():
    """"amount":"4" -- somar isso como string daria "4444" no total."""
    page = _page()
    assert _by_key(page, "3016_0")["amount"] == 4
    assert _by_key(page, "201_11")["amount"] == 1
    assert sum(i["amount"] for i in page.items) == 6


def test_tipo_e_categoria_ganham_rotulo_do_servidor():
    item = _by_key(_page(), "3016_0")
    assert (item["type"], item["type_name"]) == (2, "Consumível")
    assert (item["category"], item["category_name"]) == (4, "Itens de unidade")


def test_instance_id_ora_int_ora_string():
    """3016_0 manda 0 (int) e 201_11 manda "11" (string), na mesma resposta."""
    assert _by_key(_page(), "3016_0")["instance_id"] == 0
    assert _by_key(_page(), "201_11")["instance_id"] == 11


def test_descricao_vira_linhas_de_texto_puro():
    linhas = _by_key(_page(), "3016_0")["description_lines"]
    assert [l["text"] for l in linhas] == [
        "Bárbaro: +5% poder de ataque",
        "Cavalaria leve: +5% poder de ataque",
        "Duração: 24:00:00",
        "Efeito: Em todas as aldeias",
    ]
    # A cor acompanha cada linha do bloco de origem.
    assert [l["color"] for l in linhas] == ["", "", "green", "green"]


def test_img_de_unidade_some_mas_o_nome_da_unidade_fica():
    """
    A descricao do Reforco Defensivo traz <img> de lanceiro/espadachim antes
    do nome. Stripar a tag nao pode levar o texto junto.
    """
    linhas = [l["text"] for l in _by_key(_page(), "3095_0")["description_lines"]]
    assert linhas == [
        "Adiciona 7% do seu espaço livre em unidades à sua aldeia atual.",
        "Lanceiro (~3.5%)",
        "Espadachim (~3.5%)",
        "Hora de chegada: Entre 20 e 24 horas.",
        "Efeito: Em uma aldeia",
    ]
    assert not any("<" in l for l in linhas)


def test_instance_data_e_string_de_json_e_vira_dict():
    """O livro de habilidade carrega qual skill ele ensina, aninhado numa string."""
    assert _by_key(_page(), "201_11")["instance_data"] == {"skill_id": 8}
    assert _by_key(_page(), "3016_0")["instance_data"] is None


def test_acoes_preservam_o_caminho_de_ativacao_da_fase_2():
    acoes = _by_key(_page(), "201_11")["actions"]
    assert [a["name"] for a in acoes] == ["Usar", "Reutilizar"]
    assert "study" in acoes[0]["link"]


def test_tag_resolvida_contra_a_lista_do_servidor():
    tags = _by_key(_page(), "3016_0")["tags"]
    assert tags == [{"type": "use_type", "value": 1, "label": "Consumível"}]


def test_tag_zero_nao_vira_rotulo():
    """Indice 0 e "Nenhum" em todas as listas -- nao deve virar badge."""
    page = _page()
    assert page._resolve_tags([{"type": "use_type", "tag": 0}])[0]["label"] == ""


def test_expire_vazio_vem_como_lista_e_nao_quebra():
    """
    Na conta real veio "expire":[] -- o PHP serializa mapa vazio como lista.
    O JS o percorre por chave, ou seja vira objeto quando houver item ativo.
    """
    assert InventoryPage._normalize_expiry([]) == {}
    assert all(i["expires_at"] == [] for i in _page().items)


def test_expire_com_item_vira_lista_de_timestamps():
    page = _page(payload=_payload(expire='{"3016_0":["1755400000"]}'))
    assert _by_key(page, "3016_0")["expires_at"] == [1755400000]
    assert _by_key(page, "201_11")["expires_at"] == []


def test_ordenacao_por_categoria_depois_nome():
    assert [i["item_key"] for i in _page().items] == ["3016_0", "201_11", "3095_0"]


def test_sem_o_html_os_itens_continuam_com_rotulo_generico():
    """
    get_url devolve None em qualquer excecao (core/request.py). Perder os
    enums nao pode custar os itens -- so os nomes de tipo/categoria.
    """
    page = _page(screen=None)
    assert len(page.items) == 3
    assert page.enums_available is False
    assert _by_key(page, "3016_0")["category_name"] == "Categoria 4"
    assert _by_key(page, "3016_0")["amount"] == 4


def test_as_duas_formas_de_resposta_do_ajax():
    """
    Mesma URL, duas formas, conforme o cabecalho TribalWars-Ajax: com ele (o
    que WebWrapper.get_api_data sempre manda) o payload vem embrulhado em
    "response"; sem ele vem cru. A exploracao inicial viu so a forma crua --
    escrever contra ela teria quebrado em producao passando nos testes.
    """
    cru = _payload()
    embrulhado = {"response": _payload(), "game_data": {"player": {"id": 5955651}}}
    for forma in (cru, embrulhado):
        page = InventoryPage(_FakeWrapper(payload=forma), "41123")
        assert len(page.items) == 3
        assert _by_key(page, "3016_0")["amount"] == 4


def test_acao_desconhecida_devolve_response_false_e_nao_explode():
    """`{"response":false, "game_data":{...}}` e o que o jogo manda para um
    `ajax=` que ele nao conhece -- tem que virar RuntimeError, nao TypeError."""
    try:
        InventoryPage(
            _FakeWrapper(payload={"response": False, "game_data": {}}), "41123"
        )
    except RuntimeError:
        return
    raise AssertionError("response=false devia ter levantado RuntimeError")


def test_ajax_sem_resposta_levanta_para_o_manager_tratar():
    for ruim in (None, _FakeResponse("<html>login</html>"), "", []):
        try:
            InventoryPage(_FakeWrapper(payload=ruim), "41123")
        except RuntimeError:
            continue
        raise AssertionError("payload %r devia ter levantado RuntimeError" % (ruim,))


def test_payload_sem_a_chave_data_e_falha_mas_inventario_vazio_nao_e():
    """
    Distinguir "resposta errada" de "conta sem itens": a primeira nao tem
    "data", a segunda tem "data":{}. Tratar as duas igual esconderia sessao
    expirada atras de uma tela dizendo "inventario vazio".
    """
    try:
        InventoryPage(_FakeWrapper(payload={"inventory": {}}), "41123")
    except RuntimeError:
        pass
    else:
        raise AssertionError("payload sem 'data' devia ter levantado")

    vazio = InventoryPage(
        _FakeWrapper(payload={"inventory": {}, "data": {}, "expire": []}), "41123"
    )
    assert vazio.items == []


def test_a_url_pedida_e_a_do_ajax_de_inventario():
    """Se alguem trocar o screen, a chamada volta a cair em screen=api."""
    wrapper = _FakeWrapper()
    InventoryPage(wrapper, "41123")
    assert ("get_api_data", "41123", "get_inventory", {"screen": "inventory"}) in wrapper.calls
    assert ("get_action", "41123", "inventory") in wrapper.calls


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
