"""This file contains the graph utilities for the application."""

from typing import Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage

from src.config.settings import settings
from src.system.logs import logger
from src.data.schemas import Message


def dump_messages(messages: list[Message]) -> list[dict]:
    """Dump the messages to a list of dictionaries.

    Args:
        messages (list[Message]): The messages to dump.

    Returns:
        list[dict]: The dumped messages.
    """
    return [message.model_dump() for message in messages]


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


def _estimate_message_tokens(messages: list[dict | Message | BaseMessage]) -> int:
    """Estimate the number of tokens in a message list.

    This is a conservative fallback used when the underlying model does not
    implement native token counting (for example, DeepSeek via ChatOpenAI).
    """
    total_tokens = 0
    for message in messages:
        if isinstance(message, dict):
            content = message.get("content", "")
        else:
            content = getattr(message, "content", "")

        text = _message_content_to_text(content).strip()
        if not text:
            continue

        # Rough heuristic: 1 token ~= 4 characters, plus a small per-message overhead.
        total_tokens += max(1, (len(text) + 3) // 4) + 4

    return max(total_tokens, len(messages))


def _normalize_message(message: object) -> Optional[Message]:
    """Convert an incoming message object into the local Message schema."""
    if isinstance(message, Message):
        return message

    if isinstance(message, dict):
        role = str(message.get("role") or message.get("type") or "").lower()
        content = message.get("content", "")
    else:
        role = str(getattr(message, "role", None) or getattr(message, "type", "")).lower()
        content = getattr(message, "content", "")

    if role in {"human", "user"}:
        return Message(role="user", content=_message_content_to_text(content))
    if role in {"ai", "assistant"}:
        return Message(role="assistant", content=_message_content_to_text(content))
    if role == "system":
        return Message(role="system", content=_message_content_to_text(content))

    return None


def _trim_message_history(messages: list[object], system_prompt: str) -> list[Message]:
    """Trim the message history while preserving the latest user-aligned context."""
    normalized_messages = [
        normalized_message
        for message in messages
        if (normalized_message := _normalize_message(message)) is not None and normalized_message.role != "system"
    ]

    prepared_messages = [Message(role="system", content=system_prompt), *normalized_messages]

    while len(prepared_messages) > 1 and _estimate_message_tokens(dump_messages(prepared_messages)) > settings.MAX_TOKENS:
        # Always trim from the oldest non-system message first.
        prepared_messages.pop(1)

        # Preserve the "start_on=human" behavior by removing any leading assistant message.
        while len(prepared_messages) > 1 and prepared_messages[1].role != "user":
            prepared_messages.pop(1)

    return prepared_messages


def prepare_messages(messages: list[object], llm: BaseChatModel, system_prompt: str) -> list[Message]:
    """Prepare the messages for the LLM.

    Args:
        messages (list[Message]): The messages to prepare.
        llm (BaseChatModel): The LLM to use.
        system_prompt (str): The system prompt to use.

    Returns:
        list[Message]: The prepared messages.
    """
    return _trim_message_history(messages, system_prompt)
