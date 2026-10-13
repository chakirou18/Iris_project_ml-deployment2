"""Flask Iris prediction app with first-stage MLOps instrumentation."""
import logging
import math
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import joblib
import numpy as np
from flask import Flask, Response, abort, jsonify, render_template, request
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)

from monitoring.event_store import JsonlPredictionEventStore

PROJECT_ROOT = Path(__file__).resolve().parent
MODEL_PATH = PROJECT_ROOT / "artifacts" / "models" / "model.pkl"
FEATURE_NAMES = (
    "SepalLengthCm",
    "SepalWidthCm",
    "PetalLengthCm",
    "PetalWidthCm",
)
LOGGER = logging.getLogger(__name__)


def create_app(model=None, event_store=None, registry=None):
    """Create the app; injected dependencies make monitoring independently testable."""
    app = Flask(__name__)
    if model is None:
        model = joblib.load(MODEL_PATH)

    if event_store is None:
        events_path = Path(
            os.environ.get(
                "PREDICTION_EVENTS_PATH", str(PROJECT_ROOT / "data" / "predictions.jsonl")
            )
        )
        event_store = JsonlPredictionEventStore(events_path)

    if registry is None:
        registry = CollectorRegistry()

    model_id = os.getenv("MODEL_ID", "iris-classifier")
    # Set this to the actual deployed version/commit in the deployment environment.
    model_version = os.getenv("MODEL_VERSION", "unversioned")

    requests_total = Counter(
        "iris_prediction_requests_total",
        "Iris prediction requests by outcome.",
        ["status"],
        registry=registry,
    )
    errors_total = Counter(
        "iris_prediction_errors_total",
        "Failed Iris prediction requests.",
        registry=registry,
    )
    prediction_latency = Histogram(
        "iris_prediction_latency_seconds",
        "Time spent processing an Iris prediction request.",
        registry=registry,
    )
    predictions_by_class = Counter(
        "iris_predictions_by_class_total",
        "Successful Iris predictions by predicted class.",
        ["class_name"],
        registry=registry,
    )
    storage_errors = Counter(
        "iris_prediction_event_storage_errors_total",
        "Failures while persisting prediction events.",
        registry=registry,
    )

    @app.route("/", methods=["GET", "POST"])
    def index():
        if request.method == "GET":
            return render_template("index.html", prediction=None)

        started = time.perf_counter()
        features = {}
        prediction = None
        status = "error"
        try:
            for name in FEATURE_NAMES:
                value = float(request.form[name])
                if not math.isfinite(value):
                    raise ValueError("Feature must be finite")
                features[name] = value

            input_data = np.array([[features[name] for name in FEATURE_NAMES]])
            prediction = str(model.predict(input_data)[0])
            status = "success"
            predictions_by_class.labels(class_name=prediction).inc()
            return render_template("index.html", prediction=prediction)
        except (KeyError, TypeError, ValueError) as exc:
            LOGGER.warning("Rejected invalid Iris prediction input: %s", type(exc).__name__)
            return "Invalid prediction input", 400
        except Exception:
            LOGGER.exception("Iris prediction failed")
            return "Prediction unavailable", 500
        finally:
            elapsed_seconds = time.perf_counter() - started
            requests_total.labels(status=status).inc()
            if status == "error":
                errors_total.inc()
            prediction_latency.observe(elapsed_seconds)
            event = {
                "event_id": str(uuid4()),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "model_id": model_id,
                "model_version": model_version,
                # Invalid input is not persisted as raw request data.
                "features": features if status == "success" else None,
                "prediction": prediction,
                "latency_ms": round(elapsed_seconds * 1000, 3),
                "status": status,
            }
            try:
                event_store.append(event)
            except Exception:
                storage_errors.inc()
                LOGGER.exception("Failed to persist Iris prediction monitoring event")

    @app.get("/health")
    def health():
        return jsonify(status="ok", model_loaded=True, model_id=model_id, model_version=model_version)

    @app.get("/metrics")
    def metrics():
        # Secure by default: loopback-only, or a configured bearer token.
        # Never expose this endpoint directly on a public LoadBalancer.
        token = os.getenv("MONITORING_METRICS_TOKEN")
        if token:
            expected = "Bearer " + token
            if not secrets.compare_digest(request.headers.get("Authorization", ""), expected):
                abort(403)
        elif request.remote_addr not in ("127.0.0.1", "::1"):
            abort(403)
        return Response(generate_latest(registry), content_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()

if __name__ == "__main__":
    # The Flask development server is not intended for production serving.
    app.run(host="0.0.0.0", port=5000, debug=False)
