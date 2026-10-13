"""Periodic Evidently evaluation with bounded-cardinality Prometheus metrics."""
import argparse
import logging
import os
import time
from pathlib import Path

from prometheus_client import Gauge, start_http_server
from monitoring.drift import evaluate
from scripts.export_reference import FEATURE_NAMES

LOG = logging.getLogger(__name__)
STATUS = Gauge("iris_drift_evaluation_status", "0=insufficient data, 1=success, -1=failure")
SAMPLES = Gauge("iris_drift_window_samples", "Number of current observations")
LAST = Gauge("iris_drift_last_success_timestamp_seconds", "Last successful evaluation UTC unix time")
DRIFT_COUNT = Gauge("iris_drifted_features_count", "Evidently count of drifting Iris features")
DRIFT_SHARE = Gauge("iris_drift_share", "Evidently share of drifting features, range 0-1")
FEATURE_DRIFT = Gauge("iris_feature_drift", "1 if KS test flags the feature", ["feature"])
FEATURE_PVALUE = Gauge("iris_feature_ks_pvalue", "KS two-sample p-value for feature", ["feature"])


def clear_metrics():
    DRIFT_COUNT.set(float("nan"))
    DRIFT_SHARE.set(float("nan"))
    for feature in FEATURE_NAMES:
        FEATURE_DRIFT.labels(feature=feature).set(float("nan"))
        FEATURE_PVALUE.labels(feature=feature).set(float("nan"))


def run_check():
    root = Path(__file__).resolve().parents[1]
    events = os.getenv("PREDICTION_EVENTS_PATH", str(root / "data/predictions.jsonl"))
    reference = root / "artifacts/processed/X_train.pkl"
    report_dir = os.getenv("DRIFT_REPORT_DIR", str(root / "data/reports"))
    try:
        result = evaluate(events, reference, report_dir)
        if result is None:
            STATUS.set(0)
            clear_metrics()
            return
        SAMPLES.set(result["samples"])
        DRIFT_COUNT.set(result["drifted_features"])
        DRIFT_SHARE.set(result["drift_share"])
        for name in FEATURE_NAMES:
            values = result["features"][name]
            FEATURE_DRIFT.labels(feature=name).set(int(values["drifted"]))
            FEATURE_PVALUE.labels(feature=name).set(values["p_value"])
        LAST.set_to_current_time()
        STATUS.set(1)
    except Exception:
        STATUS.set(-1)
        clear_metrics()
        LOG.exception("Evidently drift evaluation failed")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.once:
        run_check()
        if STATUS._value.get() == -1:
            raise SystemExit(1)
        return
    port = int(os.getenv("DRIFT_EXPORTER_PORT", "8001"))
    interval = max(15, int(os.getenv("DRIFT_EVALUATION_INTERVAL_SECONDS", "30")))
    start_http_server(port)
    while True:
        run_check()
        time.sleep(interval)


if __name__ == "__main__":
    main()
