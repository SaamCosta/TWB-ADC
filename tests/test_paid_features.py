"""
Deteccao ao vivo de premium / gerente de conta / assistente de saque
(`core/paid_features.py`, docs/backend.md §8.67).

O que se protege aqui:
- so `active` booleano conta: bloco `features` ausente, recurso ausente ou
  valor nao booleano NAO desliga o modo pago (decimo quinto padrao);
- a primeira leitura do processo nao avisa; a troca ao vivo avisa uma vez;
- troca contra o estado gravado antes de um restart (venceu com o bot
  parado) avisa e diz isso; o valor do arquivo sozinho nao vale como ativo;
- desarmado e sem `path`, nao le nem grava `cache/paid_features.json`;
- o WebWrapper alimenta o detector com o `game_data` de qualquer resposta;
- `Village.paid_active` trata "nao lido" como inativo, e nunca levanta.

Fixtures: o bloco `features` com os tres ativos e verbatim de
`screen=am_village` (br143, 2026-10-18 15:35); o da conta sem nada pago e o
de 2026-10-17 citado em `Extractor.feature_active`.

Rodar: python tests/test_paid_features.py
"""
import json
import os
import shutil
import sys
import tempfile
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import paid_features as pf  # noqa: E402
from core.request import WebWrapper  # noqa: E402
from game.village import Village  # noqa: E402

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


PAID = json.loads('{"Premium":{"possible":true,"active":true},"AccountManager":'
                  '{"possible":true,"active":true},"FarmAssistent":'
                  '{"possible":true,"active":true}}')
FREE = json.loads('{"Premium": {"possible": true, "active": false}, "AccountManager":'
                  ' {"possible": false, "active": false}, "FarmAssistent": {"possible":'
                  ' true, "active": false}}')


def gd(features):
    out = {"player": {"incomings": "0"}, "screen": "overview"}
    if features is not None:
        out["features"] = features
    return out


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def detector(path=None):
    sent = []
    clock = Clock()
    return pf.PaidFeatures(path=path, clock=clock, notify=sent.append), sent, clock


def test_extract_only_counts_booleans():
    check(pf.extract(gd(PAID)) == {"Premium": True, "AccountManager": True,
                                   "FarmAssistent": True}, "bloco pago verbatim")
    check(pf.extract(gd(FREE)) == {"Premium": False, "AccountManager": False,
                                   "FarmAssistent": False}, "bloco gratis verbatim")
    check(pf.extract(gd(None)) == {}, "sem features nao e 'tudo desligado'")
    check(pf.extract({"features": {"Premium": {"active": "1"}}}) == {},
          "active nao booleano nao conta")
    check(pf.extract(None) == {} and pf.extract("lixo") == {}, "entrada ruim vira {}")


def test_first_reading_is_silent_then_live_flip_announces_once():
    d, sent, clock = detector()
    check(d.active("AccountManager") is None, "antes de ler: None")
    check(d.observe(gd(PAID)) == [], "primeira leitura nao e transicao")
    check(sent == [], "primeira leitura nao manda Telegram")
    check(d.active("AccountManager") is True, "ativo depois da leitura")
    clock.t += 60
    check(d.observe(gd(PAID)) == [] and sent == [], "mesma leitura nao avisa")
    clock.t += 60
    out = d.observe(gd(FREE))
    check(len(out) == 3 and all(v is False for _, v, _ in out), "vencimento dos tres")
    check(len(sent) == 3 and all("DESATIVADO" in s for s in sent), "um aviso por recurso")
    check(d.active("AccountManager") is False, "gerente inativo agora")
    check(d.observe(gd(FREE)) == [] and len(sent) == 3, "vencido nao repete aviso")


def test_missing_block_does_not_drop_paid_mode():
    d, sent, _ = detector()
    d.observe(gd(PAID))
    d.observe(gd(None))
    d.observe({"features": {"Premium": {"possible": True}}})
    check(d.active("Premium") is True and d.active("AccountManager") is True,
          "tela sem features derrubou o modo pago")
    check(sent == [], "falta de leitura nao e transicao")


def test_partial_block_only_touches_what_it_has():
    d, sent, _ = detector()
    d.observe(gd(PAID))
    d.observe({"features": {"FarmAssistent": {"active": False}}})
    check(d.active("FarmAssistent") is False, "assistente vencido")
    check(d.active("AccountManager") is True, "gerente nao mencionado continua ativo")
    check(len(sent) == 1, "so um aviso")


