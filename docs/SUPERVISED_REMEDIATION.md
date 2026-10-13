# PulseML — supervised remediation: first safe prototype

This stage demonstrates a **real, isolated retraining experiment**, but does
**not** fix an incident in production. It never rewrites
`artifacts/models/model.pkl`, the Flask serving model, Kubernetes files,
or a deployment environment.

## Gate / scope

- Only an Iris `data_drift` incident with verified Evidently-style evidence
  can be proposed. The local preview's *synthetic* incident is rejected.
- The existing UI's "Avis favorable" is only an advisory record. It does NOT
  give authorization to run experiments.
- A *separate explicit authorization*, bound to a specific incident, immutable
  evidence digest and allowlisted action (`evaluate_iris_candidate`), is required.
- An approval can be consumed once. Final history is stored in SQLite.
- The runner only trains a candidate locally from saved training artifacts,
  compares it with the existing model on the saved holdout, writes a JSON report
  to an ignored `data/candidates/` directory, and records the result.
- Even a passing candidate cannot be deployed, promoted or used to assert
  that live drift has been resolved. No ground-truth live labels are available.

## Run locally against a verified real monitoring incident

From the repo root on the remediation branch, install `requirements-agents.txt`
and ensure that an authentic Evidently summary has been generated and imported
using the phase 3 tools. Existing legacy incidents or the synthetic preview
cannot authorize this experiment.

```bash
python -m remediation.cli propose --incident-id INCIDENT_ID
python -m remediation.cli status --plan-id PLAN_ID
python -m remediation.cli decide --incident-id INCIDENT_ID --plan-id PLAN_ID --decision approve --confirm sandbox-only
python -m remediation.runner --plan-id PLAN_ID
python -m remediation.cli status --plan-id PLAN_ID
```

Stop before approval if the plan is unexpected. `--confirm sandbox-only` is a
distinct explicit permission for offline evaluation. You may instead reject
with `--decision reject`. Run with a dedicated OS user and isolated trusted
Python environment, never a privileged production deployment environment.

The next deliverable is to surface remediation plans and explicit action-scoped
approval on the PulseML UI, build diagnosis benchmarks, and verify any future
correction with labeled real-world data. For multi-model support, replace the
Iris-specific allowlist with signed, reviewed per-model adapters and a robust
authorization service.

## Security notes

The stored audit trail is application-level and not tamper-proof against
administrators with database write access. Serialized joblib artifacts are
loaded only from this repository's trusted local data. Never load untrusted
pickle/joblib files. This is an experimental proof of concept, not a
production-grade autonomous repair engine.
