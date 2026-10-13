from review.preview import prepare_preview
from review.store import get_incident, list_incidents
from review.app import create_app
from werkzeug.security import check_password_hash


def test_local_preview(tmp_path):
    db, env, password = prepare_preview(tmp_path)
    assert password is not None
    assert check_password_hash(env["REVIEW_PASSWORD_HASH"], password)
    incident = get_incident(db, list_incidents(db)[0]["id"])
    assert incident["evidence"]["source"] == "synthetic_local_preview"
    assert all(r["execution"] == "not_implemented" for r in incident["recommendations"])
    assert password not in (tmp_path / "data/review_credentials.env").read_text()
    _, _, second_password = prepare_preview(tmp_path)
    assert second_password is None
    assert len(list_incidents(db)) == 1
    app = create_app(database=db, password_hash=env["REVIEW_PASSWORD_HASH"],
                     secret_key=env["REVIEW_SESSION_SECRET"])
    assert app.test_client().get("/login").status_code == 200
