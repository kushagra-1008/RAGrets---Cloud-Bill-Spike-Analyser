from ragrets.ingestion import demo_data
from ragrets.schemas import BillingRecord, InvoiceRecord
from ragrets.analysis import reconcile_invoice, analyze_periods


def _models():
    records, invoices = demo_data()
    return [BillingRecord(**r, source_id="demo") for r in records], [InvoiceRecord(**i, source_id="demo") for i in invoices]


def test_tc1_invoice_reconciliation_detects_mismatch():
    records, invoices = _models()
    assert reconcile_invoice(records, invoices[0])["status"] == "reconciled"
    bad = invoices[1].model_copy(update={"invoice_total": 999})
    assert reconcile_invoice(records, bad)["status"] == "mismatch"


def test_tc2_credits_are_separate_from_usage():
    records, invoices = _models()
    result = reconcile_invoice(records, invoices[1])
    assert result["gross_usage"] == 270
    assert result["credits"] == -10
    assert result["invoice_total"] == 286


def test_tc3_all_regions_are_examined():
    records, _ = _models()
    report = analyze_periods(records, "2026-09", "2026-10")
    assert "ap-south-1" in report["filters_examined"]["available_regions"]
    assert report["region_breakdown"][0]["region"] == "ap-south-1"
