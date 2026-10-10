"""
Rotulo humano de aldeia propria: `BBM 022 (40618)`.

Log, aviso de Telegram e painel mostravam so o id das aldeias da conta, e quem
le tem que decorar 40 numeros para saber de onde saiu um nobre. Este modulo e
o lugar unico que traduz id em `nome (id)`.

Fontes do nome, nesta ordem:
1. `register()`, chamado por `Village.village_init()` toda vez que le o
   `game_data` -- e o nome atual do jogo, inclusive depois de renomear.
2. `cache/managed/<id>.json` (`name`), gravado por `Village.set_cache_vars()`.
   Cobre o processo recem-subido, em que a aldeia ainda nao rodou, e o
   webmanager, que nao roda aldeia nenhuma.

Sem nome conhecido o rotulo e o proprio id: aldeia de outro jogador ou barbara
nao tem arquivo em `cache/managed`, e o rotulo nunca inventa nome. Para alvo,
ver `conquest_label()` em game/attack.py.
"""
import json
import os
import time

# Absoluto: o webmanager nao garante cwd na raiz do repo (twb.py faz chdir).
MANAGED_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache", "managed"
)
# Quanto tempo um id sem nome espera antes de reler o disco. Uma aldeia
# conquistada agora ganha arquivo no primeiro ciclo dela; sem a releitura o
# processo mostraria so o id dela ate reiniciar.
MISS_RETRY_SECONDS = 600

_names = {}
_misses = {}


def register(village_id, name):
    """Grava o nome lido do jogo. Nome vazio nao apaga o que ja se sabe."""
    if village_id is None or not name:
        return
    vid = str(village_id)
    _names[vid] = str(name)
    _misses.pop(vid, None)


def _load_from_cache(vid):
    path = os.path.join(MANAGED_DIR, "%s.json" % vid)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    name = data.get("name") if isinstance(data, dict) else None
    return str(name) if name else None


def village_name(village_id):
    """Nome da aldeia propria, ou None se nao for conhecida."""
    if village_id is None:
        return None
    vid = str(village_id)
    if vid in _names:
        return _names[vid]
    missed_at = _misses.get(vid)
    if missed_at is not None and time.time() - missed_at < MISS_RETRY_SECONDS:
        return None
    name = _load_from_cache(vid)
    if name:
        _names[vid] = name
        _misses.pop(vid, None)
        return name
    _misses[vid] = time.time()
    return None


def village_label(village_id):
    """`BBM 022 (40618)`; so o id quando o nome nao e conhecido."""
    if village_id is None:
        return "None"
    name = village_name(village_id)
    if not name:
        return str(village_id)
    return "%s (%s)" % (name, village_id)


def village_labels(village_ids):
    """Lista de rotulos separados por virgula, na ordem recebida."""
    return ", ".join(village_label(vid) for vid in village_ids)


def reset():
    """So para teste: esquece tudo o que foi registrado ou lido."""
    _names.clear()
    _misses.clear()
