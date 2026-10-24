from ragrets.ingestion.loaders import _parse_synthetic_billing_pdf


def test_synthetic_pdf_parser_accepts_six_month_source_ids():
    periods = [
        ("2026-05", "may"),
        ("2026-06", "jun"),
        ("2026-07", "jul"),
        ("2026-08", "aug"),
        ("2026-09", "sep"),
        ("2026-10", "oct"),
    ]
    lines = [
        "Account ID Billing Period Invoice ID Currency "
        "demo-acct-02 2026-05 INV-DEMO-202605 USD",
        "Invoice totals",
    ]
    for period, _prefix in periods:
        lines.append(f"{period} $100.00 $0.00 $0.00 $10.00 $110.00")
    lines.append("Detailed usage records")
    for number, (period, prefix) in enumerate(periods, start=1):
        lines.append(
            f"{period} Compute us-east-1 cmp-prod-01 100.00 "
            f"instance-hour-equivalent $1.000 $100.00 $0.00 $0.00 "
            f"$100.00 {prefix}-001"
        )

    records, invoices = _parse_synthetic_billing_pdf("\n".join(lines))

    assert len(records) == 6
    assert len(invoices) == 6
    assert {item["billing_period"] for item in records} == {
        period for period, _ in periods
    }
    assert {item["source_record_id"] for item in records} == {
        f"{prefix}-001" for _, prefix in periods
    }
    assert all(item["account"] == "demo-acct-02" for item in records)
    assert all(item["account"] == "demo-acct-02" for item in invoices)
