"""
A bandeira de saque paga na coleta que o BOT manda? (§8.82, §8.84)

SO-LEITURA: 1 GET da tela de coleta de uma aldeia, pelo `WebWrapper` do bot,
sem `priority_mode` (captcha por taxa da conta). NAO faz POST.

Por que existe: o registro pela tela (`TWB_GATHER_SQUAD` sem `src`) nunca
dispara em campo, porque o bot so volta a tela de coleta quando as coletas ja
voltaram. A unica leitura de uma coleta EM ANDAMENTO e esta, feita a mao.

O que ja se sabe (03/11, BBM 005, fator 1): o servidor guarda em
`scavenging_squad.carry_max` a carga das unidades, nao o valor postado (o bot
mandou 149.145 e ficou 149.120 = 1.864 x 80), e o saque = isso x
`loot_factor`. Falta o caso com fator > 1:

    1. uma aldeia com a bandeira de saque equipada (e que a ordem fixa nao
       tire: ela poe a 6 antes da 8, ver §8.84);
    2. o bot manda a coleta dali com o codigo do §8.84
       (carry_max = calcMaxLoot(unidades, fator));
    3. com a coleta em andamento:  python tools/probe_scavenge_carry.py 38997

Veredito por coleta: carry_max guardado == carga x fator -> a bandeira paga, e
`HAUL_SCAVENGE` em `core/flag_planner.py` vira True; == carga nominal com fator
> 1 -> nao paga (nem o envio do JS ganharia). O fator impresso e o de AGORA:
se a bandeira mudou depois do envio, a leitura nao vale.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.extractors import Extractor
from core.filemanager import FileManager
from core.flag_planner import calc_max_loot
from core.request import WebWrapper

vid = sys.argv[1] if len(sys.argv) > 1 else "38997"
config = FileManager.load_json_file("config.json")
wrapper = WebWrapper(config["server"]["endpoint"], server=config["server"]["server"],
                     endpoint=config["server"]["endpoint"])
wrapper.headers["user-agent"] = config["bot"]["user_agent"]
wrapper.web.cookies.update(FileManager.load_json_file("cache/session.json")["cookies"])

res = wrapper.get_url(f"game.php?village={vid}&screen=place&mode=scavenge")
if res is None:
    raise SystemExit("sem resposta")
out = f"cache/debug/scavenge_carry_{vid}.html"
with open(out, "w", encoding="utf-8") as fh:
    fh.write(res.text)
vd = Extractor.village_data(res.text)
table = Extractor.scavenge_config(res.text) or {}
if not vd:
    raise SystemExit("sem var village (login? captcha?): " + out)
factor = vd.get("unit_carry_factor")
print("unit_carry_factor agora:", factor, "| tela salva em", out)
for oid, st in sorted((vd.get("options") or {}).items()):
    sq = (st or {}).get("scavenging_squad")
    if not sq:
        print(oid, "sem coleta em andamento")
        continue
    units = {u: int(n) for u, n in sq["unit_counts"].items() if int(n)}
    nominal, with_factor = calc_max_loot(units, 1), calc_max_loot(units, factor)
    stored = int(sq.get("carry_max") or 0)
    if nominal == with_factor:
        verdict = "fator 1: nao separa"
    elif stored == with_factor:
        verdict = "PAGA a bandeira"
    elif stored == nominal:
        verdict = "NAO paga a bandeira"
    else:
        verdict = "nem um nem outro: ler a mao"
    loot = sum(int(v) for v in sq["loot_res"].values())
    lf = float((table.get(oid) or {}).get("loot_factor") or 0)
    print(oid, verdict, json.dumps({"units": units, "carry_max": stored, "nominal": nominal,
                                    "com_fator": with_factor, "loot": loot, "lf": lf,
                                    "return": sq.get("return_time"), "premium": sq.get("is_premium")}))
