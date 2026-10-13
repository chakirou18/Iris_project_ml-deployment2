"""Agent orchestration tests without LLM keys or production access."""
import pytest
from agents.diagnostic_graph import analyze


def sample(drifted=True):
    return {
        "status": "evaluated",
        "model_id": "iris-classifier",
        "evaluated_at": "2026-10-13T10:00:00+00:00",
        "drifted_features": 1 if drifted else 0,
        "features": {
            "PetalLengthCm": {"drifted": drifted, "p_value": 0.001 if drifted else 0.8},
        },
    }


def test_detects_drift_and_requires_human_review():
    result = analyze(sample())
    assert result["incident"]["type"] == "data_drift"
    assert "PetalLengthCm" in result["diagnosis"]["affected_features"]
    assert result["approval_status"] == "pending_human_review"
    assert result["recommendations"]
    assert all(r["requires_approval"] for r in result["recommendations"])


def test_healthy_sample_no_recommendations():
    result = analyze(sample(False))
    assert result["incident"]["type"] == "healthy_sample"
    assert result["recommendations"] == []
    assert result["approval_status"] == "not_required"


@pytest.mark.parametrize("invalid", [
    {"status": "failed", "model_id": "iris-classifier", "drifted_features": 0},
    {"status": "evaluated", "model_id": "wrong", "drifted_features": 1},
    {"status": "evaluated", "model_id": "iris-classifier", "drifted_features": "bad"},
])
def test_rejects_untrusted_evidence(invalid):
    with pytest.raises(ValueError):
        analyze(invalid)
