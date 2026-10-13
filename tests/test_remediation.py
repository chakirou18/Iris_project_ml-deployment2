"""Security and lifecycle tests for scoped offline remediation."""
import hashlib
import json

import joblib
import pandas as pd
import pytest
from sklearn.tree import DecisionTreeClassifier

from review.store import init_db, import_incident, record_decision
from remediation.store import (
    init_remediation_db, propose_plan, decide_plan, get_plan,
    claim_approved_plan, finalize_plan,
)
from remediation.runner import run_offline


def evidence():
    return {
        "incident": {"model_id": "iris-classifier", "category": "data_drift",
                     "severity": "warning"},
        "evidence": {"status": "evaluated", "model_id": "iris-classifier",
                     "drifted_features": 1, "samples": 120,
                     "evaluated_at": "2026-10-13T10:00:00Z",
                     "features": {"PetalLengthCm": {"drifted": True, "p_value": 0.001}}},
        "diagnosis": {"observation": "Measured input shift"},
        "recommendations": [{"id": "check-data", "action": "Inspect sensors",
                             "requires_approval": True, "execution": "not_implemented"}],
    }


@pytest.fixture
def case(tmp_path):
    db = tmp_path / "review.sqlite3"
    init_db(db)
    init_remediation_db(db)
    incident_id = import_incident(db, evidence())
    return db, incident_id


def test_demo_incident_is_not_eligible(case):
    db, _ = case
    fake = evidence()
    fake["evidence"] = {"source": "synthetic_local_preview", "status": "evaluated",
                        "model_id": "iris-classifier", "drifted_features": 1,
                        "samples": 120}
    incident = import_incident(db, fake)
    with pytest.raises(ValueError):
        propose_plan(db, incident, "operator")


def test_legacy_approval_cannot_start_experiment(case):
    db, incident = case
    record_decision(db, incident, "local-reviewer", "approve", "Old advisory approval")
    plan = propose_plan(db, incident, "operator")
    assert get_plan(db, plan)["status"] == "proposed"
    with pytest.raises(ValueError):
        claim_approved_plan(db, plan)


def test_scoped_approval_and_replay_protection(case):
    db, incident = case
    plan = propose_plan(db, incident, "operator")
    assert propose_plan(db, incident, "operator") == plan
    with pytest.raises(ValueError):
        decide_plan(db, incident, plan, "operator", "approve", "")
    decide_plan(db, incident, plan, "operator", "approve", "sandbox-only")
    assert get_plan(db, plan)["status"] == "approved"
    with pytest.raises(ValueError):
        decide_plan(db, incident, plan, "operator", "reject", "")
    claim_approved_plan(db, plan)
    with pytest.raises(ValueError):
        claim_approved_plan(db, plan)
    finalize_plan(db, plan, "candidate_ready", {"drift_resolved": None})
    assert [x["event"] for x in get_plan(db, plan)["history"]] == [
        "proposed", "approved", "running", "candidate_ready"
    ]


def test_rejected_plan_is_not_executable(case):
    db, incident = case
    plan = propose_plan(db, incident, "operator")
    decide_plan(db, incident, plan, "operator", "reject", "")
    with pytest.raises(ValueError):
        claim_approved_plan(db, plan)


def test_run_candidate_does_not_modify_production_model(case, tmp_path):
    db, incident = case
    train_data = tmp_path / "artifacts"
    processed = train_data / "processed"
    models = train_data / "models"
    processed.mkdir(parents=True)
    models.mkdir()
    features = ["SepalLengthCm", "SepalWidthCm", "PetalLengthCm", "PetalWidthCm"]
    X = pd.DataFrame([
        [5 + i * .03, 3 + (i % 3)*.1, 1 + (i % 5)*.3, .1 + (i % 2)*.1]
        for i in range(80)
    ], columns=features)
    y = pd.Series(["setosa" if i < 40 else "versicolor" for i in range(80)])
    for name, obj in [("X_train", X.iloc[:60]), ("X_test", X.iloc[60:]),
                      ("y_train", y.iloc[:60]), ("y_test", y.iloc[60:])]:
        joblib.dump(obj, processed / (name + ".pkl"))
    baseline = DecisionTreeClassifier(random_state=42).fit(X.iloc[:60], y.iloc[:60])
    baseline_path = models / "model.pkl"
    joblib.dump(baseline, baseline_path)
    before = hashlib.sha256(baseline_path.read_bytes()).hexdigest()
    plan = propose_plan(db, incident, "operator")
    decide_plan(db, incident, plan, "operator", "approve", "sandbox-only")
    result = run_offline(db, plan, artifacts=train_data, destination=tmp_path / "candidates")
    assert result["production_changed"] is False
    assert result["drift_resolved"] is None
    assert hashlib.sha256(baseline_path.read_bytes()).hexdigest() == before
    assert (tmp_path / "candidates" / (plan + ".json")).exists()
    with pytest.raises(ValueError):
        run_offline(db, plan, artifacts=train_data, destination=tmp_path / "candidates")
