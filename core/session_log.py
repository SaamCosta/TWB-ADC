"""
O log da sessão anterior sobrevive ao reinício (§8.89.5).

O `twb.py` abre `cache/logs/session_latest.log` com `open(..., "w")` ao subir,
e isso apagava a sessão anterior inteira. Em 05/11 o bot parou às 23:56 sem
deixar falha no log do Windows, e a causa se perdeu porque o usuário religou
na manhã de 07/11. O usuário desliga o bot toda noite, então isso acontecia
todo dia: a fase seguinte só tinha o log do dia corrente.

`rotate()` renomeia o log anterior para `session_prev_<início>.log` antes do
`open`. `<início>` é a hora da primeira linha do log, que é quando aquela
sessão começou, e não a hora do reinício. Ficam os `KEEP` mais novos. A limpeza
só olha o prefixo `session_prev_`: os logs nomeados à mão
(`session_20261005_1850_campanha.log`) não são tocados.

Só roda sob `__main__`, depois da trava de instância única: um segundo bot
recusado não pode girar o log do que está rodando (20º padrão). Nunca impede o
bot de subir: qualquer erro devolve None e o `open(..., "w")` segue como antes.

Só stdlib: é importado antes do tee, como o `core/instance_lock`.
"""
import os
import re
import shutil
import time

LATEST = "session_latest.log"
PREFIX = "session_prev_"
KEEP = 10
# "2026-11-07 06:59:14 - root - INFO - ..." (o formato do logging do twb.py).
_FIRST_LINE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})")


def session_start(path):
    """Epoch da primeira linha com data do log, ou o mtime se não houver."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(4096).replace(b"\x00", b"").decode("utf-8", "replace")
        for line in head.splitlines():
            m = _FIRST_LINE_RE.match(line)
            if m:
                return time.mktime(tuple(int(g) for g in m.groups()) + (0, 0, -1))
        return os.path.getmtime(path)
    except (OSError, ValueError, OverflowError):
        return None


def rotate(log_dir, keep=KEEP):
    """
    Guarda o `session_latest.log` como `session_prev_<início>.log` e apaga os
    `session_prev_*` além dos `keep` mais novos. Devolve o caminho guardado,
    ou None (sem log, log vazio ou erro).
    """
    try:
        latest = os.path.join(log_dir, LATEST)
        if not os.path.exists(latest) or os.path.getsize(latest) == 0:
            return None
        start = session_start(latest)
        stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(start if start is not None else time.time()))
        target = os.path.join(log_dir, "%s%s.log" % (PREFIX, stamp))
        n = 1
        while os.path.exists(target):
            target = os.path.join(log_dir, "%s%s_%d.log" % (PREFIX, stamp, n))
            n += 1
        try:
            os.replace(latest, target)
        except OSError:
            # No Windows, o painel lendo o arquivo nessa hora impede renomear;
            # a cópia basta, porque o `open(..., "w")` vem em seguida.
            shutil.copyfile(latest, target)
        prev = sorted(f for f in os.listdir(log_dir) if f.startswith(PREFIX) and f.endswith(".log"))
        for old in prev[:-keep] if keep > 0 else prev:
            try:
                os.remove(os.path.join(log_dir, old))
            except OSError:
                pass
        return target
    except Exception:  # noqa: BLE001 -- guardar o log nunca impede o bot de subir
        return None
