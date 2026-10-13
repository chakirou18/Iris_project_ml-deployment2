"""Focused tests for phase 2: event parsing and reference data."""
import json

import pandas as pd
import pytest

from monitoring.drift import recent_data
from scripts.export_reference import FEATURE_NAMES


def test_recent_data_ignores_errors_and_invalid_events(tmp_path):
    path = tmp_path / "events.jsonl"
    events = [
        {"status": "success", "model_id": "iris-classifier",
         "features": dict(zip(FEATURE_NAMES, [5.1, 3.5, 1.4, 0.2]))},
        {"status": "error", "model_id": "iris-classifier",
         "features": dict(zip(FEATURE_NAMES, [5, 3, 1, 0]))},
        {"status": "success", "model_id": "other-model",
         "features": dict(zip(FEATURE_NAMES, [9, 9, 9, 9]))},
    ]
    path.write_text("\n".join(json.dumps(x) for x in events) + "\nnot-json\n")
    result = recent_data(path)
    assert len(result) == 1
    assert result.columns.tolist() == FEATURE_NAMES
    assert result.iloc[0]["PetalLengthCm"] == 1.4


def test_recent_data_limit_and_missing_file(tmp_path):
    path = tmp_path / "events.jsonl"
    assert recent_data(path).empty
    observations = [
        {"status": "success", "model_id": "iris-classifier",
         "features": dict(zip(FEATURE_NAMES, [float(i), 3, 2, 1]))}
        for i in range(5)
    ]
    path.write_text("\n".join(json.dumps(x) for x in observations) + "\n")
    result = recent_data(path, limit=2)
    assert len(result) == 2
    assert result.iloc[0]["SepalLengthCm"] == 3.0


def test_missing_data_does_not_report_no_drift(tmp_path):
    from monitoring.drift import evaluate
    assert evaluate(tmp_path / "absent.jsonl", tmp_path / "missing.pkl", tmp_path / "reports") is None


def test_invalid_reference_is_rejected(tmp_path):
    from monitoring.drift import evaluate
    import joblib
    path = tmp_path / "events.jsonl"
    obs = {"status": "success", "model_id": "iris-classifier",
           "features": dict(zip(FEATURE_NAMES, [5, 3, 1, 0.2]))}
    path.write_text((json.dumps(obs) + "\n") * 30)
    ref = tmp_path / "reference.pkl"
    joblib.dump(pd.DataFrame({"different": [1]}), ref)
    with pytest.raises(KeyError):
        evaluate(path, ref, tmp_path / "reports")
