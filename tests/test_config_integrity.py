"""
Integridade da config: toda chave que o codigo LE precisa estar declarada, e
toda chave declarada precisa estar documentada.

MOTIVACAO. O CLAUDE.md tem tres regras sobre isso e nada as verificava:

  1. "Toda chave lida por aldeia tem que existir em `village_template`."
     O template e o que documenta o que e configuravel por aldeia, e e a fonte
     de add_village() e do merge por build.version -- uma chave fora dele e
     invisivel para quem le a config e nasce ausente em toda aldeia nova.
  2. "Ao adicionar config nova, atualizar config.example.json e
     webmanager/helpfile.py no mesmo commit."
  3. O merge por build.version usa o template como base e so preserva chave que
     exista NOS DOIS, entao chave que so existe no config.json vivo some.

Uma chave lida mas nao declarada nao levanta: get_config() loga um WARNING e
devolve o default, e o bot roda "normal" com a feature desligada em silencio --
o decimo sexto padrao do CLAUDE.md descreve exatamente esse sintoma mudo.

O parser e AST, nao regex: as chamadas reais quebram em varias linhas e um
grep de uma linha so perde a maioria delas.

Rodar: python tests/test_config_integrity.py
"""
import ast
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


def _literal(node):
    """Valor de um no AST se for string literal, senao None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def collect_calls():
    """
    Varre os .py do projeto e devolve:
      global_reads  {(section, parameter): [arquivo:linha]}
      village_reads {parameter: [arquivo:linha]}

    So considera chamadas cujos argumentos sao literais -- chamada com variavel
    nao da para resolver estaticamente e e ignorada de proposito.
    """
    global_reads, village_reads = {}, {}
    skip = os.path.join(ROOT, "tests") + os.sep
    for path in glob.glob(os.path.join(ROOT, "**", "*.py"), recursive=True):
        if path.startswith(skip) or os.sep + "cache" + os.sep in path:
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=path)
        except (SyntaxError, UnicodeDecodeError):
            continue
        rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fname = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            where = f"{rel}:{node.lineno}"

            if fname == "get_config":
                kw = {k.arg: k.value for k in node.keywords}
                section = _literal(kw.get("section"))
                param = _literal(kw.get("parameter"))
                if section is None and len(node.args) >= 1:
                    section = _literal(node.args[0])
                if param is None and len(node.args) >= 2:
                    param = _literal(node.args[1])
                if section and param:
                    global_reads.setdefault((section, param), []).append(where)

            elif fname == "get_village_config":
                kw = {k.arg: k.value for k in node.keywords}
                param = _literal(kw.get("parameter"))
                if param is None and len(node.args) >= 2:
                    param = _literal(node.args[1])
                if param:
                    village_reads.setdefault(param, []).append(where)
    return global_reads, village_reads


with open(os.path.join(ROOT, "config.example.json"), encoding="utf-8") as fh:
    EXAMPLE = json.load(fh)
with open(os.path.join(ROOT, "webmanager", "helpfile.py"), encoding="utf-8") as fh:
    HELP_SRC = fh.read()

GLOBAL_READS, VILLAGE_READS = collect_calls()

# Chaves que o bot ESCREVE em runtime (auto-deteccao) em vez de exigir do
# usuario. Continuam precisando existir no exemplo -- estao aqui so para
# documentar por que o valor de fabrica e null.
AUTODETECTED = {
    ("world", "flags_enabled"), ("world", "knight_enabled"),
    ("world", "boosters_enabled"), ("world", "quests_enabled"),
    ("world", "archers_enabled"), ("world", "premium_account"),
}


def test_every_global_key_read_exists_in_example():
    for (section, param), where in sorted(GLOBAL_READS.items()):
        check(section in EXAMPLE,
              f"config.example.json nao tem a secao '{section}' "
              f"(lida em {where[0]})")
        if section in EXAMPLE and isinstance(EXAMPLE[section], dict):
            check(param in EXAMPLE[section],
                  f"config.example.json: '{section}.{param}' e lido em "
                  f"{', '.join(where)} mas nao existe no exemplo -- "
                  f"get_config vai logar WARNING e cair no default em silencio")


def test_every_village_key_read_exists_in_village_template():
    template = EXAMPLE.get("village_template", {})
    check(bool(template), "config.example.json nao tem village_template")
    for param, where in sorted(VILLAGE_READS.items()):
        check(param in template,
              f"village_template nao tem '{param}', lido por aldeia em "
              f"{', '.join(where)} -- a chave fica invisivel na config e nasce "
              f"ausente em toda aldeia nova (regra do CLAUDE.md)")


def test_every_example_key_is_documented_in_helpfile():
    """
    helpfile.py alimenta a UI de config do webmanager. Chave sem entrada
    aparece la sem explicacao nenhuma.
    """
    ignore_sections = {"build", "villages", "village_template", "profile_templates"}
    for section, block in EXAMPLE.items():
        if section in ignore_sections or not isinstance(block, dict):
            continue
        for key in block:
            needle = f"'{section}.{key}'"
            check(needle in HELP_SRC,
                  f"webmanager/helpfile.py nao documenta '{section}.{key}' "
                  f"(esta em config.example.json)")


def test_example_and_template_agree_on_shared_village_keys():
    """
    Chave que existe nas duas pontas nao pode divergir de TIPO -- o merge
    copia o valor do config.json vivo por cima do template, entao um tipo
    diferente vira bug silencioso.
    """
    template = EXAMPLE.get("village_template", {})
    for vid, vdata in (EXAMPLE.get("villages") or {}).items():
        if not isinstance(vdata, dict):
            continue
        for key, value in vdata.items():
            if key not in template:
                failures.append(
                    f"aldeia de exemplo {vid} tem '{key}', ausente em "
                    f"village_template")
                continue
            tval = template[key]
            if tval is None or value is None:
                continue
            check(type(tval) is type(value),
                  f"'{key}': village_template tem {type(tval).__name__} e a "
                  f"aldeia de exemplo {vid} tem {type(value).__name__}")


def test_build_version_is_a_string_and_parseable():
    """
    twb.py compara build.version por != entre config e template. Um numero
    solto (3.9 em vez de "3.9") compara diferente de string e o merge dispara
    ou nao dispara pelo motivo errado.
    """
    v = EXAMPLE.get("build", {}).get("version")
    check(isinstance(v, str), f"build.version deveria ser string, e {type(v).__name__}")
    if isinstance(v, str):
        try:
            float(v)
        except ValueError:
            failures.append(f"build.version {v!r} nao e numerico")


def test_no_section_read_that_does_not_exist():
    sections = {s for s, _ in GLOBAL_READS}
    for s in sorted(sections):
        check(s in EXAMPLE, f"secao '{s}' e lida no codigo mas nao existe no exemplo")


for fn in [
    test_every_global_key_read_exists_in_example,
    test_every_village_key_read_exists_in_village_template,
    test_every_example_key_is_documented_in_helpfile,
    test_example_and_template_agree_on_shared_village_keys,
    test_build_version_is_a_string_and_parseable,
    test_no_section_read_that_does_not_exist,
]:
    fn()

print(f"chaves globais lidas: {len(GLOBAL_READS)}   "
      f"chaves por aldeia lidas: {len(VILLAGE_READS)}")

if failures:
    print(f"FALHOU ({len(failures)} problema(s)):")
    for f in sorted(set(failures)):
        print("  -", f)
    sys.exit(1)
print("OK: config declarada, lida e documentada estao de acordo")
