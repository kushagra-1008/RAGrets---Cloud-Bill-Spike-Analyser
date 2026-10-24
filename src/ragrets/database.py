import json
import hashlib
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from .schemas import BillingRecord, InvoiceRecord, EvidenceRecord


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self.initialize()

    def connection(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self):
        with self.connection() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS ingestion_runs (run_id TEXT PRIMARY KEY, source_hash TEXT UNIQUE, status TEXT NOT NULL, issues TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS billing_records (source_id TEXT NOT NULL, source_record_id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(source_id, source_record_id));
            CREATE TABLE IF NOT EXISTS invoices (account TEXT NOT NULL, billing_period TEXT NOT NULL, source_id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(account, billing_period, source_id));
            CREATE TABLE IF NOT EXISTS evidence (source_id TEXT PRIMARY KEY, content_hash TEXT NOT NULL, retrieved_at TEXT NOT NULL, reference_text TEXT, url TEXT);
            CREATE TABLE IF NOT EXISTS approvals (action_key TEXT PRIMARY KEY, action_type TEXT NOT NULL, target TEXT NOT NULL, requested_by TEXT NOT NULL, status TEXT NOT NULL, result TEXT, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS action_results (action_key TEXT PRIMARY KEY, status TEXT NOT NULL, result TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS reports (report_id TEXT PRIMARY KEY, account TEXT NOT NULL, previous_period TEXT NOT NULL, current_period TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS audit_events (id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL);
            """)

    def record_run(self, run_id, source_hash, status, issues=()):
        with self.connection() as conn:
            conn.execute("INSERT OR IGNORE INTO ingestion_runs VALUES (?, ?, ?, ?, ?)", (run_id, source_hash, status, json.dumps(list(issues)), datetime.now(timezone.utc).isoformat()))

    def save_records(self, records: list[BillingRecord]):
        with self.connection() as conn:
            conn.executemany("INSERT OR REPLACE INTO billing_records VALUES (?, ?, ?)", [(r.source_id, r.source_record_id, r.model_dump_json()) for r in records])

    def save_invoices(self, invoices: list[InvoiceRecord]):
        with self.connection() as conn:
            conn.executemany("INSERT OR REPLACE INTO invoices VALUES (?, ?, ?, ?)", [(i.account, i.billing_period, i.source_id, i.model_dump_json()) for i in invoices])

    def save_evidence(self, evidence: EvidenceRecord):
        with self.connection() as conn:
            conn.execute("INSERT OR REPLACE INTO evidence VALUES (?, ?, ?, ?, ?)", (evidence.source_id, evidence.content_hash, evidence.retrieved_at.isoformat(), evidence.reference, evidence.url))

    def save_report(self, report: dict, account: str, previous_period: str, current_period: str) -> str:
        payload = json.dumps(report, sort_keys=True, separators=(",", ":"), default=str)
        identity = json.dumps(
            {"account": account, "previous_period": previous_period, "current_period": current_period, "report": payload},
            sort_keys=True,
            separators=(",", ":"),
        )
        report_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        with self.connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO reports VALUES (?, ?, ?, ?, ?, ?)",
                (report_id, account, previous_period, current_period, payload, datetime.now(timezone.utc).isoformat()),
            )
        return report_id

    def reports(self, limit: int = 20) -> list[dict]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT report_id, account, previous_period, current_period, payload, created_at "
                "FROM reports ORDER BY created_at DESC, report_id DESC LIMIT ?",
                (max(0, limit),),
            )
            return [
                {**dict(row), "payload": json.loads(row["payload"])}
                for row in rows
            ]

    def save_action_result(self, action_key: str, status: str, result: dict) -> None:
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO action_results VALUES (?, ?, ?, ?) "
                "ON CONFLICT(action_key) DO UPDATE SET status=excluded.status, result=excluded.result, updated_at=excluded.updated_at",
                (action_key, status, json.dumps(result, sort_keys=True), datetime.now(timezone.utc).isoformat()),
            )

    def records(self):
        with self.connection() as conn:
            return [BillingRecord.model_validate_json(row["payload"]) for row in conn.execute("SELECT payload FROM billing_records")]

    def invoices(self):
        with self.connection() as conn:
            return [InvoiceRecord.model_validate_json(row["payload"]) for row in conn.execute("SELECT payload FROM invoices")]

    def evidence(self):
        with self.connection() as conn:
            return [
                EvidenceRecord(
                    source_id=row["source_id"],
                    content_hash=row["content_hash"],
                    retrieved_at=row["retrieved_at"],
                    reference=row["reference_text"],
                    url=row["url"],
                )
                for row in conn.execute("SELECT * FROM evidence")
            ]

    def clear_billing_data(self) -> dict[str, int]:
        """Clear the current bill while retaining approval and audit history."""
        tables = ("billing_records", "invoices", "evidence")
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            counts = {
                table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in tables
            }
            for table in tables:
                conn.execute(f"DELETE FROM {table}")
            conn.execute(
                "INSERT INTO audit_events(event_type,detail,created_at) VALUES (?,?,?)",
                (
                    "billing_data_reset",
                    json.dumps(counts),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return counts

    def audit(self, event_type, detail):
        with self.connection() as conn:
            conn.execute("INSERT INTO audit_events(event_type,detail,created_at) VALUES (?,?,?)", (event_type, json.dumps(detail), datetime.now(timezone.utc).isoformat()))
