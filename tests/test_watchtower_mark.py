"""
Marca da torre de vigia nos ataques recebidos (docs/backend.md §9 item 30):
`Extractor.watchtower_mark` / os campos `watchtower`, `size` e `tower_noble`
de `Extractor.incoming_commands`, e o uso deles na defesa própria
(`core.own_defense.assess`, `window_units_cap`, `noble_nukes(max_units=)`).

Fixtures: as duas linhas verbatim do widget de comandos da visão geral, do
br143, capturadas com `tools/capture_watchtower_mark.py`:
  - `watchtower_mark_pending_br143.html`: BBM 064 (88035), 03/11 13:15, um
    ataque que a torre da BBM 002 ainda NÃO viu (`commandicon-wt`);
  - `watchtower_mark_detected_br143.html`: BBM 011 (74690), 03/11 20:12, um
    nobre sozinho de jogador amigo, que a torre já viu ("Ataque pequeno
    (1-1000 tropas)" + "Com nobre").
Só o rótulo (nome da aldeia de origem, de terceiro) foi trocado por
"Aldeia A"/"Aldeia B". O resto, `src` da CDN inclusive, é o que o servidor
mandou: o `src` é a âncora do parser.

Guarda provada: a mesma regex não acha marca nenhuma na linha de antes nem nas
linhas do fixture de 2026-10-11 (sem torre), e o caso do nobre sozinho só
deixa de pedir apoio por causa do teto da torre.

Rodar: python tests/test_watchtower_mark.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import own_defense
from core.extractors import Extractor

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return fh.read()


PENDING = _fixture("watchtower_mark_pending_br143.html")
DETECTED = _fixture("watchtower_mark_detected_br143.html")
NO_TOWER = _fixture("own_defense_village_overview_br143.html")


def _check(label, got, expected):
    assert got == expected, f"{label}: esperado {expected!r}, veio {got!r}"
    print(f"  ok  {label}: {got!r}")


def _sim():
    from game.simulator import Simulator
    return Simulator().simulate


def test_linha_antes_da_deteccao():
    print("test_linha_antes_da_deteccao")
    (row,) = Extractor.incoming_commands(PENDING)
    _check("id", row["command_id"], "1460840129")
    _check("tipo", row["command_type"], "attack")
    _check("chegada", row["arrival_at"], 1794319332)
    _check("torre vai ver", row["watchtower"], "pending")
    _check("tamanho ainda não", row["size"], None)
    _check("nobre ainda não", row["tower_noble"], None)


def test_linha_detectada():
    print("test_linha_detectada")
    (row,) = Extractor.incoming_commands(DETECTED)
    _check("id", row["command_id"], "1439754061")
    _check("tipo continua ataque", row["command_type"], "attack")
    _check("rótulo", row["origin"], "Aldeia B")
    _check("torre viu", row["watchtower"], "detected")
    _check("pequeno", row["size"], "small")
    _check("com nobre", row["tower_noble"], True)


def test_sem_torre():
    print("test_sem_torre")
    rows = Extractor.incoming_commands(NO_TOWER)
    _check("o fixture de 11/10 tem ataques", len(rows) > 0, True)
    _check("nenhum com marca", {r["watchtower"] for r in rows}, {None})
    _check("nem tamanho", {r["size"] for r in rows}, {None})
    _check("bloco inválido", Extractor.watchtower_mark(None),
           {"watchtower": None, "size": None, "tower_noble": None})


def test_detectado_sem_nobre_deduzido():
    print("test_detectado_sem_nobre_deduzido")
    # Derivada da linha verbatim tirando o span do nobre: ainda NÃO vista no
    # servidor (ver TRUST_TOWER_NO_NOBLE).
    start = DETECTED.index('</span><span class=" tooltip"') + len("</span>")
    end = DETECTED.index("</span>", DETECTED.index("snob.webp")) + len("</span>")
    no_noble = DETECTED[:start] + DETECTED[end:]
    _check("sem o ícone", "snob.webp" in no_noble, False)
    (row,) = Extractor.incoming_commands(no_noble)
    _check("detectado", row["watchtower"], "detected")
    _check("sem nobre", row["tower_noble"], False)
    medium = DETECTED.replace("attack_small.webp", "attack_medium.webp")
    _check("médio", Extractor.incoming_commands(medium)[0]["size"], "medium")


def _attack(cid, arrival, dist, **tower):
    return dict({"command_id": cid, "arrival_at": arrival,
                 "origin": {"x": 500 + dist, "y": 500}}, **tower)


SPEEDS = {"spear": 18.0, "sword": 22.0, "axe": 18.0, "spy": 9.0, "light": 10.0,
          "heavy": 11.0, "ram": 30.0, "catapult": 30.0, "knight": 10.0, "snob": 35.0}
NOW = 1793748000
VILLAGE = {"vid": "1", "name": "x", "x": 500, "y": 500, "loyalty": 100}


def test_assess_usa_o_nobre_da_torre():
    print("test_assess_usa_o_nobre_da_torre")
    # 100 campos: fora do alcance de 70, a física diz "não é nobre".
    far = _attack("1", NOW + 3600, 100, watchtower="detected", size="small", tower_noble=True)
    row = own_defense.assess(VILLAGE, [far], SPEEDS, 70, (20, 35), NOW)["attacks"][0]
    _check("torre com nobre vence a distância", row["noble_possible"], True)
    near = _attack("2", NOW + 3600, 3, watchtower="detected", size="small", tower_noble=False)
    row = own_defense.assess(VILLAGE, [near], SPEEDS, 70, (20, 35), NOW)["attacks"][0]
    _check("sem nobre desligado por padrão", own_defense.TRUST_TOWER_NO_NOBLE, False)
    _check("sem nobre ainda não descarta", row["noble_possible"], True)
    own_defense.TRUST_TOWER_NO_NOBLE = True
    try:
        row = own_defense.assess(VILLAGE, [near], SPEEDS, 70, (20, 35), NOW)["attacks"][0]
        _check("ligado, descarta", row["noble_possible"], False)
    finally:
        own_defense.TRUST_TOWER_NO_NOBLE = False


def test_teto_da_janela():
    print("test_teto_da_janela")
    loyalty_25 = dict(VILLAGE, loyalty=25)  # 1 nobre toma: todos entram na janela

    def cap(*attacks):
        verdict = own_defense.assess(loyalty_25, list(attacks), SPEEDS, 70, (20, 35), NOW)
        return own_defense.window_units_cap(verdict)

    small = dict(watchtower="detected", size="small", tower_noble=True)
    medium = dict(watchtower="detected", size="medium", tower_noble=True)
    _check("só pequenos", cap(_attack("1", NOW + 3600, 3, **small)), 1000)
    _check("o maior manda", cap(_attack("1", NOW + 3600, 3, **small),
                                _attack("2", NOW + 7200, 5, **medium)), 5000)
    _check("grande não tem teto", cap(_attack("1", NOW + 3600, 3, watchtower="detected",
                                              size="large", tower_noble=True)), None)
    _check("um sem marca derruba o teto", cap(_attack("1", NOW + 3600, 3, **small),
                                              _attack("2", NOW + 7200, 5)), None)
    _check("pendente também", cap(_attack("1", NOW + 3600, 3, watchtower="pending")), None)
    _check("sem janela, sem teto", own_defense.window_units_cap({"attacks": []}), None)


def test_composicoes_cabem_no_tamanho():
    print("test_composicoes_cabem_no_tamanho")
    full = own_defense.noble_nukes()
    capped = own_defense.noble_nukes(max_units=1000)
    for name, troops in capped.items():
        units = sum(q for u, q in troops.items() if u != "snob")
        _check("%s cabe em 1.000 tropas" % name, 900 < units <= 1000, True)
        _check("%s leva o nobre" % name, troops["snob"], 1)
    pop = own_defense._pop({u: q for u, q in capped["cavalaria"].items() if u != "snob"})
    _check("mil tropas de cavalaria (leve 4, aríete 5) pesam ~4.000", 3800 < pop <= 4200, True)
    _check("teto acima da fazenda não muda nada",
           own_defense.noble_nukes(max_units=10 ** 6), full)


def test_nobre_sozinho_nao_pede_o_teto_cheio():
    print("test_nobre_sozinho_nao_pede_o_teto_cheio")
    # O caso de 03/11: um nobre pequeno contra uma aldeia com defesa modesta.
    sim = _sim()
    defense = {"spear": 3000, "sword": 3000}
    _check("sem a torre, o teto cheio pede apoio", own_defense.assess_defense(
        defense, 14, sim, own_defense.noble_nukes())["holds"], False)
    _check("com a torre (pequeno), já segura", own_defense.assess_defense(
        defense, 14, sim, own_defense.noble_nukes(max_units=1000))["holds"], True)


if __name__ == "__main__":
    test_linha_antes_da_deteccao()
    test_linha_detectada()
    test_sem_torre()
    test_detectado_sem_nobre_deduzido()
    test_assess_usa_o_nobre_da_torre()
    test_teto_da_janela()
    test_composicoes_cabem_no_tamanho()
    test_nobre_sozinho_nao_pede_o_teto_cheio()
    print("\nOK - todos os testes da marca da torre passaram")
