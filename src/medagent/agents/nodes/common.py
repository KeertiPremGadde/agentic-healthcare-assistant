"""Small helpers shared by the nodes."""

from typing import Any, Protocol

from langchain_core.messages import AnyMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

from medagent.agents.state import AgentState


class Node(Protocol):
    """A graph node. LangGraph calls nodes with a parameter named `state` (and `config`)."""

    def __call__(self, state: AgentState) -> Any: ...


class ConfigNode(Protocol):
    def __call__(self, state: AgentState, config: RunnableConfig) -> Any: ...


RECENT_MESSAGES = 10  # what the LLM sees; the checkpoint keeps the full history

APOLOGY = (
    "Sorry, I couldn't process that just now. Please try again in a moment, or rephrase your "
    "message."
)


def last_user_text(state: AgentState) -> str:
    for message in reversed(state.get("messages", [])):
        if isinstance(message, HumanMessage):
            return str(message.content)
    return ""


def recent_messages(state: AgentState, n: int = RECENT_MESSAGES) -> list[AnyMessage]:
    """The last `n` messages, starting at a user message (the API wants user first)."""
    messages = list(state.get("messages", []))[-n:]
    while messages and not isinstance(messages[0], HumanMessage):
        messages.pop(0)
    return messages
