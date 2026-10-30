"""Importación de páginas web como fuentes: descarga, extrae el texto principal y lo convierte a markdown.

Solo usa la librería estándar. La descarga la hace la app al capturar (no el agente),
y el resultado se trata como dato no fiable igual que cualquier otra fuente de raw/.
"""
import ipaddress
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from html import unescape
from html.parser import HTMLParser

MAX_BYTES = 5_000_000
TIMEOUT = 15
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) Hive2ndBrain/1.0 (+captura personal)"

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
SKIP = {"script", "style", "noscript", "template", "svg", "canvas", "iframe", "nav", "footer", "aside", "form",
        "button", "select", "dialog", "picture", "video", "audio", "object"}
# Clases/ids típicos de navegación, menús y relleno que no forman parte del artículo
# (desde el inicio de una clase, para no confundir "has-sidebar"; "hidden" solo como clase entera, no "overflow-hidden")
NOISE = re.compile(r"(^|\s)(?:(nav|navbar|navbox|menu|sidebar|share|sharing|social|related|comments?|cookies?|consent|"
                   r"newsletter|subscribe|advert|ads|promo|breadcrumbs?|toc|mw-editsection|noprint|reflist|references|"
                   r"interlanguage|langlinks|vector-menu|catlinks|mw-jump-link|skip-link)([-_\s]|$)|hidden(\s|$))", re.I)

BLOCK = {"p", "div", "section", "article", "main", "header", "ul", "ol", "li", "pre", "blockquote", "table", "tr",
         "h1", "h2", "h3", "h4", "h5", "h6", "dl", "dt", "dd", "figure", "figcaption", "hr", "br"}


class ImportError_(ValueError):
    pass


# ---------- Descarga segura ----------

