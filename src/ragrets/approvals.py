from datetime import datetime, timezone
from .database import Database
from .schemas import ApprovalRequest


def request_action(db: Database, action_key: str, action_type: str, target: str, requested_by: str) -> ApprovalRequest:
    with db.connection() as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO approvals VALUES (?, ?, ?, ?, ?, ?, ?)",
            (action_key, action_type, target, requested_by, "pending", None, datetime.now(timezone.utc).isoformat()),
        )
        row = conn.execute("SELECT * FROM approvals WHERE action_key=?", (action_key,)).fetchone()
    request = ApprovalRequest(
        action_key=row["action_key"],
        action_type=row["action_type"],
        target=row["target"],
        requested_by=row["requested_by"],
        status=row["status"],
    )
    if cursor.rowcount:
        db.audit("action_requested", request.model_dump())
    return request


def decide_action(db: Database, action_key: str, approved: bool, approver: str) -> dict:
    status = "approved" if approved else "rejected"
    with db.connection() as conn:
        row = conn.execute("SELECT * FROM approvals WHERE action_key=?", (action_key,)).fetchone()
        if not row:
            raise ValueError("Unknown action request")
        if row["status"] != "pending":
            return dict(row)
        conn.execute("UPDATE approvals SET status=?, result=?, updated_at=? WHERE action_key=?", (status, f"decision by {approver}", datetime.now(timezone.utc).isoformat(), action_key))
    db.audit("action_decision", {"action_key": action_key, "status": status, "approver": approver})
    return {"action_key": action_key, "status": status}


def execute_simulated_action(db: Database, action_key: str) -> dict:
    with db.connection() as conn:
        row = conn.execute("SELECT * FROM approvals WHERE action_key=?", (action_key,)).fetchone()
        if not row or row["status"] == "pending":
            result = {"action_key": action_key, "status": "pending_approval", "message": "No real resources changed."}
        elif row["status"] == "rejected":
            result = {"action_key": action_key, "status": "rejected", "message": "Action was rejected; no real resources changed."}
        elif row["status"] == "completed":
            result = {"action_key": action_key, "status": "completed", "message": row["result"] or "Simulated only; no real resources changed."}
        elif row["status"] != "approved":
            result = {"action_key": action_key, "status": row["status"], "message": "No real resources changed."}
        else:
            result = {"action_key": action_key, "status": "completed", "message": "Simulated only; no real resources changed."}
            conn.execute("UPDATE approvals SET status='completed', result=?, updated_at=? WHERE action_key=?", (result["message"], datetime.now(timezone.utc).isoformat(), action_key))

    db.save_action_result(action_key, result["status"], result)
    if result["status"] == "completed" and row and row["status"] == "approved":
        db.audit("action_completed", {"action_key": action_key, "simulated": True})
    return result
