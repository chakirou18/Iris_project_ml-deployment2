# Phase 3 — Local human incident review (no execution)

This is a single-reviewer, **localhost-only prototype**. It displays
diagnosis and recommendations from the phase-3 analysis, allows a human to
approve/reject/request information, and writes a chronological record into
SQLite. An approval is **not permission to deploy**. No remediation or external
write-capable tool is wired to this interface.

## Setup and local launch

Install the minimal dependencies from a trusted environment:

```bash
python -m pip install "flask>=3,<4"
python -m review.setup_credentials
```

The command prints a randomly generated one-time local reviewer password and
writes a salted password hash plus session secret into
`data/review_credentials.env` (excluded from Git). Load this file into
your shell as environment variables using an appropriate local secret manager;
do not commit or paste the credentials into GitHub Actions logs. Never source
an untrusted environment file.

First produce an incident using the LangGraph workflow, then import it:

```bash
python -m agents.diagnostic_graph --summary data/reports/iris_drift_summary.json
python -m review.import_incident --input data/reports/iris_incident.json
python -m review.app
```

For the newer agent workflow in `agents/llm_workflow.py`, save its structured
output as JSON and import that file instead. The import CLI has no network
listener and applies validation.

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
