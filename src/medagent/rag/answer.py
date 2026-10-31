"""Cited answering over retrieved context, with an "I don't know" path that skips the LLM."""

from dataclasses import dataclass, field
from typing import Protocol

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from medagent.agents.llm import make_chat_model
from medagent.agents.prompts.rag import RAG_SYSTEM_PROMPT, format_context
from medagent.core.config import Settings, get_settings
from medagent.guardrails.disclaimer import DISCLAIMER
from medagent.rag.types import Candidate

NO_ANSWER = (
    "I don't know: the knowledge base doesn't contain enough relevant information to answer "
    "that reliably. Please ask a healthcare professional."
)


class AnswerPayload(BaseModel):
    """Structured output requested from the LLM (never parsed from free text)."""

    answer: str = Field(description="The answer with inline citations, or a short 'I don't know'.")
    used_sources: list[int] = Field(description="1-based numbers of the passages actually used.")
    context_sufficient: bool = Field(
        description="False if the passages cannot answer the question."
    )


class Retriever(Protocol):
    def search(
        self, session: Session, query: str, k: int = 5, public_only: bool = False
    ) -> list[Candidate]: ...


class AnswerLLM(Protocol):
    def generate(self, question: str, system_prompt: str) -> AnswerPayload: ...


class AnthropicAnswerLLM:
    def __init__(self, settings: Settings | None = None) -> None:
        # Default effort (answers need some reasoning). json_schema structured output works on
        # Sonnet 5.5 too, which rejects the forced tool call LangChain uses by default.
        model = make_chat_model(settings or get_settings(), effort="medium")
        self._chain = model.with_structured_output(AnswerPayload, method="json_schema")

    def generate(self, question: str, system_prompt: str) -> AnswerPayload:
        result = self._chain.invoke([("system", system_prompt), ("human", question)])
        assert isinstance(result, AnswerPayload)
        return result


@dataclass(frozen=True)
class SourceRef:
    label: str
    url: str | None
    attribution: str


@dataclass(frozen=True)
class RagAnswer:
    answer: str
    grounded: bool
    sources: list[SourceRef] = field(default_factory=list)
    disclaimer: str = DISCLAIMER

    def render(self) -> str:
        lines = [self.answer]
        if self.sources:
            lines += ["", "Sources:"]
            lines += [f"- {s.label}" + (f" <{s.url}>" if s.url else "") for s in self.sources]
            # one attribution line per distinct provider (licence requirement, e.g. MedlinePlus)
            lines += ["", *dict.fromkeys(f"Content: {s.attribution}" for s in self.sources)]
        lines += ["", self.disclaimer]
        return "\n".join(lines)


def estimate_tokens(text: str) -> int:
    """Rough (~4 characters per token); good enough to sanity-check cost before a real run."""
    return max(1, len(text) // 4)


def _label(candidate: Candidate) -> str:
    return candidate.citation.strip("[]")


def build_prompt(candidates: list[Candidate]) -> str:
    context = format_context([_label(c) for c in candidates], [c.content for c in candidates])
    return RAG_SYSTEM_PROMPT.format(context=context)


def answer_question(
    session: Session,
    retriever: Retriever,
    llm: AnswerLLM,
    question: str,
    *,
    k: int = 5,
    min_score: float | None = None,
    public_only: bool | None = None,
) -> RagAnswer:
    settings = get_settings()
    min_score = settings.rag_min_score if min_score is None else min_score
    public_only = settings.kb_public_only if public_only is None else public_only

    candidates = retriever.search(session, question, k=k, public_only=public_only)
    # Weak evidence: refuse without spending an LLM call (and without risking a made-up answer).
    if not candidates or max(c.vector_sim for c in candidates) < min_score:
        return RagAnswer(answer=NO_ANSWER, grounded=False)

    payload = llm.generate(question, build_prompt(candidates))
    used = sorted({n for n in payload.used_sources if 1 <= n <= len(candidates)})  # drop bogus ids
    if not payload.context_sufficient or not used:
        return RagAnswer(answer=NO_ANSWER, grounded=False)

    sources: list[SourceRef] = []
    for n in used:
        c = candidates[n - 1]
        ref = SourceRef(_label(c), c.url, c.attribution)
        if ref not in sources:
            sources.append(ref)
    return RagAnswer(answer=payload.answer.strip(), grounded=True, sources=sources)
