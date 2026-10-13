"""Evaluate Iris input drift against the saved training set."""
import json
import os
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import joblib
import pandas as pd

from scripts.export_reference import FEATURE_NAMES


def recent_data(path, limit=120):
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
                if all(pd.notna(value) and abs(value) < float("inf") for value in row.values()):
                    rows.append(row)
            except (ValueError, KeyError, TypeError):
                continue
    return pd.DataFrame(rows, columns=FEATURE_NAMES)


def evaluate(events, reference_path, output_path, min_samples=30):
    current = recent_data(events)
    if len(current) < min_samples:
        return None
    reference = joblib.load(reference_path)
    if not isinstance(reference, pd.DataFrame):
        raise TypeError("Training reference must be a DataFrame")
    reference = reference[FEATURE_NAMES]
    from evidently import Report
    from evidently.presets import DataDriftPreset
    snapshot = Report([DataDriftPreset()]).run(
        reference_data=reference, current_data=current
    )
    output = Path(output_path)
    output.mkdir(parents=True, exist_ok=True)
    snapshot.save_html(str(output / "iris_drift.html"))
    result = snapshot.dict()
    (output / "iris_drift.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    return {"samples": len(current), "checked_at": datetime.now(timezone.utc).isoformat()}


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    print(evaluate(
        os.getenv("PREDICTION_EVENTS_PATH", str(root / "data/predictions.jsonl")),
        root / "artifacts/processed/X_train.pkl",
        os.getenv("DRIFT_REPORT_DIR", str(root / "data/reports")),
    ))