def _check_host(host):
    """Evita que la app descargue direcciones internas (localhost, red local, tailnet, metadatos de nube)."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise ImportError_(f"No se encuentra el servidor {host}")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast
                or ip.is_unspecified or ip in ipaddress.ip_network("100.64.0.0/10")):
            raise ImportError_("Esa dirección es de una red interna y no se puede importar")


def _check_url(url):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ImportError_("La URL debe empezar por http:// o https://")
    _check_host(parts.hostname)


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url):
    _check_url(url)
    opener = urllib.request.build_opener(_SafeRedirect)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain,text/markdown;q=0.9,*/*;q=0.5",
                                               "Accept-Language": "es,en;q=0.8"})
    try:
        with opener.open(req, timeout=TIMEOUT) as r:
            ctype = r.headers.get("Content-Type", "")
            if not re.search(r"text/(html|plain|markdown)|application/xhtml", ctype):
                raise ImportError_(f"Ese enlace no es una página web ({ctype.split(';')[0] or 'tipo desconocido'})")
            data = r.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise ImportError_("La página es demasiado grande")
            charset = r.headers.get_content_charset()
            final_url = r.geturl()
    except urllib.error.HTTPError as e:
        raise ImportError_(f"La web respondió con un error {e.code}" + (" (requiere acceso o bloquea descargas)" if e.code in (401, 403) else ""))
    except urllib.error.URLError as e:
        raise ImportError_(f"No se pudo conectar: {e.reason}")
    except (TimeoutError, socket.timeout):
        raise ImportError_("La web tardó demasiado en responder")
    if not charset:
        m = re.search(rb'<meta[^>]+charset=["\']?([\w-]+)', data[:4096], re.I)
        charset = m.group(1).decode() if m else "utf-8"
    try:
        text = data.decode(charset, errors="replace")
    except LookupError:
        text = data.decode("utf-8", errors="replace")
    return text, final_url, ctype


# ---------- Árbol HTML mínimo ----------

class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag, attrs=None, parent=None):
        self.tag, self.attrs, self.children, self.parent = tag, dict(attrs or {}), [], parent


class _TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root")
        self.cur = self.root
        self.meta = {}
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "meta":
            a = dict(attrs)
            key = (a.get("property") or a.get("name") or "").lower()
            if key and a.get("content"):
                self.meta.setdefault(key, a["content"].strip())
            return
        if tag == "title":
            self._in_title = True
        node = Node(tag, attrs, self.cur)
        self.cur.children.append(node)
        if tag not in VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID and self.cur.tag == tag:
            self.cur = self.cur.parent

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        n = self.cur
        while n is not self.root and n.tag != tag:
            n = n.parent
        if n is not self.root:
            self.cur = n.parent

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        self.cur.children.append(data)


def _find_all(node, pred, out):
    for c in node.children:
        if isinstance(c, Node):
            if pred(c):
                out.append(c)
            _find_all(c, pred, out)
    return out


def _text_len(node):
    total = 0
    for c in node.children:
        if isinstance(c, str):
            total += len(c.strip())
        elif c.tag not in SKIP:
            total += _text_len(c)
    return total


def _is_noise(node):
    if node.tag in SKIP or node.attrs.get("aria-hidden") == "true" or node.attrs.get("role") in ("navigation", "banner", "contentinfo"):
        return True
    return bool(NOISE.search(" ".join([node.attrs.get("class") or "", node.attrs.get("id") or ""])))


def _link_ratio(node):
    links = sum(_text_len(a) for a in _find_all(node, lambda n: n.tag == "a", []))
    total = _text_len(node)
    return links / total if total else 0


def _densest(node):
    """Baja por el árbol mientras un único hijo concentre casi todo el texto (quita menús alrededor del artículo)."""
    while True:
        total = _text_len(node)
        kids = [c for c in node.children if isinstance(c, Node) and not _is_noise(c)]
        best = max(kids, key=_text_len, default=None)
        if best is None or total == 0 or _text_len(best) < 0.8 * total or _text_len(best) < 300:
            return node
        node = best


def _main_node(root):
    """Elige el contenedor del artículo: <article> o <main> con más texto; si no, el <body>."""
    return _densest(_main_node_raw(root))


def _main_node_raw(root):
    for tag in ("article", "main"):
        cands = _find_all(root, lambda n, t=tag: n.tag == t, [])
        if cands:
            best = max(cands, key=_text_len)
            if _text_len(best) > 300:
                return best
    cands = _find_all(root, lambda n: n.tag == "div" and re.search(
        r"(article|post|entry|content|story)[-_]?(body|content|text)?", " ".join([n.attrs.get("class") or "", n.attrs.get("id") or ""]), re.I), [])
    if cands:
        best = max(cands, key=_text_len)
        if _text_len(best) > 300:
            return best
    bodies = _find_all(root, lambda n: n.tag == "body", [])
    return bodies[0] if bodies else root


# ---------- Conversión a markdown ----------

class _Md:
    def __init__(self, base_url):
        self.base = base_url
        self.out = []

    def inline(self, node):
        parts = []
        for c in node.children:
            if isinstance(c, str):
                parts.append(re.sub(r"\s+", " ", c))
                continue
            if c.tag in SKIP:
                continue
            if c.tag == "br":
                parts.append("  \n")
            elif c.tag in ("strong", "b"):
                t = self.inline(c).strip()
                parts.append(f"**{t}**" if t else "")
            elif c.tag in ("em", "i"):
                t = self.inline(c).strip()
                parts.append(f"*{t}*" if t else "")
            elif c.tag == "code":
                t = "".join(self._raw(c)).strip()
                parts.append(f"`{t}`" if t else "")
            elif c.tag == "a":
                t = self.inline(c).strip()
                href = urllib.parse.urljoin(self.base, c.attrs.get("href") or "")
                parts.append(f"[{t}]({href})" if t and href.startswith("http") else t)
            elif c.tag == "img":
                continue
            else:
                parts.append(self.inline(c))
        return "".join(parts)

    def _raw(self, node):
        for c in node.children:
            if isinstance(c, str):
                yield c
            elif c.tag not in SKIP:
                yield from self._raw(c)

    def emit(self, text):
        text = text.strip()
        if text:
            self.out.append(text)

    def block(self, node, depth=0):
        buf = []

        def flush():
            t = "".join(buf).strip()
            if t:
                self.emit(t)
            buf.clear()

        for c in node.children:
            if isinstance(c, str):
                buf.append(re.sub(r"\s+", " ", c))
                continue
            tag = c.tag
            if _is_noise(c):
                continue
            # Listas que son casi todo enlaces (menús, "artículos relacionados", idiomas)
            if tag in ("ul", "ol") and _link_ratio(c) > 0.7 and len([li for li in c.children if isinstance(li, Node)]) > 3:
                continue
            if tag not in BLOCK:
                buf.append(self._inline_one(c))
                continue
            flush()
            if re.fullmatch(r"h[1-6]", tag):
                t = self.inline(c).strip()
                if t:
                    self.emit("#" * int(tag[1]) + " " + t)
            elif tag in ("ul", "ol"):
                self.list(c, depth, ordered=(tag == "ol"))
            elif tag == "pre":
                code = "".join(self._raw(c)).strip("\n")
                if code.strip():
                    self.emit("```\n" + code + "\n```")
            elif tag == "blockquote":
                sub = _Md(self.base)
                sub.block(c, depth)
                if sub.out:
                    self.emit("\n".join("> " + line if line else ">" for line in "\n\n".join(sub.out).split("\n")))
            elif tag == "table":
                self.table(c)
            elif tag == "hr":
                self.emit("---")
            elif tag == "br":
                buf.append("  \n")
            else:
                self.block(c, depth)
        flush()

    def _inline_one(self, node):
        wrapper = Node("span")
        wrapper.children = [node]
        return self.inline(wrapper)

    def list(self, node, depth, ordered):
        n = 0
        for li in node.children:
            if not isinstance(li, Node) or li.tag != "li":
                continue
            n += 1
            text_parts, nested = [], []
            for c in li.children:
                if isinstance(c, Node) and c.tag in ("ul", "ol"):
                    nested.append(c)
                elif isinstance(c, Node) and c.tag in ("p", "div"):
                    text_parts.append(self.inline(c))
                elif isinstance(c, Node) and c.tag not in SKIP:
                    text_parts.append(self._inline_one(c))
                elif isinstance(c, str):
                    text_parts.append(re.sub(r"\s+", " ", c))
            text = " ".join(" ".join(text_parts).split())
            marker = f"{n}." if ordered else "-"
            if text:
                self.out.append("  " * depth + f"{marker} {text}")
            for sub in nested:
                self.list(sub, depth + 1, ordered=(sub.tag == "ol"))

    def table(self, node):
        rows = []
        for tr in _find_all(node, lambda n: n.tag == "tr", []):
            cells = [" ".join(self.inline(td).split()).replace("|", "\\|") for td in tr.children
                     if isinstance(td, Node) and td.tag in ("td", "th")]
            if any(cells):
                rows.append(cells)
        if not rows:
            return
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        lines = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * width]
        lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
        self.emit("\n".join(lines))


def _join(lines):
    """Une bloques con línea en blanco, salvo elementos de lista consecutivos."""
    out = []
    for line in lines:
        is_item = bool(re.match(r"\s*(-|\d+\.) ", line))
        if out and not (is_item and re.match(r"\s*(-|\d+\.) ", out[-1].split("\n")[-1])):
            out.append("")
        out.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


# ---------- API ----------

def import_url(url):
    """Devuelve (metadatos, markdown) de la página."""
    url = url.strip()
    if not re.match(r"https?://", url, re.I):
        url = "https://" + url
    html, final_url, ctype = fetch(url)
    if not re.search(r"html", ctype):
        body = html.strip()
        meta = {"title": final_url.rsplit("/", 1)[-1] or final_url, "url": final_url}
    else:
        tb = _TreeBuilder()
        tb.feed(html)
        m = tb.meta
        title = m.get("og:title") or m.get("twitter:title") or unescape(tb.title).strip() or final_url
        # Quita el sufijo con el nombre del sitio ("Artículo - Wikipedia, la enciclopedia libre")
        host_words = [w for w in (urllib.parse.urlsplit(final_url).hostname or "").lower().split(".") if len(w) > 3]
        site = (m.get("og:site_name") or "").lower()
        mt = re.match(r"(.{2,}?)\s+[-|—·:]\s+(.+)$", title)
        if mt and (site and site in mt.group(2).lower() or any(w in mt.group(2).lower() for w in host_words)):
            title = mt.group(1)
        # ...o el prefijo ("GitHub - usuario/repo: descripción")
        elif mt and mt.group(1).strip().lower() in {site, *host_words}:
            title = mt.group(2)
        # Páginas de wiki de GitHub: el título solo ("Getting Started") es demasiado genérico
        gh = re.match(r"https://github\.com/([^/]+/[^/]+)/wiki/", final_url)
        if gh and gh.group(1).lower() not in title.lower():
            title = f"{gh.group(1)} wiki: {title}"
        # GitHub añade a la descripción una coletilla que no aporta nada
        desc = re.sub(r"\s*Contribute to \S+ development by creating an account on GitHub\.?\s*$", "",
                      " ".join((m.get("og:description") or m.get("description") or "").split()))
        meta = {
            "title": " ".join(title.split()),
            "url": m.get("og:url") if (m.get("og:url") or "").startswith("http") else final_url,
            "autor": m.get("author") or m.get("article:author") or m.get("parsely-author") or "",
            "fecha_publicacion": (m.get("article:published_time") or m.get("date") or m.get("dc.date") or "")[:10],
            "sitio": m.get("og:site_name") or urllib.parse.urlsplit(final_url).hostname or "",
            "descripcion": desc,
        }
        md = _Md(final_url)
        md.block(_main_node(tb.root))
        body = _join(md.out)
        heading = lambda line: re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", line[2:]).strip()  # sin enlaces
        # Si el título es solo el nombre del sitio ("Google Style Guides"), usa el primer h1 propio
        if meta["title"].lower() in {site, (meta["sitio"] or "").lower()}:
            h1 = next((heading(l) for l in body.split("\n") if l.startswith("# ")
                       and heading(l).lower() not in {site, meta["title"].lower()}), "")
            if h1:
                meta["title"] = h1
        # Archivo de un repo de GitHub ("nips/46.md at master · org/repo"): el título está en el documento
        if re.match(r"https://github\.com/[^/]+/[^/]+/blob/", meta["url"]):
            lines = [l for l in body.split("\n") if l.strip()]
            if lines and lines[0].startswith("# "):
                meta["title"] = heading(lines[0])
                # "# NIP-46" seguido de "## Nostr Remote Signing" -> "NIP-46: Nostr Remote Signing"
                if re.fullmatch(r"NIP-\w+", meta["title"]) and len(lines) > 1 and lines[1].startswith("## "):
                    meta["title"] += ": " + heading(lines[1][1:])
        # Quita los primeros títulos que repitan el de la página o el nombre del sitio
        while body.startswith("# ") and heading(body.split("\n", 1)[0]).lower() in {
                meta["title"].lower(), site, (meta["sitio"] or "").lower()}:
            body = body.split("\n", 1)[1].strip() if "\n" in body else ""
    if len(re.sub(r"\s+", "", body)) < 200:
        raise ImportError_("No se pudo extraer el texto del artículo (puede que la web lo cargue con JavaScript o pida "
                           "iniciar sesión). Copia y pega el texto a mano.")
    return meta, body
