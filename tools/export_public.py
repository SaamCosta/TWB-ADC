"""
Exporta a arvore publica do bot (a que os testadores instalam) a partir deste
repositorio de desenvolvimento.

Por que existe (2026-11-02): este repositorio e o diario de desenvolvimento de
UMA conta. `docs/backend.md`, o CLAUDE.md, as skills, as capturas do painel, as
docstrings e as fixtures citam o mundo, o nome do jogador e as aldeias da conta
centenas de vezes -- e isso liga a conta a um bot, o que da banimento. O repo
publico e outro: so o que um testador precisa para instalar e rodar, sem
historico, com a identidade da conta trocada por valores neutros.

A anonimizacao acontece AQUI, na exportacao, e nao no repo de desenvolvimento:
o repo dev segue dizendo o nome real das aldeias (coerente com os docs), e
codigo novo que cite uma aldeia sai anonimizado sem ninguem lembrar. A
identidade NAO fica escrita neste arquivo: vem de `cache/export_identity.json`
(fora do git, como todo o `cache/`), semeado na primeira execucao a partir do
`config.json` e do `cache/`. Termo extra (tribo, apelido) entra a mao em
`extra_terms` desse arquivo.

Tres travas, todas antes de tocar no destino:
  1. lista de INCLUSAO, nao de exclusao: so arquivo rastreado pelo git e
     dentro de `INCLUDE` sai. Diretorio novo na raiz nao vaza sozinho;
  2. varredura final de cada arquivo exportado (texto e binario, conteudo e
     caminho) atras de cada termo da identidade e dos tokens de sessao
     originais. Um acerto aborta a exportacao inteira;
  3. `--test` roda a suite (`tests/test_*.py`) DENTRO da arvore exportada, sem
     `config.json` e sem `cache/`: e a prova de que a instalacao limpa
     funciona, e de que a troca de nomes nao quebrou teste nenhum.

Uso:
    python tools/export_public.py                       # monta e confere, nao grava
    python tools/export_public.py --test                # idem, rodando a suite
    python tools/export_public.py --out ../TWB-public --test --apply

O destino tem que estar vazio, nao existir, ou ser uma exportacao anterior
(tem `twb.py`); o conteudo dele e trocado, menos o `.git`. Commit e push no
repo publico ficam com quem chama.

Risco residual, de proposito: coordenadas e ids de aldeia ficam como estao (as
fixtures sao recortes verbatim e os testes medem distancia). Sem o nome do
mundo, cruzar isso exige baixar o `village.txt` de cada mundo e comparar.
"""
import argparse
import fnmatch
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IDENTITY_FILE = os.path.join(ROOT, "cache", "export_identity.json")

INCLUDE = [
    "core", "game", "pages", "templates", "tests", "webmanager", "readme",
    "twb.py", "manager.py", "new_world_setup.py",
    "config.example.json", "requirements.txt", "installer.bat", "start.bat",
    "README.md", "ConfigReadme.md", "CHANGELOG.md", "LICENSE.md", ".gitignore",
]
# Dentro do que foi incluido: os smoke vao a rede com a conta (ou abrem
# processo de verdade), e o test_feature_map importa tools/, que nao sai.
EXCLUDE = ["tests/smoke_*", "tests/test_feature_map.py"]

TEXT_EXT = {".py", ".html", ".json", ".txt", ".md", ".js", ".css", ".bat",
            ".gitignore", ".cfg", ".ini", ".toml", ".yml", ".yaml", ".csv"}

PUBLIC_WORLD = "br999"
PUBLIC_PLAYER = "jogador_teste"
PUBLIC_PLAYER_ID = "9000001"
PUBLIC_PREFIX = "Vila"

# Tokens de sessao do jogo em fixtures: `h=` de formulario/link e o `csrf` do
# game_data. Vencem com a sessao, mas nao tem por que sair.
TOKEN_RES = [
    re.compile(r"((?:[?&]|&amp;)h=)([0-9a-f]{8})(?![0-9a-f])"),
    re.compile(r'("csrf"\s*:\s*")([0-9a-f]{8})(")'),
]
GENERIC_GUARDS = [
    (re.compile(r"[A-Za-z]:\\+Users\\+", re.I), "caminho local de usuario"),
]


def git_files():
    out = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    return [p for p in out.decode("utf-8").split("\0") if p]


def selected(path):
    if not any(path == inc or path.startswith(inc + "/") for inc in INCLUDE):
        return False
    return not any(fnmatch.fnmatch(path, pat) for pat in EXCLUDE)


