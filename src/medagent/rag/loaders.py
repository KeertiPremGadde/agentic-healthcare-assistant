"""Source loaders. Ingestion only needs `Iterator[RawDocument]`, so adding a source means
adding a loader here, not touching the pipeline."""

import html
import re
from collections.abc import Iterator
from html.parser import HTMLParser
from pathlib import Path
from typing import ClassVar, Protocol
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as SafeET
from pypdf import PdfReader

from medagent.rag.types import PageText, RawDocument


class DocumentLoader(Protocol):
    def load(self) -> Iterator[RawDocument]: ...


def _clean(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


class PdfLoader:
    """One RawDocument per PDF, one PageText per page (1-based)."""

    def __init__(
        self,
        path: Path,
        *,
        source_key: str,
        title: str,
        license: str,
        attribution: str,
        is_public: bool,
    ) -> None:
        self.path = path
        self.meta = {
            "source_key": source_key,
            "title": title,
            "license": license,
            "attribution": attribution,
            "is_public": is_public,
        }

    def load(self) -> Iterator[RawDocument]:
        reader = PdfReader(self.path)
        pages = tuple(
            PageText(text=_clean(page.extract_text() or ""), page=number)
            for number, page in enumerate(reader.pages, start=1)
        )
        yield RawDocument(
            external_id=self.path.name,
            pages=tuple(p for p in pages if p.text),
            **self.meta,  # type: ignore[arg-type]
        )


class _TextExtractor(HTMLParser):
    """Minimal HTML -> text: paragraphs/list items/headings become separate lines."""

    BLOCK: ClassVar[set[str]] = {"p", "li", "h1", "h2", "h3", "h4", "br", "ul", "ol", "div"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.BLOCK:
            self.parts.append("\n")
            if tag == "li":
                self.parts.append("- ")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def html_to_text(markup: str) -> str:
    parser = _TextExtractor()
    parser.feed(html.unescape(markup) if "&lt;" in markup else markup)
    return _clean("".join(parser.parts))


# Third-party copyrighted material (A.D.A.M. encyclopedia, ASHP drug monographs, ...) is NOT
# public domain. MedlinePlus Health Topics currently contain none; this guard keeps it that way.
THIRD_PARTY_MARKERS = re.compile(
    r"A\.D\.A\.M|(?-i:\bADAM\b|\bASHP\b)|\u00a9|"
    r"copyright|all rights reserved|reprinted (?:with|by)",
    re.IGNORECASE,
)


class MedlinePlusLoader:
    """MedlinePlus Health Topics XML (https://medlineplus.gov/xml.html), English topics only.

    Content is written by the US National Library of Medicine: a US federal work, not
    copyrighted; NLM asks that MedlinePlus be acknowledged as the source. Only the title,
    `full-summary` and `also-called` synonyms are used; the external `<site>` link records
    (third-party sites) are never ingested, and topics carrying third-party copyright markers
    are excluded.
    """

    SOURCE_KEY = "medlineplus"
    LICENSE = "Public domain (US federal work), NLM"
    ATTRIBUTION = "MedlinePlus - National Library of Medicine (medlineplus.gov)"

    def __init__(self, xml_path: Path, limit: int | None = None) -> None:
        self.xml_path = xml_path
        self.limit = limit
        self.excluded: list[str] = []  # titles skipped by the third-party-content guard

    def load(self) -> Iterator[RawDocument]:
        count = 0
        for _, element in SafeET.iterparse(self.xml_path, events=("end",)):
            if element.tag != "health-topic":
                continue
            if element.get("language") == "English":
                doc = self._to_document(element)
                if doc is not None:
                    yield doc
                    count += 1
                    if self.limit is not None and count >= self.limit:
                        return
            element.clear()  # keep memory flat on the 30 MB file

    def _to_document(self, topic: Element) -> RawDocument | None:
        title = topic.get("title", "").strip()
        summary = html_to_text(topic.findtext("full-summary") or "")
        if not title or not summary:
            return None
        if THIRD_PARTY_MARKERS.search(summary):
            self.excluded.append(title)
            return None
        synonyms = [s.text.strip() for s in topic.findall("also-called") if s.text]
        body = f"{title}\n\n{summary}"
        if synonyms:
            body += f"\n\nAlso called: {', '.join(synonyms)}"
        return RawDocument(
            source_key=self.SOURCE_KEY,
            external_id=topic.get("id", title),
            title=title,
            pages=(PageText(text=body, page=None),),
            license=self.LICENSE,
            attribution=self.ATTRIBUTION,
            is_public=True,
            url=topic.get("url"),
        )
