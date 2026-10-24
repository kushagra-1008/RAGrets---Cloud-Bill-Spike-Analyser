from typing import TypedDict, Any
from langgraph.graph import StateGraph, END
from .analysis import analyze_periods, reconcile_invoice
from .reporting import build_report


class WorkflowState(TypedDict, total=False):
    account: str
    previous_period: str
    current_period: str
    records: list
    invoices: list
    evidence: list
    reconciliations: list
    analysis: dict
    report: dict
    errors: list[str]


def _validate(state: WorkflowState):
    required = ["account", "previous_period", "current_period", "records"]
    missing = [key for key in required if not state.get(key)]
    return {"errors": [f"Missing required workflow fields: {', '.join(missing)}"]} if missing else {}


def _reconcile(state: WorkflowState):
    return {"reconciliations": [reconcile_invoice(state["records"], invoice) for invoice in state.get("invoices", []) if invoice.account == state["account"]]}


def _analyze(state: WorkflowState):
    return {"analysis": analyze_periods(state["records"], state["previous_period"], state["current_period"])}


def _report(state: WorkflowState):
    return {"report": build_report(state["analysis"], state["reconciliations"], state["records"], state.get("evidence", []))}


def _route(state: WorkflowState):
    return "end" if state.get("errors") else "reconcile"


def build_workflow():
    graph = StateGraph(WorkflowState)
    graph.add_node("validate", _validate); graph.add_node("reconcile", _reconcile); graph.add_node("analyze", _analyze); graph.add_node("report", _report)
    graph.set_entry_point("validate")
    graph.add_conditional_edges("validate", _route, {"end": END, "reconcile": "reconcile"})
    graph.add_edge("reconcile", "analyze"); graph.add_edge("analyze", "report"); graph.add_edge("report", END)
    return graph.compile()


def run_workflow(account, previous_period, current_period, records, invoices, evidence=None):
    return build_workflow().invoke({"account": account, "previous_period": previous_period, "current_period": current_period, "records": records, "invoices": invoices, "evidence": evidence or []})
