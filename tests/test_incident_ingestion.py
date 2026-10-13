"""End-to-end incident correlation tests with isolated telemetry stubs."""
import json
from datetime import datetime, timezone
import pytest
from monitoring.incident_ingestor import (
    DRIFT_KEY, poll_once, read_alert_names, checked_timestamp, get_stream_status,
)
from review.store import get_incident, list_incidents


def fake_summary(tmp_path, *, drift=1):
    path = tmp_path / "iris_drift_summary.json"
    payload = {
        "status": "evaluated", "model_id": "iris-classifier",
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "samples": 120, "drifted_features": drift,
        "drift_share": drift / 4,
        "features": {
            name: {"drifted": drift > 0 and name == "PetalLengthCm",
                   "p_value": 0.001 if drift and name == "PetalLengthCm" else 0.8}
            for name in ("SepalLengthCm", "SepalWidthCm", "PetalLengthCm", "PetalWidthCm")
        },
    }
    path.write_text(json.dumps(payload))
    return path


def fake_graph(path, model=None, *, metrics_collector=None):
    return {"diagnosis": {
        "source": "deterministic", "observation": "Input shift",
        "affected_features": ["PetalLengthCm"],
        "limitations": "Drift alone does not prove prediction failure",
    }}


def test_auto_ingestion_deduplicates_and_preserves_review(tmp_path):
    db = tmp_path / "review.db"
    summary = fake_summary(tmp_path)
    signals = lambda: {"IrisPredictionErrorsHigh"}
    initial = poll_once(db, summary, alert_reader=signals, graph_analyzer=fake_graph)
    assert initial["created"] == 2
    assert len(list_incidents(db)) == 2
    second = poll_once(db, summary, alert_reader=signals, graph_analyzer=fake_graph)
    assert second["created"] == 0
    item = get_stream_status(db, DRIFT_KEY)
    assert item["active"] == 1
    drift = get_incident(db, item["incident_id"])
    assert drift["evidence"]["source"] == "evidently_verified_summary"
    assert drift["diagnosis"]["observation"] == "Input shift"


def test_healthy_check_clears_drift_signal_not_review(tmp_path):
    db = tmp_path / "review.db"
    summary = fake_summary(tmp_path)
    poll_once(db, summary, alert_reader=lambda: set(), graph_analyzer=fake_graph)
    assert get_stream_status(db, DRIFT_KEY)["active"] == 1
    fake_summary(tmp_path, drift=0)
    result = poll_once(db, summary, alert_reader=lambda: set(), graph_analyzer=fake_graph)
    assert result["created"] == 0
    assert get_stream_status(db, DRIFT_KEY)["active"] == 0
    assert len(list_incidents(db)) == 1  # historical incident remains


def test_alert_collection_failure_never_clears_signal(tmp_path):
    db = tmp_path / "review.db"
    summary = tmp_path / "missing.json"
    poll_once(db, summary, alert_reader=lambda: {"IrisServiceDown"})
    key = "prometheus:iris-classifier:IrisServiceDown"
    assert get_stream_status(db, key)["active"] == 1
    def failed():
        raise OSError("Prometheus down")
    report = poll_once(db, summary, alert_reader=failed)
    assert "prometheus" in report["sources_failed"]
    assert get_stream_status(db, key)["active"] == 1


def test_rejects_stale_summary(tmp_path):
    db = tmp_path / "review.db"
    path = fake_summary(tmp_path)
    data = json.loads(path.read_text())
    data["evaluated_at"] = "2020-01-01T00:00:00+00:00"
    path.write_text(json.dumps(data))
    report = poll_once(db, path, alert_reader=lambda: set(), graph_analyzer=fake_graph)
    assert "evidently" in report["sources_failed"]
    assert list_incidents(db) == []


def test_blocks_injected_prometheus_rule_name(tmp_path):
    db = tmp_path / "review.db"
    result = poll_once(db, tmp_path / "no.json",
                       alert_reader=lambda: {"SomeUntrustedAction"})
    assert "prometheus" in result["sources_failed"]
    assert list_incidents(db) == []
