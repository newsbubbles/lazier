"""Structured LLM/VLM calls via pydantic-ai. Every agent returns a validated Pydantic
model — NO json.loads, NO response_format, NO manual coercion. pydantic-ai enforces the
output shape and retries automatically when the model's output fails validation; an
optional output validator raises ModelRetry to self-correct SEMANTIC constraints (e.g. a
set of ranges that must tile [0..N] exactly), feeding the reason back to the model.

Fresh Agent + fresh model per call: run_sync spins its own event loop per call (we call
these from worker threads via asyncio.to_thread), so an async client cached across calls
would bind to a dead loop. Building per call is cheap and correct under fan-out."""

from __future__ import annotations

from typing import Any, Callable, Optional, Type, TypeVar

from pydantic import BaseModel

from . import config

T = TypeVar("T", bound=BaseModel)


def _build_model(model_name: str):
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    if not config.OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY not set — agents need OpenRouter access")
    return OpenAIChatModel(
        model_name,
        provider=OpenAIProvider(base_url=config.OPENROUTER_BASE_URL,
                                api_key=config.OPENROUTER_API_KEY),
    )


def run_agent(
    system_prompt: str,
    user_prompt: Any,                       # str, or a list of parts for multimodal
    output_type: Type[T],
    *,
    model_name: Optional[str] = None,
    output_retries: int = 3,
    validator: Optional[Callable[[T], T]] = None,
) -> T:
    """Run a one-shot structured agent and return the validated output object."""
    from pydantic_ai import Agent, NativeOutput

    # NativeOutput = the provider's native json-schema structured output. The pydantic-ai
    # DEFAULT is ToolOutput (model calls a tool with the schema as args), which kimi AND
    # gemini both fail reliably over OpenRouter on non-trivial tasks (retry exhaustion).
    # NativeOutput is the reliable path and keeps whatever model we choose.
    agent = Agent(
        _build_model(model_name or config.LLM_MODEL),
        output_type=NativeOutput(output_type),
        system_prompt=system_prompt,
        retries=output_retries,   # pydantic-ai 2.2: unified retry ceiling (tools + output)
    )
    if validator is not None:
        agent.output_validator(validator)
    return agent.run_sync(user_prompt).output


def tiling_validator(n: int, get_ranges: Callable[[Any], list[tuple[int, int]]]):
    """Build an output validator that enforces the returned ranges tile [0..n-1] exactly.
    On any gap/overlap/out-of-range it raises ModelRetry with the specific diff, so the
    model fixes it on the next attempt (pydantic-ai's built-in self-correction loop)."""
    from pydantic_ai import ModelRetry

    def _validate(out: Any) -> Any:
        ranges = get_ranges(out)
        covered = [0] * n
        for i0, i1 in ranges:
            if i0 > i1 or i0 < 0 or i1 >= n:
                raise ModelRetry(
                    f"Span [{i0},{i1}] is out of range. Valid indices are 0..{n - 1}. "
                    f"Return contiguous ranges that tile 0..{n - 1}.")
            for k in range(i0, i1 + 1):
                covered[k] += 1
        gaps = [k for k, c in enumerate(covered) if c == 0]
        overlaps = [k for k, c in enumerate(covered) if c > 1]
        if gaps or overlaps:
            raise ModelRetry(
                f"Your ranges must tile 0..{n - 1} exactly: every index covered once. "
                f"Uncovered: {gaps[:12]}. Overlapping: {overlaps[:12]}. Fix and return again.")
        return out

    return _validate
