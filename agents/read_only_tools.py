"""Fixed, read-only evidence adapters for the agentic Iris diagnostic MVP.

No model may select arbitrary PromQL, URLs, local files, or shell commands.
Only aggregates (never individual predictions) are sent to an LLM.
"""
import json
import math
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

FEATURES = ("SepalLengthCm", "SepalWidthCm", "PetalLengthCm", "PetalWidthCm")
PROMETHEUS_BASE = "http://127.0.0.1:9090"
METRICS = {
    "iris_up": 'up{job="iris"}',
    "evidently_up": 'up{job="evidently"}',
    "evaluation_status": "iris_drift_evaluation_status",
    "drift_share": "iris_drift_share",
    "drift_count": "iris_drifted_features_count",
    "window_samples": "iris_drift_window_samples",
    "errors_total": "iris_prediction_errors_total",
}
for _feature in FEATURES:
    METRICS["drift_" + _feature] = 'iris_feature_drift{feature="' + _feature + '"}'
    METRICS["pvalue_" + _feature] = 'iris_feature_ks_pvalue{feature="' + _feature + '"}'


def load_evidently_summary(path):
    """Parse a bounded allowlisted summary, discarding extra/untrusted fields."""
    file = Path(path)
    if file.stat().st_size > 64_000:
        raise ValueError("Evidence summary exceeds 64 kB")
    raw = json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("status") != "evaluated":
        raise ValueError("No completed Evidently evaluation")
    if raw.get("model_id") != "iris-classifier":
        raise ValueError("Unexpected model")
    count = raw.get("drifted_features")
    share = raw.get("drift_share")
    samples = raw.get("samples")
    if type(count) is not int or not 0 <= count <= len(FEATURES):
        raise ValueError("Invalid feature drift count")
    if not isinstance(share, (float, int)) or not math.isfinite(share) or not 0 <= share <= 1:
        raise ValueError("Invalid drift share")
    if type(samples) is not int or not 1 <= samples <= 100000:
        raise ValueError("Invalid sample count")
    fields = raw.get("features")
    if not isinstance(fields, dict):
        raise ValueError("Missing feature statistics")
    cleaned = {}
    for feature in FEATURES:
        entry = fields.get(feature)
        if not isinstance(entry, dict) or type(entry.get("drifted")) is not bool:
            raise ValueError("Invalid feature drift flag: " + feature)
        value = entry.get("p_value")
        if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("Invalid feature p-value: " + feature)
        cleaned[feature] = {"drifted": entry["drifted"], "p_value": float(value)}
    if sum(1 for x in cleaned.values() if x["drifted"]) != count:
        raise ValueError("Inconsistent feature drift count")
    timestamp = raw.get("evaluated_at")
    if not isinstance(timestamp, str) or len(timestamp) > 64:
        raise ValueError("Invalid evaluation timestamp")
    return {
        "status": "evaluated", "model_id": "iris-classifier",
        "evaluated_at": timestamp, "drifted_features": count,
        "drift_share": float(share), "samples": samples,
        "features": cleaned,
    }


def query_prometheus_metric(metric_name, *, opener=urlopen):
    """Query only predefined PromQL, from a fixed local Prometheus endpoint."""
    if metric_name not in METRICS:
        raise ValueError("Metric not on the read-only allowlist")
    url = PROMETHEUS_BASE + "/api/v1/query?" + urlencode({"query": METRICS[metric_name]})
    with opener(url, timeout=4) as response:
        if getattr(response, "status", 200) != 200:
            raise ValueError("Prometheus returned HTTP error")
        payload = json.load(response)
    if payload.get("status") != "success":
        raise ValueError("Prometheus query failed")
    data = payload.get("data")
    if not isinstance(data, dict) or data.get("resultType") != "vector":
        raise ValueError("Unexpected Prometheus result type")
    results = data.get("result")
    if not isinstance(results, list):
        raise ValueError("Missing Prometheus results")
    if not results:
        return None
    if len(results) != 1:
        raise ValueError("Ambiguous Prometheus time series")
    value = float(results[0]["value"][1])
    if not math.isfinite(value):
        raise ValueError("Non-finite Prometheus value")
    return value


def collect_prometheus_metrics(*, query=query_prometheus_metric):
    """Return bounded numeric metrics or explicit collection failure."""
    values = {}
    failures = {}
    for key in METRICS:
        try:
            values[key] = query(key)
        except Exception as error:
            # Never include URLs, tokens or raw exception text in LLM context.
            failures[key] = type(error).__name__
    return {
        "status": "partial" if failures else "ok",
        "metrics": values,
        "unavailable": failures,
    }
