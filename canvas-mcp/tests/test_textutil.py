import pytest

from canvas_mcp.textutil import chunk, extract_text, html_to_text


def make_pdf(text: str) -> bytes:
    """Build a minimal one-page PDF containing `text`."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


def test_html_to_text_strips_tags_and_keeps_structure():
    html = "<p>Read <b>chapter 3</b>.</p><ul><li>Problem 1</li><li>Problem 2</li></ul><script>x()</script>"
    text = html_to_text(html)
    assert "Read chapter 3." in text
    assert "- Problem 1" in text and "- Problem 2" in text
    assert "x()" not in text
    assert "<" not in text


def test_html_to_text_keeps_link_targets():
    assert "Notes (https://ocw.mit.edu/x)" in html_to_text('<a href="https://ocw.mit.edu/x">Notes</a>')


def test_html_to_text_handles_none():
    assert html_to_text(None) == ""


def test_extract_text_from_pdf():
    assert "Eigenvalues lecture" in extract_text(make_pdf("Eigenvalues lecture"), "application/pdf", "l5.pdf")


def test_extract_text_from_plain_text():
    assert extract_text(b"hello", "text/plain", "a.txt") == "hello"


def test_extract_text_from_html_file():
    assert extract_text(b"<h1>Syllabus</h1>", "text/html", "s.html").strip() == "Syllabus"


def test_extract_text_unsupported_type():
    with pytest.raises(ValueError, match="can't read"):
        extract_text(b"\x00", "image/png", "a.png")


def test_chunk_pages_and_footer():
    text = "a" * 15000
    first = chunk(text, page=1, size=6000)
    assert first.startswith("a" * 6000)
    assert first.endswith("[part 1 of 3 — call again with page=2 for more]")
    assert chunk(text, page=3, size=6000).endswith("[part 3 of 3]")


def test_chunk_out_of_range():
    assert "only has 1 part" in chunk("short", page=5)
