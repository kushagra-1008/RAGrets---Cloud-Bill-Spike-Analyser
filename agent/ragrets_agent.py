
"""RAGrets billing agent for Agentverse and ASI:One."""

import asyncio
import hashlib
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
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
from ragrets.attachment_download import download_pdf_bytes
from ragrets.config import Settings
from ragrets.database import Database
from ragrets.groq import GroqAPIError
from ragrets.ingestion import ingest_file

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


def is_reset_command(question: str) -> bool:
    """Recognize reset commands even when ASI:One prefixes an agent mention."""
    normalized = re.sub(r"^@\S+\s+", "", question.strip(), count=1)
    return normalized.strip().casefold() == "reset"


def _ingest_pdf_resource(resource) -> dict:
    """Download, validate, parse, and ingest one Agentverse PDF attachment."""
    uri = resource.uri or ""
    metadata = resource.metadata or {}
    declared_mime = (
        metadata.get("mime_type")
        or metadata.get("content_type")
        or metadata.get("type")
        or ""
    )
    declared_mime = declared_mime.split(";", 1)[0].strip().lower()
    if declared_mime and declared_mime not in {
        "application/pdf",
        "application/x-pdf",
        "application/octet-stream",
    }:
        raise ValueError(
            f"This workflow accepts PDF attachments, not {declared_mime}."
        )

    payload = download_pdf_bytes(uri)
    digest = hashlib.sha256(payload).hexdigest()
    source_id = f"agentverse-pdf-{digest[:20]}"

    settings = Settings()
    database = Database(settings.database_path)
    with tempfile.TemporaryDirectory(prefix="ragrets-pdf-") as temp_dir:
        pdf_path = Path(temp_dir) / "attachment.pdf"
        pdf_path.write_bytes(payload)
        result = ingest_file(database, pdf_path, source_id=source_id)

    if result.get("status") != "completed":
        issues = result.get("issues") or ["The PDF could not be parsed."]
        raise ValueError("; ".join(str(issue) for issue in issues))

    result["source_id"] = source_id
    return result


async def ingest_pdf_resource(resource) -> dict:
    """Run network access, PDF parsing, and database writes off the event loop."""
    return await asyncio.to_thread(_ingest_pdf_resource, resource)


def _attachment_summary(result: dict) -> str:
    records = result.get("records", 0)
    invoices = result.get("invoices", 0)
    pages = result.get("pages", 0)
    return (
        f"PDF ingested successfully: {records} billing record"
        f"{'' if records == 1 else 's'}, {invoices} invoice"
        f"{'' if invoices == 1 else 's'}, {pages} page"
        f"{'' if pages == 1 else 's'}. "
        "The extracted records are now in RAGrets' active billing database."
    )

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
    """Handle chat sessions, PDF attachment ingestion, and billing questions."""
    await ctx.send(
        sender,
        ChatAcknowledgement(
            timestamp=datetime.now(timezone.utc),
            acknowledged_msg_id=msg.msg_id,
        ),
    )

    question = get_text(msg)
    resources = get_resources(msg)

    if is_session_start(msg):
        _histories.pop(sender, None)
        await ctx.send(sender, create_attachment_metadata_chat())
        # ASI:One may combine the start marker with the first question or
        # attachment. Only return when this is a marker-only message.
        if not question and not resources:
            return

    if is_reset_command(question):
        try:
            settings = Settings()
            counts = Database(settings.database_path).clear_billing_data()
        except Exception:
            ctx.logger.exception("Failed to reset RAGrets billing data")
            await ctx.send(
                sender,
                create_text_chat(
                    "Reset failed. Billing data was not cleared. "
                    "Please check the agent logs and try again."
                ),
            )
            return

        _histories.pop(sender, None)
        await ctx.send(
            sender,
            create_text_chat(
                "Reset complete. Cleared "
                f"{counts['billing_records']} billing record"
                f"{'' if counts['billing_records'] == 1 else 's'}, "
                f"{counts['invoices']} invoice"
                f"{'' if counts['invoices'] == 1 else 's'}, and "
                f"{counts['evidence']} evidence item"
                f"{'' if counts['evidence'] == 1 else 's'}. "
                "Conversation history was cleared. Past reports, ingestion "
                "logs, approvals, and audit history were retained. "
                "You can now upload a new billing file."
            ),
        )
        return

    if resources:
        resource_items = []
        for resource_content in resources:
            items = resource_content.resource
            if not isinstance(items, list):
                items = [items]
            resource_items.extend(items)

        if len(resource_items) != 1:
            await ctx.send(
                sender,
                create_text_chat(
                    "Please attach one PDF per message for now. "
                    "No attachment was ingested."
                ),
            )
            return

        try:
            result = await ingest_pdf_resource(resource_items[0])
        except (ValueError, RuntimeError, OSError) as exc:
            await ctx.send(
                sender,
                create_text_chat(
                    "I couldn't ingest this PDF: "
                    f"{exc} No billing records were imported from this attachment."
                ),
            )
            return
        except Exception:
            ctx.logger.exception("Unexpected RAGrets PDF ingestion error")
            await ctx.send(
                sender,
                create_text_chat(
                    "I couldn't ingest this PDF because of an unexpected "
                    "internal error. Please check the agent logs."
                ),
            )
            return

        summary = _attachment_summary(result)
        if not question:
            await ctx.send(
                sender,
                create_text_chat(
                    summary + " Ask a billing question to analyze the uploaded bill.",
                    end_session=is_session_end(msg),
                ),
            )
            if is_session_end(msg):
                _histories.pop(sender, None)
            return

        history = list(_histories.get(sender, []))
        try:
            answer = answerer(question, history)
        except (GroqAPIError, ValueError) as exc:
            answer = (
                "The PDF was ingested, but I couldn't complete the analysis: "
                f"{exc}"
            )
        except Exception:
            ctx.logger.exception("Unexpected RAGrets billing-agent error after PDF ingestion")
            answer = (
                "The PDF was ingested, but I couldn't complete the analysis. "
                "Please try again later."
            )

        append_history(sender, question, answer)
        end_session = is_session_end(msg)
        if end_session:
            _histories.pop(sender, None)
        await ctx.send(
            sender,
            create_text_chat(
                summary + "\n\n" + answer,
                end_session=end_session,
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
