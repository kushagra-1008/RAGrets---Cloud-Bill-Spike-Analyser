import json

import pytest
import requests

from ragrets.groq import GROQ_CHAT_COMPLETIONS_URL, GroqAPIError, GroqClient
from ragrets.schemas import BillingRecord


class FakeResponse:
    def __init__(self, status_code=200, content=None):
        self.status_code = status_code
        self.ok = 200 <= status_code < 400
        self.content = content

    def json(self):
        if isinstance(self.content, Exception):
            raise self.content
        return self.content


def _report():
    return {
        "analysis": {"previous_period": "2026-09", "current_period": "2026-10"},
        "reconciliations": [],
        "findings": [{
            "finding": "Compute resource i-new increased by 120.00.",
            "service": "Compute",
            "region": "ap-south-1",
            "resource_id": "i-new",
            "previous_cost": 0,
            "current_cost": 120,
            "absolute_change": 120,
            "supporting_source_record_ids": ["oct-2"],
            "provenance": [],
        }],
        "data_quality_warnings": [],
    }


def _completion(content):
    return {"choices": [{"message": {"content": content}}]}


def _tool_call(name, arguments, call_id="call-1"):
    return {"choices": [{"message": {
        "content": None,
        "tool_calls": [{
            "id": call_id,
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)},
        }],
    }}]}


def test_investigation_uses_groq_and_rejects_unknown_source_ids(monkeypatch):
    response_text = json.dumps({
        "summary": "Compute increased in October.",
        "findings": [{"statement": "i-new added 120.00.", "source_record_ids": ["oct-2"]}],
        "hypotheses": ["The resource may have been newly provisioned; configuration history is needed."],
        "recommendations": ["Review the resource owner and configuration events."],
    })
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(content=_completion(response_text))

    monkeypatch.setattr("ragrets.groq.requests.post", fake_post)
    result = GroqClient("test-key", "openai/gpt-oss-20b").investigate(_report())
    assert result["findings"][0]["source_record_ids"] == ["oct-2"]
    assert calls[0][0] == GROQ_CHAT_COMPLETIONS_URL
    assert calls[0][1]["headers"]["Authorization"] == "Bearer test-key"
    response_format = calls[0][1]["json"]["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    assert response_format["json_schema"]["schema"]["required"] == [
        "summary", "findings", "hypotheses", "recommendations"
    ]
    prompt = calls[0][1]["json"]["messages"][1]["content"]
    assert "usage_quantity" not in prompt
    assert "unit_price" not in prompt

    response_text = json.dumps({
        "summary": "Unsupported.",
        "findings": [{"statement": "A claim.", "source_record_ids": ["invented-id"]}],
        "hypotheses": [],
        "recommendations": [],
    })
    with pytest.raises(GroqAPIError, match="not present in this report"):
        GroqClient("test-key").investigate(_report())


def test_missing_credentials_and_provider_errors_are_safe(monkeypatch):
    def unexpected_post(*args, **kwargs):
        raise AssertionError("A request should not be sent without credentials")

    monkeypatch.setattr("ragrets.groq.requests.post", unexpected_post)
    with pytest.raises(GroqAPIError, match="not configured"):
        GroqClient(None).answer_question(_report(), "Why did my bill increase?")

    def rate_limited(*args, **kwargs):
        return FakeResponse(status_code=429)

    monkeypatch.setattr("ragrets.groq.requests.post", rate_limited)
    with pytest.raises(GroqAPIError, match="rate limit"):
        GroqClient("test-key").answer_question(_report(), "Why did my bill increase?")

    def timeout(*args, **kwargs):
        raise requests.Timeout()

    monkeypatch.setattr("ragrets.groq.requests.post", timeout)
    with pytest.raises(GroqAPIError, match="timed out"):
        GroqClient("test-key").answer_question(_report(), "Why did my bill increase?")


def test_chat_reuses_report_context_and_limits_question_size(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append(kwargs)
        return FakeResponse(content=_completion("Compute increased by 120.00; source oct-2."))

    monkeypatch.setattr("ragrets.groq.requests.post", fake_post)
    client = GroqClient("test-key")
    answer = client.answer_question(
        _report(),
        "What grew?",
        [{"role": "user", "content": "Earlier question"}, {"role": "assistant", "content": "Earlier answer"}],
    )
    assert "oct-2" in answer
    messages = calls[0]["json"]["messages"]
    assert messages[0]["role"] == "system"
    assert messages[-1] == {"role": "user", "content": "What grew?"}
    with pytest.raises(ValueError, match="2000 characters"):
        client.answer_question(_report(), "x" * 2001)


def test_chat_agent_queries_scoped_csv_rows_before_answering(monkeypatch):
    requests_sent = []
    responses = [
        FakeResponse(content=_tool_call("query_billing_records", {
            "billing_period": "2026-10",
            "resource_id": "i-new",
            "limit": 5,
        })),
        FakeResponse(content=_completion(
            "The October row is 120.00 for i-new (source oct-2). Its previous cost was 0.00, so the increase is 120.00."
        )),
    ]

    def fake_post(url, **kwargs):
        requests_sent.append(kwargs)
        return responses.pop(0)

    monkeypatch.setattr("ragrets.groq.requests.post", fake_post)
    row = BillingRecord(
        account="demo-acct", billing_period="2026-10", service="Compute", region="ap-south-1",
        resource_id="i-new", usage_quantity=80, usage_unit="hours", unit_price=1.5,
        usage_cost=120, net_cost=120, source_record_id="oct-2", source_id="demo.csv",
    )
    answer = GroqClient("test-key").answer_question(
        _report(), "Why did i-new increase?", records=[row]
    )

    assert "source oct-2" in answer
    assert len(requests_sent) == 2
    assert requests_sent[0]["json"]["tools"]
    tool_result = next(message for message in requests_sent[1]["json"]["messages"] if message["role"] == "tool")
    result = json.loads(tool_result["content"])
    assert result["records"][0]["source_record_id"] == "oct-2"
    assert "read-only" in requests_sent[0]["json"]["messages"][0]["content"]


def test_agent_tool_arguments_are_validated_and_tools_cannot_mutate_data(monkeypatch):
    responses = [
        FakeResponse(content=_tool_call("query_billing_records", {"limit": 500})),
        FakeResponse(content=_completion("The query limit was rejected; no billing rows were changed.")),
    ]
    calls = []

    def fake_post(url, **kwargs):
        calls.append(kwargs)
        return responses.pop(0)

    monkeypatch.setattr("ragrets.groq.requests.post", fake_post)
    answer = GroqClient("test-key").answer_question(_report(), "Show me all records")
    assert "rejected" in answer
    result = next(message for message in calls[1]["json"]["messages"] if message["role"] == "tool")
    assert "Invalid arguments" in json.loads(result["content"])["error"]
    names = {tool["function"]["name"] for tool in calls[0]["json"]["tools"]}
    assert names == {"query_billing_records", "get_cost_breakdown", "get_invoice_reconciliation"}


def test_invalid_provider_json_is_reported(monkeypatch):
    monkeypatch.setattr("ragrets.groq.requests.post", lambda *a, **k: FakeResponse(content=_completion("not json")))
    with pytest.raises(GroqAPIError, match="malformed JSON"):
        GroqClient("test-key").investigate(_report())
