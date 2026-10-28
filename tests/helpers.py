"""Utilidades comunes: importar la app y aislarla en un wiki/raw temporales."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import server  # noqa: E402


class TempData:
    """Apunta server.WIKI y server.RAW a carpetas temporales (nunca toca data/)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.wiki, self.raw = root / "wiki", root / "raw"
        for d in ("fuentes", "entidades", "conceptos", "sintesis"):
            (self.wiki / d).mkdir(parents=True)
        self.raw.mkdir()
        self._old = server.WIKI, server.RAW
        server.WIKI, server.RAW = self.wiki, self.raw

    def tearDown(self):
        server.WIKI, server.RAW = self._old
        self._tmp.cleanup()

    def page(self, rel, text):
        p = self.wiki / rel
        p.write_text(text, encoding="utf-8")
        return p
