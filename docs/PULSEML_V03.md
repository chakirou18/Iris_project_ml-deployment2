# PulseML V0.3 — optional, read-only LLM incident hypotheses

The normal Iris monitoring/ingestion stack works **without an LLM**. This
deliverable adds an optional provider-backed hypothesis on an individual
incident after the reviewer explicitly presses a button. It never modifies
the monitoring record, remediation approvals, or deployed model.

## Local setup

Install optional provider dependencies in the trusted local Python environment:

```powershell
python -m pip install "langchain-openai>=1,<2"
```

Set the provider key in your **local shell or OS secret manager**, NEVER in
GitHub, CI logs, screenshots, project .env files, or Docker Compose.
Set environment variables `OPENAI_API_KEY`, `PULSEML_LLM_MODEL` (an
available GPT model), and `PULSEML_ENABLE_LLM=true` in the reviewer
process environment. Confirm costs, retention, privacy and provider terms
before enabling external API calls.

Restart the local reviewer server using
`powershell -ExecutionPolicy Bypass -File .\scripts\start_review_windows.ps1`.
Open a **non-demo** monitoring incident and select
**Demander un diagnostic IA**. The structured result is stored in the
local SQLite audit table `incident_analyses` and displayed as a clearly
unverified hypothesis with a declared confidence level, evidence gaps,
and a proposed read-only investigation.

No key is needed to run the regression suite:
```powershell
python -m pytest -q tests/test_incident_analysis.py
```

## Boundaries

- Only allowlisted aggregates and alert names are sent to the LLM; raw
  observations, labels, and passwords are not part of the prompt.
- Review decisions and remediation plans are independent from AI hypotheses.
- No model may issue commands, arbitrary PromQL, or cloud/deployment actions.
- No automated provider invocation during ingestion; user must initiate.
- Only Iris is supported so far. Multi-model monitoring requires typed
  schemas and per-model permissions.
- This single-user localhost prototype does not have request rate-limiting
  or per-user usage quotas; keep it private. Prompt safety and diagnostic
  quality require a larger adversarial evaluation before public use.
