"""
core/templates.py::resolve_troop_template -- escolha da receita de tropa
conforme o mundo tenha ou nao arqueiro.

Motivo de existir: os quatro arquivos de receita ja existiam (bded867), mas
qual deles cada perfil usa era string literal no config.json, apontando para a
variante sem arqueiro. Levar essa config para um mundo COM arqueiro produziria
um imperio inteiro construindo lanceiro e espadachim -- sem erro, sem log, so
menos defesa. O filtro de unidades desativadas nao pega isso: ele so remove
unidade que o mundo nao tem, nunca acrescenta.

O teste toca o disco de proposito: a funcao resolve por existencia de arquivo,
e o ponto e justamente casar com os arquivos que estao em templates/troops/.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.filemanager import FileManager
from core.templates import resolve_troop_template


def _existe(nome):
    return FileManager.path_exists(
        FileManager.get_path(f"templates/troops/{nome}.txt")
    )


def test_papel_resolve_para_a_variante_do_mundo():
    """O caso central: "def"/"off" viram o arquivo certo dos dois lados."""
    assert resolve_troop_template("def", True) == "def_archer"
    assert resolve_troop_template("def", False) == "def_no_archer"
    assert resolve_troop_template("off", True) == "off_archer"
    assert resolve_troop_template("off", False) == "off_no_archer"


def test_os_quatro_arquivos_resolvidos_existem():
    """
    A funcao so promete o que o disco entrega. Se alguem renomear um dos
    quatro arquivos, este teste cai antes do bot rodar um ciclo -- e sem ele a
    falha seria silenciosa: resolve_troop_template devolveria o nome do papel
    ("def"), get_template nao acharia def.txt e a aldeia so nao recrutaria.
    """
    for papel in ("def", "off"):
        for arqueiro in (True, False):
            assert _existe(resolve_troop_template(papel, arqueiro))


def test_nome_sem_variante_passa_intacto():
    """
    watchtower_support e cavalaria pesada pura. Medido em 2026-08-20 via
    interface.php?func=get_unit_info, a pesada tem atributos IDENTICOS em
    br143 e br144 (speed 11, def 200/80/180, pop 6) -- a unica diferenca entre
    os dois mundos e o espadachim (defense_cavalry 25 -> 15). Entao esta
    receita e portavel verbatim e nao deve ganhar sufixo nenhum.
    """
    assert resolve_troop_template("watchtower_support", True) == "watchtower_support"
    assert resolve_troop_template("watchtower_support", False) == "watchtower_support"
    assert resolve_troop_template("basic", True) == "basic"
    assert resolve_troop_template("basic", False) == "basic"


def test_nome_ja_literal_nao_e_resolvido_duas_vezes():
    """
    Compatibilidade com toda config que ja existe: uma aldeia com
    "units": "def_no_archer" gravado continua usando esse arquivo. Sem esta
    regra, "def_no_archer" num mundo com arqueiro procuraria
    "def_no_archer_archer.txt".

    Nota do que este teste NAO garante: a aldeia legada tambem nao vai MUDAR
    de variante sozinha. Isso e deliberado -- um nome literal e uma escolha
    explicita de quem escreveu -- mas significa que migrar um mundo existente
    para a resolucao automatica exige trocar a string para o papel.
    """
    for nome in ("def_no_archer", "def_archer", "off_no_archer", "off_archer"):
        assert resolve_troop_template(nome, True) == nome
        assert resolve_troop_template(nome, False) == nome


def test_valor_vazio_nao_estoura():
    """
    units_get_template() chama isto depois do fallback, entao na pratica o
    nome nunca e vazio -- mas devolver None em vez de "None_archer" e a
    degradacao certa se esse caminho mudar.
    """
    assert resolve_troop_template(None, True) is None
    assert resolve_troop_template("", False) == ""


if __name__ == "__main__":
    for nome, fn in sorted(list(globals().items())):
        if nome.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {nome}")
    print("\ntodos os testes passaram")
