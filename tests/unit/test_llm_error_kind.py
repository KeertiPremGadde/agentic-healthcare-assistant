"""LLMError.kind tells a parse failure (input/prompt problem) from an API failure (outage)."""

import anthropic
import httpx
import pytest
from langchain_core.exceptions import OutputParserException
from pydantic import BaseModel, ValidationError

from medagent.agents.llm import _kind


class _M(BaseModel):
    x: int


def _validation_error() -> ValidationError:
    try:
        _M(x="not a number")  # type: ignore[arg-type]
    except ValidationError as exc:
        return exc
    raise AssertionError


_REQUEST = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


@pytest.mark.parametrize(
    ("exc", "kind"),
    [
        (OutputParserException("bad json"), "parse"),
        (_validation_error(), "parse"),
        (anthropic.APIConnectionError(request=_REQUEST), "api"),
        (anthropic.APITimeoutError(request=_REQUEST), "api"),
        (
            anthropic.InternalServerError(
                "overloaded", response=httpx.Response(529, request=_REQUEST), body=None
            ),
            "api",
        ),
        (RuntimeError("something else"), "other"),
    ],
)
def test_kind(exc: Exception, kind: str) -> None:
    assert _kind(exc) == kind
