"""
OpenAI Chat Completions compatibility helpers.

This module keeps existing behavior for legacy models/providers while
gracefully adapting request parameters for GPT-5 family models.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def is_gpt5_family(model: Optional[str]) -> bool:
    """Return True when model belongs to GPT-5 family aliases/snapshots."""
    if not model:
        return False
    return model.strip().lower().startswith("gpt-5")


# Claude (Anthropic) is reached through its OpenAI-compatible endpoint.
# Anthropic requires an explicit max_tokens and does not use OpenAI's
# response_format, so both are normalised here for every caller.
CLAUDE_DEFAULT_MAX_TOKENS = 8192


def is_claude_target(client: Any, model: Optional[str]) -> bool:
    """Return True when the request goes to Anthropic / a Claude model."""
    base_url = str(getattr(client, "base_url", "") or "").lower()
    return "anthropic.com" in base_url or (model or "").strip().lower().startswith("claude")


def is_gemini_target(client: Any, model: Optional[str]) -> bool:
    """Return True when the request goes to Google Gemini's OpenAI-compatible endpoint or a Gemini model."""
    base_url = str(getattr(client, "base_url", "") or "").lower()
    m = (model or "").strip().lower()
    return "generativelanguage.googleapis.com" in base_url or m.startswith("gemini-") or m.startswith("models/gemini-")


def create_chat_completion(
    client: Any,
    *,
    model: str,
    messages: List[Dict[str, Any]],
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    response_format: Optional[Dict[str, Any]] = None,
    agent_id: Optional[Any] = None,
    slot_index: Optional[int] = None,
) -> Any:
    """
    Create a chat completion with model-specific request parameters.

    Compatibility strategy:
    - For GPT-5 family, avoid sending temperature by default.
    - For token limit, use `max_completion_tokens` on GPT-5, `max_tokens` otherwise.
    - For Gemini targets, strip any leading `models/` prefix from model identifiers.
    - When `client` is a `MultiProviderPool`, route by `agent_id` or `slot_index` when provided.
    - Preserve the legacy request shape for every non-GPT-5 model/provider.
    - Propagate provider errors unchanged instead of guessing from message text.
    """
    if agent_id is not None and hasattr(client, "for_agent"):
        client = client.for_agent(agent_id)
    elif slot_index is not None and hasattr(client, "for_slot"):
        client = client.for_slot(slot_index)

    # If the bound client is pinned to a specific provider slot whose family differs from `model`,
    # let the bound slot's model take precedence so multi-provider pools work transparently.
    slot_model = getattr(client, "model_name", None)
    slot_provider = getattr(client, "provider", None)
    if slot_model and slot_provider:
        from .model_pool import canonical_provider
        req_provider = canonical_provider(None, None, model) if model else slot_provider
        if not model or req_provider != slot_provider:
            model = slot_model

    gemini = is_gemini_target(client, model)
    if gemini and model and model.strip().lower().startswith("models/"):
        model = model.strip().split("/", 1)[1]

    kwargs: Dict[str, Any] = {
        "model": model,
        "messages": messages,
    }

    claude = is_claude_target(client, model)

    if response_format is not None and not claude:
        kwargs["response_format"] = response_format
    elif response_format is not None and claude:
        # Ask for JSON in the prompt instead of response_format.
        kwargs["messages"] = list(messages) + [{
            "role": "user",
            "content": "Respond with a single valid JSON object only. No markdown fences, no extra text.",
        }]

    if claude and max_tokens is None:
        max_tokens = CLAUDE_DEFAULT_MAX_TOKENS

    gpt5_family = is_gpt5_family(model)

    if temperature is not None and not gpt5_family:
        kwargs["temperature"] = temperature

    if max_tokens is not None:
        if gpt5_family:
            kwargs["max_completion_tokens"] = max_tokens
        else:
            kwargs["max_tokens"] = max_tokens

    return client.chat.completions.create(**kwargs)


def extract_chat_completion_text(response: Any) -> str:
    """Extract plain text from chat completion response across SDK content shapes."""
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""

    message = getattr(choices[0], "message", None)
    if message is None:
        return ""

    content = getattr(message, "content", "")

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        chunks: List[str] = []
        for item in content:
            if isinstance(item, dict):
                text_obj = item.get("text")
                if isinstance(text_obj, dict):
                    text_obj = text_obj.get("value")
                if isinstance(text_obj, str):
                    chunks.append(text_obj)
                elif isinstance(item.get("content"), str):
                    chunks.append(item["content"])
                continue

            text_obj = getattr(item, "text", None)
            if isinstance(text_obj, dict):
                text_obj = text_obj.get("value")
            if isinstance(text_obj, str):
                chunks.append(text_obj)
                continue

            content_obj = getattr(item, "content", None)
            if isinstance(content_obj, str):
                chunks.append(content_obj)

        return "".join(chunks).strip()

    return str(content or "")
