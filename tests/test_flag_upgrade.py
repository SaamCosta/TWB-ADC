"""
Upgrade de bandeira (DefenceManager.manage_flags / flag_upgrade), §8.54.

MOTIVACAO. Em 2026-10-05 o bot postou `upgrade_flag` 43 vezes seguidas na
BBM 037 (tipo 3, nivel 2), uma a cada ~30 s, logando "Upgraded flag 3" em
todas -- e nada subiu: em 43 "sucessos" ele nunca tentou subir o nivel 3,
que teria chegado a 3 bandeiras em no maximo tres upgrades de verdade.

Tres defeitos juntos:

1. Faltava `confirm`. O `Flags.2dbd8d.js` do br143 faz o upgrade em duas
   etapas: `confirm:!1` devolve so a previa do popup (`current_flag`,
   `upgraded_flag`), `confirm:!0` sobe e devolve as contagens novas.
2. Sucesso era "a resposta e JSON". A previa e JSON sem erro.
3. O contador de tentativas zerava a cada "sucesso" e a releitura era
   recursiva, entao a guarda do Bug 2 nunca disparava.

Bonus achado no mesmo passo: `setFlagCounts` publica STRING por nivel
(`"2"`), e o laco antigo fazia `for amount in "12"` -- 12 bandeiras liam
como "1" e "2".

O servidor falso abaixo modela as duas etapas como o JS as le. Que a
resposta SEM `confirm` seja a previa e inferencia (o JS so a manda com
`confirm:!1`); o laco de campo e consistente com ela. O teste nao depende
disso: o que ele trava e que sucesso so conta quando a contagem cai.

Rodar: python tests/test_flag_upgrade.py
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import game.defence_manager as dm_module
from game.defence_manager import DefenceManager

dm_module.time.sleep = lambda s: None

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


# Estrutura verbatim do br143 (game.php?village=55647&screen=flags,
# 2026-10-05, por cache/_probe_flag_upgrade.py): oito tipos, niveis 1 a 7,
# quantidade em STRING. A linha do `required_for_upgrade` tambem e verbatim.
REAL_SET_FLAG_COUNTS = (
    '{"1":{"1":"0","2":"0","3":"0","4":"0","5":"0","6":"0","7":"0"},'
    '"2":{"1":"0","2":"0","3":"0","4":"0","5":"0","6":"0","7":"0"},'
    '"3":{"1":"1","2":"0","3":"1","4":"1","5":"0","6":"1","7":"1"},'
    '"4":{"1":"0","2":"2","3":"2","4":"1","5":"1","6":"1","7":"1"},'
    '"5":{"1":"2","2":"0","3":"2","4":"2","5":"2","6":"1","7":"1"},'
    '"6":{"1":"2","2":"0","3":"0","4":"0","5":"0","6":"0","7":"0"},'
    '"7":{"1":"0","2":"0","3":"0","4":"0","5":"0","6":"0","7":"0"},'
    '"8":{"1":"1","2":"2","3":"1","4":"2","5":"1","6":"2","7":"1"}}'
)
REQUIRED_LINE = "FlagsScreen.required_for_upgrade = 3;"


class FakeResponse:
    def __init__(self, text):
        self.text = text


class FakeServer:
    """
    Inventario de conta com as duas etapas do upgrade. `honor_confirm=False`
    simula um servidor que nunca sobe (o pior caso: a guarda tem que parar).
    """

    def __init__(self, counts, honor_confirm=True, required=3, error=None):
        self.counts = json.loads(counts) if isinstance(counts, str) else counts
        self.honor_confirm = honor_confirm
        self.required = required
        self.error = error
        self.gets = 0
        self.posts = []
        self.last_h = "abc"

    def page(self):
        return (
            '<div id="current_flag" style="margin-top: 10px">'
            '<img src="https://x/graphic/flags/big/2_7.webp"><p>+18%% recrutamento</p></div>'
            '<script>$(function() { FlagsScreen.required_for_upgrade = %d; '
            'FlagsScreen.setFlagCounts(%s); FlagsScreen.init(); });</script>'
            % (self.required, json.dumps(self.counts))
        )

    def get_url(self, url):
        self.gets += 1
        return FakeResponse(self.page())

    def get_api_action(self, village_id, action, params=None, data=None):
        self.posts.append(dict(data or {}))
        if self.error:
            return {"error": self.error}
        t, lvl = str(data["flag_type"]), str(data["from_level"])
        if data.get("confirm") != "true" or not self.honor_confirm:
            # A previa do popup -- JSON sem erro, e nada muda.
            return {"response": {"current_flag": {"img": "x", "description": "a"},
                                 "upgraded_flag": {"img": "y", "description": "b"}}}
        n = int(self.counts[t][lvl])
        if n < self.required:
            return {"error": "Bandeiras insuficientes"}
        self.counts[t][lvl] = str(n - self.required)
        nxt = str(int(lvl) + 1)
        self.counts[t][nxt] = str(int(self.counts[t].get(nxt, "0")) + 1)
        return {"response": self.counts}


def make(server):
    d = DefenceManager(village_id="55647", wrapper=server)
    d.logger = logging.getLogger("test-flag-upgrade")
    d.manage_flags_enabled = True
    return d


def with_counts(**cells):
    """Inventario real com algumas celulas trocadas: t3_2="12"."""
    counts = json.loads(REAL_SET_FLAG_COUNTS)
    for key, value in cells.items():
        t, lvl = key[1:].split("_")
        counts[t][lvl] = value
    return counts


# --------------------------------------------------------------- o laco de 05/10

def test_upgrade_sends_confirm():
    server = FakeServer(with_counts(t3_2="3"))
    make(server).manage_flags(force=True)
    check(server.posts and all(p.get("confirm") == "true" for p in server.posts),
          f"todo upgrade_flag tem que levar confirm=true: {server.posts}")


def test_preview_answer_is_not_success_and_does_not_loop():
    """O cenario de campo: o jogo responde sem erro e nada sobe."""
    server = FakeServer(with_counts(t3_2="3"), honor_confirm=False)
    d = make(server)
    d.manage_flags(force=True)
    check(len(server.posts) == DefenceManager.FLAG_UPGRADE_MAX_ATTEMPTS,
          f"sem a contagem cair, sao {DefenceManager.FLAG_UPGRADE_MAX_ATTEMPTS} "
          f"tentativas e fim; vieram {len(server.posts)}")
    check(d._upgrade_attempts.get((3, 2)) == DefenceManager.FLAG_UPGRADE_MAX_ATTEMPTS,
          f"as tentativas falhas ficam contadas: {d._upgrade_attempts}")
    check(d._flags_fresh, "a leitura chegou ao fim, o inventario esta fresco")

    # E o proximo ciclo nao recomeca o laco.
    d.manage_flags(force=True)
    check(len(server.posts) == DefenceManager.FLAG_UPGRADE_MAX_ATTEMPTS,
          f"depois de desistir, nao posta de novo na mesma sessao: {len(server.posts)}")


def test_error_answer_does_not_cost_a_reread():
    server = FakeServer(with_counts(t3_2="3"), error="Bandeiras insuficientes")
    make(server).manage_flags(force=True)
    check(server.gets == 1,
          f"recusa explicita nao precisa de releitura: {server.gets} GETs")
    check(len(server.posts) == DefenceManager.FLAG_UPGRADE_MAX_ATTEMPTS,
          f"recusa conta tentativa: {len(server.posts)} POSTs")


# ----------------------------------------------------------- upgrade de verdade

def test_real_upgrade_cascades_upward_and_stops():
    # 7 no nivel 2 -> dois upgrades (7->4->1), nivel 3 vai de 1 a 3 -> mais um.
    server = FakeServer(with_counts(t3_2="7"))
    d = make(server)
    d.manage_flags(force=True)
    sent = [(p["flag_type"], p["from_level"]) for p in server.posts]
    check(sent == [(3, 2), (3, 2), (3, 3)],
          f"cascata esperada [(3,2),(3,2),(3,3)], veio {sent}")
    check(server.counts["3"]["2"] == "1" and server.counts["3"]["3"] == "0"
          and server.counts["3"]["4"] == "2",
          f"inventario final errado: {server.counts['3']}")
    check(d.flag_supply.get(3, {}).get(4) == 2,
          f"flag_supply tem que vir da ULTIMA leitura: {d.flag_supply.get(3)}")
    check(d._upgrade_attempts == {}, f"sucesso limpa as tentativas: {d._upgrade_attempts}")


def test_two_digit_amount_is_read_as_a_number():
    server = FakeServer(with_counts(t5_2="12"), honor_confirm=False)
    d = make(server)
    d.manage_flags(force=True)
    check(any(p["flag_type"] == 5 and p["from_level"] == 2 for p in server.posts),
          "12 bandeiras sao >= 3; o laco antigo lia '1' e '2' e nunca tentava")
    check(d.flag_supply.get(5, {}).get(2) == 12,
          f"oferta de 12 lida como {d.flag_supply.get(5, {}).get(2)}")


def test_nothing_to_upgrade_in_the_real_inventory():
    server = FakeServer(REAL_SET_FLAG_COUNTS)
    d = make(server)
    d.manage_flags(force=True)
    check(server.posts == [] and server.gets == 1,
          f"inventario real de 05/10 nao tem nivel com 3: {server.posts}, {server.gets} GETs")
    check(d._flags_fresh, "leitura sem upgrade tambem e leitura completa")


def test_top_level_is_never_upgraded():
    counts = with_counts()
    counts["3"]["9"] = "5"
    server = FakeServer(counts)
    make(server).manage_flags(force=True)
    check(server.posts == [], f"nivel {DefenceManager.FLAG_MAX_LEVEL} e o teto: {server.posts}")


def test_required_amount_comes_from_the_page():
    server = FakeServer(with_counts(t3_2="4"), required=5)
    d = make(server)
    d.manage_flags(force=True)
    check(server.posts == [], f"com required_for_upgrade=5, 4 bandeiras nao sobem: {server.posts}")
    check(d._flag_upgrade_required == 5, f"lido {d._flag_upgrade_required}")


def test_verbatim_required_line_is_parsed():
    import re
    m = re.search(r"FlagsScreen\.required_for_upgrade\s*=\s*(\d+)", REQUIRED_LINE)
    check(m and m.group(1) == "3", "a linha verbatim do br143 tem que casar")


def test_error_text_is_read_from_both_envelopes():
    err = DefenceManager._flag_upgrade_error
    check(err(None) is not None, "sem resposta e falha")
    check(err({"error": ["a", "b"]}) == "a; b", f"lista: {err({'error': ['a', 'b']})}")
    check(err({"response": {"error": "x"}}) == "x", "erro dentro de response")
    check(err({"response": {"current_flag": {}}}) is None,
          "previa nao e erro -- e por isso a releitura decide")


def test_hunter_checkpoint_runs_before_each_upgrade():
    """O laco de 05/10 segurou o ciclo 24 min e o Hunter perdeu uma saida."""
    server = FakeServer(with_counts(t3_2="7"))
    d = make(server)
    calls = []
    d.service_callback = lambda: calls.append(len(server.posts))
    d.manage_flags(force=True)
    check(calls == [0, 1, 2],
          f"o Hunter tem que ser servido antes de CADA upgrade: {calls}")


TESTS = [
    test_hunter_checkpoint_runs_before_each_upgrade,
    test_upgrade_sends_confirm,
    test_preview_answer_is_not_success_and_does_not_loop,
    test_error_answer_does_not_cost_a_reread,
    test_real_upgrade_cascades_upward_and_stops,
    test_two_digit_amount_is_read_as_a_number,
    test_nothing_to_upgrade_in_the_real_inventory,
    test_top_level_is_never_upgraded,
    test_required_amount_comes_from_the_page,
    test_verbatim_required_line_is_parsed,
    test_error_text_is_read_from_both_envelopes,
]

if __name__ == "__main__":
    logging.basicConfig(level=logging.CRITICAL)
    for t in TESTS:
        try:
            t()
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{t.__name__}: {type(exc).__name__}: {exc}")
    if failures:
        print("FALHOU:")
        for f in failures:
            print(" -", f)
        sys.exit(1)
    print(f"OK ({len(TESTS)} testes)")
