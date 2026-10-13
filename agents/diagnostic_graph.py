"""Read-only incident workflow with LangGraph and human approval by default.

Uses deterministic rules in the initial MVP; an LLM-enabled diagnostic can be
plugged in later, without granting write access to infrastructure.
"""
import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from langgraph.graph import StateGraph, END

class IncidentState(TypedDict, total=False):
    evidence: dict
    incident: dict
    diagnosis: dict
    recommendations: list
    approval_status: str


def detect(state: IncidentState) -> dict:
    evidence = state["evidence"]
    if not isinstance(evidence, dict) or evidence.get("status") != "evaluated":
        raise ValueError("No successful drift evaluation; cannot infer model health")
    if evidence.get("model_id") != "iris-classifier":
        raise ValueError("Unknown model ID")
    count = evidence.get("drifted_features")
    if type(count) is not int or not 0 <= count <= 4:
        raise ValueError("Invalid drifted feature count")
    return {"incident": {
        "incident_id": "iris-" + str(evidence.get("evaluated_at", "unknown")),
        "model_id": evidence["model_id"],
        "severity": "warning" if count else "informational",
        "type": "data_drift" if count else "healthy_sample",
        "drifted_features": count,
        "detected_at": datetime.now(timezone.utc).isoformat(),
    }}


def diagnose(state: IncidentState) -> dict:
    evidence = state["evidence"]
    features = evidence.get("features", {})
    affected = sorted(name for name, result in features.items()
                      if isinstance(result, dict) and result.get("drifted") is True)
    return {"diagnosis": {
        "observations": "Statistical input distribution change" if affected else "No input drift flagged",
        "affected_features": affected,
        "possible_causes": [
            "Changed input population", "Sensor or input preprocessing changed"
        ] if affected else [],
        "limitations": "Input drift does not establish loss of predictive accuracy. Labels are required.",
    }}


def recommend(state: IncidentState) -> dict:
    if state["incident"]["type"] != "data_drift":
        return {"recommendations": []}
    return {"recommendations": [
        {"id": "inspect-input", "action": "Inspect feature collection, schema, and sensors",
         "risk": "low", "requires_approval": True},
        {"id": "review-performance", "action": "Collect ground-truth labels and compare model performance",
         "risk": "low", "requires_approval": True},
        {"id": "retrain-in-sandbox", "action": "If accuracy loss confirmed, evaluate retraining in an isolated environment",
         "risk": "medium", "requires_approval": True},
    ]}


def request_human_approval(state: IncidentState) -> dict:
    # Deliberately do not execute any corrective operation or tool.
    return {"approval_status": "pending_human_review" if state["recommendations"] else "not_required"}


def build_graph():
    builder = StateGraph(IncidentState)
    builder.add_node("detect", detect)
    builder.add_node("diagnose", diagnose)
    builder.add_node("recommend", recommend)
    builder.add_node("human_gate", request_human_approval)
    builder.set_entry_point("detect")
    builder.add_edge("detect", "diagnose")
    builder.add_edge("diagnose", "recommend")
    builder.add_edge("recommend", "human_gate")
    builder.add_edge("human_gate", END)
    return builder.compile()


def analyze(summary):
    # Only an evidence document is needed; production services are never contacted.
    return build_graph().invoke({"evidence": summary})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, default=Path("data/reports/iris_drift_summary.json"))
    parser.add_argument("--output", type=Path, default=Path("data/reports/iris_incident.json"))
    args = parser.parse_args()
    result = analyze(json.loads(args.summary.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Created incident for human review:", args.output)


if __name__ == "__main__":
    main()
