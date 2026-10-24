import hashlib
import re
from pathlib import Path
import pymupdf
from .database import Database
from .schemas import EvidenceRecord


def ingest_pdf_evidence(db: Database, path: str | Path, source_id: str | None = None) -> dict:
    path = Path(path)
    raw = path.read_bytes()
    source_id = source_id or path.name
    document = pymupdf.open(path)
    pages = [{"page": i + 1, "text": page.get_text()} for i, page in enumerate(document)]
    db.save_evidence(EvidenceRecord(source_id=source_id, content_hash=hashlib.sha256(raw).hexdigest(), reference="pages " + ", ".join(str(p["page"]) for p in pages)))
    amounts = []
    for page in pages:
        amounts.extend({"page": page["page"], "value": value} for value in re.findall(r"(?:[$€£]\s?)([\d,]+(?:\.\d{2})?)", page["text"]))
    return {"source_id": source_id, "pages": len(pages), "amount_candidates": amounts, "needs_review": True, "message": "PDF values are evidence candidates and require review before becoming invoice records."}
