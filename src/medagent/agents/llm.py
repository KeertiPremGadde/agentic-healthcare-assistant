"""LLM access for graph nodes: one method, typed in and typed out.

`method="json_schema"` uses the API's native structured outputs (`output_config.format`).
LangChain's default ("function_calling") forces a tool call, which Claude Sonnet 5.5 rejects
with a 400, so this keeps the code working on both the dev model (Haiku) and the demo model.
"""

from collections.abc import Sequence
from typing import Literal, Protocol, TypeVar

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import BaseMessage, SystemMessage
from pydantic import BaseModel

from medagent.core.config import Settings, get_settings

T = TypeVar("T", bound=BaseModel)
Effort = Literal["low", "medium", "high"]


class LLMError(Exception):
    """The model call failed or returned something unusable. Message never contains user text."""


class StructuredLLM(Protocol):
    def invoke(self, schema: type[T], system: str, messages: Sequence[BaseMessage]) -> T: ...


def make_chat_model(settings: Settings, effort: Effort, max_tokens: int = 4096) -> ChatAnthropic:
    key = settings.anthropic_api_key
    if key is None:
        raise RuntimeError("ANTHROPIC_API_KEY is not set (put it in .env)")
    # No `temperature`: rejected by the API for current models. Thinking is on by default on
    # Haiku 5.5 and bills as output, so `effort` is the cost/latency control. max_tokens leaves
    # room for thinking plus the structured answer.
    return ChatAnthropic(  # type: ignore[call-arg]
        model_name=settings.llm_model, api_key=key, max_tokens=max_tokens, effort=effort
    )


class AnthropicStructuredLLM:
    """Routing and extraction calls: short structured answers, so low effort by default."""

    def __init__(self, settings: Settings | None = None, effort: Effort = "low") -> None:
        self._model = make_chat_model(settings or get_settings(), effort)

    def invoke(self, schema: type[T], system: str, messages: Sequence[BaseMessage]) -> T:
        chain = self._model.with_structured_output(schema, method="json_schema")
        try:
            result = chain.invoke([SystemMessage(system), *messages])
        except Exception as exc:  # network, 4xx/5xx, refusal, schema violation
            raise LLMError(f"{type(exc).__name__} during {schema.__name__}") from exc
        if not isinstance(result, schema):
            raise LLMError(f"unexpected output type for {schema.__name__}")
        return result
