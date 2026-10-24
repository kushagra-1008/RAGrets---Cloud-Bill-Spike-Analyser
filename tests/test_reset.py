import json
from pathlib import Path

from ragrets.approvals import request_action
from ragrets.database import Database
from ragrets.ingestion import demo_data, ingest_file, ingest_records
from ragrets.workflow import run_workflow


SAMPLE_JSON = Path(__file__).parents[1] / "sample_data" / "hackathon_billing_demo.json"


def test_reset_clears_billing_data_but_preserves_approval_and_audit_history(tmp_path):
    db = Database(tmp_path / "reset.db")
    records, invoices = demo_data()
    ingest_records(db, records, invoices, "demo")
    request_action(db, "delete-demo-instance", "delete_instance", "i-demo", "analyst")

    counts = db.clear_billing_data()

    assert counts == {"billing_records": 4, "invoices": 2, "evidence": 1}
    assert db.records() == []
    assert db.invoices() == []
    assert db.evidence() == []
    with db.connection() as conn:
        approval = conn.execute("SELECT status FROM approvals WHERE action_key='delete-demo-instance'").fetchone()
        audit_events = [row["event_type"] for row in conn.execute("SELECT event_type FROM audit_events ORDER BY id")]
    assert approval["status"] == "pending"
    assert audit_events == ["action_requested", "billing_data_reset"]


def test_new_upload_can_be_analyzed_after_reset(tmp_path):
    db = Database(tmp_path / "reset-and-upload.db")
    records, invoices = demo_data()
    ingest_records(db, records, invoices, "demo")
    db.clear_billing_data()

    upload = ingest_file(db, SAMPLE_JSON)
    state = run_workflow("demo-acct", "2026-09", "2026-10", db.records(), db.invoices(), db.evidence())

    assert upload["status"] == "completed"
    assert not state.get("errors")
    assert state["report"]["analysis"]["resource_breakdown"][0]["region"] == "ap-south-1"
