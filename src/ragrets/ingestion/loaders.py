
import hashlib
import json
import re
from pathlib import Path
from uuid import uuid5, NAMESPACE_URL

import pandas as pd
from pydantic import ValidationError

from ..database import Database
from ..schemas import BillingRecord, InvoiceRecord, EvidenceRecord


RECORD_COLUMNS = set(BillingRecord.model_fields) - {"source_id"}
INVOICE_COLUMNS = set(InvoiceRecord.model_fields) - {"source_id"}


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def ingest_records(
    db: Database,
    records_data: list[dict],
    invoices_data: list[dict],
    source_id: str,
    raw: bytes | None = None,
) -> dict:
    raw = raw or json.dumps(
        {"records": records_data, "invoices": invoices_data},
        sort_keys=True,
    ).encode()

    content_hash = _digest(raw)
    run_id = str(uuid5(NAMESPACE_URL, content_hash))
    issues = []

    try:
        records = [
            BillingRecord(**item, source_id=source_id)
            for item in records_data
        ]
        invoices = [
            InvoiceRecord(**item, source_id=source_id)
            for item in invoices_data
        ]
    except ValidationError as exc:
        issues.append(str(exc))
        db.record_run(run_id, content_hash, "failed", issues)
        return {
            "run_id": run_id,
            "status": "failed",
            "issues": issues,
        }

    if not records:
        issues.append("No billing records were found.")
        db.record_run(run_id, content_hash, "failed", issues)
        return {
            "run_id": run_id,
            "status": "failed",
            "issues": issues,
        }

    db.record_run(run_id, content_hash, "completed")
    db.save_records(records)
    db.save_invoices(invoices)
    db.save_evidence(
        EvidenceRecord(
            source_id=source_id,
            content_hash=content_hash,
            reference="normalized billing export",
        )
    )

    return {
        "run_id": run_id,
        "status": "completed",
        "records": len(records),
        "invoices": len(invoices),
        "issues": issues,
    }


def _money(value: str) -> float:
    """Parse values such as $60.00, -$5.00, and $0.00."""
    value = value.strip().replace(",", "").replace("$", "")
    return float(value)


def _extract_pdf_text(raw: bytes) -> tuple[str, int]:
    """Extract selectable text from a PDF using PyMuPDF."""
    try:
        import pymupdf
    except ImportError as exc:
        raise RuntimeError(
            "PDF support requires PyMuPDF. Install it with "
            "'python -m pip install pymupdf'."
        ) from exc

    with pymupdf.open(stream=raw, filetype="pdf") as document:
        page_count = len(document)
        text = "\n".join(page.get_text() for page in document).strip()

    if not text:
        raise ValueError(
            "No selectable text was found in the PDF. "
            "It may be scanned and require OCR."
        )

    return text, page_count


def _parse_synthetic_billing_pdf(text: str) -> tuple[list[dict], list[dict]]:
    """
    Parse the specific synthetic cloud bill created for RAGrets.

    This parser expects the source IDs and fields in the detailed usage
    table, such as may-001, oct-001, and nov-001. It deliberately fails closed if
    the expected table rows cannot be recognized.
    """
    records = []
    invoices = []

    # Extract account and billing-period metadata from the summary table.
    account_match = re.search(
        r"Account ID\s+Billing Period\s+Invoice ID\s+Currency\s+"
        r"(demo-acct-\S+)\s+(\d{4}-\d{2})\s+(\S+)\s+USD",
        text,
        re.IGNORECASE,
    )
    if not account_match:
        raise ValueError(
            "Could not recognize the synthetic bill's account summary."
        )

    account = account_match.group(1)

    # Extract the invoice table. The expected columns are:
    # period, usage subtotal, credits, adjustments, tax, invoice total.
    invoice_pattern = re.compile(
        r"(\d{4}-\d{2})\s+"
        r"(\$[\d,]+\.\d{2})\s+"
        r"(-?\$[\d,]+\.\d{2})\s+"
        r"(\$[\d,]+\.\d{2})\s+"
        r"(\$[\d,]+\.\d{2})\s+"
        r"(\$[\d,]+\.\d{2})"
    )

    invoice_section = text.split("Invoice totals", 1)
    if len(invoice_section) != 2:
        raise ValueError("Invoice totals section was not found.")

    invoice_text = invoice_section[1].split(
        "Detailed usage records", 1
    )[0]

    for match in invoice_pattern.finditer(invoice_text):
        period, subtotal, credits, adjustments, tax, total = match.groups()
        invoices.append(
            {
                "account": account,
                "billing_period": period,
                "usage_subtotal": _money(subtotal),
                "credits": _money(credits),
                "adjustments": _money(adjustments),
                "tax": _money(tax),
                "invoice_total": _money(total),
            }
        )

    # PDF text extraction often separates table cells by whitespace.
    # Parse the known row layout, while requiring an explicit source ID.
    row_pattern = re.compile(
        r"(2026-\d{2})\s+"
        r"(Compute|Storage|Database|Networking)\s+"
        r"([a-z]{2}-[a-z]+-\d)\s+"
        r"([A-Za-z0-9_-]+)\s+"
        r"([\d.]+)\s+"
        r"(\$[\d.]+)\s+"
        r"(\$[\d.]+)\s+"
        r"(-?\$[\d.]+)\s+"
        r"(\$[\d.]+)\s+"
        r"(\$[\d.]+)\s+"
        r"([A-Za-z][A-Za-z0-9_-]*-\d+)",
        re.IGNORECASE,
    )

    # Handle the generated table's compact usage column, e.g.
    # "500 inst-hr" or "800 GB-month".
    compact_row_pattern = re.compile(
        r"(2026-\d{2})\s+"
        r"(Compute|Storage|Database|Networking)\s+"
        r"([a-z]{2}-[a-z]+-\d)\s+"
        r"([A-Za-z0-9_-]+)\s+"
        r"([\d.]+)\s+"
        r"(\S+)\s+"
        r"(\$[\d.]+)\s+"
        r"(\$[\d.]+)\s+"
        r"(-?\$[\d.]+)\s+"
        r"(\$[\d.]+)\s+"
        r"(\$[\d.]+)\s+"
        r"([A-Za-z][A-Za-z0-9_-]*-\d+)",
        re.IGNORECASE,
    )

    for match in compact_row_pattern.finditer(text):
        (
            period, service, region, resource_id, quantity, unit,
            unit_price, usage_cost, credits, adjustments, net_cost, source_id
        ) = match.groups()

        records.append(
            {
                "account": account,
                "billing_period": period,
                "service": service,
                "region": region,
                "resource_id": resource_id,
                "usage_quantity": float(quantity),
                "usage_unit": unit,
                "unit_price": _money(unit_price),
                "usage_cost": _money(usage_cost),
                "credits": _money(credits),
                "adjustments": _money(adjustments),
                "net_cost": _money(net_cost),
                "source_record_id": source_id,
            }
        )

    # Do not silently accept a PDF if its line-item table was not parsed.
    if not records:
        raise ValueError(
            "The PDF text was extracted, but its detailed billing table "
            "did not match the supported synthetic format. No records imported."
        )

    if not invoices:
        raise ValueError(
            "No invoice totals could be extracted from the PDF. "
            "No records imported."
        )

    # Validate against the project's schemas before returning any data.
    try:
        for item in records:
            BillingRecord(**item, source_id="pdf-validation")
        for item in invoices:
            InvoiceRecord(**item, source_id="pdf-validation")
    except ValidationError as exc:
        raise ValueError(
            f"Extracted PDF data failed schema validation: {exc}"
        ) from exc

    return records, invoices


