from .analysis import analyze_periods, reconcile_invoice
from .ingestion import ingest_file
from .reporting import build_report


def reconcile_tool(records, invoices, tolerance=0.01):
    return [reconcile_invoice(records, invoice, tolerance) for invoice in invoices]


def analysis_tool(records, previous_period, current_period):
    return analyze_periods(records, previous_period, current_period)


def report_tool(analysis, reconciliations):
    return build_report(analysis, reconciliations)


def ingest_tool(database, path):
    return ingest_file(database, path)
