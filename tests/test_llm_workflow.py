import json
from pathlib import Path
import pytest

from agents.llm_workflow import LlmOpinion, analyze
from agents.read_only_tools import load_evidently_summary, query_prometheus_metric

FEATURES = ("SepalLengthCm", "SepalWidthCm", "PetalLengthCm", "PetalWidthCm")


def make_summary(tmp_path, drift=True):
    features = {
        name: {"drifted": bool(drift and name == "PetalLengthCm"),
               "p_value": 0.001 if drift and name == "PetalLengthCm" else 0.7}
        for name in FEATURES
    }
    obj = {
        "status": "evaluated", "model_id": "iris-classifier",
        "evaluated_at": "2026-10-13T10:00:00+00:00",
        "drifted_features": 1 if drift else 0,
        "drift_share": 0.25 if drift else 0,
        "samples": 120, "features": features,
    }
    path = tmp_path / "summary.json"
    path.write_text(json.dumps(obj), encoding="utf-8")
    return path


class FakeLLM:
    def invoke(self, prompt):
        assert "ground-truth" not in prompt or isinstance(prompt, str)
        return LlmOpinion(
            likely_cause="Input distribution changed",
            explanation="A sensor change is possible but unconfirmed.",
            confidence="low", recommended_investigation="Review sensor calibration",
        )


class BrokenLLM:
    def invoke(self, prompt):
        raise RuntimeError("unavailable")


def infra():
    return {"status": "ok", "metrics": {"iris_up": 1.0}, "unavailable": {}}


def test_llm_diagnosis_read_only(tmp_path):
    result = analyze(make_summary(tmp_path), FakeLLM(), metrics_collector=infra)
    assert result["diagnosis"]["source"] == "llm_assisted"
    assert result["incident"]["affected_features"] == ["PetalLengthCm"]
    assert result["approval_status"] == "pending_human_review"
    assert all(x["execution"] == "not_implemented" for x in result["recommendations"])


def test_llm_failure_falls_back(tmp_path):
    result = analyze(make_summary(tmp_path), BrokenLLM(), metrics_collector=infra)
    assert result["diagnosis"]["source"] == "fallback"
    assert result["approval_status"] == "pending_human_review"


def test_no_drift_does_not_call_llm(tmp_path):
    result = analyze(make_summary(tmp_path, drift=False), BrokenLLM(), metrics_collector=infra)
    assert result["recommendations"] == []
    assert result["approval_status"] == "not_required"


def test_summary_rejects_extra_nonmatching_flags(tmp_path):
    path = make_summary(tmp_path)
    data = json.loads(path.read_text())
    data["drifted_features"] = 0
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_evidently_summary(path)


def test_prometheus_metric_allowlist():
    with pytest.raises(ValueError):
        query_prometheus_metric("up or arbitrary query")