def test_restart_flip_is_detected_against_file():
    tmp = tempfile.mkdtemp()
    try:
        path = os.path.join(tmp, "paid_features.json")
        d, _, _ = detector(path)
        d.observe(gd(PAID))
        check(os.path.exists(path), "primeira leitura grava o arquivo")
        # Novo processo: o gerente venceu com o bot parado.
        # Uma tela que so traz o Premium carrega o arquivo, mas nao confirma
        # o gerente: o True gravado antes do restart nao pode valer.
        d0, _, _ = detector(path)
        d0.observe({"features": {"Premium": {"active": True}}})
        check(d0.active("AccountManager") is None,
              "valor do arquivo valeu como ativo sem leitura deste processo")
        d2, sent, _ = detector(path)
        out = d2.observe(gd(FREE))
        check(len(out) == 3 and all(o == "restart" for _, _, o in out), "origem restart")
        check(len(sent) == 3 and all("parado" in s for s in sent), "aviso diz que foi parado")
        data = pf.read(path)
        check(data["available"] and data["features"]["AccountManager"]["active"] is False,
              "arquivo atualizado")
        check(len(data["history"]) == 3, "historico com as tres trocas")
        # Mesmo estado depois do restart: sem aviso.
        d3, sent3, _ = detector(path)
        d3.observe(gd(FREE))
        check(sent3 == [] and d3.active("Premium") is False, "restart sem troca e silencioso")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_unarmed_without_path_touches_no_file():
    pf.disarm()
    d = pf.PaidFeatures(notify=lambda _t: None)
    check(d._file() is None, "desarmado sem path nao pode apontar para o cache real")
    d.observe(gd(PAID))
    check(d.active("Premium") is True, "desarmado ainda detecta em memoria")


def test_wrapper_feeds_detector_from_any_response():
    w = WebWrapper("https://x/", endpoint="https://x/")
    w.paid_features.notify = lambda _t: None
    body = '<html><script>TribalWars.updateGameData(%s);</script></html>' % json.dumps(
        dict(gd(PAID), village={"id": 32056}))
    w.post_process(SimpleNamespace(text=body, url="https://x/game.php?village=32056&screen=main",
                                   headers={"content-type": "text/html"}))
    check(w.paid_features.active("AccountManager") is True, "wrapper nao alimentou o detector")
    envelope = json.dumps({"response": {}, "game_data": gd(FREE)})
    w.post_process(SimpleNamespace(text=envelope, url="https://x/game.php?screen=api",
                                   headers={"content-type": "application/json"}))
    check(w.paid_features.active("AccountManager") is False, "envelope AJAX tambem conta")


def test_village_paid_active_defaults_to_free():
    v = Village.__new__(Village)
    v.wrapper = None
    check(v.paid_active("Premium") is False and v.premium_active() is False, "sem wrapper")
    v.wrapper = SimpleNamespace()
    check(v.paid_active("Premium") is False, "wrapper sem detector")
    d, _, _ = detector()
    v.wrapper = SimpleNamespace(paid_features=d)
    check(v.paid_active("AccountManager") is False, "nao lido conta como inativo")
    d.observe(gd(PAID))
    check(v.paid_active("AccountManager") is True and v.premium_active() is True, "lido ativo")
    v.wrapper = SimpleNamespace(paid_features=SimpleNamespace(active=lambda n: 1 / 0))
    check(v.paid_active("Premium") is False, "detector que levanta nao derruba a aldeia")


for fn in [
    test_extract_only_counts_booleans,
    test_first_reading_is_silent_then_live_flip_announces_once,
    test_missing_block_does_not_drop_paid_mode,
    test_partial_block_only_touches_what_it_has,
    test_restart_flip_is_detected_against_file,
    test_unarmed_without_path_touches_no_file,
    test_wrapper_feeds_detector_from_any_response,
    test_village_paid_active_defaults_to_free,
]:
    try:
        fn()
    except Exception as exc:
        failures.append(f"{fn.__name__} levantou {exc!r}")

if failures:
    print(f"FALHOU ({len(failures)} problema(s)):")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("OK: recursos pagos ao vivo")
