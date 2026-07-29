# career_hunt/htmltext.py
"""Visible-text extraction from posting HTML — shared by feeds/jd_hydrate.py and
career_hunt.sources.ats (moved here from jd_hydrate so sources never import feeds)."""
from html.parser import HTMLParser


class _Text(HTMLParser):
    """Visible-text extractor: drops script/style/head, collapses whitespace."""

    SKIP = {"script", "style", "head", "noscript", "svg", "template"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.chunks, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            t = " ".join(data.split())
            if t:
                self.chunks.append(t)


def extract_text(html: str) -> str:
    p = _Text()
    p.feed(html)
    return "\n".join(p.chunks)
