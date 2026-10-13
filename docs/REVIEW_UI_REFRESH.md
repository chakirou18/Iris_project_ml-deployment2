# Reviewer interface refresh

This branch redesigns the local incident review UI for readability and small screens.

- New shared French navigation, dashboard summary cards, text search and status filter.
- Clear incident diagnosis with affected features and limitations.
- Recommendations displayed as separate non-executable cards.
- Decision history presented as a timeline; approval form only shown before a final decision.
- Demo incidents are visibly marked as **fictional**.
- No Bootstrap CDN, JavaScript tracking, or new production dependency is required. All assets are local.

## View the refreshed preview on Windows

```powershell
git fetch origin
git switch feature/iris-review-ui-refresh
git pull origin feature/iris-review-ui-refresh
powershell -ExecutionPolicy Bypass -File .\scripts\start_review_windows.ps1
```

Then open `http://127.0.0.1:5050/login`. If the old server is still running,
stop it with Ctrl+C before restarting. Reload the browser with Ctrl+F5 if
the old stylesheet was cached.

The password and decision history in `data/` are retained. An existing final
approval stays final; no UI redesign unlocks or reverses it. The UI only
records human review opinions; it cannot deploy, retrain or change a model.

## Verify

```bash
python -m pytest -q tests/test_review.py tests/test_review_preview.py tests/test_review_ui.py
```

Do not merge this stacked branch into `main` until review of the CI/CD
deployment workflow; the dashboard is a localhost-only demonstration.
