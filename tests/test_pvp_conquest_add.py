"""
Cadastro de operacao PvP pelo painel (PvpConquestReader.add).

Regressao de 2026-09-20: o formulario gravava o texto digitado direto como
nome de arquivo. Coordenadas ("557|293") estouravam
`OSError: [Errno 22] Invalid argument` no `open()` -- 500 na cara do usuario,
nada escrito, e a operacao inteira perdida (os nobres tiveram que sair na
mao). O resolvedor de identificador ja existia ao lado, usado so pela
conquista barbara.

Sem rede e sem estado de jogo: os dois diretorios (cache/villages e
cache/pvp_conquest) sao redirecionados para um tmpdir.
Roda sozinho, sem pytest:  python tests/test_pvp_conquest_add.py
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from webmanager import utils
from webmanager.utils import PvpConquestReader

checks = 0


def check(cond, msg):
    global checks
    checks += 1
    if not cond:
        raise AssertionError(msg)


def expect_error(fn, fragment, msg):
    try:
        fn()
    except ValueError as e:
        check(fragment in str(e), "%s -- mensagem inesperada: %s" % (msg, e))
        return
    raise AssertionError("%s -- nenhum ValueError levantado" % msg)


tmp = tempfile.mkdtemp(prefix="twb_pvp_add_")
villages_dir = os.path.join(tmp, "villages")
pvp_dir = os.path.join(tmp, "pvp_conquest")
os.makedirs(villages_dir)
os.makedirs(pvp_dir)

# Aldeia real do br143, a mesma que quebrou o cadastro.
with open(os.path.join(villages_dir, "44167.json"), "w", encoding="utf-8") as f:
    json.dump({
        "id": "44167", "name": "JULIET", "location": [557, 293],
        "points": 1017, "owner": "919832469", "tribe": "0",
    }, f)

utils.villages_cache_dir = lambda: villages_dir
PvpConquestReader._dir = staticmethod(lambda: pvp_dir)

ARRIVAL = "2026-09-21 14:30:00"

try:
    # 1. Coordenadas resolvem para o ID do jogo, e e o ID que vira arquivo.
    vid = PvpConquestReader.add("557|293", ARRIVAL)
    check(vid == "44167", "coordenada devia resolver para #44167, veio %r" % vid)
    check(
        os.listdir(pvp_dir) == ["44167.json"],
        "arquivo devia se chamar 44167.json, veio %r" % os.listdir(pvp_dir),
    )
    with open(os.path.join(pvp_dir, "44167.json"), encoding="utf-8") as f:
        data = json.load(f)
    check(data["target_id"] == "44167", "target_id gravado errado: %r" % data["target_id"])
    check(data["target_name"] == "JULIET", "nome do alvo nao foi resolvido: %r" % data)
    check(data["target_location"] == [557, 293], "location nao gravada: %r" % data)
    check(data["status"] == "pending_scout", "status inicial errado: %r" % data["status"])

    # 2. Alvo duplicado e recusado sem sobrescrever o registro existente.
    expect_error(
        lambda: PvpConquestReader.add("44167", ARRIVAL),
        "Já existe uma operação",
        "duplicata devia ser recusada",
    )

    # 3. Os outros separadores de coordenada que o resolvedor aceita.
    os.remove(os.path.join(pvp_dir, "44167.json"))
    for ident in ("557,293", "557 293", "  557|293  ", "44167"):
        check(
            PvpConquestReader.add(ident, ARRIVAL) == "44167",
            "identificador %r devia resolver para 44167" % ident,
        )
        os.remove(os.path.join(pvp_dir, "44167.json"))

    # 4. Recusas: nada e escrito em disco em nenhuma delas.
    expect_error(
        lambda: PvpConquestReader.add("", ARRIVAL),
        "Informe um ID",
        "identificador vazio devia ser recusado",
    )
    expect_error(
        lambda: PvpConquestReader.add("aldeia do fulano", ARRIVAL),
        "Formato inválido",
        "texto livre devia ser recusado",
    )
    expect_error(
        lambda: PvpConquestReader.add("999|999", ARRIVAL),
        "Nenhuma aldeia encontrada",
        "coordenada fora do cache devia ser recusada",
    )
    expect_error(
        lambda: PvpConquestReader.add("99999", ARRIVAL),
        "não encontrada no cache local",
        "ID fora do cache devia ser recusado",
    )
    # Data invalida levantava nada: `add` devolvia False e a rota ignorava.
    expect_error(
        lambda: PvpConquestReader.add("44167", ""),
        "Chegada desejada inválida",
        "chegada vazia devia ser recusada",
    )
    expect_error(
        lambda: PvpConquestReader.add("44167", "21/09/2026 14:30"),
        "Chegada desejada inválida",
        "formato de data errado devia ser recusado",
    )
    check(
        os.listdir(pvp_dir) == [],
        "nenhuma recusa podia escrever em disco, sobrou %r" % os.listdir(pvp_dir),
    )
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("OK - %d checks" % checks)
