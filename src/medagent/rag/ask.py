"""CLI: ask a question against the knowledge base and get a cited answer.

uv run python -m medagent.rag.ask "What are the symptoms of diabetes?"
uv run python -m medagent.rag.ask "..." --retrieval-only     # no LLM call, no cost
"""

import argparse

from medagent.core.config import get_settings
from medagent.db.session import get_sessionmaker
from medagent.rag.answer import AnthropicAnswerLLM, answer_question, build_prompt, estimate_tokens
from medagent.rag.embeddings import get_embedder
from medagent.rag.retriever import HybridRetriever


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("question")
    parser.add_argument("-k", type=int, default=5, help="passages to retrieve")
    parser.add_argument("--show-context", action="store_true", help="print retrieved passages")
    parser.add_argument("--retrieval-only", action="store_true", help="no LLM call")
    args = parser.parse_args()

    settings = get_settings()
    retriever = HybridRetriever(get_embedder())
    with get_sessionmaker()() as session:
        if args.show_context or args.retrieval_only:
            hits = retriever.search(
                session, args.question, k=args.k, public_only=settings.kb_public_only
            )
            for rank, c in enumerate(hits, start=1):
                print(
                    f"{rank}. {c.citation} sim={c.vector_sim:.3f} score={c.final_score:.3f} "
                    f"(vec#{c.vector_rank}, fts#{c.text_rank})\n   {c.content[:160]!r}"
                )
            tokens = estimate_tokens(build_prompt(hits)) if hits else 0
            print(f"~{tokens} prompt tokens if sent to the LLM\n")
        if args.retrieval_only:
            return
        llm = AnthropicAnswerLLM(settings)
        result = answer_question(session, retriever, llm, args.question, k=args.k)
    print(result.render())


if __name__ == "__main__":
    main()
