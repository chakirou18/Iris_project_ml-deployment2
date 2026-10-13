# PulseML — local automatic ingestion of real monitoring signals

The local stack now includes a periodic `incident-ingestor` container.
It reads two independent sources:

- A recent (<=5 minutes), validated Evidently JSON summary in
  `data/reports/iris_drift_summary.json`.
- The fixed internal Prometheus `/api/v1/alerts` endpoint, accepting only
  specified, **firing** Iris rules.

Each continuous issue is represented as an incident record in the existing
`data/review.sqlite3` file, without copying raw predictions, user secrets or
free-form alert annotations into the database. Repeated polls of a still active
signal do not create duplicate incidents. A healthy measurement clears the
*active signal* in the stream table, **not** the immutable incident review or
the model itself. It does not prove that predictive performance recovered.

The ingestion worker reuses the LangGraph deterministic diagnosis as a
read-only collaborator for Evidently drift. This deployment uses **no live LLM
API**. Prometheus technical alerts get rule-based diagnoses and suggested
investigations. There is no automatic retraining, cloud action, model promotion,
or deployment.

## Test locally
Switch to `feature/pulseml-auto-incidents`, then:

```powershell
python scripts/setup_monitoring_env.py
docker compose -f docker-compose.monitoring.yml up --build -d
docker compose -f docker-compose.monitoring.yml ps
```

Only run the setup command the **first** time; do not regenerate existing
credentials. Starting the Compose stack adds the ingestion worker, but the
local UI is still started independently:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_review_windows.ps1
```

Open `http://127.0.0.1:5050/login` and sign in with the same local reviewer
password as before. Both the UI and Docker worker share `data/review.sqlite3`
through the project directory.

Use only disposable local traffic for testing (never submit synthetic requests
to a public/production inference endpoint):

```powershell
docker compose -f docker-compose.monitoring.yml exec -T iris python -m scripts.generate_monitoring_traffic --scenario drift --count 120
docker compose -f docker-compose.monitoring.yml exec -T evidently python -m monitoring.drift_worker --once
docker compose -f docker-compose.monitoring.yml exec -T incident-ingestor python -m monitoring.incident_ingestor --once
```

Reload the PulseML dashboard. Its monitoring incidents now come from the local
Evidently/Prometheus evaluation; the old preview incident remains marked as a
demo. The ingestor waits for Prometheus rules to reach firing status and will
not interpret unavailable telemetry as recovery.

## Security and limitations

- The ingestion worker is private to Docker Compose and has no external HTTP
  server or public port.
- The endpoint and alert names are fixed; free-form external webhooks are not
  accepted.
- A statistical drift signal is not a confirmed drop in model accuracy.
- A stopped/restarted component may temporarily interrupt ingestion. The local
  JSONL/SQLite storage is only an MVP, not high-availability multi-tenant storage.
- No alert-message delivery (email/push) or production incident resolution
  automation is included. Refresh the dashboard to see new incidents.
- The remediation approval gate remains separate; old advisory decisions cannot
  authorize execution.
