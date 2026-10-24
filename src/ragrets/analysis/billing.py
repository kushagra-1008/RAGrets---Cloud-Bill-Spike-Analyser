import pandas as pd
from ..schemas import BillingRecord, InvoiceRecord


def _frame(records: list[BillingRecord]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(columns=["billing_period", "usage_cost", "credits", "adjustments", "net_cost", "service", "region", "resource_id"])
    frame = pd.DataFrame([r.model_dump() for r in records]).drop_duplicates(subset=["source_id", "source_record_id"])
    return frame


def reconcile_invoice(records: list[BillingRecord], invoice: InvoiceRecord, tolerance: float = 0.01) -> dict:
    frame = _frame([r for r in records if r.account == invoice.account and r.billing_period == invoice.billing_period])
    gross = round(float(frame.usage_cost.sum()), 2)
    credits = round(float(frame.credits.sum()), 2)
    adjustments = round(float(frame.adjustments.sum()), 2)
    detailed_net = round(float(frame.net_cost.sum()), 2)
    expected_pre_tax = round(invoice.usage_subtotal + invoice.credits + invoice.adjustments, 2)
    expected_invoice = round(expected_pre_tax + invoice.tax, 2)
    detail_difference = round(detailed_net - expected_pre_tax, 2)
    invoice_difference = round(invoice.invoice_total - expected_invoice, 2)
    return {"account": invoice.account, "billing_period": invoice.billing_period, "gross_usage": gross, "credits": credits, "adjustments": adjustments, "detailed_net": detailed_net, "tax": invoice.tax, "invoice_total": invoice.invoice_total, "expected_invoice_total": expected_invoice, "detail_difference": detail_difference, "invoice_difference": invoice_difference, "tolerance": tolerance, "status": "reconciled" if abs(detail_difference) <= tolerance and abs(invoice_difference) <= tolerance else "mismatch"}


def _breakdown(frame: pd.DataFrame, previous: str, current: str, group: list[str]) -> list[dict]:
    data = frame[frame.billing_period.isin([previous, current])]
    pivot = data.pivot_table(index=group, columns="billing_period", values="net_cost", aggfunc="sum", fill_value=0)
    pivot["previous_cost"] = pivot.get(previous, 0.0)
    pivot["current_cost"] = pivot.get(current, 0.0)
    pivot["absolute_change"] = pivot["current_cost"] - pivot["previous_cost"]
    pivot["percent_change"] = pivot.apply(lambda r: None if r.previous_cost == 0 else round(r.absolute_change / r.previous_cost * 100, 2), axis=1)
    return pivot.reset_index().sort_values("absolute_change", ascending=False).round(2).to_dict("records")


def analyze_periods(records: list[BillingRecord], previous: str, current: str) -> dict:
    frame = _frame(records)
    if previous == current:
        raise ValueError("Comparison periods must differ")
    all_regions = sorted(frame.region.dropna().unique().tolist())
    return {"previous_period": previous, "current_period": current, "filters_examined": {"billing_periods": [previous, current], "regions": "all available regions", "available_regions": all_regions}, "service_breakdown": _breakdown(frame, previous, current, ["service"]), "region_breakdown": _breakdown(frame, previous, current, ["region"]), "resource_breakdown": _breakdown(frame, previous, current, ["service", "region", "resource_id"])}
