from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from medagent.rag.answer import (
    NO_ANSWER,
    AnswerPayload,
    answer_question,
    build_prompt,
    estimate_tokens,
)
from medagent.rag.chunking import CHUNK_SIZE, chunk_pages, context_header
from medagent.rag.ingest import document_hash
from medagent.rag.loaders import MedlinePlusLoader, PdfLoader, html_to_text
from medagent.rag.retriever import ScoreReranker, reciprocal_rank_fusion
from medagent.rag.types import Candidate, PageText, RawDocument
from tests.fakes import FakeAnswerLLM

FIXTURES = Path(__file__).parent.parent / "fixtures"


# ------------------------------------------------------------------ chunking
def test_chunks_keep_their_page_and_are_numbered_in_order() -> None:
    pages = [
        PageText("Alpha sentence about hearts. " * 80, page=1),
        PageText("Beta sentence about lungs. " * 80, page=2),
    ]
    chunks = chunk_pages(pages)
    assert [c.index for c in chunks] == list(range(len(chunks)))
    assert {c.page for c in chunks} == {1, 2}
    assert all("lungs" not in c.text for c in chunks if c.page == 1)
    assert all(len(c.text) <= CHUNK_SIZE for c in chunks)


def test_consecutive_chunks_overlap() -> None:
    text = " ".join(f"word{i}" for i in range(600))
    chunks = chunk_pages([PageText(text, page=None)], chunk_size=300, overlap=60)
    assert len(chunks) > 2
    assert chunks[0].text.split()[-1] in chunks[1].text  # tail of one reappears in the next


def test_tiny_fragments_are_dropped() -> None:
    assert chunk_pages([PageText("12", page=1), PageText("   ", page=2)]) == []


# ------------------------------------------------------------------ fusion + rerank
def test_rrf_rewards_agreement_between_lists() -> None:
    scores = reciprocal_rank_fusion([[1, 2, 3], [3, 1, 4]], k=60)
    assert scores[1] == pytest.approx(1 / 61 + 1 / 62)
    assert scores[3] == pytest.approx(1 / 63 + 1 / 61)
    assert max(scores, key=lambda i: scores[i]) == 1
    assert scores[2] == pytest.approx(1 / 62)  # only in one list
    assert reciprocal_rank_fusion([]) == {}


def _cand(chunk_id: int, sim: float, fused: float) -> Candidate:
    return Candidate(
        chunk_id=chunk_id,
        content=f"chunk {chunk_id}",
        document_title="Doc",
        source_key="s",
        url=None,
        attribution="Src - long name",
        page=None,
        vector_sim=sim,
        fused_score=fused,
    )


def test_score_reranker_orders_by_blended_score() -> None:
    best = 2 / 61
    low_sim_high_rank = _cand(1, sim=0.2, fused=best)
    high_sim_low_rank = _cand(2, sim=0.9, fused=0.2 * best)
    ranked = ScoreReranker(similarity_weight=0.6).rerank(
        "q", [low_sim_high_rank, high_sim_low_rank]
    )
    assert [c.chunk_id for c in ranked] == [2, 1]
    assert ranked[0].final_score == pytest.approx(0.6 * 0.9 + 0.4 * 0.2)


def test_citation_formats() -> None:
    paged = _cand(1, 0.5, 0.0)
    paged.page = 12
    paged.document_title = "Medical_book"
    assert paged.citation == "[Medical_book p.12]"
    web = _cand(2, 0.5, 0.0)
    web.document_title = "Diabetes"
    web.attribution = "MedlinePlus - National Library of Medicine (medlineplus.gov)"
    assert web.citation == "[MedlinePlus: Diabetes]"


# ------------------------------------------------------------------ loaders
def test_html_to_text_strips_tags_and_keeps_structure() -> None:
    text = html_to_text(
        "&lt;p&gt;Hello &lt;a href='x'&gt;world&lt;/a&gt;&lt;/p&gt;"
        "&lt;ul&gt;&lt;li&gt;one&lt;/li&gt;&lt;/ul&gt;"
    )
    assert "Hello world" in text
    assert "- one" in text
    assert "<" not in text


