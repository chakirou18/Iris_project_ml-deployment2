"""Evaluate tabular Iris input drift against the saved training set.

Evidently provides the authoritative dataset-level drift decision.
We use the same explicit two-sample KS test for per-feature Prometheus metrics.
"""
import json
import math
import os
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import joblib
import pandas as pd
from scipy.stats import ks_2samp
from scripts.export_reference import FEATURE_NAMES

P_THRESHOLD = 0.05


def recent_data(path, limit=120):
    if limit < 1:
        raise ValueError("limit must be positive")
    rows = deque(maxlen=limit)
    source = Path(path)
    if not source.exists():
        return pd.DataFrame(columns=FEATURE_NAMES)
    with source.open(encoding="utf-8") as stream:
        for line in stream:
            try:
                event = json.loads(line)
                if event.get("status") != "success" or event.get("model_id") != "iris-classifier":
                    continue
                values = event["features"]
                row = {name: float(values[name]) for name in FEATURE_NAMES}
                if all(math.isfinite(value) for value in row.values()):
                    rows.append(row)
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
    return pd.DataFrame(rows, columns=FEATURE_NAMES)


def extract_evidently_summary(snapshot):
    metrics = snapshot.get("metrics")
    if not isinstance(metrics, list):
        raise ValueError("Evidently metrics list missing")
    summaries = [m for m in metrics if str(m.get("metric_name", "")).startswith("DriftedColumnsCount")]
    if len(summaries) != 1:
        raise ValueError("Expected one Evidently DriftedColumnsCount metric")
    values = summaries[0].get("value")
    if not isinstance(values, dict):
        raise ValueError("Invalid Evidently drift summary")
    count, share = float(values["count"]), float(values["share"])
    if not (math.isfinite(count) and math.isfinite(share)
            and count.is_integer() and 0 <= count <= len(FEATURE_NAMES)
            and 0 <= share <= 1):
        raise ValueError("Invalid Evidently drift values")
    return {"drifted_features": int(count), "drift_share": share}


def evaluate(events, reference_path, output_path, min_samples=30):
    current = recent_data(events)
    if len(current) < min_samples:
        return None
    reference = joblib.load(reference_path)
    if not isinstance(reference, pd.DataFrame):
        raise TypeError("Training reference must be a DataFrame")
    reference = reference.loc[:, FEATURE_NAMES].copy()
    if reference.empty:
        raise ValueError("Reference is empty")
    for name in FEATURE_NAMES:
        reference[name] = pd.to_numeric(reference[name], errors="raise")
    if not all(reference[name].map(math.isfinite).all() for name in FEATURE_NAMES):
        raise ValueError("Non-finite reference values")
    from evidently import Report
    from evidently.presets import DataDriftPreset

    # Pin the statistical method so per-column p-values are interpretable.
    snapshot = Report([
        DataDriftPreset(columns=FEATURE_NAMES, num_method="ks", num_threshold=P_THRESHOLD)
    ]).run(reference_data=reference, current_data=current)
    raw = snapshot.dict()
    summary = extract_evidently_summary(raw)
    features = {}
    for name in FEATURE_NAMES:
        pvalue = float(ks_2samp(reference[name], current[name]).pvalue)
        if not math.isfinite(pvalue):
            raise ValueError("Invalid KS p-value for " + name)
        features[name] = {"p_value": pvalue, "drifted": pvalue < P_THRESHOLD}
    summary.update({
        "model_id": "iris-classifier",
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "samples": len(current),
        "reference_samples": len(reference),
        "method": "ks",
        "pvalue_threshold": P_THRESHOLD,
        "features": features,
        "status": "evaluated",
    })
    output = Path(output_path)
    output.mkdir(parents=True, exist_ok=True)
    # Atomic replace; readers never see a partially serialized report.
    tmp_html = output / "iris_drift.tmp.html"
    snapshot.save_html(str(tmp_html))
    os.replace(tmp_html, output / "iris_drift.html")
    for filename, payload in (
        ("iris_drift.json", raw),
        ("iris_drift_summary.json", summary),
    ):
        temp = output / (filename + ".tmp")
        temp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        os.replace(temp, output / filename)
    return summary


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    print(evaluate(
        os.getenv("PREDICTION_EVENTS_PATH", str(root / "data/predictions.jsonl")),
        root / "artifacts/processed/X_train.pkl",
        os.getenv("DRIFT_REPORT_DIR", str(root / "data/reports")),
    ))
