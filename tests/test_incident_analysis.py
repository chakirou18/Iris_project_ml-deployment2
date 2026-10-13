import pytest
from werkzeug.security import generate_password_hash
from review.store import init_db, import_incident, get_incident
from review.app import create_app
from agents.incident_analysis import analyze_incident, latest_analysis


class FakeLLM:
    def invoke(self, prompt):
        assert "drifted_features" in prompt
        return {"probable_cause": "Données d'entrée modifiées", "explanation": "Hypothèse non confirmée",
                "confidence": "low", "evidence_gaps": ["Étiquettes réelles absentes"],
                "next_read_only_check": "Comparer les distributions d'entrée"}


def create_real(db):
    return import_incident(db, {
        "incident": {"model_id": "iris-classifier", "category": "data_drift", "severity": "warning"},
        "evidence": {"source": "evidently_verified_summary", "model_id": "iris-classifier",
                     "status": "evaluated", "drifted_features": 1, "samples": 120,
                     "features": {"PetalLengthCm": {"drifted": True, "p_value": .001}}},
        "diagnosis": {"observation": "Drift détecté"},
        "recommendations": [{"action": "Vérifier", "requires_approval": True,
                             "execution": "not_implemented"}] })


def test_llm_hypothesis_is_separate_and_does_not_change_incident(tmp_path):
    db=tmp_path/"incidents.sqlite3"
    init_db(db)
    inc=create_real(db)
    old=get_incident(db,inc)
    result=analyze_incident(db,inc,structured_model=FakeLLM())
    assert result["confidence"]=="low"
    assert latest_analysis(db,inc)["status"]=="hypothesis_not_verified"
    assert get_incident(db,inc)==old


def test_demo_rejected(tmp_path):
    db=tmp_path/"incidents.sqlite3"
    init_db(db)
    inc=import_incident(db,{
        "incident":{"model_id":"iris-classifier","category":"data_drift","severity":"warning"},
        "evidence":{"source":"synthetic_local_preview"},
        "diagnosis":{"observation":"DEMO"},
        "recommendations":[]})
    with pytest.raises(ValueError):
        analyze_incident(db,inc,structured_model=FakeLLM())


def test_web_request_never_runs_without_opt_in(tmp_path,monkeypatch):
    monkeypatch.delenv("PULSEML_ENABLE_LLM",raising=False)
    db=tmp_path/"incidents.sqlite3"
    init_db(db)
    inc=create_real(db)
    app=create_app(database=db,password_hash=generate_password_hash("secret"),secret_key="x"*64)
    app.config["TESTING"]=True
    client=app.test_client()
    client.get("/login")
    with client.session_transaction() as sess:
        csrf=sess["csrf"]
    assert client.post("/login",data={"csrf":csrf,"password":"secret"}).status_code==302
    with client.session_transaction() as sess:
        csrf=sess["csrf"]
    assert client.get("/incidents/"+inc).status_code==200
    assert client.post("/incidents/"+inc+"/ai-analyze",data={"csrf":csrf}).status_code==403
    assert latest_analysis(db,inc) is None
