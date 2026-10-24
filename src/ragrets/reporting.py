import json
import math
from pathlib import Path
import pandas as pd
from .schemas import BillingRecord, EvidenceRecord


CAUSE_LIMITATION = (
    "Billing records confirm the cost change, but do not establish why the resource usage or price changed."
)
CAUSE_EVIDENCE_NEEDED = [
    "resource utilization or configuration history",
    "deployment, scaling, or reservation-change events",
    "provider pricing or rate-plan evidence",
]


def _finding_for_driver(driver: dict, records: list[BillingRecord], evidence_by_source: dict[str, EvidenceRecord]) -> dict:
    matching = [
        record for record in records
        if record.billing_period in {driver["previous_period"], driver["current_period"]}
        and record.service == driver["service"]
        and record.region == driver["region"]
        and record.resource_id == driver["resource_id"]
    ]
    supporting_record_ids = sorted({record.source_record_id for record in matching})
    source_ids = sorted({record.source_id for record in matching})
    provenance = []
    missing_evidence_sources = []
    for source_id in source_ids:
        item = {"source_id": source_id, "source_record_ids": sorted({record.source_record_id for record in matching if record.source_id == source_id})}
        evidence = evidence_by_source.get(source_id)
        if evidence:
            item["content_hash"] = evidence.content_hash
            item["retrieved_at"] = evidence.retrieved_at.isoformat()
            if evidence.reference:
                item["reference"] = evidence.reference
            if evidence.url:
                item["url"] = evidence.url
        else:
            missing_evidence_sources.append(source_id)
        provenance.append(item)
    return {
        "service": driver["service"],
        "region": driver["region"],
        "resource_id": driver["resource_id"],
        "previous_cost": driver["previous_cost"],
        "current_cost": driver["current_cost"],
        "absolute_change": driver["absolute_change"],
        "finding": f"{driver['service']} {driver['resource_id']} in {driver['region']} increased by {driver['absolute_change']:.2f}.",
        "cost_change_status": "confirmed" if supporting_record_ids else "uncertain",
        "supporting_source_record_ids": supporting_record_ids,
        "provenance": provenance,
        "cause_assessment": {
            "status": "uncertain",
            "explanation": CAUSE_LIMITATION,
            "additional_evidence_needed": CAUSE_EVIDENCE_NEEDED,
        },
        "evidence_quality_warnings": [f"Evidence metadata is missing for source: {source_id}." for source_id in missing_evidence_sources],
    }


def build_report(
    analysis: dict,
    reconciliations: list[dict],
    records: list[BillingRecord] | None = None,
    evidence: list[EvidenceRecord] | None = None,
) -> dict:
    records = records or []
    evidence_by_source = {item.source_id: item for item in evidence or []}
    drivers = [r for r in analysis["resource_breakdown"] if r["absolute_change"] > 0][:5]
    findings = [_finding_for_driver({**driver, "previous_period": analysis["previous_period"], "current_period": analysis["current_period"]}, records, evidence_by_source) for driver in drivers]
    data_quality_warnings = []
    reconciled_periods = {item["billing_period"] for item in reconciliations}
    for period in (analysis["previous_period"], analysis["current_period"]):
        if period not in reconciled_periods:
            data_quality_warnings.append(f"Missing invoice data for billing period {period}; detailed records cannot be reconciled to an invoice.")
    if any(item["status"] != "reconciled" for item in reconciliations):
        data_quality_warnings.append("At least one invoice does not reconcile within the stated $0.01 tolerance.")
    for finding in findings:
        data_quality_warnings.extend(finding["evidence_quality_warnings"])
    return {"analysis": analysis, "reconciliations": reconciliations, "findings": findings, "recommendations": ["Review the confirmed cost changes with the service owner.", "Collect causal evidence before attributing a cost increase to a specific operational change.", "Use the approval workflow before any resource-changing action."], "data_quality_warnings": list(dict.fromkeys(data_quality_warnings))}


def display_breakdown(rows: list[dict]) -> list[dict]:
    """Format only presentation values; deterministic calculation values remain unchanged."""
    formatted = []
    for row in rows:
        item = dict(row)
        percentage = item.get("percent_change")
        try:
            numeric_percentage = float(percentage)
        except (TypeError, ValueError):
            numeric_percentage = None
        item["percent_change"] = (
            "— (no baseline)"
            if numeric_percentage is None or not math.isfinite(numeric_percentage)
            else f"{numeric_percentage:.2f}%"
        )
        formatted.append(item)
    return formatted


def ready_for_new_bill_message(records: list[BillingRecord], reset_message: str | None) -> str | None:
    """Return the empty-state banner text only while no billing records are loaded."""
    if records:
        return None
    return reset_message or "Ready for a new billing file. Upload CSV or JSON to begin."


def export_report(report: dict, directory: str | Path) -> dict:
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "ragrets-report.json"
    csv_path = directory / "cost-drivers.csv"
    summary_path = directory / "ragrets-summary.md"
    json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    csv_rows = []
    for breakdown_name in ("service_breakdown", "region_breakdown", "resource_breakdown"):
        csv_rows.extend({"breakdown": breakdown_name.removesuffix("_breakdown"), **row} for row in report["analysis"][breakdown_name])
    pd.DataFrame(csv_rows).to_csv(csv_path, index=False)
    lines = ["# RAGrets report", "", "## Evidence-backed findings", ""]
    for finding in report["findings"]:
        lines.extend([
            f"- **Confirmed cost change:** {finding['finding']}",
            f"  - Previous: {finding['previous_cost']:.2f}; current: {finding['current_cost']:.2f}; change: {finding['absolute_change']:.2f}",
            f"  - Source record IDs: {', '.join(finding['supporting_source_record_ids']) or 'none'}",
            f"  - Cause assessment: {finding['cause_assessment']['status']} — {finding['cause_assessment']['explanation']}",
        ])
        for provenance in finding["provenance"]:
            details = [f"source {provenance['source_id']}"]
            if provenance.get("url"):
                details.append(provenance["url"])
            if provenance.get("retrieved_at"):
                details.append(f"retrieved {provenance['retrieved_at']}")
            lines.append("  - Provenance: " + "; ".join(details))
    if report["data_quality_warnings"]:
        lines.extend(["", "## Data quality warnings", ""])
        lines.extend(f"- {warning}" for warning in report["data_quality_warnings"])
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": json_path, "csv": csv_path, "summary": summary_path}
