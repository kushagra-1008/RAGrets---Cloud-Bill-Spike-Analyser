from ragrets.database import Database
from ragrets.schemas import BillingRecord


def test_database_initializes(tmp_path):
    db = Database(tmp_path / "test.db")
    db.audit("test", {"ok": True})
    assert db.records() == []


def test_billing_period_validation():
    payload = dict(account="a", billing_period="2026-10", service="EC2", region="us-east-1", resource_id="i-1", usage_quantity=1, usage_unit="hour", unit_price=1, usage_cost=1, net_cost=1, source_record_id="r1")
    assert BillingRecord(**payload).billing_period == "2026-10"
