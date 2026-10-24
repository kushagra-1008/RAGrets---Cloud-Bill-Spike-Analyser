from datetime import datetime, timezone
import pandas as pd

from ragrets.analysis import analyze_periods
from ragrets.ingestion import demo_data
from ragrets.reporting import CAUSE_LIMITATION, build_report, display_breakdown, export_report, ready_for_new_bill_message
from ragrets.schemas import BillingRecord, EvidenceRecord, InvoiceRecord
from ragrets.analysis import reconcile_invoice
from ragrets.workflow import run_workflow


def _models():
    records, invoices = demo_data()
    return [BillingRecord(**item, source_id="demo") for item in records], [InvoiceRecord(**item, source_id="demo") for item in invoices]


def test_findings_include_deterministic_costs_and_traceable_provenance():
    records, invoices = _models()
    analysis = analyze_periods(records, "2026-09", "2026-10")
    evidence = [EvidenceRecord(source_id="demo", content_hash="abc123", retrieved_at=datetime(2026, 10, 20, tzinfo=timezone.utc), url="https://billing.example/export")]
    report = build_report(analysis, [reconcile_invoice(records, invoice) for invoice in invoices], records, evidence)
    finding = next(item for item in report["findings"] if item["resource_id"] == "i-new")
    assert {key: finding[key] for key in ("service", "region", "resource_id", "previous_cost", "current_cost", "absolute_change")} == {"service": "Compute", "region": "ap-south-1", "resource_id": "i-new", "previous_cost": 0.0, "current_cost": 120.0, "absolute_change": 120.0}
    assert finding["supporting_source_record_ids"] == ["oct-2"]
    assert finding["provenance"][0]["url"] == "https://billing.example/export"
    assert finding["provenance"][0]["retrieved_at"] == "2026-10-20T00:00:00+00:00"
    assert finding["cost_change_status"] == "confirmed"


def test_missing_evidence_is_uncertain_and_explains_what_is_needed():
    records, invoices = _models()
    report = build_report(analyze_periods(records, "2026-09", "2026-10"), [reconcile_invoice(records, invoice) for invoice in invoices], records, [])
    finding = report["findings"][0]
    assert finding["cause_assessment"]["status"] == "uncertain"
    assert finding["cause_assessment"]["explanation"] == CAUSE_LIMITATION
    assert finding["cause_assessment"]["additional_evidence_needed"]
    assert "Evidence metadata is missing for source: demo." in report["data_quality_warnings"]


def test_missing_invoice_data_is_reported_without_stopping_analysis():
    records, _ = _models()
    state = run_workflow("demo-acct", "2026-09", "2026-10", records, [])
    assert not state.get("errors")
    assert "Missing invoice data for billing period 2026-09; detailed records cannot be reconciled to an invoice." in state["report"]["data_quality_warnings"]
    assert "Missing invoice data for billing period 2026-10; detailed records cannot be reconciled to an invoice." in state["report"]["data_quality_warnings"]


def test_display_breakdown_marks_zero_baseline_without_a_misleading_percentage():
    rows = [
        {"previous_cost": 0.0, "current_cost": 120.0, "absolute_change": 120.0, "percent_change": None},
        {"previous_cost": 0.0, "current_cost": 120.0, "absolute_change": 120.0, "percent_change": float("nan")},
        {"previous_cost": 0.0, "current_cost": 120.0, "absolute_change": 120.0, "percent_change": float("inf")},
        {"previous_cost": 100.0, "current_cost": 125.0, "absolute_change": 25.0, "percent_change": 25.0},
    ]
    assert [item["percent_change"] for item in display_breakdown(rows)] == [
        "— (no baseline)",
        "— (no baseline)",
        "— (no baseline)",
        "25.00%",
    ]


def test_ready_for_new_bill_message_is_hidden_when_billing_records_are_loaded():
    records, _ = _models()
    assert ready_for_new_bill_message([], None) == "Ready for a new billing file. Upload CSV or JSON to begin."
    assert ready_for_new_bill_message([], "Ready for a new billing file. Upload CSV or JSON to begin.") == "Ready for a new billing file. Upload CSV or JSON to begin."
    assert ready_for_new_bill_message(records, "Ready for a new billing file. Upload CSV or JSON to begin.") is None


def test_export_report_writes_json_csv_and_evidence_backed_markdown(tmp_path):
    records, invoices = _models()
    analysis = analyze_periods(records, "2026-09", "2026-10")
    report = build_report(analysis, [reconcile_invoice(records, invoice) for invoice in invoices], records)
    paths = export_report(report, tmp_path)
    assert all(path.exists() for path in paths.values())
    assert {"service", "region", "resource"}.issubset(set(pd.read_csv(paths["csv"])["breakdown"]))
    summary = paths["summary"].read_text(encoding="utf-8")
    assert "Confirmed cost change" in summary
    assert "Cause assessment: uncertain" in summary
