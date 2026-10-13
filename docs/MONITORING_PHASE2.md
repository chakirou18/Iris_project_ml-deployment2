# Phase 2 — Local Iris MLOps monitoring

This is an **isolated local demo**, not a deployment to Kubernetes or a public
multi-user monitoring platform. It adds Evidently data drift reports, a
Prometheus exporter and a provisioned Grafana dashboard. The original Flask
prediction form and trained model remain unchanged.

## Start with Docker Compose

Requirements: Docker Engine / Docker Desktop with the Compose plugin and Python 3.

From the repository root:

```bash
python scripts/setup_monitoring_env.py
docker compose -f docker-compose.monitoring.yml up --build -d
```

The initialization script creates ignored secrets in `.env` and
`monitoring/secrets/metrics_token`. **Never commit or share them.**

Services (all exposed only to your local computer):
- Iris Flask form: http://127.0.0.1:5000/
- Prometheus: http://127.0.0.1:9090/targets
- Grafana: http://127.0.0.1:3000/

Use `GRAFANA_ADMIN_USER` and `GRAFANA_ADMIN_PASSWORD` from your private
`.env` file to log in. Dashboard: **ML Monitoring / Iris ML Monitoring | Phase 2**.

Prometheus scrapes the Flask endpoint using the locally generated bearer token.
The Evidently worker publishes a numeric evaluation state. An evaluation state
of 1 means a drift report was generated; it DOES NOT mean there is no drift.
Read the Evidently report for the actual statistical test results.

## Generate known baseline and shifted demo observations

**Stop other traffic first.** This synthetic traffic is solely for the local
demo; do not point the script at a production model.

```bash
python scripts/generate_monitoring_traffic.py --scenario baseline --count 120
docker compose -f docker-compose.monitoring.yml exec evidently python -m monitoring.drift_worker --once
```

The worker runs automatically every 30 seconds. The drift report files are
`data/reports/iris_drift.html` and `data/reports/iris_drift.json`.

To demonstrate a strong change in petal length, clear only the **local demo**
observation file (not the training data) and generate a fresh window:

```bash
docker compose -f docker-compose.monitoring.yml down
```

Move or delete `data/predictions.jsonl` after confirming it contains *only
disposable demo events*, restart Compose and run:

```bash
docker compose -f docker-compose.monitoring.yml up -d
python scripts/generate_monitoring_traffic.py --scenario drift --count 120
```

Review the resulting HTML report, compare with baseline and inspect the
evaluator's health/status in Grafana. The synthetic shift is not evidence of a
real production drift.

## What is monitored

- Flask service availability and request counters
- Prediction latency and errors
- Evidently evaluation status, recency and sample count
- Saved Evidently DataDriftPreset HTML and JSON reports for all Iris inputs

The current Grafana dashboard shows evaluator health, **not yet a validated
numeric drift-score series**. For drift details open the Evidently report.
Drift-to-Prometheus metric extraction, per-column alert rules and incident
notification are next extensions, not completed features of this initial stack.

For a production rollout, replace JSONL with shared durable storage, add
authenticated tenant-aware ingestion, consider retention/privacy, ensure
Prometheus exporters remain private and configure alert delivery.

## Stop and test

```bash
docker compose -f docker-compose.monitoring.yml down
python -m pip install -r requirements-monitoring.txt
python -m pytest -q tests/test_monitoring.py tests/test_drift.py
```

Do **not** use `docker compose down -v` unless you intend to erase local
Prometheus/Grafana volumes.
