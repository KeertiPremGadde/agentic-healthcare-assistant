"""Builds the multi-agent graph.

START -> guardrail -> supervisor -> {medical_rag | doctor_finder | booking | respond}
booking -> confirm (interrupt) -> book_appointment
every path ends in output_guard -> END (emergencies skip the supervisor entirely)
"""

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from medagent.agents.deps import AgentDeps
from medagent.agents.nodes.booking import (
    confirm_node,
    make_book_appointment_node,
    make_booking_node,
)
from medagent.agents.nodes.doctor_finder import make_doctor_finder_node
from medagent.agents.nodes.guardrail import after_guardrail, guardrail_node
from medagent.agents.nodes.medical_rag import make_medical_rag_node
from medagent.agents.nodes.output_guard import output_guard_node
from medagent.agents.nodes.respond import respond_node
from medagent.agents.nodes.supervisor import after_supervisor, make_supervisor_node
from medagent.agents.state import AgentState

AgentGraph = CompiledStateGraph[AgentState, None, AgentState, AgentState]


def build_graph(
    deps: AgentDeps, checkpointer: BaseCheckpointSaver[str] | None = None
) -> AgentGraph:
    graph = StateGraph(AgentState)

    graph.add_node("guardrail", guardrail_node)
    graph.add_node("supervisor", make_supervisor_node(deps))
    graph.add_node("medical_rag", make_medical_rag_node(deps))
    graph.add_node("doctor_finder", make_doctor_finder_node(deps))
    graph.add_node("respond", respond_node)
    # Nodes that route with Command(goto=...) declare where they can go (for the diagram).
    graph.add_node("booking", make_booking_node(deps), destinations=("confirm", "output_guard"))
    graph.add_node("confirm", confirm_node, destinations=("book_appointment", "output_guard"))
    graph.add_node(
        "book_appointment",
        make_book_appointment_node(deps),
        destinations=("confirm", "output_guard"),
    )
    graph.add_node("output_guard", output_guard_node)

    graph.add_edge(START, "guardrail")
    graph.add_conditional_edges("guardrail", after_guardrail, ["supervisor", "output_guard"])
    graph.add_conditional_edges(
        "supervisor",
        after_supervisor,
        ["medical_rag", "doctor_finder", "booking", "respond", "output_guard"],
    )
    for node in ("medical_rag", "doctor_finder", "respond"):
        graph.add_edge(node, "output_guard")
    graph.add_edge("output_guard", END)

    return graph.compile(checkpointer=checkpointer)
