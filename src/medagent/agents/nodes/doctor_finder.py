"""Symptoms -> specialty (an enum, chosen by the LLM) -> doctors from the database."""

from typing import Any

import structlog

from medagent.agents.deps import AgentDeps
from medagent.agents.llm import LLMError
from medagent.agents.nodes.common import APOLOGY, Node, recent_messages
from medagent.agents.prompts.booking import DOCTOR_FINDER_SYSTEM_PROMPT
from medagent.agents.schemas import DoctorQuery
from medagent.agents.state import AgentState, DoctorOption
from medagent.db import repository

log = structlog.get_logger("medagent.agents")
MAX_OPTIONS = 5


def make_doctor_finder_node(deps: AgentDeps) -> Node:
    def doctor_finder_node(state: AgentState) -> dict[str, Any]:
        try:
            query = deps.llm.invoke(
                DoctorQuery, DOCTOR_FINDER_SYSTEM_PROMPT, recent_messages(state)
            )
        except LLMError as exc:
            log.warning("node_failed", node="doctor_finder", error=str(exc))
            return {"draft": APOLOGY, "draft_kind": "info"}

        specialty = query.specialty.value
        relaxed: list[str] = []
        with deps.session_factory() as session:
            doctors = repository.get_doctors(session, specialty, query.city, query.language)
            # Relax the optional filters one at a time rather than returning nothing.
            if not doctors and query.language:
                relaxed.append(f"speaking {query.language}")
                doctors = repository.get_doctors(session, specialty, query.city)
            if not doctors and query.city:
                relaxed.append(f"in {query.city}")
                doctors = repository.get_doctors(session, specialty)
            options = [
                DoctorOption(
                    id=d.id, name=d.name, specialty=d.specialty, city=d.city, languages=d.languages
                )
                for d in doctors[:MAX_OPTIONS]
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