def _find_player():
    """(id, nome) do `game_data` guardado em algum JSON do cache, ou (None, None)."""
    pat = re.compile(r'"player"\s*:\s*\{\s*"id"\s*:\s*"?(\d+)"?\s*,\s*"name"\s*:\s*"([^"]+)"')
    for path in glob.glob(os.path.join(ROOT, "cache", "**", "*.json"), recursive=True):
        try:
            if os.path.getsize(path) > 20_000_000:
                continue
            with open(path, encoding="utf-8", errors="ignore") as f:
                m = pat.search(f.read())
        except OSError:
            continue
        if m:
            return m.group(1), m.group(2)
    return None, None


def derive_identity():
    ident = {"world": None, "player_id": None, "player_name": None,
             "village_prefix": None, "extra_terms": []}
    try:
        with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as f:
            ident["world"] = (json.load(f).get("server") or {}).get("server")
    except (OSError, ValueError):
        pass
    names = []
    for path in glob.glob(os.path.join(ROOT, "cache", "managed", "*.json")):
        try:
            with open(path, encoding="utf-8") as f:
                name = json.load(f).get("name")
        except (OSError, ValueError):
            continue
        if name:
            names.append(name)
    firsts = {n.split()[0] for n in names if " " in n}
    if len(firsts) == 1:
        ident["village_prefix"] = firsts.pop()
    ident["player_id"], ident["player_name"] = _find_player()
    return ident


def load_identity():
    """Le `cache/export_identity.json`, completando o que faltar com o derivado."""
    ident = {}
    if os.path.exists(IDENTITY_FILE):
        with open(IDENTITY_FILE, encoding="utf-8") as f:
            ident = json.load(f)
    derived = derive_identity()
    changed = not os.path.exists(IDENTITY_FILE)
    for key, value in derived.items():
        if ident.get(key) in (None, "") and value not in (None, ""):
            ident[key] = value
            changed = True
    ident.setdefault("extra_terms", [])
    if changed:
        os.makedirs(os.path.dirname(IDENTITY_FILE), exist_ok=True)
        with open(IDENTITY_FILE, "w", encoding="utf-8") as f:
            json.dump(ident, f, ensure_ascii=False, indent=2)
    missing = [k for k in ("world", "player_name", "player_id", "village_prefix")
               if not ident.get(k)]
    if missing:
        sys.exit(f"identidade incompleta ({', '.join(missing)}): preencher "
                 f"{os.path.relpath(IDENTITY_FILE, ROOT)} a mao")
    return ident


def build_rules(ident):
    """Lista de (regex, troca, rotulo); o rotulo e o que a trava procura depois."""
    rules = [
        (re.compile(r"(?<![A-Za-z0-9])" + re.escape(ident["world"]) + r"(?![0-9])", re.I),
         PUBLIC_WORLD, "mundo"),
        (re.compile(r"(?<!\w)" + re.escape(ident["player_name"]) + r"(?!\w)"),
         PUBLIC_PLAYER, "jogador"),
        (re.compile(r"(?<!\d)" + re.escape(str(ident["player_id"])) + r"(?!\d)"),
         PUBLIC_PLAYER_ID, "id do jogador"),
        (re.compile(r"(?<![A-Za-z0-9])" + re.escape(ident["village_prefix"]) + r"(?![A-Za-z0-9])"),
         PUBLIC_PREFIX, "prefixo de aldeia"),
    ]
    for item in ident.get("extra_terms") or []:
        rules.append((re.compile(re.escape(item["term"])), item["replacement"], "termo extra"))
    return rules


def fake_token(value):
    return hashlib.sha1(("twb-export:" + value).encode()).hexdigest()[:8]


def transform(text, rules, tokens):
    # Troca literal do VALOR, em qualquer lugar: o mesmo token aparece na
    # fixture e na constante do teste que confere o parse (`CSRF = "..."`).
    for tok in tokens:
        text = text.replace(tok, fake_token(tok))
    for rx, new, _ in rules:
        text = rx.sub(new, text)
    return text


def is_text(path):
    base = os.path.basename(path)
    return os.path.splitext(base)[1].lower() in TEXT_EXT or base in (".gitignore",)


def collect_tokens(files):
    tokens = set()
    for rel in files:
        if not is_text(rel) or not os.path.isfile(os.path.join(ROOT, rel)):
            continue
        with open(os.path.join(ROOT, rel), encoding="utf-8", newline="") as f:
            text = f.read()
        for rx in TOKEN_RES:
            tokens.update(m.group(2) for m in rx.finditer(text))
    return tokens


