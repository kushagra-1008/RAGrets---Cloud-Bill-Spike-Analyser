from ragrets.asi1 import ASI_ONE_CHAT_COMPLETIONS_URL, ASI1Client


class FakeResponse:
    status_code = 200
    ok = True

    def json(self):
        return {"choices": [{"message": {"content": "Compute increased by $120."}}]}


def test_asi1_client_uses_asi_endpoint_and_bearer_key(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse()

    monkeypatch.setattr("ragrets.asi1.requests.post", fake_post)
    client = ASI1Client("test-key", "asi1-mini")
    message = client._request_message(
        [{"role": "user", "content": "Summarize the bill"}],
        tools=[{"type": "function", "function": {"name": "query_billing_records"}}],
    )

    assert message["content"] == "Compute increased by $120."
    assert calls[0][0] == ASI_ONE_CHAT_COMPLETIONS_URL
    assert calls[0][1]["headers"]["Authorization"] == "Bearer test-key"
    assert calls[0][1]["json"]["model"] == "asi1-mini"
    assert calls[0][1]["json"]["tools"]


def test_asi1_client_reports_provider_rate_limits(monkeypatch):
    class RateLimitedResponse:
        status_code = 429
        ok = False

    monkeypatch.setattr(
        "ragrets.asi1.requests.post",
        lambda *args, **kwargs: RateLimitedResponse(),
    )

    import pytest
    from ragrets.groq import GroqAPIError

    with pytest.raises(GroqAPIError, match="ASI:One rate limit"):
        ASI1Client("test-key", "asi1-mini")._request_message(
            [{"role": "user", "content": "hello"}]
        )
