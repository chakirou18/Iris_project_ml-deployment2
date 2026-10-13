"""Local-only operator console. Approval records a decision; it never executes it."""
import os
import secrets
from functools import wraps
from pathlib import Path

from flask import Flask, abort, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from review.store import init_db, list_incidents, get_incident, record_decision
from review.view_models import counts, filter_incidents, decorate_detail
from remediation.store import init_remediation_db, plans_for_incident, can_plan, propose_plan, decide_plan

ROOT = Path(__file__).resolve().parents[1]


def create_app(*, database=None, password_hash=None, secret_key=None):
    database = str(database or os.environ.get("REVIEW_DB_PATH", ROOT / "data/review.sqlite3"))
    password_hash = password_hash or os.environ.get("REVIEW_PASSWORD_HASH")
    secret_key = secret_key or os.environ.get("REVIEW_SESSION_SECRET")
    if not password_hash or not secret_key or len(secret_key) < 32:
        raise RuntimeError("REVIEW_PASSWORD_HASH and strong REVIEW_SESSION_SECRET required")
    app = Flask(__name__, template_folder="templates")
    app.secret_key = secret_key
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_SECURE=os.getenv("REVIEW_HTTPS", "false").lower() == "true",
        MAX_CONTENT_LENGTH=4000,
    )
    app.config["REVIEW_DB_PATH"] = database
    init_db(database)
    init_remediation_db(database)

    @app.after_request
    def secure_headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; form-action 'self'; frame-ancestors 'none'"
        return response

    def csrf_token():
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
        return session["csrf"]

    app.jinja_env.globals["csrf_token"] = csrf_token

    def require_csrf():
        if not secrets.compare_digest(request.form.get("csrf", ""), session.get("csrf", "!")):
            abort(403)

    def authenticated(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not session.get("authenticated"):
                return redirect(url_for("login"))
            return fn(*args, **kwargs)
        return wrapper

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            require_csrf()
            password = request.form.get("password", "")
            if not check_password_hash(password_hash, password):
                return render_template("login.html", error="Mot de passe incorrect."), 401
            session.clear()
            session["authenticated"] = True
            session["actor"] = "local-reviewer"
            csrf_token()
            return redirect(url_for("index"))
        return render_template("login.html", error=None)

    @app.post("/logout")
    @authenticated
    def logout():
        require_csrf()
        session.clear()
        return redirect(url_for("login"))

    @app.get("/")
    @authenticated
    def index():
        all_incidents = list_incidents(database)
        return render_template("index.html", incidents=filter_incidents(
            all_incidents, request.args.get("q", ""), request.args.get("status", "all")
        ), summary=counts(all_incidents), search=request.args.get("q", "")[:80],
            active_status=request.args.get("status", "all"))

    @app.get("/incidents/<incident_id>")
    @authenticated
    def detail(incident_id):
        incident = get_incident(database, incident_id)
        if incident is None:
            abort(404)
        return render_template("detail.html", item=decorate_detail(incident),
                               remediation_plans=plans_for_incident(database, incident_id),
                               can_propose_remediation=can_plan(incident), message=None)

    @app.post("/incidents/<incident_id>/decision")
    @authenticated
    def decision(incident_id):
        require_csrf()
        try:
            record_decision(database, incident_id, session["actor"],
                            request.form.get("decision"), request.form.get("comment", ""))
        except ValueError:
            abort(400)
        return redirect(url_for("detail", incident_id=incident_id))

    @app.post("/incidents/<incident_id>/remediation/propose")
    @authenticated
    def remediation_propose(incident_id):
        require_csrf()
        try:
            propose_plan(database, incident_id, session["actor"])
        except ValueError:
            abort(400)
        return redirect(url_for("detail", incident_id=incident_id))

    @app.post("/incidents/<incident_id>/remediation/<plan_id>/decision")
    @authenticated
    def remediation_decision(incident_id, plan_id):
        require_csrf()
        try:
            decide_plan(database, incident_id, plan_id, session["actor"],
                        request.form.get("decision"), request.form.get("confirmation"))
        except ValueError:
            abort(400)
        return redirect(url_for("detail", incident_id=incident_id))

    return app


def main():
    app = create_app()
    app.run(host="127.0.0.1", port=5050, debug=False)


if __name__ == "__main__":
    main()
