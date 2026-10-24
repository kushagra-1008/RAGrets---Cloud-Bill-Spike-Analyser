from ragrets.database import Database
from ragrets.ingestion import ingest_records, demo_data


def test_repeat_ingestion_is_idempotent(tmp_path):
    db = Database(tmp_path / "data.db")
    records, invoices = demo_data()
    first = ingest_records(db, records, invoices, "demo")
    second = ingest_records(db, records, invoices, "demo")
    assert first["run_id"] == second["run_id"]
    assert len(db.records()) == 4
