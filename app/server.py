#!/usr/bin/env python3
"""Interfaz web local del Second Brain.

- Consulta: navega y busca en wiki/ (solo lectura).
- Captura: guarda fuentes nuevas en raw/ como markdown, para que el
  agente las ingiera después ("ingiere lo nuevo de raw/").

Uso: python3 app/server.py [puerto]   (por defecto 8765, solo localhost)
"""
import json
import re
import sys
import unicodedata
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import webimport

ROOT = Path(__file__).resolve().parent.parent
WIKI = ROOT / "data" / "wiki"
RAW = ROOT / "data" / "raw"
STATIC = Path(__file__).resolve().parent / "index.html"
STATIC_DIR = Path(__file__).resolve().parent / "static"
MIME = {".js": "text/javascript; charset=utf-8", ".png": "image/png",
        ".webmanifest": "application/manifest+json", ".json": "application/json"}


def slugify(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return text[:80] or "fuente"


def frontmatter(text):
    meta = {}
    m = re.match(r"^---\n(.*?)\n---\n?", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = re.sub(r"\s#.*$", "", v).strip()
    return meta


def parse_area(value):
    """'salud' o '[ia, salud]' -> ['salud'] / ['ia', 'salud']"""
    return [a.strip().lower() for a in value.strip("[] ").split(",") if a.strip()]


def wiki_pages():
    pages = []
    for p in sorted(WIKI.rglob("*.md")):
        text = p.read_text(encoding="utf-8", errors="replace")
        meta = frontmatter(text)
        pages.append({
            "name": p.stem,
            "path": str(p.relative_to(WIKI)),
            "section": p.parent.name if p.parent != WIKI else "",
            "titulo": meta.get("titulo", p.stem),
            "tipo": meta.get("tipo", ""),
            "actualizado": meta.get("actualizado", ""),
            "area": parse_area(meta.get("area", "")),
        })
    return pages


def find_page(name):
    if not re.fullmatch(r"[a-zA-Z0-9_\-]+", name):
        return None
    for p in WIKI.rglob(name + ".md"):
        return p
    return None


def search(q):
    q = q.lower().strip()
    if not q:
        return []
    results = []
    for p in WIKI.rglob("*.md"):
        text = p.read_text(encoding="utf-8", errors="replace")
        low = text.lower()
        count = low.count(q)
        if count == 0 and q not in p.stem:
            continue
        i = low.find(q)
        snippet = text[max(0, i - 80): i + 120].replace("\n", " ") if i >= 0 else ""
        results.append({"name": p.stem, "titulo": frontmatter(text).get("titulo", p.stem),
                        "score": count + (10 if q in p.stem else 0), "snippet": snippet})
    return sorted(results, key=lambda r: -r["score"])[:50]


def pending_raw():
    done = (RAW / "_procesado.md").read_text(encoding="utf-8") if (RAW / "_procesado.md").exists() else ""
    return [p.name for p in sorted(RAW.glob("*.md"))
            if p.name != "_procesado.md" and p.name not in done]


def save_source(data):
    title = (data.get("titulo") or "").strip()
    body = (data.get("contenido") or "").strip()
    url = (data.get("url") or "").strip()
    if not title or not body:
        raise ValueError("Faltan título o contenido")
    today = date.today().isoformat()
    base = f"{today}-{slugify(title)}"
    path = RAW / f"{base}.md"
    n = 2
    while path.exists():
        path = RAW / f"{base}-{n}.md"
        n += 1
    clean = lambda s: s.replace("\n", " ").replace('"', "'")
    lines = ["---", f'title: "{clean(title)}"']
    if url:
        lines.append(f'url: "{clean(url)}"')
    if data.get("autor"):
        lines.append(f'autor: "{clean(data["autor"])}"')
    lines += ["origen: usuario", f"capturado: {today}", "---", "", body, ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path.name


def save_md_file(data):
    """Guarda un .md subido tal cual (es la fuente original); solo normaliza el nombre."""
    name = (data.get("nombre") or "").strip()
    body = data.get("contenido") or ""
    if not body.strip():
        raise ValueError(f"{name or 'El archivo'} está vacío")
    # Si ya hay un archivo con el mismo contenido, no se duplica
    for existing in RAW.glob("*.md"):
        if existing.name != "_procesado.md" and existing.read_text(encoding="utf-8", errors="replace").rstrip("\n") == body.rstrip("\n"):
            return existing.name, True
    stem = re.sub(r"\.(md|markdown|txt)$", "", Path(name).name, flags=re.I)
    base = slugify(stem)
    if base.startswith("procesado"):
        base = "fuente-" + base
    path = RAW / f"{base}.md"
    n = 2
    while path.exists():
        path = RAW / f"{base}-{n}.md"
        n += 1
    path.write_text(body if body.endswith("\n") else body + "\n", encoding="utf-8")
    return path.name, False


def save_url(data):
    """Descarga una página web, la convierte a markdown y la guarda en raw/ con origen: web."""
    url = (data.get("url") or "").strip()
    if not url:
        raise ValueError("Falta la URL")
    # Si ya se importó esa URL, no se duplica
    for existing in RAW.glob("*.md"):
        head = existing.read_text(encoding="utf-8", errors="replace")[:2000]
        if re.search(r'^url: "?' + re.escape(url.rstrip("/")) + r'/?"?\s*$', head, re.M):
            return existing.name, True
    try:
        meta, body = webimport.import_url(url)
    except webimport.ImportError_ as e:
        raise ValueError(str(e))
    today = date.today().isoformat()
    base = f"{today}-{slugify(meta['title'])}"
    path = RAW / f"{base}.md"
    n = 2
    while path.exists():
        path = RAW / f"{base}-{n}.md"
        n += 1
    clean = lambda s: s.replace("\n", " ").replace('"', "'")
    lines = ["---", f'title: "{clean(meta["title"])}"', f'url: "{clean(meta["url"])}"']
    for key in ("autor", "fecha_publicacion", "sitio", "descripcion"):
        if meta.get(key):
            lines.append(f'{key}: "{clean(meta[key])}"')
    lines += ["origen: web", f"capturado: {today}", "---", "", body, ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path.name, False


class Handler(BaseHTTPRequestHandler):
    def send(self, status, payload, ctype="application/json; charset=utf-8", headers=None):
        body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        path, _, query = self.path.partition("?")
        params = dict(kv.split("=", 1) for kv in query.split("&") if "=" in kv)
        from urllib.parse import unquote_plus
        if path == "/":
            return self.send(200, STATIC.read_bytes(), "text/html; charset=utf-8")
        if path == "/sw.js":
            # Servido en la raíz para que su alcance cubra toda la app
            return self.send(200, (STATIC_DIR / "sw.js").read_bytes(), "text/javascript; charset=utf-8",
                             {"Cache-Control": "no-cache"})
        if path.startswith("/static/"):
            f = (STATIC_DIR / unquote_plus(path[len("/static/"):])).resolve()
            if not f.is_relative_to(STATIC_DIR) or not f.is_file():
                return self.send(404, {"error": "No encontrado"})
            return self.send(200, f.read_bytes(), MIME.get(f.suffix, "application/octet-stream"))
        if path == "/api/pages":
            # no-store: que ningún navegador sirva un listado viejo
            return self.send(200, {"pages": wiki_pages(), "pendientes": pending_raw()}, headers={"Cache-Control": "no-store"})
        if path.startswith("/api/page/"):
            p = find_page(unquote_plus(path[len("/api/page/"):]))
            if not p:
                return self.send(404, {"error": "Página no encontrada"})
            return self.send(200, {"name": p.stem, "content": p.read_text(encoding="utf-8")})
        if path == "/api/search":
            return self.send(200, {"results": search(unquote_plus(params.get("q", "")))})
        self.send(404, {"error": "No encontrado"})

    def do_HEAD(self):
        # Igual que GET pero sin cuerpo (lo usan curl -I y algunos monitores)
        self.do_GET()

    def do_POST(self):
        handlers = {"/api/fuente": save_source, "/api/fuente-md": save_md_file, "/api/fuente-url": save_url}
        if self.path not in handlers:
            return self.send(404, {"error": "No encontrado"})
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > 5_000_000:
                raise ValueError("Contenido demasiado grande")
            result = handlers[self.path](json.loads(self.rfile.read(length)))
            name, dup = result if isinstance(result, tuple) else (result, False)
            self.send(200 if dup else 201, {"archivo": name, "duplicado": dup})
        except (ValueError, json.JSONDecodeError) as e:
            self.send(400, {"error": str(e)})

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    print(f"Second Brain en http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
