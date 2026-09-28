"""
Trava curta entre processos para um arquivo de estado compartilhado.

Motivação (A26-12, `docs/backend.md` §8.32): `cache/hunter/schedules.json` é
escrito pelo bot (Hunter, planejador de conquista) e pelo webmanager (criar e
apagar schedule), que são processos diferentes. Cada um fazia "lê, muda, grava
tudo" sem trava, então a gravação de um desfazia a do outro.

Esta trava protege só o **trecho curto** de reler, mesclar e gravar. Ela não
deve ser segurada durante espera longa (o Hunter dorme até 120 s dentro da
janela de envio), senão o painel congelaria. Quem dorme precisa reler o disco
na hora de gravar e mesclar as próprias mudanças por cima, em vez de gravar a
cópia que carregou antes de dormir.

Reaproveita as primitivas de `core.instance_lock` (byte 0 de um arquivo
`.lock` ao lado, travado pelo SO, que solta sozinho se o processo morrer).

Política de falha, a mesma de `InstanceLock`: se a trava não sair dentro de
`timeout`, ou der erro de I/O, o bloco roda **sem** ela e `held` fica False. A
trava é uma proteção; não pode ser o motivo de um nobre não sair.
"""

import logging
import os
import time
from contextlib import contextmanager

from core.instance_lock import LockBusy, _lock_first_byte, _unlock_first_byte

logger = logging.getLogger("FileLock")


class _LockState:
    def __init__(self, path):
        self.path = path
        self.held = False


@contextmanager
def file_lock(path, timeout=10.0, poll=0.05):
    """
    Trava exclusiva em `<path>.lock`. Uso:

        with file_lock(caminho_do_json) as lock:
            ... reler, mesclar, gravar ...
            # lock.held diz se a trava foi de fato obtida

    Não é reentrante: não aninhar duas travas do mesmo arquivo no mesmo fluxo.
    """
    state = _LockState(os.path.abspath(path) + ".lock")
    fd = None
    try:
        os.makedirs(os.path.dirname(state.path), exist_ok=True)
        fd = os.open(state.path, os.O_RDWR | os.O_CREAT, 0o644)
        deadline = time.monotonic() + timeout
        while True:
            try:
                _lock_first_byte(fd)
                state.held = True
                break
            except LockBusy:
                if time.monotonic() >= deadline:
                    logger.warning(
                        "Trava de %s ocupada por mais de %.1f s -- seguindo sem ela",
                        state.path, timeout
                    )
                    break
                time.sleep(poll)
    except OSError as exc:
        logger.warning("Trava de %s indisponivel (%s) -- seguindo sem ela",
                       state.path, exc)

    try:
        yield state
    finally:
        if fd is not None:
            if state.held:
                try:
                    _unlock_first_byte(fd)
                except OSError:
                    pass
            try:
                os.close(fd)
            except OSError:
                pass
