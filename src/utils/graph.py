"""This file contains the graph utilities for the application."""

from dataclasses import dataclass
from typing import Literal, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage

from src.config.settings import settings
from src.data.schemas import Message
from src.system.logs import logger


_SYSTEM_PROMPT_TRUNCATION_MARKER = "\n\n[... system prompt truncated to fit token budget ...]\n\n"


@dataclass(slots=True)
class PreparedMessage:
    """Internal message representation for LLM calls.

    Unlike the API-facing ``Message`` schema, this internal structure does not
    enforce the request validation length cap, which allows large system prompts
    and retrieved context to be prepared safely before they are trimmed to the
    token budget.
    """

    role: Literal["user", "assistant", "system"]
    content: str


def dump_messages(messages: list[object]) -> list[dict[str, str]]:
    """Dump the messages to a list of dictionaries.

    Args:
        messages (list[object]): The messages to dump.

    Returns:
        list[dict]: The dumped messages.
    """
    dumped_messages: list[dict[str, str]] = []
    for message in messages:
        if (normalized_message := _normalize_message(message)) is None:
            continue
        dumped_messages.append({"role": normalized_message.role, "content": normalized_message.content})
    return dumped_messages


def process_llm_response(response: BaseMessage) -> BaseMessage:
    """Process LLM response to handle structured content blocks (e.g., from GPT-5 models).

    GPT-5 models return content as a list of blocks like:
    [
        {'id': '...', 'summary': [], 'type': 'reasoning'},
        {'type': 'text', 'text': 'actual response'}
    ]

    This function extracts the actual text content from such structures.

    Args:
        response: The raw response from the LLM

    Returns:
        BaseMessage with processed content
    """
    if isinstance(response.content, list):
        # Extract text from content blocks
        text_parts = []
        for block in response.content:
            if isinstance(block, dict):
                # Handle text blocks
                if block.get("type") == "text" and "text" in block:
                    text_parts.append(block["text"])
                # Log reasoning blocks for debugging
                elif block.get("type") == "reasoning":
                    logger.debug(
                        "reasoning_block_received",
                        reasoning_id=block.get("id"),
                        has_summary=bool(block.get("summary")),
                    )
            elif isinstance(block, str):
                text_parts.append(block)

        # Join all text parts
        response.content = "".join(text_parts)
        logger.debug(
            "processed_structured_content",
            block_count=len(response.content) if isinstance(response.content, list) else 1,
            extracted_length=len(response.content) if isinstance(response.content, str) else 0,
        )

    return response


def _message_content_to_text(content: object) -> str:
    """Convert structured message content into plain text for token estimation."""
    if content is None:
        return ""

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                if "text" in block:
                    parts.append(str(block["text"]))
                elif "content" in block:
                    parts.append(str(block["content"]))
            elif isinstance(block, str):
                parts.append(block)
            else:
                parts.append(str(block))
        return "".join(parts)

    return str(content)


def _estimate_message_tokens(messages: list[object]) -> int:
    """Estimate the number of tokens in a message list.

    This is a conservative fallback used when the underlying model does not
    implement native token counting (for example, DeepSeek via ChatOpenAI).
    """
    total_tokens = 0
    for message in dump_messages(messages):
        content = message.get("content", "")

        text = _message_content_to_text(content).strip()
        if not text:
            continue

        # Rough heuristic: 1 token ~= 4 characters, plus a small per-message overhead.
        total_tokens += max(1, (len(text) + 3) // 4) + 4

    return max(total_tokens, len(messages))


def _normalize_role(role: object) -> Optional[Literal["user", "assistant", "system"]]:
    """Normalize supported message roles to OpenAI-style role names."""
    role_value = str(role or "").lower()
    if role_value in {"human", "user"}:
        return "user"
    if role_value in {"ai", "assistant"}:
        return "assistant"
    if role_value == "system":
        return "system"
    return None


def _truncate_text_to_token_budget(text: str, token_budget: int) -> str:
    """Truncate text to the approximate token budget used by the fallback estimator."""
    effective_token_budget = max(token_budget - 4, 1)
    char_budget = effective_token_budget * 4
    if len(text) <= char_budget:
        return text

    if char_budget <= len(_SYSTEM_PROMPT_TRUNCATION_MARKER):
        return text[:char_budget]

    remaining_chars = char_budget - len(_SYSTEM_PROMPT_TRUNCATION_MARKER)
    head_chars = max(remaining_chars // 2, 1)
    tail_chars = max(remaining_chars - head_chars, 1)
    return f"{text[:head_chars]}{_SYSTEM_PROMPT_TRUNCATION_MARKER}{text[-tail_chars:]}"


def _normalize_message(message: object) -> Optional[PreparedMessage]:
    """Convert an incoming message object into the local Message schema."""
    if isinstance(message, PreparedMessage):
        return message

    if isinstance(message, Message):
        return PreparedMessage(role=message.role, content=message.content)

    if isinstance(message, dict):
        role = message.get("role") or message.get("type")
        content = message.get("content", "")
    else:
        role = getattr(message, "role", None) or getattr(message, "type", "")
        content = getattr(message, "content", "")

    normalized_role = _normalize_role(role)
    if normalized_role is None:
        return None

    return PreparedMessage(role=normalized_role, content=_message_content_to_text(content))


def _trim_message_history(messages: list[object], system_prompt: str) -> list[PreparedMessage]:
    """Trim the message history while preserving the latest user-aligned context."""
    normalized_messages = [
        normalized_message
        for message in messages
        if (normalized_message := _normalize_message(message)) is not None and normalized_message.role != "system"
    ]

    prepared_messages = [PreparedMessage(role="system", content=system_prompt), *normalized_messages]

    while len(prepared_messages) > 2 and _estimate_message_tokens(prepared_messages) > settings.MAX_TOKENS:
        # Always trim from the oldest non-system message first.
        prepared_messages.pop(1)

        # Preserve the "start_on=human" behavior by removing any leading assistant message.
        while len(prepared_messages) > 2 and prepared_messages[1].role != "user":
            prepared_messages.pop(1)

    if prepared_messages and _estimate_message_tokens(prepared_messages) > settings.MAX_TOKENS:
        non_system_token_count = _estimate_message_tokens(prepared_messages[1:])
        truncated_system_prompt = _truncate_text_to_token_budget(
            prepared_messages[0].content,
            settings.MAX_TOKENS - non_system_token_count,
        )
        if truncated_system_prompt != prepared_messages[0].content:
            logger.info(
                "system_prompt_truncated_to_budget",
                original_length=len(prepared_messages[0].content),
                truncated_length=len(truncated_system_prompt),
                max_tokens=settings.MAX_TOKENS,
            )
            prepared_messages[0] = PreparedMessage(role="system", content=truncated_system_prompt)

    return prepared_messages


def prepare_messages(messages: list[object], llm: BaseChatModel, system_prompt: str) -> list[PreparedMessage]:
    """Prepare the messages for the LLM.

    Args:
        messages (list[Message]): The messages to prepare.
        llm (BaseChatModel): The LLM to use.
        system_prompt (str): The system prompt to use.

    Returns:
        list[PreparedMessage]: The prepared messages.
    """
    return _trim_message_history(messages, system_prompt)
