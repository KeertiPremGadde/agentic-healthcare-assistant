"""Symptoms -> specialty (an enum, chosen by the LLM) -> doctors via the clinic tools."""

from typing import Any

import structlog

from medagent.agents.deps import AgentDeps
from medagent.agents.llm import LLMError
from medagent.agents.nodes.common import APOLOGY, Node, recent_messages
from medagent.agents.prompts.booking import DOCTOR_FINDER_SYSTEM_PROMPT
from medagent.agents.schemas import DoctorQuery
from medagent.agents.state import AgentState, DoctorOption
from medagent.tools.clinic import ToolError

log = structlog.get_logger("medagent.agents")

MAX_OPTIONS = 5


def make_doctor_finder_node(deps: AgentDeps) -> Node:
    async def doctor_finder_node(state: AgentState) -> dict[str, Any]:
        try:
            query = await deps.llm.ainvoke(
                DoctorQuery, DOCTOR_FINDER_SYSTEM_PROMPT, recent_messages(state)
            )
            specialty = query.specialty.value
            relaxed: list[str] = []
            found = await deps.tools.search_doctors(
                specialty, query.city, query.language, limit=MAX_OPTIONS
            )
            # Relax the optional filters one at a time rather than returning nothing.
            if not found.doctors and query.language:
                relaxed.append(f"speaking {query.language}")
                found = await deps.tools.search_doctors(specialty, query.city, limit=MAX_OPTIONS)
            if not found.doctors and query.city:
                relaxed.append(f"in {query.city}")
                found = await deps.tools.search_doctors(specialty, limit=MAX_OPTIONS)
        except (LLMError, ToolError) as exc:
            log.warning("node_failed", node="doctor_finder", error=str(exc))
            return {"draft": APOLOGY, "draft_kind": "info"}

        options = [
            DoctorOption(
                id=d.id, name=d.name, specialty=d.specialty, city=d.city, languages=d.languages
            )
            for d in found.doctors
        ]
        if not options:
            text = f"I couldn't find a {specialty} at the clinic right now."
            return {"doctor_options": [], "draft": text, "draft_kind": "doctors"}
        lines = [f"Based on what you describe, a {specialty} is the right specialist to see."]
        if relaxed:
            lines.append(f"I couldn't find one {' and '.join(relaxed)}, so here are others:")
        else:
            lines.append("Doctors you can book:")
        lines += [
            f"{i}. {o['name']} - {o['city']} ({', '.join(o['languages'])})"
            for i, o in enumerate(options, 1)
        ]
        lines.append(
            'Tell me which doctor and when, for example: "Book number 1 next Tuesday afternoon".'
        )
        return {
            "doctor_options": options,
            "booking_doctor_id": None,
            "draft": "\n".join(lines),
            "draft_kind": "doctors",
        }

    return doctor_finder_node
