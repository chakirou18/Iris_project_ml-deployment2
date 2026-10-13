"""A past advisory approval must never grant remediation execution."""
import pytest
from werkzeug.security import generate_password_hash

from review.app import create_app
from review.store import init_db, import_incident, record_decision
from remediation.store import get_plan, plans_for_incident
from tests.test_remediation import evidence


@pytest.fixture
def ui(tmp_path):
    db = tmp_path / "review.sqlite3"
    init_db(db)
    incident = import_incident(db, evidence())
    app = create_app(database=db, password_hash=generate_password_hash("testpass"),
                     secret_key="x" * 64)
    app.config["TESTING"] = True
    http = app.test_client()
    http.get("/login")
    with http.session_transaction() as session:
        token = session["csrf"]
    assert http.post("/login", data={"csrf": token, "password": "testpass"}).status_code == 302
    with http.session_transaction() as session:
        token = session["csrf"]
    return http, db, incident, token


def test_plan_creation_and_explicit_approval(ui):
    http, db, incident, csrf = ui
    assert http.get("/incidents/" + incident).status_code == 200
    assert not plans_for_incident(db, incident)
    response = http.post("/incidents/" + incident + "/remediation/propose",
                         data={"csrf": csrf})
    assert response.status_code == 302
    plan = plans_for_incident(db, incident)[0]
    assert plan["status"] == "proposed"
    url = "/incidents/" + incident + "/remediation/" + plan["id"] + "/decision"
    assert http.post(url, data={"csrf": csrf, "decision": "approve"}).status_code == 400
    assert get_plan(db, plan["id"])["status"] == "proposed"
    assert http.post(url, data={"csrf": csrf, "decision": "approve",
                                 "confirmation": "sandbox-only"}).status_code == 302
    assert get_plan(db, plan["id"])["status"] == "approved"
    assert http.post(url, data={"csrf": csrf, "decision": "approve",
                                 "confirmation": "sandbox-only"}).status_code == 400


def test_old_advisory_review_does_not_approve_plan(ui):
    http, db, incident, csrf = ui
    record_decision(db, incident, "local-reviewer", "approve", "Advisory only")
    http.post("/incidents/" + incident + "/remediation/propose", data={"csrf": csrf})
    plan = plans_for_incident(db, incident)[0]
    assert get_plan(db, plan["id"])["status"] == "proposed"


def test_action_csrf_and_auth(ui):
    http, db, incident, token = ui
    assert http.post("/incidents/" + incident + "/remediation/propose").status_code == 403
    assert not plans_for_incident(db, incident)
