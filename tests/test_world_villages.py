"""
Testes da TERCEIRA fonte de descoberta de alvo: `map/village.txt`.

  game/world_villages.py     -- parse, guardas e cache
  ConquestManager._candidate_pool()  -- a precedencia entre as tres fontes

O DEFEITO QUE ISTO FECHA (docs/backend.md 8.6, "O terceiro funil")
------------------------------------------------------------------
Depois do conserto de 19/09/2026 o pool tinha duas fontes -- o scan vivo da
aldeia e o snapshot `cache/villages` -- e as duas sofrem do mesmo limite: so
contem o que alguma aldeia NOSSA ja escaneou algum dia. Medido no br143 em
20/09/2026:

    scan vivo da ancora ......    332 aldeias   0,25% do mundo
    cache/villages ...........    851 aldeias   0,65% do mundo
    map/village.txt .......... 130.937 aldeias

Com isso `conquest.max_radius` era peneira de DESCOBERTA disfarcada de decisao
de alcance: subir o raio nao alcanca alvo que nunca entrou na lista.

AS LINHAS DE FIXTURE SAO VERBATIM do village.txt do br143, copiadas do arquivo
que o bot baixou em 20/09/2026 -- inclusive `40382` e `51991`, as duas
barbaras reais que os testes de alcance da 8.6 ja usavam, e `30375`/`34331`,
duas das 38 que o cache local jurava barbaras e o mundo ja tinha dado a
jogadores. Fixture de markup/formato se copia do servidor, nao se inventa
(CLAUDE.md).

Nada aqui toca cache/ nem a rede: o download e o disco sao substituidos por
dubles em memoria. O bot escreve nesses mesmos arquivos enquanto roda
(vigesimo primeiro padrao do CLAUDE.md).

Rodar: python tests/test_world_villages.py
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import game.attack as attack_mod
import game.world_villages as wv_mod
from game.attack import ConquestManager
from game.world_villages import WorldVillages, parse


# Verbatim: as tres primeiras linhas do arquivo e cinco do K25/K63.
VILLAGE_TXT = "\n".join([
    "1,011,631,531,7363091,10106,0",
    "2,K46+004,600,423,919524568,9622,0",
    "3,004+-+Voyage,489,470,7941477,2596,0",
    "30375,Ge+203,602,338,919935540,2484,0",
    "34331,Ge+202,605,334,919935540,3284,0",
    "40382,Aldeia+de+b%C3%A1rbaros,543,296,0,979,0",
    "41123,BBM+001,577,306,5955651,9898,0",
    "51991,Aldeia+de+b%C3%A1rbaros,570,293,0,1001,0",
]) + "\n"

BBM_001 = (577, 306)
BBM_023 = (553, 300)
OESTE = "40382"        # 543|296, barbara de 979 pts
PERTO = "51991"        # 570|293, barbara de 1001 pts
FANTASMA = "34331"     # 605|334 -- cache local dizia barbara; o mundo nao


# --------------------------------------------------------------------------
# parse
# --------------------------------------------------------------------------

def test_parse_le_o_formato_real():
    linhas = parse(VILLAGE_TXT)
    assert len(linhas) == 8
    x, y, owner, points, raw_name = linhas[PERTO]
    assert (x, y) == (570, 293)
    assert owner == "0"        # barbara
    assert points == 1001
    # O nome fica CRU aqui de proposito (ver o docstring de parse): decodificar
    # 130 mil nomes custava 2,7 s e 24 MB para os poucos milhares que saem.
    assert raw_name == "Aldeia+de+b%C3%A1rbaros"


def test_nome_e_decodificado_so_na_saida():
    world = _world(VILLAGE_TXT)
    entrada = world.in_box(560, 580, 285, 310)[PERTO]
    assert entrada["name"] == "Aldeia de bárbaros"
    # Mesma forma de cache/villages, para o pool poder misturar as fontes.
    assert entrada["location"] == [570, 293]
    assert entrada["id"] == PERTO


def test_linha_quebrada_nao_derruba_as_outras():
    """130 mil linhas; uma truncada nao pode custar o arquivo inteiro."""
    sujo = VILLAGE_TXT + "99999,sem,campos,suficientes\n" + "88888,x,y,z,w,v\n"
    linhas = parse(sujo)
    assert len(linhas) == 8
    assert "99999" not in linhas    # poucos campos
    assert "88888" not in linhas    # x/y nao sao inteiros


def test_nome_com_virgula_nao_existe_no_formato():
    """
    O primeiro registro real do arquivo se chama `011` e o quarto campo e
    `531`: tudo numero, nenhuma virgula dentro do nome. O formato nao tem
    aspas nem escape, entao um nome com virgula quebraria o split -- e o
    servidor resolve isso URL-encodando (`%2C`). Este teste existe para
    registrar a premissa, que e o que permite usar `split(",")` cru.
    """
    linhas = parse("7,a%2Cb,500,500,0,100,0\n" * 1 + VILLAGE_TXT)
    assert linhas["7"][4] == "a%2Cb"
    world = _world("7,a%2Cb,500,500,0,100,0\n" + VILLAGE_TXT)
    assert world.in_box(499, 501, 499, 501)["7"]["name"] == "a,b"


# --------------------------------------------------------------------------
# As tres guardas
# --------------------------------------------------------------------------

class _Res:
    def __init__(self, text, status=200):
        self.text = text
        self.status_code = status
        self.content = text.encode("utf-8")


def _world(texto_da_rede, disco=None, status=200, explode=False, minimo=1):
    """
    Um WorldVillages com rede e disco falsos. `disco` e o conteudo do cache.

    `minimo` baixa `MIN_VILLAGES` para 1 durante a construcao do objeto. A
    fixture tem 8 linhas VERBATIM e o mundo real tem 130 mil, entao sem isso a
    propria guarda das 100 recusaria a fixture -- e a alternativa seria
    inventar 100 linhas plausiveis, que e exatamente o que a regra de fixture
    deste repo proibe. A guarda com o valor de producao tem teste proprio
    (test_guarda_recusa_lista_curta_e_devolve_o_cache_velho), que e onde ela
    precisa ser exercitada de verdade.
    """
    world = WorldVillages(config={"server": {"server": "br143",
                                             "endpoint": "https://x/game.php"}})
    world.min_villages = minimo
    estado = {"disco": disco, "gravou": 0, "baixou": 0}

    def _download(self=world):
        estado["baixou"] += 1
        if explode:
            return None
        if status != 200:
            self._last_error = "HTTP %d" % status
            return None
        return texto_da_rede

    world._download = _download
    world._read_disk = lambda: estado["disco"]
    world._disk_age = lambda: None if estado["disco"] is None else 0.0

    def _write(texto):
        estado["gravou"] += 1
        estado["disco"] = texto

    world._write_disk = _write
    world._estado = estado
    return world


def test_guarda_recusa_lista_curta_com_o_limiar_de_producao():
    """
    UM PUNHADO DE ALDEIAS NAO E UM MUNDO. Um redirect para login ou uma pagina
    de erro voltam com HTTP 200 e sao indistinguiveis de um arquivo bom se so
    olharmos o codigo. Sem esta guarda o bot concluiria que o mundo tem 2
    aldeias e a descoberta morreria em silencio -- decimo quinto padrao do
    CLAUDE.md pelo avesso: a guarda que NUNCA dispara.

    Limiar de PRODUCAO aqui de proposito (os outros testes o baixam para poder
    usar a fixture verbatim de 8 linhas -- ver `_world`). O que se afirma: a
    resposta curta e recusada e NAO e gravada por cima do cache bom.
    """
    world = _world("1,a,1,1,0,100,0\n2,b,2,2,0,100,0\n",
                   minimo=wv_mod.MIN_VILLAGES)
    assert world.rows() == {}
    assert world._estado["gravou"] == 0
    assert "abaixo do minimo de 100" in world._last_error


def test_lista_curta_nao_apaga_a_leitura_boa_que_ja_estava_em_memoria():
    """
    A recusa preserva o estado anterior: `_adopt` so troca `_villages` depois
    de passar na guarda. Um soluco do servidor no meio de um dia nao pode
    cegar o bot que ja tinha a lista.
    """
    world = _world(VILLAGE_TXT)
    assert len(world.rows()) == 8
    world._parsed_at = 0.0                      # forca o TTL a vencer
    world._download = lambda: "1,a,1,1,0,100,0\n"
    world._read_disk = lambda: None
    world._disk_age = lambda: None
    world.min_villages = wv_mod.MIN_VILLAGES
    assert len(world.rows()) == 8               # seguiu com o que tinha


def test_guarda_recusa_corpo_absurdo():
    """
    Acima do teto nao e "grande demais para caber": e sinal de que nao e o
    arquivo. Como o teto e sobre bytes, este teste usa o `_download` real com
    um `requests.get` falso -- e o unico jeito de exercitar a guarda.
    """
    world = WorldVillages(config={"server": {"endpoint": "https://x/game.php"}})
    gigante = _Res("x" * 10)
    gigante.content = b"x" * (wv_mod.MAX_BYTES + 1)

    class _Req:
        RequestException = Exception

        @staticmethod
        def get(url, headers=None, timeout=None):
            return gigante

    original = wv_mod.requests
    wv_mod.requests = _Req
    try:
        assert world._download() is None
        assert "acima do teto" in world._last_error
    finally:
        wv_mod.requests = original


def test_falha_de_rede_serve_o_cache_vencido():
    """
    Uma lista de ontem e imensamente melhor que nenhuma: sem ela o bot volta
    calado aos 851 do cache local, que e o funil que esta feature existe para
    abrir.
    """
    world = _world("", disco=VILLAGE_TXT, explode=True)
    world._disk_age = lambda: 99 * 3600      # vencido, muito alem do TTL
    assert len(world.rows()) == 8


def test_sem_rede_e_sem_disco_devolve_vazio_sem_levantar():
    world = _world("", disco=None, explode=True)
    assert world.rows() == {}


def test_cache_em_disco_dentro_do_ttl_nao_vai_a_rede():
    world = _world(VILLAGE_TXT, disco=VILLAGE_TXT)
    world._disk_age = lambda: 60.0
    assert len(world.rows()) == 8
    assert world._estado["baixou"] == 0


def test_desligado_no_config_nao_le_nada():
    world = _world(VILLAGE_TXT)
    world.config = {"conquest": {"use_world_village_list": False}}
    assert world.rows() == {}
    assert world._estado["baixou"] == 0


# --------------------------------------------------------------------------
# Precedencia das tres fontes, no _candidate_pool real
# --------------------------------------------------------------------------

class _Logger:
    def debug(self, *a, **k): pass
    def info(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def error(self, *a, **k): pass


class _Map:
    def __init__(self, villages, my_location=BBM_001):
        self.villages = villages
        self.my_location = list(my_location)

    def get_dist(self, ext_loc):
        return math.sqrt((self.my_location[0] - ext_loc[0]) ** 2
                         + (self.my_location[1] - ext_loc[1]) ** 2)


def _manager(scan, shared, world=None):
    class _FM:
        @staticmethod
        def list_directory(directory, ends_with=None):
            return ["%s.json" % vid for vid in shared] if "villages" in directory else []

        @staticmethod
        def load_json_file(path, **k):
            return shared.get(os.path.basename(path).replace(".json", ""))

    attack_mod.FileManager = _FM
    man = ConquestManager.__new__(ConquestManager)
    man.village_id = "41123"
    man.map = _Map(scan)
    man.config = {"server": {"server": "br143", "endpoint": "https://x/game.php"}}
    man.logger = _Logger()
    man.world_villages = world
    return man


def _entrada(x, y, points=900, owner="0", name="local"):
    return {"id": "x", "name": name, "location": [x, y],
            "points": points, "owner": owner}


def test_mundo_descobre_alvo_que_nenhuma_fonte_local_conhece():
    """
    O ponto inteiro da feature: `40382` nao esta no scan nem no
    `cache/villages`, e mesmo assim tem que virar candidato.
    """
    man = _manager(scan={}, shared={}, world=_world(VILLAGE_TXT))
    pool = man._candidate_pool([BBM_001, BBM_023], max_radius=50)
    assert OESTE in pool
    assert pool[OESTE]["points"] == 979
    assert pool[OESTE]["owner"] == "0"


def test_scan_vivo_vence_o_mundo():
    """
    Precedencia de POSSE: o scan e a unica fonte deste ciclo e pode
    contradizer as outras duas nos dois sentidos.
    """
    scan = {PERTO: _entrada(570, 293, points=1234, owner="0", name="do scan")}
    man = _manager(scan=scan, shared={}, world=_world(VILLAGE_TXT))
    pool = man._candidate_pool([BBM_001], max_radius=50)
    assert pool[PERTO]["name"] == "do scan"
    assert pool[PERTO]["points"] == 1234


def test_cache_local_vence_o_mundo_nos_campos_descritivos():
    """
    `cache/villages` tem campos que o village.txt nao publica (tribo, scout,
    buildings), entao ele entra por cima -- menos em posse, ver abaixo.
    """
    shared = {PERTO: _entrada(570, 293, points=1001, owner="0", name="do cache")}
    man = _manager(scan={}, shared=shared, world=_world(VILLAGE_TXT))
    pool = man._candidate_pool([BBM_001], max_radius=50)
    assert pool[PERTO]["name"] == "do cache"


def test_barbara_fantasma_do_cache_local_perde_para_o_mundo():
    """
    A MEDICAO QUE INVERTEU O DESENHO (20/09/2026). Cruzando as 851 entradas do
    `cache/villages` com o village.txt do mesmo instante:

        cache diz BARBARA e o mundo diz JOGADOR .... 38
        cache diz JOGADOR e o mundo diz BARBARA ....  0

    38 a 0 nao e empate: barbara virar aldeia de jogador e o que conquista faz,
    e o cache local nao fica sabendo -- as 38 entradas tinham 20,6 dias. Se o
    cache ganhasse em posse, essas 38 continuariam elegiveis e o bot mandaria
    nobre contra aldeia de gente. E o incidente da 8.7 por outra porta.

    `34331` e uma das 38, verbatim nas duas fontes.
    """
    shared = {FANTASMA: _entrada(605, 334, points=900, owner="0")}
    man = _manager(scan={}, shared=shared, world=_world(VILLAGE_TXT))
    pool = man._candidate_pool([BBM_001], max_radius=50)
    assert pool[FANTASMA]["owner"] == "919935540"    # o dono real, do mundo
    assert pool[FANTASMA]["points"] == 3284


def test_alvo_fora_da_caixa_de_coordenadas_nao_entra():
    """
    O recorte por caixa roda ANTES de qualquer pontuacao, e e ele que segura o
    custo: sem ele o laco de find_target() iria de ~851 para 130.937 iteracoes
    por ciclo. Medido em 20/09/2026 com raio 50 e as 30 aldeias gerenciadas: o
    pool fica em 4.097 e o find_target() inteiro em 0,39 s.
    """
    man = _manager(scan={}, shared={}, world=_world(VILLAGE_TXT))
    pool = man._candidate_pool([BBM_001], max_radius=20)
    assert PERTO in pool            # 570|293, dentro da caixa
    assert "2" not in pool          # 600|423, o K46 la longe
    assert "3" not in pool          # 489|470


def test_sem_max_radius_a_fonte_fica_de_fora_inteira():
    """
    Sem raio nao ha recorte seguro, e entrar com 130 mil e pior que nao
    entrar. Falha fechada, nao aberta.
    """
    man = _manager(scan={}, shared={}, world=_world(VILLAGE_TXT))
    assert man._candidate_pool([BBM_001], max_radius=None) == {}


def test_caminho_historico_de_uma_aldeia_so_nao_muda():
    """Sem reach_from o pool continua sendo so o scan, byte por byte."""
    scan = {PERTO: _entrada(570, 293)}
    man = _manager(scan=scan, shared={"x": _entrada(1, 1)},
                   world=_world(VILLAGE_TXT))
    assert man._candidate_pool(None) is scan


def test_sem_world_villages_o_pool_volta_a_ter_duas_fontes():
    """
    `world_villages=None` e o caminho dos testes antigos e de quem desliga a
    feature: o pool tem que se comportar exatamente como antes da Feature 36.
    """
    shared = {PERTO: _entrada(570, 293)}
    man = _manager(scan={}, shared=shared, world=None)
    pool = man._candidate_pool([BBM_001], max_radius=50)
    assert set(pool) == {PERTO}


if __name__ == "__main__":
    testes = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in testes:
        t()
        print("ok  %s" % t.__name__)
    print("\n%d testes, todos verdes" % len(testes))
