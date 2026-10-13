"""Local human review store; append-only decisions and no action execution."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ALLOWED = {"approve", "reject", "request_information"}


def connect(path):
    db = sqlite3.connect(str(path))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=5000")
    return db


def init_db(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS incidents (
            id TEXT PRIMARY KEY, model_id TEXT NOT NULL,
            category TEXT NOT NULL, severity TEXT NOT NULL,
            evidence TEXT NOT NULL, diagnosis TEXT NOT NULL,
            recommendations TEXT NOT NULL, created_at TEXT NOT NULL
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_id TEXT NOT NULL REFERENCES incidents(id),
            actor TEXT NOT NULL, decision TEXT NOT NULL,
            comment TEXT NOT NULL, created_at TEXT NOT NULL
        )""")


def import_incident(path, incident):
    if not isinstance(incident, dict):
        raise ValueError("Invalid incident")
    details = incident.get("incident", {})
    diagnosis = incident.get("diagnosis", {})
    recommendations = incident.get("recommendations", [])
    if not isinstance(details, dict) or details.get("model_id") != "iris-classifier":
        raise ValueError("Unknown incident model")
    if details.get("category") not in ("data_drift", "no_drift_detected",
                                     "service_unavailable", "monitoring_unavailable",
                                     "monitoring_failed", "prediction_errors",
                                     "prediction_latency"):
        raise ValueError("Unknown incident category")
    if details.get("severity") not in ("warning", "info", "critical"):
        raise ValueError("Unknown incident severity")
    if not isinstance(diagnosis, dict) or not isinstance(recommendations, list):
        raise ValueError("Malformed incident")
    if len(recommendations) > 10 or any(not isinstance(x, dict) or
       x.get("requires_approval") is not True or x.get("execution") != "not_implemented"
       for x in recommendations):
        raise ValueError("Unsafe recommendations")
    if len(json.dumps(incident)) > 32000:
        raise ValueError("Incident too large")
    import hashlib
    # Deduplicate identical evidence without trusting a user-provided ID.
    evidence = incident.get("evidence", {})
    canonical = json.dumps([details, evidence], sort_keys=True)
    incident_id = hashlib.sha256(canonical.encode()).hexdigest()[:24]
    created_at = datetime.now(timezone.utc).isoformat()
    with connect(path) as db:
        db.execute("""INSERT OR IGNORE INTO incidents
        (id,model_id,category,severity,evidence,diagnosis,recommendations,created_at)
        VALUES (?,?,?,?,?,?,?,?)""", (
            incident_id, "iris-classifier", details["category"], details["severity"],
            json.dumps(evidence), json.dumps(diagnosis),
            json.dumps(recommendations), created_at,
        ))
    return incident_id


def list_incidents(path):
    with connect(path) as db:
        rows = db.execute("""SELECT i.id,i.model_id,i.category,i.severity,i.created_at,
          (SELECT d.decision FROM decisions d WHERE d.incident_id=i.id
           ORDER BY d.id DESC LIMIT 1) last_decision
          FROM incidents i ORDER BY i.created_at DESC""").fetchall()
        return [dict(x) for x in rows]


def get_incident(path, incident_id):
    with connect(path) as db:
        row = db.execute("SELECT * FROM incidents WHERE id=?", (incident_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        for key in ("evidence", "diagnosis", "recommendations"):
            result[key] = json.loads(result[key])
        result["decisions"] = [dict(x) for x in db.execute(
            "SELECT actor,decision,comment,created_at FROM decisions WHERE incident_id=? ORDER BY id",
            (incident_id,),
        ).fetchall()]
        return result


def record_decision(path, incident_id, actor, decision, comment):
    if decision not in ALLOWED:
        raise ValueError("Invalid decision")
    if not isinstance(comment, str) or not 1 <= len(comment.strip()) <= 1000:
        raise ValueError("A comment of 1-1000 characters is required")
    with connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT category FROM incidents WHERE id=?", (incident_id,)).fetchone()
        if row is None or row["category"] == "no_drift_detected":
            raise ValueError("Incident unavailable for review")
        last = db.execute(
            "SELECT decision FROM decisions WHERE incident_id=? ORDER BY id DESC LIMIT 1",
            (incident_id,),
        ).fetchone()
        if last and last["decision"] in ("approve", "reject"):
            raise ValueError("Final decision already recorded")
        db.execute("""INSERT INTO decisions(incident_id,actor,decision,comment,created_at)
        VALUES(?,?,?,?,?)""", (
            incident_id, actor, decision, comment.strip(),
            datetime.now(timezone.utc).isoformat(),
        ))
    # This changes only the local audit database: NO execution pathway.
