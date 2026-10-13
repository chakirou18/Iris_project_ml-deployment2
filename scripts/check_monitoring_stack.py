"""CI integration assertions for the LOCAL Docker Compose demo.

Uses Python stdlib and calls only loopback endpoints.
"""
import argparse
import base64
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def read_local_env():
    entries = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            entries[key] = value
    return entries


def get_json(url, headers=None):
    with urlopen(Request(url, headers=headers or {}), timeout=5) as response:
        assert response.status == 200, (url, response.status)
        return json.load(response)


def prometheus_query(expr):
    url = "http://127.0.0.1:9090/api/v1/query?" + urlencode({"query": expr})
    result = get_json(url)
    assert result["status"] == "success", result
    values = result["data"]["result"]
    assert len(values) == 1, (expr, values)
    return float(values[0]["value"][1])


def poll(check, name, timeout=120):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            check()
            print("PASS:", name)
            return
        except Exception as error:
            last_error = str(error)
            time.sleep(3)
    raise AssertionError(name + " failed after waiting: " + str(last_error))


def verify_services():
    def check_app():
        status = get_json("http://127.0.0.1:5000/health")
        assert status["model_loaded"] is True, status
    poll(check_app, "Iris Flask healthy")

    def check_grafana():
        status = get_json("http://127.0.0.1:3000/api/health")
        assert status["database"] == "ok", status
    poll(check_grafana, "Grafana healthy")

    env = read_local_env()
    userpass = (env["GRAFANA_ADMIN_USER"] + ":" + env["GRAFANA_ADMIN_PASSWORD"]).encode()
    auth = "Basic " + base64.b64encode(userpass).decode()

    def check_dashboard():
        data = get_json(
            "http://127.0.0.1:3000/api/dashboards/uid/iris-phase2",
            headers={"Authorization": auth},
        )
        assert data["dashboard"]["title"].startswith("Iris ML Monitoring")
    poll(check_dashboard, "Grafana provisioned dashboard")

    for job in ("iris", "evidently"):
        def check_target():
            assert prometheus_query('up{job="' + job + '"}') == 1.0
        poll(check_target, "Prometheus target " + job)


def verify_baseline():
    poll(
        lambda: assert_metric("iris_prediction_requests_total", 120.0),
        "Prometheus prediction counter",
    )
    report = ROOT / "data" / "reports" / "iris_drift.html"
    result = ROOT / "data" / "reports" / "iris_drift.json"

    def check_report():
        assert report.is_file() and report.stat().st_size > 500
        assert result.is_file()
        payload = json.loads(result.read_text(encoding="utf-8"))
        assert isinstance(payload.get("metrics"), list) and payload["metrics"]
        assert prometheus_query("iris_drift_evaluation_status") == 1.0
    poll(check_report, "Evidently baseline HTML/JSON report and successful scrape", timeout=90)


def assert_metric(expr, minimum):
    value = prometheus_query(expr)
    assert value >= minimum, (expr, value, minimum)


def verify_drift():
    result = ROOT / "data" / "reports" / "iris_drift.json"
    def check_detected():
        assert result.is_file()
        data = json.loads(result.read_text(encoding="utf-8"))
        metrics = data.get("metrics", [])
        assert metrics, "Missing Evidently metrics"
        # Evidently 0.7.x: DataDriftPreset emits DriftedColumnsCount.
        summaries = [
            metric for metric in metrics
            if str(metric.get("metric_name", "")).startswith("DriftedColumnsCount")
        ]
        assert summaries, "No drift summary found in Evidently report"
        count = float(summaries[0]["value"]["count"])
        assert count >= 1, "Injected petal-length shift not detected"
        assert prometheus_query("iris_drift_evaluation_status") == 1.0
    poll(check_detected, "Injected drift detected in Evidently report", timeout=90)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", choices=["services", "baseline", "drift"], required=True)
    args = parser.parse_args()
    if args.check == "services":
        verify_services()
    elif args.check == "baseline":
        verify_baseline()
    else:
        verify_drift()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("FAIL:", error, file=sys.stderr)
        sys.exit(1)
