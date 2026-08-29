"""Shared helpers for calling the Claude API and parsing its JSON output."""

import json
import logging
import re
from functools import cache
from pathlib import Path

import anthropic
from django.conf import settings

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


@cache
def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text()


def get_client() -> anthropic.Anthropic:
    if not settings.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not set — add it to .env")
    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)


def system_prompt() -> str:
    return load_prompt("audience.txt")


def complete(model: str, user_content: str, max_tokens: int = 4096) -> str:
    """One non-streaming Claude call; returns the concatenated text output."""
    client = get_client()
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt(),
        messages=[{"role": "user", "content": user_content}],
    )
    return "".join(block.text for block in response.content if block.type == "text")


def parse_json(raw: str) -> object:
    """Parse Claude output defensively: strip code fences, find the JSON payload.

    Raises ValueError (with the raw text logged) if nothing parseable is found.
    """
    text = raw.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Fall back to the outermost bracketed span.
    for open_ch, close_ch in (("[", "]"), ("{", "}")):
        start, end = text.find(open_ch), text.rfind(close_ch)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    logger.error("unparseable Claude response: %r", raw[:2000])
    raise ValueError("Claude response was not valid JSON")
