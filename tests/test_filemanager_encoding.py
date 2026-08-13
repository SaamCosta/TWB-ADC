"""
Testes de encoding do FileManager para JSON.

Os dois casos abaixo aconteceram de verdade neste projeto, em maquina Windows
pt-BR (locale cp1252):

- BOM: config.json salvo com `Set-Content -Encoding utf8` (PowerShell 5.1) ou
  pelo Bloco de Notas derrubava o bot com "Expecting value: line 1 column 1".
- Acento: o webmanager grava com ensure_ascii=False e encoding="utf-8"
  ("Bárbara #NNNN"), e a leitura sem encoding declarado caia no locale.

Rodar: python tests/test_filemanager_encoding.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.filemanager import FileManager


def _escreve(nome, texto, encoding):
    """Grava em cache/ (dentro da raiz do projeto, que e o que FileManager assume)."""
    caminho = FileManager.get_path(os.path.join("cache", nome))
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, "w", encoding=encoding) as f:
        f.write(texto)
    return os.path.join("cache", nome)


def test_json_com_bom_e_lido():
    """utf-8-sig descarta o BOM em vez de tratar como lixo antes do '{'."""
    rel = _escreve("_t_bom.json", '{"conquest": {"loyalty_regen_per_hour": 1}}', "utf-8-sig")
    try:
        dados = FileManager.load_json_file(rel)
        assert dados["conquest"]["loyalty_regen_per_hour"] == 1
    finally:
        FileManager.remove_file(rel)


def test_json_sem_bom_continua_igual():
    """O caso normal nao pode ter regredido."""
    rel = _escreve("_t_sem_bom.json", '{"a": 1, "b": [2, 3]}', "utf-8")
    try:
        assert FileManager.load_json_file(rel) == {"a": 1, "b": [2, 3]}
    finally:
        FileManager.remove_file(rel)


def test_acentos_utf8_nao_viram_mojibake():
    """
    Arquivo gravado como o webmanager grava (UTF-8 real, sem escapes).
    Lido no locale cp1252, "Bárbara" viraria "BÃ¡rbara".
    """
    rel = _escreve(
        "_t_acento.json",
        json.dumps({"target_name": "Bárbara #40314"}, ensure_ascii=False),
        "utf-8",
    )
    try:
        assert FileManager.load_json_file(rel)["target_name"] == "Bárbara #40314"
    finally:
        FileManager.remove_file(rel)


def test_ida_e_volta_com_acento():
    """save_json_file -> load_json_file preserva acento mesmo sem escapes."""
    rel = os.path.join("cache", "_t_roundtrip.json")
    try:
        FileManager.save_json_file({"nome": "Aldeia Bárbara — çãé"}, rel, ensure_ascii=False)
        assert FileManager.load_json_file(rel)["nome"] == "Aldeia Bárbara — çãé"
    finally:
        FileManager.remove_file(rel)


def test_arquivo_inexistente_devolve_none():
    assert FileManager.load_json_file(os.path.join("cache", "_nao_existe_.json")) is None


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
