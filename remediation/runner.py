"""Offline Iris candidate evaluation. Never changes the deployed model.

This is an experiment on historical TRAIN and HOLDOUT splits, not proof of
recovery from live data drift. Candidate promotion is deliberately impossible.
"""
import argparse
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.metrics import accuracy_score, f1_score
from sklearn.tree import DecisionTreeClassifier

from remediation.store import claim_approved_plan, finalize_plan

ROOT = Path(__file__).resolve().parents[1]
FEATURES = ("SepalLengthCm", "SepalWidthCm", "PetalLengthCm", "PetalWidthCm")


def run_offline(db, plan_id, artifacts=ROOT / "artifacts", destination=ROOT / "data" / "candidates"):
    """Consume an explicit scoped approval before training an isolated candidate."""
    plan = claim_approved_plan(db, plan_id)
    try:
        artifacts = Path(artifacts)
        root = Path(destination)
        root.mkdir(parents=True, exist_ok=True)
        inputs = [joblib.load(artifacts / "processed" / (name + ".pkl")) for name in
                  ("X_train", "X_test", "y_train", "y_test")]
        x_train, x_test, y_train, y_test = inputs
        if list(x_train.columns) != list(FEATURES) or list(x_test.columns) != list(FEATURES):
            raise ValueError("Unexpected Iris feature schema")
        if len(x_train) < 10 or len(x_test) < 10:
            raise ValueError("Not enough training/holdout observations")
        for x in (x_train, x_test):
            if not np.isfinite(np.asarray(x, dtype=float)).all():
                raise ValueError("Non-finite features")
        baseline_file = artifacts / "models" / "model.pkl"
        original_hash = hashlib.sha256(baseline_file.read_bytes()).hexdigest()
        baseline = joblib.load(baseline_file)
        baseline_predictions = baseline.predict(x_test)
        candidate = DecisionTreeClassifier(criterion="gini", max_depth=15, random_state=42)
        candidate.fit(x_train, y_train)
        proposed_predictions = candidate.predict(x_test)
        baseline_metrics = {
            "accuracy": float(accuracy_score(y_test, baseline_predictions)),
            "f1_weighted": float(f1_score(y_test, baseline_predictions, average="weighted")),
        }
        candidate_metrics = {
            "accuracy": float(accuracy_score(y_test, proposed_predictions)),
            "f1_weighted": float(f1_score(y_test, proposed_predictions, average="weighted")),
        }
        # No promotion automatically: even a better holdout metric is not evidence
        # the original input drift is resolved without labeled live observations.
        pass_holdout = (
            candidate_metrics["accuracy"] + 0.0000001 >= baseline_metrics["accuracy"]
            and candidate_metrics["f1_weighted"] + 0.0000001 >= baseline_metrics["f1_weighted"]
        )
        if hashlib.sha256(baseline_file.read_bytes()).hexdigest() != original_hash:
            raise RuntimeError("Source model changed during evaluation")
        result = {
            "plan_id": plan_id,
            "mode": "historical_holdout_only",
            "baseline": baseline_metrics, "candidate": candidate_metrics,
            "holdout_samples": int(len(x_test)),
            "original_sha256": original_hash,
            "passes_holdout": bool(pass_holdout),
            "production_changed": False,
            "drift_resolved": None,
            "requires_live_labels_for_resolution": True,
        }
        # Persist only a report; do not replace, copy, or save a model artifact
        # anywhere in serving/model directories.
        report = root / (plan_id + ".json")
        report.write_text(json.dumps(result, indent=2), encoding="utf-8")
        finalize_plan(db, plan_id, "candidate_ready" if pass_holdout else "candidate_rejected", result)
        return result
    except Exception as exc:
        # No exception text in audit to avoid paths/secrets leaking into UI.
        finalize_plan(db, plan_id, "failed", {"error_type": type(exc).__name__,
                                            "production_changed": False})
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan-id", required=True)
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "review.sqlite3")
    args = parser.parse_args()
    print(json.dumps(run_offline(args.db, args.plan_id), indent=2))


if __name__ == "__main__":
    main()
