"""Immutable, explicitly approved remediation plans stored separately from review opinions.

No old 'approve' incident decision authorizes an execution. The only allowlisted
MVP action is offline Iris candidate training/evaluation.
"""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from review.store import connect, get_incident

ACTION = "evaluate_iris_candidate"
STATES = {"proposed", "approved", "rejected", "running", "candidate_ready",
          "candidate_rejected", "failed"}
ALLOWLIST = {"iris-classifier": ACTION}


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def init_remediation_db(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS remediation_plans (
          id TEXT PRIMARY KEY,
          incident_id TEXT NOT NULL REFERENCES incidents(id),
          model_id TEXT NOT NULL,
          action TEXT NOT NULL,
          evidence_digest TEXT NOT NULL,
          status TEXT NOT NULL,
          approved_by TEXT,
          approved_at TEXT,
          result_json TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(incident_id, action)
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS remediation_history (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          plan_id TEXT NOT NULL REFERENCES remediation_plans(id),
          actor TEXT NOT NULL, event TEXT NOT NULL, note TEXT NOT NULL,
          created_at TEXT NOT NULL
        )""")


def _canonical_evidence(incident):
    return json.dumps({
        "model_id": incident["model_id"],
        "category": incident["category"],
        "evidence": incident["evidence"],
        "diagnosis": incident["diagnosis"],
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _eligible(incident):
    evidence = incident["evidence"]
    return (
        incident["model_id"] in ALLOWLIST
        and incident["category"] == "data_drift"
        and isinstance(evidence, dict)
        and evidence.get("status") == "evaluated"
        and evidence.get("model_id") == incident["model_id"]
        and type(evidence.get("drifted_features")) is int
        and evidence["drifted_features"] > 0
        and type(evidence.get("samples")) is int
        and evidence["samples"] >= 30
        and evidence.get("source") != "synthetic_local_preview"
    )


def get_plan(path, plan_id):
    with connect(path) as db:
        row = db.execute("SELECT * FROM remediation_plans WHERE id=?", (plan_id,)).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["history"] = [
            dict(r) for r in db.execute(
                "SELECT actor,event,note,created_at FROM remediation_history WHERE plan_id=? ORDER BY id",
                (plan_id,),
            )
        ]
        data["result"] = json.loads(data["result_json"]) if data["result_json"] else None
        return data


def plans_for_incident(path, incident_id):
    with connect(path) as db:
        return [dict(r) for r in db.execute(
            "SELECT * FROM remediation_plans WHERE incident_id=? ORDER BY created_at DESC",
            (incident_id,),
        )]


def can_plan(incident):
    return _eligible(incident)


def propose_plan(path, incident_id, actor):
    incident = get_incident(path, incident_id)
    if incident is None or not _eligible(incident):
        raise ValueError("No eligible verified Iris drift evidence")
    if not actor or len(actor) > 80:
        raise ValueError("Invalid reviewer")
    action = ALLOWLIST[incident["model_id"]]
    digest = hashlib.sha256(_canonical_evidence(incident).encode()).hexdigest()
    plan_id = hashlib.sha256((incident_id + "|" + action + "|" + digest).encode()).hexdigest()[:24]
    now = utcnow()
    with connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        old = db.execute("SELECT id FROM remediation_plans WHERE incident_id=? AND action=?",
                         (incident_id, action)).fetchone()
        if old:
            return old["id"]
        db.execute("""INSERT INTO remediation_plans
          (id,incident_id,model_id,action,evidence_digest,status,created_at,updated_at)
          VALUES (?,?,?,?,?,?,?,?)""",
          (plan_id, incident_id, incident["model_id"], action, digest, "proposed", now, now))
        db.execute("""INSERT INTO remediation_history(plan_id,actor,event,note,created_at)
          VALUES (?,?,?,?,?)""", (plan_id, actor, "proposed", "Offline candidate only", now))
    return plan_id


def decide_plan(path, incident_id, plan_id, actor, decision, confirmation):
    if decision not in ("approve", "reject"):
        raise ValueError("Unknown plan decision")
    if decision == "approve" and confirmation != "sandbox-only":
        raise ValueError("Explicit action-scoped confirmation required")
    now = utcnow()
    with connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("""SELECT status,action FROM remediation_plans
            WHERE id=? AND incident_id=?""", (plan_id, incident_id)).fetchone()
        if row is None or row["status"] != "proposed" or row["action"] != ACTION:
            raise ValueError("Plan absent or already decided")
        updated = "approved" if decision == "approve" else "rejected"
        db.execute("""UPDATE remediation_plans SET status=?, approved_by=?, approved_at=?,updated_at=?
            WHERE id=? AND status='proposed'""",
            (updated, actor, now if decision == "approve" else None, now, plan_id))
        db.execute("""INSERT INTO remediation_history(plan_id,actor,event,note,created_at)
            VALUES (?,?,?,?,?)""",
            (plan_id, actor, updated, "No production deployment permitted", now))


def claim_approved_plan(path, plan_id, actor="offline-runner"):
    """Atomically claim one approved, immutable plan (no replay)."""
    with connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM remediation_plans WHERE id=?", (plan_id,)).fetchone()
        if row is None or row["status"] != "approved" or row["action"] != ACTION:
            raise ValueError("No unused, scoped approval for this plan")
        incident = get_incident(path, row["incident_id"])
        if incident is None or not _eligible(incident):
            raise ValueError("Evidence no longer eligible")
        digest = hashlib.sha256(_canonical_evidence(incident).encode()).hexdigest()
        if digest != row["evidence_digest"]:
            raise ValueError("Evidence changed after plan creation")
        now = utcnow()
        changed = db.execute("""UPDATE remediation_plans SET status='running',updated_at=?
            WHERE id=? AND status='approved'""", (now, plan_id))
        if changed.rowcount != 1:
            raise ValueError("Approval already consumed")
        db.execute("""INSERT INTO remediation_history(plan_id,actor,event,note,created_at)
            VALUES (?,?,?,?,?)""", (plan_id, actor, "running", "Offline evaluation started", now))
    return dict(row)


def finalize_plan(path, plan_id, outcome, result, actor="offline-runner"):
    if outcome not in ("candidate_ready", "candidate_rejected", "failed"):
        raise ValueError("Invalid outcome")
    payload = json.dumps(result, allow_nan=False)
    if len(payload) > 16000:
        raise ValueError("Result too large")
    now = utcnow()
    with connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        update = db.execute("""UPDATE remediation_plans SET status=?, result_json=?, updated_at=?
            WHERE id=? AND status='running'""", (outcome, payload, now, plan_id))
        if update.rowcount != 1:
            raise ValueError("Plan is not running")
        db.execute("""INSERT INTO remediation_history(plan_id,actor,event,note,created_at)
            VALUES (?,?,?,?,?)""",
            (plan_id, actor, outcome, "No serving-model changes", now))
