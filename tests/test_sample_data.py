from pathlib import Path

from ragrets.analysis import reconcile_invoice
from ragrets.database import Database
from ragrets.ingestion import ingest_file


SAMPLE_DATA = Path(__file__).parents[1] / "sample_data"


def test_json_hackathon_sample_uploads_and_reconciles(tmp_path):
    db = Database(tmp_path / "json-sample.db")
    result = ingest_file(db, SAMPLE_DATA / "hackathon_billing_demo.json")
    assert result["status"] == "completed"
    assert result["records"] == 4
    assert result["invoices"] == 2
    october_invoice = next(invoice for invoice in db.invoices() if invoice.billing_period == "2026-10")
    reconciliation = reconcile_invoice(db.records(), october_invoice)
    assert reconciliation["status"] == "reconciled"
    assert reconciliation["gross_usage"] == 270.0
    assert reconciliation["credits"] == -10.0
    assert reconciliation["invoice_total"] == 286.0


def test_csv_hackathon_sample_uploads_as_billing_details_only(tmp_path):
    db = Database(tmp_path / "csv-sample.db")
    result = ingest_file(db, SAMPLE_DATA / "hackathon_billing_demo.csv")
    assert result["status"] == "completed"
    assert result["records"] == 4
    assert result["invoices"] == 0
    assert {record.region for record in db.records()} == {"us-east-1", "ap-south-1", "eu-west-1"}
