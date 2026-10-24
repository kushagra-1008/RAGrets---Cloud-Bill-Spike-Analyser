from ragrets.agent_service import answer_synthetic_demo_question, build_synthetic_demo_context


def test_build_synthetic_demo_context_is_fresh_and_traceable():
    report, records, invoices = build_synthetic_demo_context()
    _, fresh_records, _ = build_synthetic_demo_context()

    assert records is not fresh_records
    assert [record.source_id for record in records] == ['agentverse-synthetic-demo'] * 4
    assert [invoice.source_id for invoice in invoices] == ['agentverse-synthetic-demo'] * 2
    assert report['analysis']['previous_period'] == '2026-09'
    assert report['analysis']['current_period'] == '2026-10'


def test_answer_synthetic_demo_question_uses_existing_groq_client(monkeypatch):
    captured = {}

    class FakeGroqClient:
        def __init__(self, api_key, model):
            captured['credentials'] = (api_key, model)

        def answer_question(self, report, question, history, records, invoices):
            captured['question'] = question
            captured['history'] = history
            captured['records'] = records
            captured['invoices'] = invoices
            captured['report'] = report
            return 'The largest increase is Compute in ap-south-1. [oct-2]'

    monkeypatch.setattr('ragrets.agent_service.GroqClient', FakeGroqClient)
    answer = answer_synthetic_demo_question('What increased?', [{'role': 'user', 'content': 'Start'}])

    assert answer.endswith('[oct-2]')
    assert captured['question'] == 'What increased?'
    assert captured['history'] == [{'role': 'user', 'content': 'Start'}]
    assert {record.source_id for record in captured['records']} == {'agentverse-synthetic-demo'}
    assert captured['report']['analysis']['current_period'] == '2026-10'