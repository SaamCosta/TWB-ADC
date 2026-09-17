"""
Testes das regras do nobre lidas do mundo.

  WorldConfig._parse_snob()               -- bloco <snob> do get_config
  WorldConfig.noble_max_distance()        -- alcance maximo, em campos
  WorldConfig.barbarian_conquest_allowed()
  ConquestManager._effective_radius()     -- raio limitado pelo alcance real

Por que existe: `ConquestManager.MAX_RADIUS` era 100, chumbado, herdado do bot
base, e nao corresponde a regra de mundo nenhuma. O br143 limita o nobre a 70
campos, e o numero estava publicado de graca em
`interface.php?func=get_config` -- endpoint publico, sem autenticacao, que este
mesmo modulo ja baixava e cujo bloco <snob> jogava fora.

Configurar `conquest.max_radius` acima do alcance real elegeria alvos que o
jogo recusa NO ENVIO, ou seja, no fim do caminho: depois de escolher alvo,
montar escolta, sondar duracao e agendar no Hunter. E a mesma classe de erro do
<archer> em 2026-08-17 -- o dado estava na resposta que o bot ja tinha em maos.

O XML abaixo e recorte VERBATIM do br143, lido em 17/09/2026. Fixture de markup
se copia do servidor, nao se inventa (CLAUDE.md).

Rodar: python tests/test_world_snob_limits.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.world_config import WorldConfig


# Recorte verbatim de https://br143.tribalwars.com.br/interface.php?func=get_config
# (17/09/2026). `no_barb_conquer` vem VAZIA neste mundo -- e o caso que
# distingue "desligado" de "ligado", e o que quase me fez tratar a presenca da
# tag como o valor dela.
BR143 = """<config>
<speed>1</speed>
<unit_speed>1</unit_speed>
<snob>
<gold>1</gold>
<auto_minting>1</auto_minting>
<cheap_rebuild>0</cheap_rebuild>
<rise>2</rise>
<max_dist>70</max_dist>
<factor>1</factor>
<coin_wood>28000</coin_wood>
<coin_stone>30000</coin_stone>
<coin_iron>25000</coin_iron>
<no_barb_conquer/>
</snob>
</config>"""


def test_le_o_alcance_real_do_br143():
    snob = WorldConfig._parse_snob(BR143)
    assert snob["max_dist"] == 70


def test_tag_vazia_nao_conta_como_ligada():
    """
    `<no_barb_conquer/>` sem conteudo e o caso do br143 e significa DESLIGADO.
    Um parser que olhasse so a presenca da tag concluiria que o mundo proibe
    conquistar barbara -- e desligaria a Feature 8 inteira num mundo onde ela
    e permitida, sem erro nenhum, so parando de agir.
    """
    snob = WorldConfig._parse_snob(BR143)
    assert snob["no_barb_conquer"] is None
    assert WorldConfig.barbarian_conquest_allowed({"snob": snob}) is True


def test_mundo_que_proibe_barbara():
    xml = "<config><snob><max_dist>50</max_dist>" \
          "<no_barb_conquer>1</no_barb_conquer></snob></config>"
    assert WorldConfig.barbarian_conquest_allowed(
        {"snob": WorldConfig._parse_snob(xml)}) is False


def test_zero_significa_sem_limite_e_nao_zero_campos():
    """
    0 em max_dist e "sem limite", nao "alcance zero". Tratar literalmente
    faria o raio efetivo virar 0 e NENHUM alvo passar no filtro -- o bot
    pararia de conquistar sem uma linha de erro.
    """
    xml = "<config><snob><max_dist>0</max_dist></snob></config>"
    assert WorldConfig.noble_max_distance(
        {"snob": WorldConfig._parse_snob(xml)}) is None


def test_mundo_sem_o_bloco_devolve_desconhecido():
    xml = "<config><game><archer>0</archer></game></config>"
    snob = WorldConfig._parse_snob(xml)
    assert snob == {"max_dist": None, "no_barb_conquer": None}
    assert WorldConfig.noble_max_distance({"snob": snob}) is None
    assert WorldConfig.noble_max_distance({}) is None


# --------------------------------------------------------------------------
# _effective_radius
# --------------------------------------------------------------------------

class _Logger:
    def __init__(self):
        self.avisos = 0

    def debug(self, *a, **k): pass
    def info(self, *a, **k): pass
    def warning(self, *a, **k): self.avisos += 1
    def error(self, *a, **k): pass


def _manager(world_limit):
    """ConquestManager cru, com o alcance do mundo controlado (sem rede)."""
    import core.world_config as wc_mod
    import game.attack as attack_mod
    from game.attack import ConquestManager

    class _WC:
        @staticmethod
        def get(server=None, endpoint=None, force_refresh=False):
            return {"snob": {"max_dist": world_limit}}
        noble_max_distance = staticmethod(wc_mod.WorldConfig.noble_max_distance)

    attack_mod.WorldConfig = _WC
    man = ConquestManager.__new__(ConquestManager)
    man.config = {"server": {"server": "br143", "endpoint": "https://x/game.php"}}
    man.logger = _Logger()
    return man


def test_raio_e_cortado_pelo_alcance_do_mundo():
    man = _manager(70)
    assert man._effective_radius({"max_radius": 100}) == 70
    assert man.logger.avisos == 1, "cortar em silencio esconde config errada"


def test_config_menor_que_o_limite_e_respeitada():
    """
    O limite do mundo e um TETO, nao um alvo: 30 e escolha do operador e
    continua valendo."""
    man = _manager(70)
    assert man._effective_radius({"max_radius": 30}) == 30
    assert man.logger.avisos == 0


def test_mundo_desconhecido_cai_no_teto_antigo():
    from game.attack import ConquestManager
    man = _manager(None)
    assert man._effective_radius({"max_radius": 100}) == ConquestManager.MAX_RADIUS


def test_filtro_e_pontuacao_usam_o_mesmo_raio():
    """
    find_target() filtra por raio e _score_target() normaliza a distancia por
    ele. Se os dois lerem numeros diferentes, a pontuacao passa a se referir a
    um raio que a selecao nao usa -- e o sintoma seria so um ranking
    silenciosamente errado.
    """
    import ast
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(raiz, "game", "attack.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name not in ("find_target", "_score_target"):
            continue
        corpo = ast.get_source_segment(src, node) or ""
        assert "_effective_radius" in corpo, (
            "%s nao usa _effective_radius" % node.name
        )
        assert "self.MAX_RADIUS" not in corpo, (
            "%s voltou a aplicar MAX_RADIUS direto, ignorando o alcance real "
            "do nobre neste mundo" % node.name
        )


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
