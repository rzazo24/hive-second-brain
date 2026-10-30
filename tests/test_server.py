import json
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date
from http.server import ThreadingHTTPServer
from unittest import mock

from helpers import TempData, server

TODAY = date.today().isoformat()
TMUX = "---\ntitulo: tmux\ntipo: entidad\narea: informatica\nactualizado: 2026-10-28\n---\n\n# tmux\nMultiplexor de terminal.\n"
IBU = "---\ntitulo: Ibuprofeno\ntipo: concepto\narea: [salud, veterinaria]  # comentario\n---\n\nAINE. Tóxico para gatos.\n"


class TestHelpers(unittest.TestCase):
    def test_slugify(self):
        self.assertEqual(server.slugify("Guía de Ñandúes: ¡Básico!"), "guia-de-nandues-basico")
        self.assertEqual(server.slugify("¡¡!!"), "fuente")
        self.assertEqual(len(server.slugify("a" * 200)), 80)

    def test_frontmatter(self):
        meta = server.frontmatter(IBU)
        self.assertEqual(meta["titulo"], "Ibuprofeno")
        self.assertEqual(meta["area"], "[salud, veterinaria]")  # el comentario se descarta
        self.assertEqual(server.frontmatter("sin frontmatter"), {})
        self.assertEqual(server.frontmatter("---\ntitulo: C# para .NET\n---\n")["titulo"], "C# para .NET")  # #3

    def test_parse_area(self):
        self.assertEqual(server.parse_area("salud"), ["salud"])
        self.assertEqual(server.parse_area("[IA, salud]"), ["ia", "salud"])
        self.assertEqual(server.parse_area(""), [])


