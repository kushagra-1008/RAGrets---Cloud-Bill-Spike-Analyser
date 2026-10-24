
"""RAGrets billing agent for Agentverse and ASI:One."""

import os
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import urlparse
from uuid import uuid4

from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    EndSessionContent,
    MetadataContent,
    ResourceContent,
    StartSessionContent,
    TextContent,
    chat_protocol_spec,
)

from ragrets.agent_service import answer_database_question
from ragrets.groq import GroqAPIError

MAX_HISTORY_MESSAGES = 20
_histories: dict[str, list[dict[str, str]]] = {}


def create_text_chat(text: str, *, end_session: bool = False) -> ChatMessage:
    content = [TextContent(type="text", text=text)]
    if end_session:
        content.append(EndSessionContent(type="end-session"))

    return ChatMessage(
        timestamp=datetime.now(timezone.utc),
        msg_id=uuid4(),
        content=content,
    )


def create_attachment_metadata_chat() -> ChatMessage:
    return ChatMessage(
        timestamp=datetime.now(timezone.utc),
        msg_id=uuid4(),
        content=[
            MetadataContent(
                type="metadata",
                metadata={"attachments": "true"},
            )
        ],
    )


def is_session_start(msg: ChatMessage) -> bool:
    return any(isinstance(item, StartSessionContent) for item in msg.content)


def is_session_end(msg: ChatMessage) -> bool:
    return any(isinstance(item, EndSessionContent) for item in msg.content)


def get_resources(msg: ChatMessage) -> list[ResourceContent]:
    return [
        item
        for item in msg.content
        if isinstance(item, ResourceContent)
    ]


def get_text(msg: ChatMessage) -> str:
    return "\n".join(
        item.text.strip()
        for item in msg.content
        if isinstance(item, TextContent) and item.text.strip()
    ).strip()


def describe_resources(resources: list[ResourceContent]) -> str:
    """Describe attachments without exposing their complete URIs."""
    lines: list[str] = []

    for resource_content in resources:
        items = resource_content.resource
        if not isinstance(items, list):
            items = [items]

        for resource in items:
            uri = resource.uri or ""
            parsed_uri = urlparse(uri)
            scheme = parsed_uri.scheme or "no-scheme"
            host = parsed_uri.hostname or "unknown"
            metadata = resource.metadata or {}

            filename = (
                metadata.get("filename")
                or metadata.get("file_name")
                or metadata.get("name")
                or "not provided"
            )
            mime_type = (
                metadata.get("mime_type")
                or metadata.get("content_type")
                or metadata.get("type")
                or "not provided"
            )

            lines.append(
                f"- Filename: {filename}\n"
                f"- MIME type: {mime_type}\n"
                f"- Metadata keys: "
                f"{', '.join(sorted(metadata.keys())) or '(none)'}\n"
                f"- URI scheme: {scheme}\n"
                f"- URI host: {host}\n"
                f"- URI present: {'yes' if uri else 'no'}"
            )

    return "\n\n".join(lines) or "No resource details found."


def append_history(sender: str, question: str, answer: str) -> None:
    history = _histories.setdefault(sender, [])
    history.extend(
        [
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        ]
    )
    del history[:-MAX_HISTORY_MESSAGES]


async def handle_chat_message(
    ctx: Context,
    sender: str,
    msg: ChatMessage,
    answerer: Callable[
        [str, list[dict[str, str]]], str
    ] = answer_database_question,
) -> None:
    """Handle chat sessions, attachment diagnostics, and billing questions."""
    await ctx.send(
        sender,
        ChatAcknowledgement(
            timestamp=datetime.now(timezone.utc),
            acknowledged_msg_id=msg.msg_id,
        ),
    )

    if is_session_start(msg):
        _histories.pop(sender, None)
        await ctx.send(sender, create_attachment_metadata_chat())
        return

    question = get_text(msg)
    resources = get_resources(msg)

    if question.lower() == "reset":
        _histories.pop(sender, None)
        await ctx.send(
            sender,
            create_text_chat(
                "Conversation history cleared. Your billing database was not changed."
            ),
        )
        return

    if resources:
        details = describe_resources(resources)
        await ctx.send(
            sender,
            create_text_chat(
                "Attachment diagnostic information:\n\n"
                f"{details}\n\n"
                "The file has been detected, but not downloaded or ingested yet."
            ),
        )
        return

    if not question:
        if is_session_end(msg):
            _histories.pop(sender, None)

        await ctx.send(
            sender,
            create_text_chat(
                "Ask a billing question or attach a billing PDF."
            ),
        )
        return

    history = list(_histories.get(sender, []))

    try:
        answer = answerer(question, history)
    except (GroqAPIError, ValueError) as exc:
        answer = f"I could not complete the billing investigation: {exc}"
    except Exception:
        ctx.logger.exception("Unexpected RAGrets billing-agent error")
        answer = (
            "I could not complete the billing investigation. "
            "Please try again later."
        )

    append_history(sender, question, answer)

    end_session = is_session_end(msg)
    if end_session:
        _histories.pop(sender, None)

    await ctx.send(
        sender,
        create_text_chat(answer, end_session=end_session),
    )


def build_agent() -> tuple[Agent, Protocol]:
    """Create the mailbox uAgent without exposing the seed phrase."""
    seed = os.getenv("AGENT_SEED_PHRASE")
    if not seed:
        raise RuntimeError(
            "AGENT_SEED_PHRASE must be set before starting the RAGrets agent."
        )

    endpoint = os.getenv("RAGRETS_AGENT_ENDPOINT", "").strip()
    settings = {
        "name": os.getenv("RAGRETS_AGENT_NAME", "ragrets-billing-agent"),
        "seed": seed,
        "port": int(os.getenv("RAGRETS_AGENT_PORT", "8000")),
        "mailbox": True,
        "publish_agent_details": True,
        "readme_path": "README.md",
    }

    if endpoint:
        settings["endpoint"] = [endpoint]

    agent = Agent(**settings)
    protocol = Protocol(spec=chat_protocol_spec)

    @protocol.on_message(ChatMessage)
    async def on_chat_message(ctx: Context, sender: str, msg: ChatMessage):
        await handle_chat_message(ctx, sender, msg)

    @protocol.on_message(ChatAcknowledgement)
    async def on_chat_acknowledgement(
        ctx: Context,
        sender: str,
        msg: ChatAcknowledgement,
    ):
        pass

    agent.include(protocol, publish_manifest=True)
    return agent, protocol


if __name__ == "__main__":
    ragrets_agent, _ = build_agent()
    ragrets_agent.run()
