import inspect
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
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