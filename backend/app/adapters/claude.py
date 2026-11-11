"""Thin Anthropic Messages wrapper behind a port, so agents can be tested with a fake."""

from typing import Any, Protocol

import anthropic


class ClaudeUnavailable(Exception):
    """Claude could not answer (network, rate limit, server error)."""


class ClaudePort(Protocol):
    async def create(self, **kwargs: Any) -> dict[str, Any]:
        """`POST /v1/messages` with these parameters; the message as a plain dict."""
        ...


class ClaudeClient:
    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is required")
        self._client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=2)

    async def create(self, **kwargs: Any) -> dict[str, Any]:
        try:
            message = await self._client.messages.create(**kwargs)
        except (anthropic.APIConnectionError, anthropic.RateLimitError) as exc:
            raise ClaudeUnavailable(str(exc)) from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500:
                raise ClaudeUnavailable(str(exc)) from exc
            raise
        return message.model_dump(mode="json", exclude_none=True)
