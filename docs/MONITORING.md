# Iris monitoring — Livrable 1

This branch instruments the existing Flask Iris classifier without retraining
its model or modifying the prediction form. It is an **MVP for a single process**,
not yet a multi-tenant monitoring platform.

## What is recorded?

Each POST to the original "/" form produces one JSONL event with:
- event_id (random UUID), UTC timestamp, model ID and version
- the four feature values on success (no raw invalid inputs)
- predicted Iris class, request latency in milliseconds, success/error status

Stored locally at \`data/predictions.jsonl\`, or configure
\`PREDICTION_EVENTS_PATH\` to another writable location. The file is excluded from
Git. This is **not** ground truth, so classification accuracy cannot be
calculated from predictions alone. Add verified labels later via an independent
data source and match them by prediction/event ID.

## Endpoints

- \`GET /\`: unchanged prediction form
- \`POST /\`: predicts and records an event (bad input -> 400; model failure -> 500)
- \`GET /health\`: status and model identifier/version
- \`GET /metrics\`: Prometheus text metrics

Metrics:
- \`iris_prediction_requests_total{status="success|error"}\`
- \`iris_prediction_errors_total\`
- \`iris_prediction_latency_seconds\` (histogram)
- \`iris_predictions_by_class_total{class_name="..."}\`
- \`iris_prediction_event_storage_errors_total\`

Do **not** use event UUIDs, feature values, user IDs or timestamps as Prometheus
labels; they would cause unbounded series cardinality.

## Local run / tests

From the repository root in a Python environment:

\`\`\`bash
python -m pip install flask numpy joblib scikit-learn pandas prometheus-client pytest
python -m pytest -q tests/test_monitoring.py
python scripts/export_reference.py
python application.py
\`\`\`

The existing package installation (\`pip install -e .\`) also includes
\`prometheus-client\` from requirements.txt. The first command above is a
lightweight alternative for testing without optional training dependencies.

Visit http://127.0.0.1:5000/ and make predictions, then inspect:
- http://127.0.0.1:5000/health
- http://127.0.0.1:5000/metrics
- \`data/predictions.jsonl\`
- \`data/reference_iris.csv\` (generated from **the saved X_train.pkl**, not from test data)

Do not load pickle/joblib artifacts from unknown or untrusted sources.

## Security and deployment limitations

Metrics are allowed from **loopback only by default**. Set
\`MONITORING_METRICS_TOKEN\` to require
\`Authorization: Bearer <token>\` for all metrics requests; configure your
Prometheus scrape job with matching credentials. Even with a token, restrict
network access to metrics and use HTTPS. Do **not** publish raw metrics publicly
through a Kubernetes LoadBalancer. Never commit a token.

Configure \`MODEL_VERSION\` from the actual deployed model version or commit;
the default \`unversioned\` is only a placeholder. \`MODEL_ID\` defaults to
\`iris-classifier\`.

The local JSONL adapter supports threads within one Python process only:
multiple workers, pod replicas and restarts without persistent storage need a
database or queue-backed event store with durability guarantees. The existing
Docker/Kubernetes deployment files are deliberately **unchanged**. Flask's
built-in server is a development server, not a hardened production setup.

## Next steps

1. Run Evidently analyses comparing recent observations with the saved training
   reference; keep the reference distinct from live data.
2. Configure a private Prometheus scrape target for the application.
3. Configure Grafana dashboards and bounded alert rules.
4. Add true-label ingestion and model performance monitoring.
5. Move event storage to a durable shared database for multiple deployments.
6. Only then add AI agents for diagnosis and human-approved remediation.