def ingest_file(
    db: Database,
    path: str | Path,
    source_id: str | None = None,
) -> dict:
    path = Path(path)
    raw = path.read_bytes()
    source_id = source_id or path.name
    suffix = path.suffix.lower()

    if suffix == ".csv":
        records = pd.read_csv(path).fillna(0).to_dict("records")
        return ingest_records(db, records, [], source_id, raw)

    if suffix == ".json":
        payload = json.loads(raw)
        if isinstance(payload, list):
            payload = {"records": payload, "invoices": []}

        return ingest_records(
            db,
            payload.get("records", []),
            payload.get("invoices", []),
            source_id,
            raw,
        )

    if suffix == ".pdf":
        text, page_count = _extract_pdf_text(raw)
        records, invoices = _parse_synthetic_billing_pdf(text)

        result = ingest_records(
            db,
            records,
            invoices,
            source_id,
            raw,
        )
        result["pages"] = page_count
        result["extraction"] = "synthetic-layout-parser"
        return result

    raise ValueError(
        "Unsupported file type. Supported formats: CSV, JSON, PDF."
    )


def demo_data():
    records = [
        {
            "account": "demo-acct",
            "billing_period": "2026-09",
            "service": "Compute",
            "region": "us-east-1",
            "resource_id": "i-steady",
            "usage_quantity": 100,
            "usage_unit": "hours",
            "unit_price": 1,
            "usage_cost": 100,
            "credits": -10,
            "adjustments": 0,
            "net_cost": 90,
            "source_record_id": "sep-1",
        },
        {
            "account": "demo-acct",
            "billing_period": "2026-10",
            "service": "Compute",
            "region": "us-east-1",
            "resource_id": "i-steady",
            "usage_quantity": 100,
            "usage_unit": "hours",
            "unit_price": 1,
            "usage_cost": 100,
            "credits": -10,
            "adjustments": 0,
            "net_cost": 90,
            "source_record_id": "oct-1",
        },
        {
            "account": "demo-acct",
            "billing_period": "2026-10",
            "service": "Compute",
            "region": "ap-south-1",
            "resource_id": "i-new",
            "usage_quantity": 80,
            "usage_unit": "hours",
            "unit_price": 1.5,
            "usage_cost": 120,
            "credits": 0,
            "adjustments": 0,
            "net_cost": 120,
            "source_record_id": "oct-2",
        },
        {
            "account": "demo-acct",
            "billing_period": "2026-10",
            "service": "Storage",
            "region": "eu-west-1",
            "resource_id": "bucket-logs",
            "usage_quantity": 1000,
            "usage_unit": "GB-month",
            "unit_price": 0.05,
            "usage_cost": 50,
            "credits": 0,
            "adjustments": 0,
            "net_cost": 50,
            "source_record_id": "oct-3",
        },
    ]

    invoices = [
        {
            "account": "demo-acct",
            "billing_period": "2026-09",
            "usage_subtotal": 100,
            "credits": -10,
            "adjustments": 0,
            "tax": 9,
            "invoice_total": 99,
        },
        {
            "account": "demo-acct",
            "billing_period": "2026-10",
            "usage_subtotal": 270,
            "credits": -10,
            "adjustments": 0,
            "tax": 26,
            "invoice_total": 286,
        },
    ]
    return records, invoices