class TestWiki(TempData, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.page("entidades/tmux.md", TMUX)
        self.page("conceptos/ibuprofeno.md", IBU)
        self.page("index.md", "# Índice\n")

    def test_wiki_pages(self):
        pages = {p["name"]: p for p in server.wiki_pages()}
        self.assertEqual(pages["tmux"]["section"], "entidades")
        self.assertEqual(pages["tmux"]["area"], ["informatica"])
        self.assertEqual(pages["ibuprofeno"]["area"], ["salud", "veterinaria"])
        self.assertEqual(pages["index"]["section"], "")
        self.assertEqual(pages["index"]["titulo"], "index")

    def test_find_page(self):
        self.assertEqual(server.find_page("tmux").name, "tmux.md")
        self.assertIsNone(server.find_page("no-existe"))
        for bad in ("../CLAUDE", "a/b", "*", ""):
            self.assertIsNone(server.find_page(bad), bad)

    def test_search(self):
        res = server.search("TERMINAL")
        self.assertEqual([r["name"] for r in res], ["tmux"])
        self.assertIn("terminal", res[0]["snippet"].lower())
        self.assertEqual(server.search("   "), [])
        # coincidir en el nombre del archivo pesa más que en el texto
        self.page("fuentes/gatos.md", "---\ntitulo: Gatos\n---\nibuprofeno ibuprofeno ibuprofeno")
        self.assertEqual(server.search("ibuprofeno")[0]["name"], "ibuprofeno")

    def test_pending_raw(self):
        (self.raw / "a.md").write_text("x")
        (self.raw / "b.md").write_text("x")
        (self.raw / "_procesado.md").write_text("- a.md — 2026-10-28\n")
        self.assertEqual(server.pending_raw(), ["b.md"])
        # Un nombre contenido en otro ya procesado sigue pendiente (#1)
        (self.raw / "guia-de-gatos.md").write_text("x")
        (self.raw / "gatos.md").write_text("x")
        (self.raw / "_procesado.md").write_text("- a.md — 2026-10-28\n- guia-de-gatos.md — 2026-10-29\n")
        self.assertEqual(server.pending_raw(), ["b.md", "gatos.md"])


class TestCaptura(TempData, unittest.TestCase):
    def test_save_source(self):
        name = server.save_source({"titulo": 'Dosis "gato"', "contenido": "texto", "url": "https://x.es", "autor": "A\nB"})
        self.assertEqual(name, f"{TODAY}-dosis-gato.md")
        text = (self.raw / name).read_text()
        self.assertIn("title: \"Dosis 'gato'\"", text)
        self.assertIn('autor: "A B"', text)
        self.assertIn("origen: usuario", text)
        self.assertTrue(text.rstrip().endswith("texto"))
        # nunca sobrescribe
        self.assertEqual(server.save_source({"titulo": 'Dosis "gato"', "contenido": "otro"}), f"{TODAY}-dosis-gato-2.md")

    def test_save_source_requires_fields(self):
        with self.assertRaises(ValueError):
            server.save_source({"titulo": "", "contenido": "x"})
        with self.assertRaises(ValueError):
            server.save_source({"titulo": "x", "contenido": "  "})

    def test_save_md_file(self):
        body = "---\ntitle: Esquema\norigen: claude\nformato: esquema\n---\n# A\n- b"
        self.assertEqual(server.save_md_file({"nombre": "Mi Esquema.MD", "contenido": body}), ("mi-esquema.md", False))
        self.assertEqual((self.raw / "mi-esquema.md").read_text(), body + "\n")  # se guarda tal cual
        # mismo contenido: no se duplica
        self.assertEqual(server.save_md_file({"nombre": "otro.md", "contenido": body + "\n"}), ("mi-esquema.md", True))
        # mismo nombre, distinto contenido: sufijo
        self.assertEqual(server.save_md_file({"nombre": "mi-esquema.md", "contenido": "otro"}), ("mi-esquema-2.md", False))

    def test_save_md_file_cannot_touch_procesado_or_escape(self):
        self.assertEqual(server.save_md_file({"nombre": "_procesado.md", "contenido": "x"})[0], "fuente-procesado.md")
        name, _ = server.save_md_file({"nombre": "../../CLAUDE.md", "contenido": "y"})
        self.assertEqual(name, "claude.md")
        self.assertTrue((self.raw / "claude.md").exists())
        with self.assertRaises(ValueError):
            server.save_md_file({"nombre": "vacio.md", "contenido": " \n"})

    def test_save_url(self):
        meta = {"title": "Comandos Bash", "url": "https://ej.es/bash", "sitio": "ej.es", "autor": ""}
        with mock.patch.object(server.webimport, "import_url", return_value=(meta, "cuerpo")) as imp:
            self.assertEqual(server.save_url({"url": "https://ej.es/bash"}), (f"{TODAY}-comandos-bash.md", False))
            text = (self.raw / f"{TODAY}-comandos-bash.md").read_text()
            self.assertIn('url: "https://ej.es/bash"', text)
            self.assertIn("origen: web", text)
            self.assertNotIn("autor:", text)
            # misma URL (con o sin barra final): duplicado, sin volver a descargar
            self.assertEqual(server.save_url({"url": "https://ej.es/bash/"}), (f"{TODAY}-comandos-bash.md", True))
            self.assertEqual(imp.call_count, 1)
            # reimportar: si el texto no cambia, no se crea otra copia
            self.assertEqual(server.save_url({"url": "https://ej.es/bash", "reimportar": True}), (f"{TODAY}-comandos-bash.md", True))
        with mock.patch.object(server.webimport, "import_url", return_value=(meta, "cuerpo completo")):
            # si cambia, fuente nueva y la anterior intacta
            self.assertEqual(server.save_url({"url": "https://ej.es/bash", "reimportar": True}), (f"{TODAY}-comandos-bash-2.md", False))
            self.assertIn("cuerpo\n", (self.raw / f"{TODAY}-comandos-bash.md").read_text())

    def test_save_url_errors(self):
        with self.assertRaises(ValueError):
            server.save_url({"url": " "})
        with mock.patch.object(server.webimport, "import_url", side_effect=server.webimport.ImportError_("mal")):
            with self.assertRaisesRegex(ValueError, "mal"):
                server.save_url({"url": "https://ej.es"})


class TestHTTP(TempData, unittest.TestCase):
    """Servidor real en un puerto libre de localhost."""

    def setUp(self):
        super().setUp()
        self.page("entidades/tmux.md", TMUX)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        super().tearDown()

    def req(self, path, data=None, method=None):
        body = json.dumps(data).encode() if data is not None else None
        r = urllib.request.Request(self.base + path, data=body, method=method,
                                   headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read()

    def test_index_and_sw(self):
        status, headers, body = self.req("/")
        self.assertEqual(status, 200)
        self.assertIn(b"Hive2nd Brain", body)
        status, headers, _ = self.req("/sw.js")
        self.assertEqual(headers["Cache-Control"], "no-cache")

    def test_head_has_headers_without_body(self):
        status, headers, body = self.req("/", method="HEAD")
        self.assertEqual(status, 200)
        self.assertGreater(int(headers["Content-Length"]), 0)
        self.assertEqual(body, b"")

    def test_static_path_traversal(self):
        self.assertEqual(self.req("/static/manifest.webmanifest")[0], 200)
        for p in ("/static/../server.py", "/static/%2e%2e/server.py", "/static/..%2F..%2FCLAUDE.md", "/static/nada.js"):
            self.assertEqual(self.req(p)[0], 404, p)

    def test_api(self):
        status, _, body = self.req("/api/pages")
        data = json.loads(body)
        self.assertEqual([p["name"] for p in data["pages"]], ["tmux"])
        self.assertEqual(data["pendientes"], [])
        self.assertEqual(json.loads(self.req("/api/page/tmux")[2])["name"], "tmux")
        self.assertEqual(self.req("/api/page/..%2Findex")[0], 404)
        self.assertEqual(json.loads(self.req("/api/search?q=multiplexor+de")[2])["results"][0]["name"], "tmux")

    def test_post_fuente(self):
        status, _, body = self.req("/api/fuente", {"titulo": "Nota", "contenido": "hola"})
        self.assertEqual(status, 201)
        self.assertEqual(json.loads(body), {"archivo": f"{TODAY}-nota.md", "duplicado": False})
        self.assertEqual(self.req("/api/fuente-md", {"nombre": "x.md", "contenido": "a"})[0], 201)
        self.assertEqual(self.req("/api/fuente-md", {"nombre": "y.md", "contenido": "a"})[0], 200)  # duplicado
        self.assertEqual(self.req("/api/fuente", {"titulo": ""})[0], 400)
        self.assertEqual(self.req("/api/otra", {})[0], 404)


if __name__ == "__main__":
    unittest.main()


class TestOrigen(TestHTTP):
    """Quién puede hablar con el servidor: Host conocido y, para escribir, mismo origen y JSON."""

    def call(self, path, method="GET", headers=None, data=None):
        port = self.httpd.server_address[1]
        c = __import__("http.client").client.HTTPConnection("127.0.0.1", port)
        c.request(method, path, body=data, headers=headers or {})
        r = c.getresponse(); r.read(); c.close()
        return r.status

    def test_host_desconocido_rechazado(self):
        # DNS rebinding: una web con su propio dominio apuntando a 127.0.0.1 llega con ese Host
        self.assertEqual(self.call("/api/pages", headers={"Host": "evil.example:8765"}), 403)
        self.assertEqual(self.call("/api/pages", headers={"Host": "localhost:8765"}), 200)
        with mock.patch.object(server, "tailnet_name", lambda refresh=False: "cerebro.tailabc.ts.net"):
            self.assertEqual(self.call("/api/pages", headers={"Host": "cerebro.tailabc.ts.net"}), 200)
            # otro nombre de Tailscale (otra tailnet) no vale
            self.assertEqual(self.call("/api/pages", headers={"Host": "otro.tailzzz.ts.net"}), 403)

    def test_post_de_otra_web_rechazado(self):
        port = self.httpd.server_address[1]
        body = json.dumps({"titulo": "x", "contenido": "y"})
        host = f"127.0.0.1:{port}"
        # una web cualquiera que manda texto "simple" (sin preflight): ni Origin ni Content-Type valen
        self.assertEqual(self.call("/api/fuente", "POST", {"Host": host, "Origin": "https://evil.example", "Content-Type": "application/json"}, body), 403)
        self.assertEqual(self.call("/api/fuente", "POST", {"Host": host, "Origin": "null", "Content-Type": "application/json"}, body), 403)
        self.assertEqual(self.call("/api/fuente", "POST", {"Host": host, "Sec-Fetch-Site": "cross-site", "Content-Type": "application/json"}, body), 403)
        self.assertEqual(self.call("/api/fuente", "POST", {"Host": host, "Origin": f"http://{host}", "Content-Type": "text/plain"}, body), 415)
        self.assertEqual(list(self.raw_dir()), [])
        # la propia app: mismo origen y JSON
        self.assertEqual(self.call("/api/fuente", "POST", {"Host": host, "Origin": f"http://{host}", "Sec-Fetch-Site": "same-origin", "Content-Type": "application/json"}, body), 201)

    def raw_dir(self):
        return [p.name for p in self.raw.glob("*.md")]

    def test_hostname(self):
        self.assertEqual(server._hostname("[::1]:8765"), "::1")
        self.assertEqual(server._hostname("Cerebro.Tail.ts.net:443"), "cerebro.tail.ts.net")
        self.assertFalse(server.host_allowed(None))
        self.assertFalse(server.host_allowed("ts.net.evil.example"))

    def test_tailnet_name(self):
        out = json.dumps({"Self": {"DNSName": "Cerebro.TailABC.ts.net."}})
        server._tailnet.update(name=None, checked=0.0)
        try:
            with mock.patch.object(server.subprocess, "run", return_value=mock.Mock(stdout=out)) as run:
                self.assertEqual(server.tailnet_name(), "cerebro.tailabc.ts.net")
                self.assertEqual(server.tailnet_name(), "cerebro.tailabc.ts.net")
                self.assertEqual(run.call_count, 1)                      # se guarda
                self.assertFalse(server.host_allowed("otro.tailzzz.ts.net"))
                self.assertEqual(run.call_count, 1)                      # no repregunta antes de 30 s
            server._tailnet.update(name=None, checked=0.0)
            with mock.patch.object(server.subprocess, "run", side_effect=OSError):
                self.assertIsNone(server.tailnet_name())                 # sin Tailscale: solo localhost
                self.assertFalse(server.host_allowed("cerebro.tailabc.ts.net"))
                self.assertTrue(server.host_allowed("localhost:8765"))
        finally:
            server._tailnet.update(name=None, checked=0.0)
