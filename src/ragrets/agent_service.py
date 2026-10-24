"""Billing service used by the Agentverse ACP adapter."""

from .config import Settings
from .database import Database
from .groq import GroqClient
from .ingestion import demo_data
from .schemas import BillingRecord, InvoiceRecord
from .workflow import run_workflow


def build_synthetic_demo_context():
    """Build the existing bundled synthetic demo context."""
    raw_records, raw_invoices = demo_data()

    records = [
        BillingRecord(**record, source_id="agentverse-synthetic-demo")
        for record in raw_records
    ]
    invoices = [
        InvoiceRecord(**invoice, source_id="agentverse-synthetic-demo")
        for invoice in raw_invoices
    ]

    account = records[0].account
    periods = sorted({record.billing_period for record in records})

    state = run_workflow(
        account,
        periods[-2],
        periods[-1],
        records,
        invoices,
        evidence=[],
    )

    if state.get("errors"):
        raise ValueError("; ".join(state["errors"]))

    return state["report"], records, invoices


def build_database_context():
    """Build a billing report from records stored in the configured database."""
    settings = Settings()
    database = Database(settings.database_path)

    records = database.records()
    invoices = database.invoices()
    evidence = database.evidence()

    if not records:
        raise ValueError(
            "No billing records are loaded. Ingest a billing file before asking questions."
        )

    accounts = sorted({record.account for record in records})
    if len(accounts) != 1:
        raise ValueError(
            "Multiple accounts are loaded. Select an account before investigating."
        )

    account = accounts[0]

    account_records = [r for r in records if r.account == account]
    account_invoices = [i for i in invoices if i.account == account]
    periods = sorted({r.billing_period for r in account_records})

    if len(periods) < 2:
        raise ValueError(
            "At least two billing periods are required for a cost comparison."
        )

    previous_period, current_period = periods[-2], periods[-1]

    state = run_workflow(
        account,
        previous_period,
        current_period,
        account_records,
        account_invoices,
        evidence=evidence,
    )

    if state.get("errors"):
        raise ValueError("; ".join(state["errors"]))

    return state["report"], account_records, account_invoices


def _answer_question(question, history, context_builder):
    settings = Settings()
    client = GroqClient(settings.groq_api_key, settings.groq_model)

    report, records, invoices = context_builder()

    return client.answer_question(
        report,
        question,
        history,
        records,
        invoices,
    )


def answer_synthetic_demo_question(
    question: str,
    history: list[dict[str, str]] | None = None,
) -> str:
    """Answer using only the bundled synthetic demo."""
    return _answer_question(
        question,
        history,
        build_synthetic_demo_context,
    )


def answer_database_question(
    question: str,
    history: list[dict[str, str]] | None = None,
) -> str:
    """Answer using billing data stored in the configured database."""
    return _answer_question(
        question,
        history,
        build_database_context,
    )