def test_medlineplus_loader_filters_and_maps_fields() -> None:
    loader = MedlinePlusLoader(FIXTURES / "medlineplus_sample.xml")
    docs = list(loader.load())
    assert [d.title for d in docs] == ["Diabetes", "Adam's Apple"]  # no Spanish/empty/third-party
    diabetes = docs[0]
    assert diabetes.is_public
    assert diabetes.url == "https://medlineplus.gov/diabetes.html"
    assert diabetes.source_key == "medlineplus"
    assert "Public domain" in diabetes.license
    assert "MedlinePlus" in diabetes.attribution
    body = diabetes.pages[0].text
    assert "increased thirst" in body
    assert "Also called: Diabetes mellitus, High blood sugar" in body
    assert "Merck" not in body  # external <site> link records are never ingested
    assert diabetes.pages[0].page is None


def test_third_party_copyrighted_topics_are_excluded_and_reported() -> None:
    loader = MedlinePlusLoader(FIXTURES / "medlineplus_sample.xml")
    list(loader.load())
    assert loader.excluded == ["Licensed Encyclopedia Entry"]


def test_medlineplus_loader_respects_limit() -> None:
    assert len(list(MedlinePlusLoader(FIXTURES / "medlineplus_sample.xml", limit=1).load())) == 1


