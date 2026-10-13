import json
import pytest
from werkzeug.security import generate_password_hash

from review.app import create_app
from review.store import init_db, import_incident, get_incident, record_decision


def sample():
    return {
        "incident": {"model_id": "iris-classifier", "category": "data_drift", "severity": "warning"},
        "evidence": {"evaluated_at": "2026-10-13T09:00:00Z"},
        "diagnosis": {"observation": "Input feature distribution changed"},
        "recommendations": [{"id": "inspect", "action": "Inspect data", "requires_approval": True,
                             "execution": "not_implemented"}],
    }


@pytest.fixture
def client(tmp_path):
    db = tmp_path / "reviews.sqlite3"
    init_db(db)
    incident_id = import_incident(db, sample())
    app = create_app(database=db, password_hash=generate_password_hash("test-password"),
                     secret_key="x" * 64)
    app.config["TESTING"] = True
    return app.test_client(), db, incident_id


def login(client):
    response = client.get("/login")
    with client.session_transaction() as session:
        token = session["csrf"]
    return client.post("/login", data={"csrf": token, "password": "test-password"})


def csrf(client):
    with client.session_transaction() as session:
        return session["csrf"]


def test_authentication_required(client):
    http, _, incident_id = client
    assert http.get("/").status_code == 302
    assert http.get("/incidents/" + incident_id).status_code == 302


def test_authenticated_review_and_history(client):
    http, db, incident_id = client
    assert login(http).status_code == 302
    assert http.get("/").status_code == 200
    assert http.get("/incidents/" + incident_id).status_code == 200
    result = http.post("/incidents/" + incident_id + "/decision",
                       data={"csrf": csrf(http), "decision": "approve",
                             "comment": "Reviewed data. Needs a separate deployment approval."})
    assert result.status_code == 302
    stored = get_incident(db, incident_id)
    assert len(stored["decisions"]) == 1
    assert stored["decisions"][0]["decision"] == "approve"
    assert stored["recommendations"][0]["execution"] == "not_implemented"
    response = http.post("/incidents/" + incident_id + "/decision",
                         data={"csrf": csrf(http), "decision": "reject", "comment": "No"})
    assert response.status_code == 400


def test_csrf_rejected(client):
    http, db, incident_id = client
    login(http)
    r = http.post("/incidents/" + incident_id + "/decision",
                  data={"decision": "approve", "comment": "yes"})
    assert r.status_code == 403
    assert get_incident(db, incident_id)["decisions"] == []


def test_invalid_decisions_not_written(client):
    _, db, incident_id = client
    with pytest.raises(ValueError):
        record_decision(db, incident_id, "local-reviewer", "deploy", "now")
    with pytest.raises(ValueError):
        record_decision(db, incident_id, "local-reviewer", "approve", "")
    assert get_incident(db, incident_id)["decisions"] == []


def test_import_deduplicates(client):
    _, db, incident_id = client
    assert import_incident(db, sample()) == incident_id


def test_reject_unsafe_action(client):
    _, db, _ = client
    payload = sample()
    payload["recommendations"][0]["execution"] = "run_shell"
    with pytest.raises(ValueError):
        import_incident(db, payload)


def test_missing_credentials_refused(tmp_path, monkeypatch):
    monkeypatch.delenv("REVIEW_PASSWORD_HASH", raising=False)
    monkeypatch.delenv("REVIEW_SESSION_SECRET", raising=False)
    with pytest.raises(RuntimeError):
        create_app(database=tmp_path / "no.sqlite3")


def test_comment_escaped_by_template(client):
    http, db, incident_id = client
    login(http)
    http.post("/incidents/" + incident_id + "/decision",
              data={"csrf": csrf(http), "decision": "request_information",
                    "comment": "<script>alert(1)</script>"})
    response = http.get("/incidents/" + incident_id)
    assert b"&lt;script&gt;" in response.data
    assert b"<script>" not in response.data
