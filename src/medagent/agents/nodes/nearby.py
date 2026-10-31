"""Real clinics near a place, from OpenStreetMap. Clearly separated from the bookable demo doctors:
these results are never offered for booking and always carry the ODbL attribution."""

from typing import Any

import structlog

from medagent.agents.deps import AgentDeps
from medagent.agents.llm import LLMError
from medagent.agents.nodes.common import APOLOGY, Node, recent_messages
from medagent.agents.schemas import NearbyQuery
from medagent.agents.state import AgentState
from medagent.tools.clinic import ToolError

log = structlog.get_logger("medagent.agents")

NEARBY_SYSTEM_PROMPT = (
    "Extract the city or place the user wants clinics near. Leave it empty if none."
)
NOT_BOOKABLE = (
    "These are real places from OpenStreetMap; I can't book them. I can book appointments with the "
    "MedAgent demo clinic's doctors (fictional), if you'd like."
)
MAX_SHOWN = 8


def make_nearby_node(deps: AgentDeps) -> Node:
    async def nearby_node(state: AgentState) -> dict[str, Any]:
        try:
            query = await deps.llm.ainvoke(
                NearbyQuery, NEARBY_SYSTEM_PROMPT, recent_messages(state)
            )
            if not query.city:
                return {"draft": "Near which city or place should I look?", "draft_kind": "info"}
            result = await deps.tools.find_nearby_clinics(query.city)
        except (LLMError, ToolError) as exc:
            log.warning("node_failed", node="nearby_clinics", error=str(exc))
            return {"draft": APOLOGY, "draft_kind": "info"}

        if not result.clinics:
            reason = (
                "I couldn't reach OpenStreetMap just now."
                if result.error
                else f"I couldn't find clinics on OpenStreetMap near {result.city}."
            )
            return {"draft": f"{reason}\n\n{result.attribution}", "draft_kind": "nearby"}
        lines = [f"Clinics and hospitals near {result.city} (OpenStreetMap):"]
        for i, clinic in enumerate(result.clinics[:MAX_SHOWN], 1):
            details = ", ".join(p for p in (clinic.kind, clinic.address) if p)
            lines.append(f"{i}. {clinic.name} ({details}) {clinic.website or clinic.osm_url}")
        lines += ["", NOT_BOOKABLE, result.attribution]
        return {"draft": "\n".join(lines), "draft_kind": "nearby"}

    return nearby_node
