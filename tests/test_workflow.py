from ragrets.ingestion import demo_data
from ragrets.schemas import BillingRecord, InvoiceRecord
from ragrets.workflow import run_workflow


def test_workflow_generates_traceable_report():
    records, invoices = demo_data()
    state = run_workflow("demo-acct", "2026-09", "2026-10", [BillingRecord(**x, source_id="demo") for x in records], [InvoiceRecord(**x, source_id="demo") for x in invoices])
    assert state["report"]["findings"]
    assert state["report"]["analysis"]["filters_examined"]["regions"] == "all available regions"
