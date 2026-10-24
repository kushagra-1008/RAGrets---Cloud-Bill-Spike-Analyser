import json

from ragrets.approvals import decide_action, execute_simulated_action, request_action
from ragrets.database import Database


def _status(db, action_key):
    with db.connection() as conn:
        return conn.execute("SELECT status FROM approvals WHERE action_key=?", (action_key,)).fetchone()["status"]


def _completion_audits(db):
    with db.connection() as conn:
        return [json.loads(row["detail"]) for row in conn.execute("SELECT detail FROM audit_events WHERE event_type='action_completed'")]


def test_pending_approval_blocks_execution(tmp_path):
    db = Database(tmp_path / "actions.db")
    request_action(db, "delete-i-new", "delete_instance", "i-new", "analyst")
    result = execute_simulated_action(db, "delete-i-new")
    assert result["status"] == "pending_approval"
    assert _status(db, "delete-i-new") == "pending"
    with db.connection() as conn:
        saved = conn.execute("SELECT status, result FROM action_results WHERE action_key='delete-i-new'").fetchone()
    assert saved["status"] == "pending_approval"
    assert json.loads(saved["result"]) == result


def test_approved_execution_is_completed_once_and_is_idempotent(tmp_path):
    db = Database(tmp_path / "actions.db")
    request_action(db, "delete-i-new", "delete_instance", "i-new", "analyst")
    assert decide_action(db, "delete-i-new", True, "owner")["status"] == "approved"
    done = execute_simulated_action(db, "delete-i-new")
    assert done["status"] == "completed"
    assert "no real resources" in done["message"].lower()
    assert execute_simulated_action(db, "delete-i-new")["status"] == "completed"
    assert _status(db, "delete-i-new") == "completed"
    assert _completion_audits(db) == [{"action_key": "delete-i-new", "simulated": True}]
    with db.connection() as conn:
        saved = conn.execute("SELECT status, result FROM action_results WHERE action_key='delete-i-new'").fetchone()
    assert saved["status"] == "completed"
    assert json.loads(saved["result"])["message"] == "Simulated only; no real resources changed."


def test_rerequesting_a_completed_action_does_not_reset_it(tmp_path):
    db = Database(tmp_path / "actions.db")
    request_action(db, "delete-i-new", "delete_instance", "i-new", "analyst")
    decide_action(db, "delete-i-new", True, "owner")
    execute_simulated_action(db, "delete-i-new")

    existing = request_action(db, "delete-i-new", "delete_instance", "i-new", "another-analyst")

    assert existing.status == "completed"
    assert existing.requested_by == "analyst"
    assert _status(db, "delete-i-new") == "completed"
    assert execute_simulated_action(db, "delete-i-new")["status"] == "completed"
    assert len(_completion_audits(db)) == 1
