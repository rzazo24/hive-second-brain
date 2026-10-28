import unittest
from unittest import mock

from helpers import server  # noqa: F401  (añade app/ a sys.path)
import webimport

ARTICLE = """<!doctype html><html><head>
<meta charset="utf-8"><title>Guía de gatos - Mi Blog</title>
<meta property="og:site_name" content="Mi Blog">
<meta name="author" content="Ana">
<meta property="article:published_time" content="2025-03-01T10:00:00Z">
<meta name="description" content="Todo   sobre gatos">
</head><body>
<nav class="menu"><a href="/">Inicio</a><a href="/b">Blog</a></nav>
<div id="cookie-consent">Aceptamos cookies</div>
<article>
<h1>Guía de gatos</h1>
<p>El <strong>Maine Coon</strong> es una raza grande y sociable. Necesita cepillado frecuente
por su pelo semilargo y una dieta adecuada a su tamaño. Ver <a href="/razas">razas</a>.</p>
<h2>Cuidados</h2>
<ul><li>Cepillado <em>semanal</em></li><li>Revisión veterinaria anual</li></ul>
<pre><code>dosis = no inventar</code></pre>
<table><tr><th>Edad</th><th>Peso</th></tr><tr><td>1 año</td><td>6 kg</td></tr></table>
<script>alert('x')</script>
<p>Texto de relleno suficiente para superar el mínimo de caracteres que exige el importador al extraer.</p>
</article>
<footer>© Mi Blog</footer>
</body></html>"""


def fake_fetch(html, url="https://blog.ej.es/gatos", ctype="text/html; charset=utf-8"):
    return mock.patch.object(webimport, "fetch", return_value=(html, url, ctype))


class TestImportUrl(unittest.TestCase):
    def test_article(self):
        with fake_fetch(ARTICLE):
            meta, body = webimport.import_url("blog.ej.es/gatos")
        self.assertEqual(meta["title"], "Guía de gatos")  # sin el sufijo " - Mi Blog"
        self.assertEqual(meta["autor"], "Ana")
        self.assertEqual(meta["fecha_publicacion"], "2025-03-01")
        self.assertEqual(meta["sitio"], "Mi Blog")
        self.assertEqual(meta["descripcion"], "Todo sobre gatos")
        self.assertFalse(body.startswith("# Guía de gatos"))  # título repetido eliminado
        self.assertIn("**Maine Coon**", body)
        self.assertIn("[razas](https://blog.ej.es/razas)", body)  # enlaces absolutos
        self.assertIn("## Cuidados", body)
        self.assertIn("- Cepillado *semanal*", body)
        self.assertIn("dosis = no inventar", body)
        self.assertIn("| 1 año | 6 kg |", body)
        for noise in ("alert(", "Aceptamos cookies", "© Mi Blog", "Inicio"):
            self.assertNotIn(noise, body)

    def test_adds_https(self):
        with fake_fetch(ARTICLE) as f:
            webimport.import_url("  blog.ej.es/gatos ")
        f.assert_called_once_with("https://blog.ej.es/gatos")

    def test_plain_text(self):
        text = "Línea de texto plano. " * 20
        with fake_fetch(text, "https://ej.es/notas.txt", "text/plain"):
            meta, body = webimport.import_url("https://ej.es/notas.txt")
        self.assertEqual(meta["title"], "notas.txt")
        self.assertEqual(body, text.strip())

    def test_too_short(self):
        with fake_fetch("<html><body><div id='app'></div><script>render()</script></body></html>"):
            with self.assertRaisesRegex(webimport.ImportError_, "No se pudo extraer"):
                webimport.import_url("https://spa.ej.es")


class TestSSRF(unittest.TestCase):
    """Las IP literales se resuelven sin red, así que estos tests funcionan sin conexión."""

    def test_blocks_internal(self):
        for url in ("http://127.0.0.1:8765/", "http://localhost/", "http://192.168.1.1/", "http://10.0.0.5/",
                    "http://172.16.0.1/", "http://169.254.169.254/latest/meta-data", "http://100.101.102.103/",
                    "http://[::1]/", "http://0.0.0.0/"):
            with self.assertRaises(webimport.ImportError_, msg=url):
                webimport._check_url(url)

    def test_scheme(self):
        for url in ("file:///etc/passwd", "ftp://ej.es/x", "javascript:alert(1)", "https://"):
            with self.assertRaisesRegex(webimport.ImportError_, "http", msg=url):
                webimport._check_url(url)

    def test_allows_public_ip(self):
        webimport._check_url("https://1.1.1.1/")

    def test_fetch_checks_before_connecting(self):
        with mock.patch("urllib.request.OpenerDirector.open") as op:
            with self.assertRaises(webimport.ImportError_):
                webimport.fetch("http://127.0.0.1/")
            op.assert_not_called()

    def test_redirect_to_internal_blocked(self):
        h = webimport._SafeRedirect()
        with self.assertRaises(webimport.ImportError_):
            h.redirect_request(None, None, 302, "Found", {}, "http://169.254.169.254/")


class TestJoin(unittest.TestCase):
    def test_lists_stay_together(self):
        self.assertEqual(webimport._join(["# T", "- a", "- b", "texto"]), "# T\n\n- a\n- b\n\ntexto")


if __name__ == "__main__":
    unittest.main()
