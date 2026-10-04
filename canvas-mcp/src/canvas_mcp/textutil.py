"""Turn Canvas HTML and course files into plain text a small model can read."""

from __future__ import annotations

import io
import re
from html.parser import HTMLParser

from pypdf import PdfReader

_BLOCK_TAGS = {"p", "div", "br", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "table", "ul", "ol", "pre", "blockquote"}
_SKIP_TAGS = {"script", "style", "head"}
MAX_PDF_PAGES = 300  # bound parsing time/memory on huge or hostile PDFs


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0
        self._href: str | None = None

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")
        elif tag == "a":
            self._href = dict(attrs).get("href")

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")
        elif tag == "a" and self._href:
            if self._href.startswith("http"):
                self.parts.append(f" ({self._href})")
            self._href = None

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str | None) -> str:
    if not html:
        return ""
    parser = _TextParser()
    parser.feed(html)
    text = "".join(parser.parts)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def extract_text(data: bytes, content_type: str | None, filename: str) -> str:
    ctype = (content_type or "").lower()
    name = filename.lower()
    if "pdf" in ctype or name.endswith(".pdf"):
        reader = PdfReader(io.BytesIO(data))
        pages = [p.extract_text() or "" for p in reader.pages[:MAX_PDF_PAGES]]
        return "\n\n".join(f"--- slide/page {i} ---\n{t.strip()}" for i, t in enumerate(pages, 1) if t.strip())
    if "html" in ctype or name.endswith((".html", ".htm")):
        return html_to_text(data.decode("utf-8", errors="replace"))
    if ctype.startswith("text/") or name.endswith((".txt", ".md", ".csv", ".py", ".tex")):
        return data.decode("utf-8", errors="replace")
    raise ValueError(f"can't read this file type ({content_type or filename}); only PDF and text files are supported")


def chunk(text: str, page: int = 1, size: int = 6000) -> str:
    total = max(1, -(-len(text) // size))
    if page < 1 or page > total:
        return f"[this file only has {total} part{'s' if total > 1 else ''}]"
    body = text[(page - 1) * size : page * size]
    if total == 1:
        return body
    more = f" — call again with page={page + 1} for more" if page < total else ""
    return f"{body}\n\n[part {page} of {total}{more}]"
