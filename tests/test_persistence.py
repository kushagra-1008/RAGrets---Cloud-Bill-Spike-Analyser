from ragrets.database import Database


def test_reports_are_persisted_once_per_content_and_periods(tmp_path):
    db = Database(tmp_path / "reports.db")
    report = {"analysis": {"total_change": 120.0}, "findings": []}

    report_id = db.save_report(report, "account-a", "2026-09", "2026-10")
    repeated_id = db.save_report(report, "account-a", "2026-09", "2026-10")

    assert repeated_id == report_id
    saved = db.reports()
    assert len(saved) == 1
    assert saved[0]["report_id"] == report_id
    assert saved[0]["payload"] == report

    db.save_report(report, "account-a", "2026-10", "2026-11")
    assert len(db.reports()) == 2


def test_action_result_upsert_keeps_latest_status(tmp_path):
    db = Database(tmp_path / "actions.db")

    db.save_action_result("delete-one", "pending_approval", {"status": "pending_approval"})
    db.save_action_result("delete-one", "completed", {"status": "completed", "simulated": True})

    with db.connection() as conn:
        row = conn.execute("SELECT status, result FROM action_results WHERE action_key='delete-one'").fetchone()
    assert row["status"] == "completed"
    assert '"simulated": true' in row["result"]
