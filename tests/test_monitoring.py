"""Regression tests for the unchanged Iris form plus monitoring behavior."""
import json

import joblib
import pandas as pd
import pytest
from prometheus_client import CollectorRegistry

from application import create_app
from monitoring.event_store import JsonlPredictionEventStore
from scripts.export_reference import FEATURE_NAMES, export_reference


class FakeIrisModel:
    def predict(self, values):
        assert len(values[0]) == 4
        return ["Iris-setosa"]


class FailingModel:
    def predict(self, values):
        raise RuntimeError("model unavailable")


VALID_FORM = {
    "SepalLengthCm": "5.1",
    "SepalWidthCm": "3.5",
    "PetalLengthCm": "1.4",
    "PetalWidthCm": "0.2",
}


@pytest.fixture
def client_and_events(tmp_path, monkeypatch):
    monkeypatch.delenv("MONITORING_METRICS_TOKEN", raising=False)
    events_path = tmp_path / "predictions.jsonl"
    app = create_app(
        model=FakeIrisModel(),
        event_store=JsonlPredictionEventStore(events_path),
        registry=CollectorRegistry(),
    )
    app.config["TESTING"] = True
    return app.test_client(), events_path


def test_existing_page_and_successful_prediction(client_and_events):
    client, events_path = client_and_events
    response = client.get("/")
    assert response.status_code == 200
    assert b"SepalLengthCm" in response.data

    response = client.post("/", data=VALID_FORM)
    assert response.status_code == 200
    assert b"Iris-setosa" in response.data

    event = json.loads(events_path.read_text(encoding="utf-8").strip())
    assert event["status"] == "success"
    assert event["prediction"] == "Iris-setosa"
    assert event["features"]["SepalLengthCm"] == 5.1
    assert event["event_id"]
    assert event["timestamp"].endswith("+00:00")
    assert event["latency_ms"] >= 0


def test_prometheus_metrics_and_health(client_and_events):
    client, _ = client_and_events
    client.post("/", data=VALID_FORM)
    response = client.get("/metrics")
    assert response.status_code == 200
    assert b'iris_prediction_requests_total{status="success"} 1.0' in response.data
    assert b'iris_predictions_by_class_total{class_name="Iris-setosa"} 1.0' in response.data
    assert b"iris_prediction_latency_seconds_count 1.0" in response.data
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json["model_loaded"] is True


@pytest.mark.parametrize("invalid_form", [
    {},
    dict(VALID_FORM, SepalLengthCm="nan"),
    dict(VALID_FORM, PetalLengthCm="not-a-number"),
])
def test_invalid_input_is_recorded_without_raw_values(client_and_events, invalid_form):
    client, events_path = client_and_events
    response = client.post("/", data=invalid_form)
    assert response.status_code == 400
    event = json.loads(events_path.read_text(encoding="utf-8").strip())
    assert event["status"] == "error"
    assert event["features"] is None
    response = client.get("/metrics")
    assert b"iris_prediction_errors_total 1.0" in response.data


def test_prediction_error_is_recorded(tmp_path, monkeypatch):
    monkeypatch.delenv("MONITORING_METRICS_TOKEN", raising=False)
    path = tmp_path / "events.jsonl"
    app = create_app(
        model=FailingModel(),
        event_store=JsonlPredictionEventStore(path),
        registry=CollectorRegistry(),
    )
    response = app.test_client().post("/", data=VALID_FORM)
    assert response.status_code == 500
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "error"


def test_metrics_block_nonlocal_without_token(client_and_events):
    client, _ = client_and_events
    response = client.get("/metrics", environ_overrides={"REMOTE_ADDR": "192.0.2.4"})
    assert response.status_code == 403


def test_metrics_token(client_and_events, monkeypatch):
    client, _ = client_and_events
    monkeypatch.setenv("MONITORING_METRICS_TOKEN", "test-token")
    denied = client.get("/metrics")
    allowed = client.get("/metrics", headers={"Authorization": "Bearer test-token"})
    assert denied.status_code == 403
    assert allowed.status_code == 200


def test_export_reference_uses_training_artifact(tmp_path):
    training = pd.DataFrame([[5.1, 3.5, 1.4, 0.2]], columns=FEATURE_NAMES)
    source = tmp_path / "X_train.pkl"
    output = tmp_path / "reference.csv"
    joblib.dump(training, source)
    assert export_reference(source, output) == 1
    exported = pd.read_csv(output)
    assert exported.columns.tolist() == FEATURE_NAMES
    assert exported.iloc[0]["SepalLengthCm"] == 5.1
