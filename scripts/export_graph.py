"""Write the compiled agent graph as Mermaid to docs/diagrams/agent_graph.md (no network needed).

uv run python scripts/export_graph.py
"""

from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from medagent.agents.deps import AgentDeps
from medagent.agents.graph import build_graph

OUT = Path("docs/diagrams/agent_graph.md")


class _Unused:
    """Placeholder dependencies: drawing the graph never calls them."""

    def __getattr__(self, name: str) -> object:
        raise RuntimeError("not used when drawing")


def main() -> None:
    deps = AgentDeps(
        tools=_Unused(),  # type: ignore[arg-type]
        llm=_Unused(),  # type: ignore[arg-type]
        answer_llm=_Unused(),  # type: ignore[arg-type]
        retriever=_Unused(),  # type: ignore[arg-type]
        session_factory=lambda: nullcontext(None),  # type: ignore[arg-type,return-value]
        clock=lambda: datetime.now(UTC),
        tz=ZoneInfo("Europe/Berlin"),
        public_only=True,
        rag_min_score=0.7,
    )
    mermaid = build_graph(deps).get_graph().draw_mermaid()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        "# Agent graph (generated)\n\n"
        "Generated from the compiled LangGraph by `uv run python scripts/export_graph.py`; "
        "do not edit by hand. Dotted edges are conditional or `Command` routes.\n\n"
        f"```mermaid\n{mermaid}```\n",
        encoding="utf-8",
    )
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
