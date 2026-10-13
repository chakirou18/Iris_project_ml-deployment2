# Phase 3 — Prototype agentic incident diagnosis

This is a **read-only LangGraph workflow**, designed to keep monitoring decisions
auditable. It is an initial rules-based agent graph, not yet an LLM-powered
root-cause analysis agent. It does not autonomously remediate incidents.

The pipeline is: detect -> diagnose -> recommend -> human_gate -> END.

The graph loads validated JSON evidence from the phase-2 Evidently report.
It prepares a structured incident and recommended human-approved responses.
**No production API, shell execution, model registry write, re-training,
GitHub action, or cloud permissions are granted to the graph.** The status
`pending_human_review` means approval is required; it is NOT approval granted.

To run after collecting enough demo traffic and producing a drift report:

```bash
python -m pip install -r requirements-agents.txt
python -m agents.diagnostic_graph --summary data/reports/iris_drift_summary.json
python -m pytest -q tests/test_agent_diagnostics.py
```

The incident is saved to `data/reports/iris_incident.json` (ignored by git).

The next stage should add restricted read-only Prometheus tools, retrieval
of bounded and redacted diagnostic evidence, persistence and authentication
for approvals, and optionally LLM-based diagnosis evaluated on a fixed incident
benchmark. Any action executor must live outside the graph and verify an
authenticated approval, permissions, pre-deployment checks and rollback.