def build_tree(dest, rules):
    files = [p for p in git_files() if selected(p)]
    seen_tokens = collect_tokens(files)
    for rel in files:
        src = os.path.join(ROOT, rel)
        if not os.path.isfile(src):          # apagado no disco, ainda no indice
            continue
        out_rel = rel
        for rx, new, _ in rules:
            out_rel = rx.sub(new, out_rel)
        dst = os.path.join(dest, out_rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if is_text(rel):
            with open(src, encoding="utf-8", newline="") as f:
                text = f.read()
            with open(dst, "w", encoding="utf-8", newline="") as f:
                f.write(transform(text, rules, seen_tokens))
        else:
            shutil.copyfile(src, dst)
    return len(files), seen_tokens


def guard(dest, rules, seen_tokens):
    """Procura cada termo original na arvore pronta. Devolve a lista de acertos."""
    hits = []
    for dirpath, _, names in os.walk(dest):
        if ".git" in dirpath.split(os.sep):
            continue
        for name in names:
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, dest).replace(os.sep, "/")
            for rx, _, label in rules:
                if rx.search(rel):
                    hits.append((rel, 0, label + " no caminho"))
            with open(path, "rb") as f:
                raw = f.read()
            if is_text(rel):
                text = raw.decode("utf-8", errors="replace")
                for lineno, line in enumerate(text.splitlines(), 1):
                    for rx, _, label in rules:
                        if rx.search(line):
                            hits.append((rel, lineno, label))
                    for rx, label in GENERIC_GUARDS:
                        if rx.search(line):
                            hits.append((rel, lineno, label))
                    for tok in seen_tokens:
                        if tok in line:
                            hits.append((rel, lineno, "token de sessao"))
            else:
                text = raw.decode("latin-1")
                for rx, _, label in rules[:2]:   # mundo e jogador; o resto da falso positivo em binario
                    if rx.search(text):
                        hits.append((rel, 0, label + " (binario)"))
    return hits


def run_tests(dest):
    tests = sorted(glob.glob(os.path.join(dest, "tests", "test_*.py")))
    failed = []
    for path in tests:
        rel = os.path.relpath(path, dest)
        try:
            proc = subprocess.run([sys.executable, rel], cwd=dest, capture_output=True,
                                  text=True, encoding="utf-8", errors="replace", timeout=600)
            code, tail = proc.returncode, (proc.stdout + proc.stderr)[-1500:]
        except subprocess.TimeoutExpired:
            code, tail = "timeout", ""
        if code != 0:
            failed.append((rel, code, tail))
    return len(tests), failed


def replace_dest(src, out):
    if os.path.exists(out):
        entries = [e for e in os.listdir(out) if e != ".git"]
        if entries and not os.path.exists(os.path.join(out, "twb.py")):
            sys.exit(f"{out} nao esta vazio e nao parece uma exportacao anterior (sem twb.py)")
        for e in entries:
            p = os.path.join(out, e)
            shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
    else:
        os.makedirs(out)
    for e in os.listdir(src):
        s, d = os.path.join(src, e), os.path.join(out, e)
        shutil.copytree(s, d) if os.path.isdir(s) else shutil.copyfile(s, d)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=os.path.join(os.path.dirname(ROOT), "TWB-ADC-public"))
    ap.add_argument("--test", action="store_true", help="roda tests/test_*.py na arvore exportada")
    ap.add_argument("--apply", action="store_true", help="grava no destino (sem isso, so confere)")
    ap.add_argument("--keep", action="store_true", help="nao apaga a arvore temporaria (depuracao)")
    args = ap.parse_args()

    rules = build_rules(load_identity())
    tmp = tempfile.mkdtemp(prefix="twb-export-")
    if args.keep:
        print(f"arvore mantida em {tmp}")
    try:
        count, tokens = build_tree(tmp, rules)
        print(f"{count} arquivos montados em {tmp} ({len(tokens)} tokens de sessao trocados)")
        hits = guard(tmp, rules, tokens)
        if hits:
            for rel, lineno, label in hits[:60]:
                print(f"  VAZA {rel}:{lineno}: {label}")
            sys.exit(f"exportacao abortada: {len(hits)} acerto(s) da trava")
        print("trava: nenhum termo da identidade na arvore exportada")
        if args.test:
            total, failed = run_tests(tmp)
            for rel, code, tail in failed:
                print(f"  FALHOU {rel} (codigo {code})\n{tail}\n")
            if failed:
                sys.exit(f"exportacao abortada: {len(failed)} de {total} testes falharam na arvore limpa")
            print(f"suite: {total} de {total} testes passam na arvore limpa")
        if args.apply:
            replace_dest(tmp, args.out)
            print(f"gravado em {args.out}")
        else:
            print("nada gravado (use --apply)")
    finally:
        if not args.keep:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
