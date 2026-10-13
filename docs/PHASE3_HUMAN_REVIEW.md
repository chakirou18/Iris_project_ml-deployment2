# Phase 3 — Local human incident review (no execution)

This is a single-reviewer, **localhost-only prototype**. It displays
diagnosis and recommendations from the phase-3 analysis, allows a human to
approve/reject/request information, and writes a chronological record into
SQLite. An approval is **not permission to deploy**. No remediation or external
write-capable tool is wired to this interface.

## Setup and local launch

Install the minimal dependencies from a trusted environment:

```bash
python -m pip install -r requirements-agents.txt
python -m review.setup_credentials
```

The command prints a randomly generated one-time local reviewer password and
writes a salted password hash plus session secret into
`data/review_credentials.env` (excluded from Git). Load this file into your shell as environment variables using an appropriate
local secret manager; do not commit or paste the credentials into GitHub
Actions logs. For local PowerShell only, after reviewing the generated file,
you can use:\n\n```powershell\nGet-Content data/review_credentials.env | ForEach-Object {\n  $key, $value = $_ -split '=', 2\n  [Environment]::SetEnvironmentVariable($key, $value, 'Process')\n}\n``` Never source
an untrusted environment file.

First produce a compatible review incident using the read-only LangGraph workflow, then import it:

```bash
python -m review.prepare_incident --summary data/reports/iris_drift_summary.json
python -m review.import_incident --input data/reports/iris_review_ready.json
python -m review.app
```

The incident preparation command uses the phase-3 read-only LangGraph workflow,
without contacting a real LLM or Prometheus. The import CLI has no network
listener and applies validation. The legacy `agents.diagnostic_graph` JSON
format is not directly importable.

Open http://127.0.0.1:5050/login. Authenticate with the generated reviewer
password. The interface allows decisions and shows history.

## Security and limitations

- Session cookie is HttpOnly and SameSite=Strict; enable REVIEW_HTTPS=true
  only when using a TLS terminator and secure local configuration.
- All state-changing requests require a per-session CSRF token.
- The SQLite record provides an application-level append-only history.
  It is *not* a tamper-proof audit log for privileged OS/database users.
- The local password system has no multi-user accounts, MFA, rate limiting,
  external authentication or tenant isolation. Do not expose it to the Internet.
- Import only incident files from the trusted monitoring pipeline; output is
  escaped in HTML, and only non-executable recommendations are accepted.
- To use outside a local demo, add production-grade authentication, rate
  limits, role enforcement, encrypted storage, durable history and a
  separately authorized correction executor.
- This interface does not automatically ingest alerts. Import is a manual
  CLI step until the next integration.

## Tests

```bash
python -m pytest -q tests/test_review.py
```
