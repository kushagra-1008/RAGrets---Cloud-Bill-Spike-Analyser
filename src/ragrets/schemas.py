from datetime import date, datetime, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class BillingRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account: str
    billing_period: str
    service: str
    region: str
    resource_id: str
    usage_quantity: float = Field(ge=0)
    usage_unit: str
    unit_price: float = Field(ge=0)
    usage_cost: float = Field(ge=0)
    credits: float = 0
    adjustments: float = 0
    net_cost: float
    source_record_id: str
    source_id: str = "unknown"

    @field_validator("billing_period")
    @classmethod
    def valid_period(cls, value: str) -> str:
        try:
            date.fromisoformat(f"{value}-01")
        except ValueError as exc:
            raise ValueError("billing_period must be YYYY-MM") from exc
        return value


class InvoiceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account: str
    billing_period: str
    usage_subtotal: float
    credits: float = 0
    adjustments: float = 0
    tax: float = 0
    invoice_total: float
    source_id: str = "unknown"

    @field_validator("billing_period")
    @classmethod
    def valid_period(cls, value: str) -> str:
        BillingRecord.valid_period(value)
        return value


class EvidenceRecord(BaseModel):
    source_id: str
    content_hash: str
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reference: str | None = None
    url: str | None = None


class ApprovalRequest(BaseModel):
    action_key: str
    action_type: str
    target: str
    requested_by: str
    status: Literal["pending", "approved", "rejected", "completed", "failed"] = "pending"