def _tiny_pdf(texts: list[str]) -> bytes:
    """Hand-built minimal PDF, one text line per page (pypdf can read but not draw text)."""
    objects: list[bytes] = []
    n = len(texts)
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode())
    for i, text in enumerate(texts):
        content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
        page = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {4 + 2 * i} 0 R "
            "/Resources << /Font << /F1 << /Type /Font /Subtype /Type1 "
            "/BaseFont /Helvetica >> >> >> >>"
        )
        objects.append(page.encode())
        objects.append(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(out)


def test_pdf_loader_gives_one_document_with_numbered_pages(tmp_path: Path) -> None:
    pdf = tmp_path / "book.pdf"
    pdf.write_bytes(_tiny_pdf(["Heart disease facts", "Lung disease facts"]))
    loader = PdfLoader(
        pdf,
        source_key="book",
        title="Book",
        license="x",
        attribution="Book - local",
        is_public=False,
    )
    (doc,) = list(loader.load())
    assert doc.external_id == "book.pdf"
    assert not doc.is_public
    assert [(p.page, p.text) for p in doc.pages] == [
        (1, "Heart disease facts"),
        (2, "Lung disease facts"),
    ]


# ------------------------------------------------------------------ ingest hashing
def _doc(**overrides: object) -> RawDocument:
    base: dict[str, object] = {
        "source_key": "s",
        "external_id": "1",
        "title": "T",
        "pages": (PageText("some text here", 1),),
        "license": "L",
        "attribution": "A",
        "is_public": True,
    }
    return RawDocument(**{**base, **overrides})  # type: ignore[arg-type]


def test_document_hash_changes_with_text_or_metadata_only() -> None:
    base = document_hash(_doc())
    assert document_hash(_doc()) == base
    assert document_hash(_doc(pages=(PageText("other text", 1),))) != base
    assert document_hash(_doc(is_public=False)) != base
    assert document_hash(_doc(license="M")) != base


def test_context_header_names_topic_and_synonyms_but_not_paged_sources() -> None:
    topic = _doc(pages=(PageText("body", None),), title="Flu", synonyms=("Influenza", "Grippe"))
    assert context_header(topic) == "Flu (also called: Influenza, Grippe)"
    assert context_header(_doc(pages=(PageText("body", None),), title="Gout")) == "Gout"
    assert context_header(_doc()) == ""  # paged source: the title is a file name


def test_document_hash_changes_with_the_header() -> None:
    plain = _doc(pages=(PageText("body", None),))
    assert document_hash(plain) != document_hash(
        _doc(pages=(PageText("body", None),), synonyms=("X",))
    )


# ------------------------------------------------------------------ answering
class _FakeRetriever:
    def __init__(self, candidates: list[Candidate]) -> None:
        self.candidates = candidates
        self.public_only_seen: bool | None = None

    def search(
        self, session: Session, query: str, k: int = 5, public_only: bool = False
    ) -> list[Candidate]:
        self.public_only_seen = public_only
        return self.candidates[:k]


def _payload(**kw: object) -> AnswerPayload:
    base: dict[str, object] = {
        "answer": "Symptoms include thirst [MedlinePlus: Diabetes].",
        "used_sources": [1],
        "context_sufficient": True,
    }
    return AnswerPayload(**{**base, **kw})  # type: ignore[arg-type]


def _web_candidate(sim: float = 0.8) -> Candidate:
    c = _cand(7, sim, 0.01)
    c.document_title = "Diabetes"
    c.attribution = "MedlinePlus - National Library of Medicine (medlineplus.gov)"
    c.url = "https://medlineplus.gov/diabetes.html"
    return c


def test_grounded_answer_has_citations_and_disclaimer() -> None:
    llm = FakeAnswerLLM(_payload())
    result = answer_question(
        None, _FakeRetriever([_web_candidate()]), llm, "symptoms?", min_score=0.3
    )  # type: ignore[arg-type]
    assert result.grounded
    assert [s.label for s in result.sources] == ["MedlinePlus: Diabetes"]
    rendered = result.render()
    assert "medlineplus.gov/diabetes.html" in rendered
    assert "not medical advice" in rendered
    assert "[MedlinePlus: Diabetes]" in llm.calls[0][1]  # labelled passage reached the prompt


def test_weak_evidence_says_dont_know_without_calling_the_llm() -> None:
    llm = FakeAnswerLLM(_payload())
    result = answer_question(
        None,
        _FakeRetriever([_web_candidate(sim=0.1)]),
        llm,
        "q",
        min_score=0.35,  # type: ignore[arg-type]
    )
    assert not result.grounded
    assert result.answer == NO_ANSWER
    assert llm.calls == []
    assert "not medical advice" in result.render()  # disclaimer even on refusals


def test_no_results_says_dont_know() -> None:
    llm = FakeAnswerLLM(_payload())
    assert not answer_question(None, _FakeRetriever([]), llm, "q", min_score=0.3).grounded  # type: ignore[arg-type]
    assert llm.calls == []


def test_llm_saying_context_insufficient_is_respected() -> None:
    llm = FakeAnswerLLM(_payload(context_sufficient=False))
    result = answer_question(None, _FakeRetriever([_web_candidate()]), llm, "q", min_score=0.3)  # type: ignore[arg-type]
    assert not result.grounded
    assert result.sources == []


def test_hallucinated_source_numbers_are_dropped() -> None:
    llm = FakeAnswerLLM(_payload(used_sources=[1, 9, 0, -2]))
    result = answer_question(None, _FakeRetriever([_web_candidate()]), llm, "q", min_score=0.3)  # type: ignore[arg-type]
    assert len(result.sources) == 1
    only_bogus = FakeAnswerLLM(_payload(used_sources=[5]))
    assert not answer_question(
        None, _FakeRetriever([_web_candidate()]), only_bogus, "q", min_score=0.3
    ).grounded  # type: ignore[arg-type]


def test_public_only_flag_is_forwarded_to_the_retriever() -> None:
    retriever = _FakeRetriever([_web_candidate()])
    answer_question(
        None, retriever, FakeAnswerLLM(_payload()), "q", min_score=0.3, public_only=True
    )  # type: ignore[arg-type]
    assert retriever.public_only_seen is True


def test_prompt_numbers_passages_and_token_estimate_is_positive() -> None:
    prompt = build_prompt([_web_candidate(), _web_candidate()])
    assert "[1] (label: MedlinePlus: Diabetes)" in prompt
    assert "[2] (label: MedlinePlus: Diabetes)" in prompt
    assert estimate_tokens(prompt) > 50


def test_a_dose_in_the_llm_answer_is_replaced_before_anything_reaches_the_caller() -> None:
    """The dose guard lives in answer_question itself, so the CLI and any other caller get it
    too, not only the graph's output guard."""
    from medagent.guardrails.dose import DOSE_REFERRAL

    llm = FakeAnswerLLM(
        _payload(answer="The usual adult dose is 400 mg [MedlinePlus: Diabetes].", used_sources=[1])
    )
    result = answer_question(
        None,
        _FakeRetriever([_web_candidate()]),
        llm,
        "how much?",
        min_score=0.3,  # type: ignore[arg-type]
    )
    assert result.answer == DOSE_REFERRAL
    assert not result.grounded
    assert result.sources == []  # nothing to cite: no medical content is being shown
    assert "400" not in result.render()
    assert len(llm.calls) == 1  # the model was asked; its answer was withheld


def test_an_answer_without_a_dose_is_unchanged_by_the_dose_guard() -> None:
    llm = FakeAnswerLLM(_payload())  # "Symptoms include thirst [MedlinePlus: Diabetes]."
    result = answer_question(
        None,
        _FakeRetriever([_web_candidate()]),
        llm,
        "symptoms?",
        min_score=0.3,  # type: ignore[arg-type]
    )
    assert result.grounded
    assert result.answer.startswith("Symptoms include thirst")
