"""
tools/feature_map.py: a captura que mapeia o que e premium e o que nao e.

O que se protege aqui:
- a captura so le: URL com `action`, `ajaxaction` ou `h` e recusada ANTES de
  qualquer requisicao;
- `data-bot-protect` com qualquer valor para a captura (o `pending` antecede o
  captcha; memoria nunca-usar-priority-mode-ao-sondar);
- o resumo da pagina (fingerprint) e estavel entre dias: ids, tokens e
  numeros saem da chave, senao toda comparacao premium x gratis teria ruido;
- a descoberta nunca agenda compra/transferencia de pontos premium.

Fixture: o menu de premium e o bloco `features` do `game_data` sao recortes
verbatim de `screen=overview_villages&mode=prod` do br143 (2026-09-23), com o
id da aldeia trocado e o resto do `game_data` (jogador, aldeia, csrf) cortado.
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import feature_map as fm  # noqa: E402

MENU = (
    '<table cellspacing="0" class="menu_column"><tr><td class="menu-column-item">'
    '<a href="/game.php?village=1000&amp;screen=premium&amp;mode=use">Subscrições</a></td></tr>'
    '<tr><td class="menu-column-item"><a href="/game.php?village=1000&amp;screen=premium&amp;'
    'mode=premium" class="premium-buy">Compra</a></td></tr><tr><td class="menu-column-item">'
    '<a href="/game.php?village=1000&amp;screen=premium&amp;mode=cosmetics">Cosméticos</a></td></tr>'
    '<tr><td class="menu-column-item"><a href="/game.php?village=1000&amp;screen=premium&amp;'
    'mode=transfer">Transferir</a></td></tr><tr><td class="menu-column-item"><a href="/game.php?'
    'village=1000&amp;screen=premium&amp;mode=log">Histórico de pontos</a></td></tr><tr>'
    '<td class="menu-column-item"><a href="/game.php?village=1000&amp;screen=premium&amp;'
    'mode=feature_log">Histórico de funcionalidades</a></td></tr><tr><td class="bottom">'
    '<div class="corner"></div><div class="decoration"></div></td></tr></table>'
)
GAME_DATA = (
    '<script>TribalWars.updateGameData({"features":{"Premium":{"possible":true,"active":true},'
    '"AccountManager":{"possible":true,"active":true},"FarmAssistent":{"possible":true,'
    '"active":true}},"screen":"overview_villages","mode":"prod"});</script>'
)
PAGE = "<html><body>" + GAME_DATA + MENU + "</body></html>"


class SafeQueryTest(unittest.TestCase):
    def test_reading_is_allowed(self):
        self.assertTrue(fm.is_safe_query("screen=overview_villages&mode=prod"))
        self.assertTrue(fm.is_safe_query("screen=overview_villages&mode=commands&page=-1"))

    def test_action_params_are_refused(self):
        for q in ("screen=snob&action=coin", "screen=main&ajaxaction=upgrade_building",
                  "screen=premium&mode=use&h=abc123"):
            self.assertFalse(fm.is_safe_query(q), q)

    def test_every_fixed_screen_only_reads(self):
        keys = [k for k, _, _ in fm.SCREENS]
        self.assertEqual(len(keys), len(set(keys)), "chave repetida na lista fixa")
        for key, query, village in fm.SCREENS:
            self.assertTrue(fm.is_safe_query(query), key)
            self.assertNotIn("group=", query, key)
            self.assertIn(village, ("v", "t"), key)

    def test_fetch_refuses_before_any_request(self):
        class Boom:
            captcha_hit = False

            def get_url(self, url):
                raise AssertionError("nao devia ter pedido nada")
        with self.assertRaises(ValueError):
            fm._fetch(Boom(), "/nao/existe", "x", "screen=snob&action=coin", "1", 0, 0)


class NormalizeTest(unittest.TestCase):
    def test_ids_and_tokens_leave_the_key(self):
        self.assertEqual(
            fm.normalize_link("/game.php?village=41123&amp;screen=report&amp;mode=all&amp;view=99&amp;h=ab12"),
            "report&mode=all")
        self.assertEqual(
            fm.normalize_link("game.php?village=1&screen=main&ajaxaction=upgrade_building&id=wood&h=x"),
            "main&ajaxaction=upgrade_building")

    def test_not_a_screen(self):
        self.assertIsNone(fm.normalize_link("/page/settings"))


class FingerprintTest(unittest.TestCase):
    def test_real_menu_and_features(self):
        fp = fm.fingerprint(PAGE)
        self.assertEqual(fp["screen"], "overview_villages")
        self.assertEqual(fp["features"]["FarmAssistent"], {"possible": True, "active": True})
        self.assertEqual(set(fp["premium_links"]), {
            "premium&mode=use", "premium&mode=premium", "premium&mode=cosmetics",
            "premium&mode=transfer", "premium&mode=log", "premium&mode=feature_log"})
        self.assertIn("premium-buy", fp["premium_classes"])
        self.assertEqual(fp["bot_protect"], [])

    def test_stable_across_ids(self):
        other = PAGE.replace("village=1000", "village=2222")
        self.assertEqual(fm.compare_fingerprints(fm.fingerprint(PAGE), fm.fingerprint(other)), {})

    def test_missing_link_shows_up(self):
        trimmed = PAGE.replace("mode=feature_log", "mode=zzz")
        diff = fm.compare_fingerprints(fm.fingerprint(PAGE), fm.fingerprint(trimmed))
        self.assertIn("premium&mode=feature_log", diff["links"]["so_em_a"])
        self.assertIn("premium&mode=zzz", diff["links"]["so_em_b"])

    def test_css_only_gate_is_seen(self):
        # Recorte verbatim de place&mode=scavenge_mass (br143, 2026-10-04,
        # conta com premium): o aviso vem no HTML mesmo com premium ativo, e
        # quem o esconde e o CSS via `has-pa` no body. Uma tela que so muda
        # por isso tem que sair diferente na comparacao.
        hint = (
            '<h3>Coleta em Massa</h3>\n<div class="premium_account_hint">\n'
            '    <div class="content">\n        Evolua para um <a class="premium_direct_buy" '
            'data-feature="Premium" href="#">Conta premium</a> para poder enviar comandos de '
            'coleta de várias aldeias ao mesmo tempo.    </div>\n</div>\n\n'
            '<div class="premium-required">\n')
        paid = '<body id="ds_body" class="desktop    has-pa" dir="ltr"\n      >' + hint
        free = '<body id="ds_body" class="desktop" dir="ltr">' + hint
        fp_paid, fp_free = fm.fingerprint(paid), fm.fingerprint(free)
        self.assertEqual(fp_paid["body_classes"], ["desktop", "has-pa"])
        self.assertEqual(fp_paid["data_features"], ["Premium"])
        self.assertEqual(len(fp_paid["premium_hints"]), 1)
        self.assertIn("coleta de várias aldeias", fp_paid["premium_hints"][0])
        diff = fm.compare_fingerprints(fp_paid, fp_free)
        self.assertEqual(diff["body_classes"]["so_em_a"], ["has-pa"])

    def test_day_to_day_noise_is_normalized(self):
        # Os dois defeitos que a captura 2 (06/10) mostrou: hash do CDN
        # dentro de titulo escapado em JS, e campo de nome aleatorio na praca
        # (valores verbatim das duas capturas).
        def page(cdn, name):
            return ('<h4>&lt;img src="https://dsbr.innogamescdn.com/asset/%s/graphic/'
                    'buildings/main.webp"&gt; +10%% na velocidade de construção</h4>'
                    '<input type="hidden" name="%s" value="x">' % (cdn, name))
        a = fm.fingerprint(page("07afad24", "cbf3f5a1f2a3fb9"))
        b = fm.fingerprint(page("1ce2b9a0", "8fa4f1f0e2fdb5d1a"))
        self.assertEqual(fm.compare_fingerprints(a, b), {})
        self.assertEqual(a["inputs"], ["(nome aleatorio)"])
        self.assertEqual(a["headings"], ["+#% na velocidade de construção"])

    def test_presence(self):
        self.assertEqual(fm.compare_fingerprints(None, {"x": 1}),
                         {"presence": ("ausente", "presente")})


class DiscoverTest(unittest.TestCase):
    def test_never_schedules_purchase_or_transfer(self):
        fp = fm.fingerprint(PAGE)
        found = dict(fm.discover({"overview_villages/prod": fp}, {"premium/use"}))
        self.assertIn("premium/log", found)
        self.assertIn("premium/feature_log", found)
        for denied in ("premium/premium", "premium/transfer", "premium/cosmetics", "premium/use"):
            self.assertNotIn(denied, found)
        for query in found.values():
            self.assertTrue(fm.is_safe_query(query))


class CaptchaStopTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.dir, "pages"))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _wrapper(self, html, hit=False):
        class Res:
            status_code = 200
            url = "https://x/game.php?village=1&screen=overview"
            text = html

        class W:
            captcha_hit = hit

            def get_url(self, url):
                return Res()
        return W()

    def test_pending_stops(self):
        page = PAGE.replace("<body>", '<body data-bot-protect="pending">')
        with self.assertRaises(fm.CaptchaHit):
            fm._fetch(self._wrapper(page), self.dir, "overview", "screen=overview", "1", 0, 0)

    def test_wrapper_captcha_stops(self):
        with self.assertRaises(fm.CaptchaHit):
            fm._fetch(self._wrapper(PAGE, hit=True), self.dir, "overview", "screen=overview", "1", 0, 0)

    def test_session_lost_stops_without_saving(self):
        # 07/10 05:51: sessao vencida, `market/exchange` voltou 200 de
        # https://www.tribalwars.com.br/ (o portal), sem game_data.
        class Res:
            status_code = 200
            url = "https://www.tribalwars.com.br/"
            text = "<html><body class=\"portal\"><form id=\"login_form\"></form></body></html>"

        class W:
            captcha_hit = False
            endpoint = "https://br143.tribalwars.com.br/"

            def get_url(self, url):
                return Res()
        with self.assertRaises(fm.SessionLost):
            fm._fetch(W(), self.dir, "market/exchange", "screen=market&mode=exchange", "1", 0, 0)
        self.assertEqual(os.listdir(os.path.join(self.dir, "pages")), [])

    def test_session_lost_rule(self):
        gd = {"screen": "overview"}
        host = "br143.tribalwars.com.br"
        self.assertFalse(fm.session_lost("https://br143.tribalwars.com.br/game.php?screen=x", gd, host))
        self.assertTrue(fm.session_lost("https://www.tribalwars.com.br/", gd, host))
        self.assertTrue(fm.session_lost("https://br143.tribalwars.com.br/game.php", {}, host))

    def test_clean_page_is_saved(self):
        rec, _ = fm._fetch(self._wrapper(PAGE), self.dir, "overview", "screen=overview", "1", 0, 0)
        self.assertEqual(rec["status"], 200)
        self.assertTrue(os.path.exists(os.path.join(self.dir, "pages", "overview.html.gz")))


if __name__ == "__main__":
    unittest.main()
