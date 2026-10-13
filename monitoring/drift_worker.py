"""Run periodic Evidently checks and expose Prometheus status metrics."""
import logging
import os
import time
from pathlib import Path

from prometheus_client import Gauge, start_http_server
from monitoring.drift import evaluate

LOG = logging.getLogger(__name__)
STATUS = Gauge("iris_drift_evaluation_status", "0=waiting, 1=success, -1=error")
SAMPLES = Gauge("iris_drift_window_samples", "Observations in latest successful drift check")
LAST = Gauge("iris_drift_last_success_timestamp_seconds", "Last Evidently successful run")


def run_check():
    root = Path(__file__).resolve().parents[1]
    event_path = os.getenv("PREDICTION_EVENTS_PATH", str(root / "data/predictions.jsonl"))
    reference = root / "artifacts/processed/X_train.pkl"
    report_dir = os.getenv("DRIFT_REPORT_DIR", str(root / "data/reports"))
    try:
        result = evaluate(event_path, reference, report_dir)
        if result is None:
            STATUS.set(0)
            return
        SAMPLES.set(result["samples"])
        LAST.set_to_current_time()
        STATUS.set(1)
    except Exception:
        STATUS.set(-1)
        LOG.exception("Evidently evaluation failed")


def main():
    logging.basicConfig(level=logging.INFO)
    port = int(os.getenv("DRIFT_EXPORTER_PORT", "8001"))
    interval = max(15, int(os.getenv("DRIFT_EVALUATION_INTERVAL_SECONDS", "30")))
    start_http_server(port)
    LOG.info("Private drift exporter serving on port %d", port)
    while True:
        run_check()
        time.sleep(interval)


if __name__ == "__main__":
    main()
