import re
import shutil
import subprocess
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"


class TestFrontend(unittest.TestCase):
    def test_sw_version_format(self):
        sw = (APP / "static" / "sw.js").read_text(encoding="utf-8")
        self.assertRegex(sw, r"const VERSION = 'v\d+';")

    def test_known_areas(self):
        html = (APP / "index.html").read_text(encoding="utf-8")
        claude = (APP.parent / "CLAUDE.md").read_text(encoding="utf-8")
        listed = re.search(r"^area: (.+?)\s+#", claude, re.M).group(1).replace(" ", "").split("|")
        areas = re.findall(r"(\w+):'", re.search(r"const AREAS = \{(.*?)\}", html).group(1))
        self.assertEqual(sorted(areas), sorted(listed), "Las áreas de la app y de CLAUDE.md no coinciden")

    @unittest.skipUnless(shutil.which("node"), "node no instalado")
    def test_js_syntax(self):
        html = (APP / "index.html").read_text(encoding="utf-8")
        scripts = re.findall(r"<script>([\s\S]*?)</script>", html)
        self.assertTrue(scripts)
        for src in scripts + [(APP / "static" / "sw.js").read_text(encoding="utf-8")]:
            r = subprocess.run(["node", "--check", "-"], input=src, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
