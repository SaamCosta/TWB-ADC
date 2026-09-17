"""
Teste da area de interesse da conquista barbara.

  ConquestManager._prefer_area_of_interest()

Por que existe: `priority: "fill_gaps"` pontua com 60% de peso na distancia
MEDIA do alvo a todas as aldeias gerenciadas, ou seja, elege o que esta mais
ao centro do proprio cluster. Isso adensa o miolo e nunca escolhe a fronteira
-- e o que a tribo pediu no forum do br143 (SQUAD 02, 16/09/2026) e o oposto:
crescer para o norte, para dentro do K25.

Numeros reais da conta em 16/09/2026, que os testes abaixo usam como fixture:
o centroide das 28 aldeias fica em ~(577|308); a barbara 49709 (572|295) esta
na fronteira norte e a 40374x (fixture no miolo) esta colada no centroide. Sem
a area, a segunda ganha sempre.

A regra e preferencia e nao filtro por causa da redacao do proprio post:
"nao quero jogador crescendo para fora da regiao ENQUANTO AINDA TIVERMOS BBs e
alvos disponiveis dentro da nossa area". Area esgotada libera o resto; um
filtro duro deixaria o bot parado.

Rodar: python tests/test_conquest_area_of_interest.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game.attack import ConquestManager


class _Logger:
    def __init__(self):
        self.info_calls = 0

    def debug(self, *a, **k): pass
    def info(self, *a, **k): self.info_calls += 1
    def warning(self, *a, **k): pass
    def error(self, *a, **k): pass


def _man():
    man = ConquestManager.__new__(ConquestManager)
    man.village_id = "41123"
    man.logger = _Logger()
    return man


# Area escolhida em 16/09/2026: faixa sul do K25 + metade do K26.
AREA = {"enabled": True, "x_min": 500, "x_max": 650, "y_min": 270, "y_max": 299}

FRONTEIRA = ("49709", 0.80, [572, 295])   # dentro da area, score pior
MIOLO     = ("44620", 0.12, [586, 308])   # fora da area, score melhor
LONGE     = ("41733", 0.95, [552, 297])   # dentro da area, score pior ainda


def test_dentro_da_area_ganha_mesmo_com_score_pior():
    """
    O caso que motivou tudo: o fill_gaps prefere o miolo (0.12) a fronteira
    (0.80), e e exatamente essa preferencia que o squad proibiu.
    """
    out = _man()._prefer_area_of_interest([MIOLO, FRONTEIRA], {"area_of_interest": AREA})
    assert out == [FRONTEIRA]


def test_ranking_dentro_da_area_continua_sendo_o_fill_gaps():
    """
    A area diz PARA QUE LADO crescer, nao qual alvo. Dentro dela o score
    original e preservado, e e ele que produz o "expandir gradativamente" do
    post: a borda mais proxima do cluster tem distancia media menor.
    """
    out = _man()._prefer_area_of_interest(
        [LONGE, MIOLO, FRONTEIRA], {"area_of_interest": AREA}
    )
    assert out == [LONGE, FRONTEIRA]
    assert min(out, key=lambda c: c[1]) == FRONTEIRA


def test_area_vazia_libera_os_de_fora():
    """
    "enquanto ainda tivermos BBs disponiveis dentro da nossa area" -- esgotada
    a area, o bot volta a expandir em vez de ficar parado.
    """
    man = _man()
    out = man._prefer_area_of_interest([MIOLO], {"area_of_interest": AREA})
    assert out == [MIOLO]
    assert man.logger.info_calls == 1  # o fallback e anunciado, nao silencioso


def test_desligada_nao_altera_nada():
    desligada = {"enabled": False, "x_min": 500, "x_max": 650,
                 "y_min": 270, "y_max": 299}
    entrada = [MIOLO, FRONTEIRA]
    assert _man()._prefer_area_of_interest(entrada, {"area_of_interest": desligada}) is entrada


def test_config_ausente_nao_altera_nada():
    """Conta que nunca configurou a area continua no comportamento antigo."""
    entrada = [MIOLO, FRONTEIRA]
    assert _man()._prefer_area_of_interest(entrada, {}) is entrada


def test_bordas_sao_inclusivas():
    """
    y_max=299 tem que incluir a linha 299: e a divisa K25/K35, onde estao as
    barbaras mais proximas do cluster (a 025 da conta fica em 571|299).
    """
    borda_y = ("x", 0.5, [600, 299])
    borda_x = ("y", 0.5, [650, 270])
    fora_por_um = ("z", 0.5, [651, 270])
    out = _man()._prefer_area_of_interest(
        [borda_y, borda_x, fora_por_um], {"area_of_interest": AREA}
    )
    assert out == [borda_y, borda_x]


def test_area_quebrada_nao_derruba_a_conquista():
    """
    Config editada na mao com chave faltando: seguir sem a area vale mais que
    parar de noblar. So nao pode ser em silencio.
    """
    man = _man()
    entrada = [MIOLO, FRONTEIRA]
    assert man._prefer_area_of_interest(
        entrada, {"area_of_interest": {"enabled": True, "x_min": 500}}
    ) is entrada


def test_lista_vazia_passa_direto():
    assert _man()._prefer_area_of_interest([], {"area_of_interest": AREA}) == []


# --------------------------------------------------------------------------
# A area de verdade, contra o cache real de aldeias
# --------------------------------------------------------------------------

def test_area_configurada_cobre_as_barbaras_do_squad():
    """
    Le cache/villages e config.json (so leitura) e exige que a caixa gravada
    realmente selecione barbaras. Uma caixa com os eixos trocados, ou apontada
    para o hemisferio errado, passa em todos os testes sinteticos acima e
    seleciona ZERO alvos em campo -- que e o decimo quinto padrao do CLAUDE.md
    (guarda que nunca dispara) virado do avesso.
    """
    import glob
    import json

    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(raiz, "config.json"), encoding="utf-8") as f:
        area = json.load(f)["conquest"]["area_of_interest"]
    if not area.get("enabled"):
        return  # desligada de proposito, nada a exigir

    candidatos = []
    for caminho in glob.glob(os.path.join(raiz, "cache", "villages", "*.json")):
        try:
            with open(caminho, encoding="utf-8") as f:
                v = json.load(f)
        except (OSError, ValueError):
            continue
        loc = v.get("location")
        if not loc or len(loc) != 2 or str(v.get("owner", "0")) != "0":
            continue
        vid = os.path.basename(caminho)[:-5]
        candidatos.append((vid, 0.5, [int(loc[0]), int(loc[1])]))

    if not candidatos:
        return  # cache ainda nao populado; nada a exigir

    dentro = _man()._prefer_area_of_interest(candidatos, {"area_of_interest": area})
    assert dentro is not candidatos, (
        "a area gravada em config.json nao selecionou NENHUMA das %d barbaras "
        "do cache -- caixa errada" % len(candidatos)
    )
    print("     (%d de %d barbaras do cache caem na area)" % (len(dentro), len(candidatos)))


# --------------------------------------------------------------------------
# O que o painel mostra (webmanager)
# --------------------------------------------------------------------------

def _reader(area, villages):
    """ConquestReader com um cache/villages de mentira, em disco temporário."""
    import json
    import tempfile
    sys.path.insert(0, os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "webmanager"))
    from webmanager.utils import ConquestReader

    tmp = tempfile.mkdtemp()
    for vid, (x, y, owner, pts) in villages.items():
        with open(os.path.join(tmp, "%s.json" % vid), "w", encoding="utf-8") as f:
            json.dump({"location": [x, y], "owner": owner, "points": pts}, f)
    ConquestReader._villages_dir = staticmethod(lambda: tmp)
    cfg = {"conquest": {"area_of_interest": area, "min_points": 100,
                        "max_points": 1100, "max_radius": 30}}
    return ConquestReader.area_of_interest(cfg)


ALDEIAS = {
    "1": (572, 295, "0", 856),    # bárbara dentro
    "2": (568, 294, "0", 951),    # bárbara dentro
    "3": (586, 308, "0", 700),    # bárbara fora (miolo, ao sul)
    "4": (570, 293, "5555", 900),  # dentro mas tem dono
    "5": (571, 294, "0", 50),     # dentro mas abaixo de min_points
    "6": (573, 296, "0", 5000),   # dentro mas acima de max_points
}


def test_painel_conta_so_barbara_elegivel_dentro_da_area():
    """
    A contagem é o que separa uma caixa certa de uma caixa com os eixos
    trocados -- as duas são idênticas olhando só os números. Dono e pontos
    entram porque são os mesmos filtros que find_target() aplica.
    """
    out = _reader(AREA, ALDEIAS)
    assert out["enabled"] is True and out["usable"] is True
    assert out["label"] == "500–650 | 270–299"
    assert out["inside"] == 2     # só a 1 e a 2
    assert out["total"] == 3      # elegíveis no geral: 1, 2 e 3


def test_painel_com_area_desligada():
    out = _reader({"enabled": False}, ALDEIAS)
    assert out["enabled"] is False
    assert out["inside"] == 0


def test_painel_com_area_quebrada_nao_explode():
    """
    Config editada na mão com chave faltando: a página tem que dizer isso, não
    dar erro 500 nem fingir que a área está valendo.
    """
    out = _reader({"enabled": True, "x_min": 500}, ALDEIAS)
    assert out["enabled"] is True
    assert out["usable"] is False
    assert out["label"] is None


def test_pagina_de_conquista_mostra_a_area():
    """
    A área governa a escolha de alvo, mas só aparecia na tela de configuração
    -- a página que descreve a seleção não a mencionava. Guarda contra ela
    sumir de novo numa reescrita do template.
    """
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, raiz)
    sys.path.insert(0, os.path.join(raiz, "webmanager"))
    import webmanager.server as srv

    srv.app.jinja_env.auto_reload = True
    srv.app.jinja_env.cache = {}
    html = srv.app.test_client().get("/conquest").get_data(as_text=True)
    assert 'id="area-de-interesse"' in html
    assert "Área de interesse" in html
    # E o link de configurar tem que apontar para uma âncora que existe.
    import re
    m = re.search(r'href="/config#([^"]+)"', html)
    assert m, "o painel da área perdeu o link para a configuração"
    cfg_html = srv.app.test_client().get("/config").get_data(as_text=True)
    assert ('id="%s"' % m.group(1)) in cfg_html, (
        "o link aponta para a âncora #%s, que não existe na página de config"
        % m.group(1)
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
