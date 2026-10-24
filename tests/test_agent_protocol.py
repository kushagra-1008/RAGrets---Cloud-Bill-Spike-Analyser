import asyncio
import inspect
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from ragrets.database import Database
from ragrets.ingestion import demo_data, ingest_records
from uagents_core.contrib.protocols.chat import (
    ChatMessage,
    EndSessionContent,
    StartSessionContent,
    TextContent,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))
import ragrets_agent


def message(text, *extra_content):
    return ChatMessage(
        timestamp=datetime.now(timezone.utc),
        msg_id=uuid4(),
        content=[TextContent(type='text', text=text), *extra_content],
    )


def test_acp_handler_and_reply_messages_follow_the_chat_protocol():
    reply = ragrets_agent.create_text_chat('Billing increased by $120.', end_session=True)

    assert inspect.iscoroutinefunction(ragrets_agent.handle_chat_message)
    assert reply.text() == 'Billing increased by $120.'
    assert any(isinstance(item, EndSessionContent) for item in reply.content)


def test_session_markers_and_sender_histories_are_isolated():
    ragrets_agent._histories.clear()
    started = message('New request', StartSessionContent(type='start-session'))
    ended = message('Done', EndSessionContent(type='end-session'))

    ragrets_agent.append_history('alice', 'Why?', 'Because of Compute.')
    ragrets_agent.append_history('bob', 'What changed?', 'Storage changed.')

    assert ragrets_agent.is_session_start(started)
    assert not ragrets_agent.is_session_end(started)
    assert ragrets_agent.is_session_end(ended)
    assert len(ragrets_agent._histories['alice']) == 2
    assert len(ragrets_agent._histories['bob']) == 2


def test_history_is_bounded_to_temporary_recent_context():
    ragrets_agent._histories.clear()
    for index in range(15):
        ragrets_agent.append_history('alice', f'q{index}', f'a{index}')

    history = ragrets_agent._histories['alice']
    assert len(history) == ragrets_agent.MAX_HISTORY_MESSAGES
    assert history[0] == {'role': 'user', 'content': 'q5'}
    assert history[-1] == {'role': 'assistant', 'content': 'a14'}


def test_build_agent_requires_seed_phrase(monkeypatch):
    monkeypatch.delenv('AGENT_SEED_PHRASE', raising=False)
    with pytest.raises(RuntimeError, match='AGENT_SEED_PHRASE'):
        ragrets_agent.build_agent()

def test_reset_command_accepts_asi_one_agent_mention_prefix():
    assert ragrets_agent.is_reset_command('reset')
    assert ragrets_agent.is_reset_command('RESET')
    assert ragrets_agent.is_reset_command('@agent1qt7zrs78qu8q9wqt97t43r9y8ramf24j3gmnf38wg0aftqw3tv75w8nycc8 reset')
    assert not ragrets_agent.is_reset_command('please reset the investigation')


class FakeContext:
    def __init__(self):
        self.sent = []
        self.logger = logging.getLogger("test-ragrets-agent")

    async def send(self, recipient, msg):
        self.sent.append((recipient, msg))


def test_reset_command_clears_billing_database_and_history(tmp_path, monkeypatch):
    database_path = tmp_path / "agent-reset.db"
    db = Database(database_path)
    records, invoices = demo_data()
    ingest_records(db, records, invoices, "test-demo")

    ragrets_agent._histories.clear()
    ragrets_agent.append_history("alice", "Old question", "Old answer")
    monkeypatch.setattr(
        ragrets_agent,
        "Settings",
        lambda: SimpleNamespace(database_path=database_path),
    )

    ctx = FakeContext()
    reset_message = message(
        "@agent1qt7zrs78qu8q9wqt97t43r9y8ramf24j3gmnf38wg0aftqw3tv75w8nycc8 reset"
    )
    asyncio.run(ragrets_agent.handle_chat_message(ctx, "alice", reset_message))

    assert db.records() == []
    assert db.invoices() == []
    assert db.evidence() == []
    assert "alice" not in ragrets_agent._histories
    response = ctx.sent[-1][1].text()
    assert "4 billing records" in response
    assert "2 invoices" in response
    assert "1 evidence items" in response
    assert "You can now upload a new billing file." in response
