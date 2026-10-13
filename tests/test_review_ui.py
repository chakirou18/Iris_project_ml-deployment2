"""UI regression tests: semantic presentation and secure review behavior."""
from review.view_models import counts, filter_incidents, decorate_detail, formatted_date
from review.store import get_incident
from tests.test_review import login, csrf, client  # noqa: F401 - pytest fixture


def test_dashboard_stats_and_filters(client):
    http, db, incident_id = client
    login(http)
    response = http.get("/")
    assert response.status_code == 200
    assert b"Centre de surveillance" in response.data
    assert b"Incidents enregistr" in response.data
    assert b"Examiner" in response.data
    assert b"iris-classifier" in response.data
    assert http.get("/?q=does-not-exist").status_code == 200
    assert b"Aucun incident trouv" in http.get("/?q=does-not-exist").data
    assert b"iris-classifier" not in http.get("/?status=rejected").data


def test_incident_detail_readable_and_no_raw_json(client):
    http, db, incident_id = client
    login(http)
    response = http.get("/incidents/" + incident_id)
    assert response.status_code == 200
    assert b"Diagnostic" in response.data
    assert b"Recommandations" in response.data
    assert b"Historique des d" in response.data
    assert b"Enregistrer ma d" in response.data
    assert b"<pre>" not in response.data
    assert b'csrf' in response.data


def test_final_decision_is_read_only(client):
    http, db, incident_id = client
    login(http)
    response = http.post(
        "/incidents/" + incident_id + "/decision",
        data={"csrf": csrf(http), "decision": "approve", "comment": "Vérifié"},
    )
    assert response.status_code == 302
    html = http.get("/incidents/" + incident_id).data
    assert b"Revue termin" in html
    assert b"Enregistrer ma d" not in html
    assert get_incident(db, incident_id)["decisions"][-1]["decision"] == "approve"


def test_summary_helper():
    items = [
        {"last_decision": None},
        {"last_decision": "approve"},
        {"last_decision": "reject"},
        {"last_decision": "request_information"},
    ]
    assert counts(items) == {"total": 4, "pending": 2, "approved": 1, "rejected": 1}


def test_dates_are_stable():
    assert "UTC" in formatted_date("2026-10-13T10:26:28+00:00")
