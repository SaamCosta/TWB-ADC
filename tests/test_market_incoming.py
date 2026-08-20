"""
Testes da guarda do bloco "recursos a caminho" do mercado.

  ResourceManager._parse_incoming_resources(html)

O parser em si (INCOMING_RE) ja tinha sido corrigido no P1-14: o regex original
ancorava no literal holandes "Aankomend:" e nunca casava no servidor pt-BR,
entao `resource_incoming` ficava sempre {} e o bot criava oferta duplicada para
recurso que ja estava a caminho, gastando mercadores a toa.

Junto veio uma guarda para separar duas hipoteses que antes se confundiam num
DEBUG so: "nao ha nada a caminho" (normal) e "o rotulo esta la mas a estrutura
mudou" (precisa de acao). A guarda procurava o rotulo solto na pagina -- e
"Chegando" tambem e o nome de um item do MENU de navegacao, presente em toda
tela de mercado. Resultado, medido em 2026-08-20: WARNING em todo ciclo sem
nada a caminho, mais um dump de 58 KB. Uma guarda sempre ligada nao distingue
nada, e mascararia a mudanca de estrutura que ela existe para detectar.

Rodar: python tests/test_market_incoming.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game.resources import ResourceManager

# --- verbatim: o item de menu presente em toda tela de mercado do br143 ----
MENU = (
    '<td class="menu-column-item"><a href="/game.php?village=41114&amp;'
    'screen=overview_villages&amp;mode=incomings">Chegando</a></td></tr>'
)

# --- estrutura real de um bloco com recurso a caminho ----------------------
COM_RECURSO = (
    'Chegando: <span class="icon header wood"></span>1.234 '
    '<span class="icon header stone"></span>567 '
)


class _Man(ResourceManager):
    def __init__(self):
        self.avisos = []
        self.dumps = []
        self.logger = self

    # captura em vez de logar/gravar
    def warning(self, *a, **k):
        self.avisos.append(a)

    def debug(self, *a, **k):
        pass

    def _dump_response(self, path, content, overwrite=False):
        self.dumps.append(path)


def test_menu_sozinho_nao_dispara_o_aviso():
    """
    O caso que motivou a correcao: pagina normal, nada a caminho, e o rotulo
    aparecendo so como item de menu.
    """
    man = _Man()
    assert man._parse_incoming_resources(MENU) == {}
    assert man.avisos == [], "guarda disparou no item de menu"
    assert man.dumps == [], "gravou dump de 58 KB a toa"


def test_pagina_sem_o_rotulo_nao_dispara():
    man = _Man()
    assert man._parse_incoming_resources("<html>nada aqui</html>") == {}
    assert man.avisos == []


def test_rotulo_com_dois_pontos_mas_estrutura_quebrada_dispara():
    """
    O caso que a guarda existe para pegar: o rotulo real esta la (com ':'),
    mas o que vem depois nao casa mais.
    """
    man = _Man()
    assert man._parse_incoming_resources("Chegando: <div>markup novo</div>") == {}
    assert len(man.avisos) == 1, "a guarda tem que disparar aqui"
    assert man.dumps, "e guardar a pagina para diagnostico"


def test_menu_junto_com_bloco_real_quebrado_ainda_dispara():
    """O menu nao pode silenciar a deteccao quando ha problema de verdade."""
    man = _Man()
    man._parse_incoming_resources(MENU + "Chegando: <div>markup novo</div>")
    assert len(man.avisos) == 1


def test_bloco_valido_e_lido_e_nao_avisa():
    man = _Man()
    resultado = man._parse_incoming_resources(MENU + COM_RECURSO)
    assert resultado, "o bloco valido tem que ser lido"
    assert man.avisos == []


def test_outros_idiomas_seguem_cobertos():
    for rotulo in ("Aankomend", "Incoming", "Ankommend"):
        man = _Man()
        man._parse_incoming_resources(f"{rotulo}: <div>markup novo</div>")
        assert len(man.avisos) == 1, rotulo


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
