"""Start a localhost demonstration. No cloud connection or real model traffic."""
import threading
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

from review.app import create_app
from review.setup_credentials import create as create_credentials
from review.store import import_incident, init_db, list_incidents

ROOT = Path(__file__).resolve().parents[1]
LOCAL_URL = "http://127.0.0.1:5050/login"


def make_demo_incident():
    return {
        "incident": {
            "model_id": "iris-classifier",
            "category": "data_drift",
            "severity": "warning",
        },
        "evidence": {
            "source": "synthetic_local_preview",
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "drifted_features": 1,
            "example_feature": "PetalLengthCm",
            "notice": "DEMONSTRATION ONLY - not a real model alert",
        },
        "diagnosis": {
            "source": "simulated_example",
            "observation": "DEMONSTRATION: PetalLengthCm distribution appears shifted",
            "affected_features": ["PetalLengthCm"],
            "limitations": "Fictional alert; Evidently was not run for this preview.",
        },
        "recommendations": [
            {"id": "demo-investigate",
             "action": "DEMO: Inspect input collection and preprocessing",
             "requires_approval": True, "execution": "not_implemented"},
            {"id": "demo-labels",
             "action": "DEMO: Collect labels before evaluating predictive accuracy",
             "requires_approval": True, "execution": "not_implemented"},
        ],
    }


def read_private_env(file):
    values = {}
    for line in Path(file).read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value
    if not values.get("REVIEW_PASSWORD_HASH") or not values.get("REVIEW_SESSION_SECRET"):
        raise RuntimeError("Incomplete review credentials")
    return values


def prepare_preview(directory=ROOT):
    """Prepare local credentials and one fake incident without starting a server."""
    directory = Path(directory)
    data = directory / "data"
    db = data / "review.sqlite3"
    credentials = data / "review_credentials.env"
    password = None
    if not credentials.exists():
        credentials, password = create_credentials(credentials)
    values = read_private_env(credentials)
    init_db(db)
    if not list_incidents(db):
        import_incident(db, make_demo_incident())
    return db, values, password


def main():
    db, values, password = prepare_preview()
    print("\nLOCAL MONITORING PREVIEW — DEMO DATA ONLY", flush=True)
    if password:
        print("One-time local reviewer password:", password, flush=True)
        print("Save it privately; only its hash is stored.", flush=True)
    else:
        print("Using existing credentials; enter your previously saved password.", flush=True)
    print("Open:", LOCAL_URL, flush=True)
    print("Press Ctrl+C to stop. No production access is enabled.", flush=True)
    app = create_app(
        database=db,
        password_hash=values["REVIEW_PASSWORD_HASH"],
        secret_key=values["REVIEW_SESSION_SECRET"],
    )
    threading.Timer(2.0, lambda: webbrowser.open(LOCAL_URL)).start()
    app.run(host="127.0.0.1", port=5050, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
