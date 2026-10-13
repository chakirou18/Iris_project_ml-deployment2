"""Poll fixed local telemetry endpoints and synchronize real monitoring incidents.

No browser uploads, remote callbacks, arbitrary PromQL or execution tools.
The first event in each continuous episode becomes one reviewable incident;
later polls refresh its monitoring state without rewriting approved evidence.
"""
import argparse
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

from agents.llm_workflow import analyze
from agents.read_only_tools import load_evidently_summary
from review.store import import_incident, init_db, get_incident, connect

LOG = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
PROM_ALERTS_URL = "http://prometheus:9090/api/v1/alerts"
ALERT_RULES = {
    "IrisServiceDown": ("service_unavailable", "critical",
        "Service Iris indisponible selon Prometheus.",
        "Vérifier le service, ses journaux et les sondes de disponibilité."),
    "IrisDriftEvaluatorDown": ("monitoring_unavailable", "critical",
        "L'évaluateur Evidently ne répond plus.",
        "Vérifier le processus Evidently et ses métriques."),
    "IrisDriftEvaluationFailed": ("monitoring_failed", "warning",
        "Une analyse Evidently s'est terminée en erreur.",
        "Vérifier les données d'entrée et les journaux de l'évaluateur."),
    "IrisPredictionErrorsHigh": ("prediction_errors", "warning",
        "Taux d'erreurs de prédiction anormal.",
        "Contrôler la validation des entrées et les journaux Flask."),
    "IrisPredictionLatencyHigh": ("prediction_latency", "warning",
        "Latence de prédiction excessive.",
        "Contrôler la charge, la saturation et les temps de traitement."),
}
DRIFT_KEY = "evidently:iris-classifier:data_drift"


def checked_timestamp(value, now=None):
    """Accept only recent, timezone-aware completed reports (5-minute freshness)."""
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("Invalid Evidently timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Evidently timestamp has no timezone")
    seconds = parsed.timestamp()
    now = time.time() if now is None else now
    if not now - 300 <= seconds <= now + 60:
        raise ValueError("Evidently report is too old or from the future")
    return seconds


def read_alert_names(*, opener=urlopen):
    """Only allowlisted, firing Prometheus rules from a fixed internal URL."""
    with opener(PROM_ALERTS_URL, timeout=5) as response:
        if getattr(response, "status", 200) != 200:
            raise ValueError("Prometheus alerts endpoint unavailable")
        data = json.load(response)
    if not isinstance(data, dict) or data.get("status") != "success":
        raise ValueError("Invalid Prometheus response")
    alerts = data.get("data", {}).get("alerts")
    if not isinstance(alerts, list):
        raise ValueError("Missing Prometheus alert list")
    if len(alerts) > 200:
        raise ValueError("Unexpected number of alerts")
    return {item.get("labels", {}).get("alertname") for item in alerts
            if isinstance(item, dict) and isinstance(item.get("labels"), dict)
            and item.get("state") == "firing"
            and item["labels"].get("alertname") in ALERT_RULES}


def init_stream_db(path):
    init_db(path)
    with connect(path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS incident_stream (
          signal_key TEXT PRIMARY KEY, incident_id TEXT NOT NULL REFERENCES incidents(id),
          active INTEGER NOT NULL CHECK(active IN (0,1)),
          started_at TEXT NOT NULL, last_seen TEXT NOT NULL, cleared_at TEXT
        )""")


def get_stream_status(path, key):
    with connect(path) as db:
        row = db.execute("SELECT * FROM incident_stream WHERE signal_key=?", (key,)).fetchone()
        return dict(row) if row else None


def put_signal(db_path, key, incident):
    """Idempotent while an alert episode remains active, with auditable status."""
    now = datetime.now(timezone.utc).isoformat()
    with connect(db_path) as db:
        row = db.execute("SELECT incident_id,active FROM incident_stream WHERE signal_key=?",
                         (key,)).fetchone()
        if row and row["active"]:
            db.execute("UPDATE incident_stream SET last_seen=? WHERE signal_key=?", (now, key))
            return row["incident_id"], False

    # Import is deduplicated by its canonical incident+evidence, and existing
    # review/approval history is never mutated by new telemetry.
    incident_id = import_incident(db_path, incident)
    with connect(db_path) as db:
        db.execute("""INSERT INTO incident_stream(signal_key,incident_id,active,started_at,last_seen,cleared_at)
          VALUES(?,?,1,?,?,NULL)
          ON CONFLICT(signal_key) DO UPDATE SET
          incident_id=excluded.incident_id,active=1,started_at=excluded.started_at,
          last_seen=excluded.last_seen,cleared_at=NULL""",
          (key, incident_id, now, now))
    return incident_id, True


def clear_missing(db_path, prefix, active_keys):
    """Signal cleared != model repaired. Never change human decision status."""
    now = datetime.now(timezone.utc).isoformat()
    with connect(db_path) as db:
        rows = db.execute("""SELECT signal_key FROM incident_stream
            WHERE active=1 AND signal_key LIKE ?""", (prefix + "%",)).fetchall()
        for item in rows:
            key = item["signal_key"]
            if key not in active_keys:
                db.execute("""UPDATE incident_stream SET active=0,cleared_at=?
                    WHERE signal_key=? AND active=1""", (now, key))


def drift_incident(summary, diagnosis):
    """Only a validated Evidently result can create a drift incident."""
    features = diagnosis.get("affected_features", [])
    return {
        "incident": {
            "model_id": "iris-classifier", "category": "data_drift",
            "severity": "warning", "evaluated_at": summary["evaluated_at"],
        },
        "evidence": dict(summary, source="evidently_verified_summary"),
        "diagnosis": {
            "source": diagnosis.get("source", "deterministic"),
            "observation": diagnosis["observation"],
            "affected_features": features,
            "limitations": diagnosis["limitations"],
            "possible_causes": ["Input population changed", "Schema or sensor change"],
        },
        "recommendations": [
            {"id": "inspect-input", "action": "Vérifier les données et le prétraitement.",
             "requires_approval": True, "execution": "not_implemented"},
            {"id": "collect-labels", "action": "Obtenir des étiquettes réelles avant toute conclusion sur la précision.",
             "requires_approval": True, "execution": "not_implemented"},
        ],
    }


def alert_incident(alert_name, seen_at):
    category, severity, description, recommendation = ALERT_RULES[alert_name]
    return {
        "incident": {"model_id": "iris-classifier", "category": category,
                     "severity": severity, "evaluated_at": seen_at},
        "evidence": {"source": "prometheus_rule", "model_id": "iris-classifier",
                     "rule": alert_name, "observed_at": seen_at},
        "diagnosis": {"source": "deterministic", "observation": description,
                      "affected_features": [], "limitations":
                      "Une alerte de monitoring ne prouve pas, à elle seule, la cause exacte."},
        "recommendations": [
            {"id": "check-telemetry", "action": recommendation,
             "requires_approval": True, "execution": "not_implemented"},
        ],
    }


def poll_once(db_path, summary_path, *, alert_reader=read_alert_names, graph_analyzer=analyze):
    """Independent data sources: a failure does not imply a cleared signal."""
    init_stream_db(db_path)
    counts = {"created": 0, "active": 0, "sources_failed": []}
    try:
        if Path(summary_path).exists():
            summary = load_evidently_summary(summary_path)
            checked_timestamp(summary["evaluated_at"])
            if summary["drifted_features"] > 0:
                def no_prometheus():
                    return {"status": "partial", "metrics": {},
                            "unavailable": {"prometheus": "not_collected"}}
                # Existing tested LangGraph diagnostic workflow; LLM is
                # optional and disabled for safe unattended ingestion.
                result = graph_analyzer(summary_path, model=None, metrics_collector=no_prometheus)
                incident_id, created = put_signal(db_path, DRIFT_KEY, drift_incident(
                    summary, result["diagnosis"]))
                counts["created"] += int(created)
                counts["active"] += 1
            else:
                clear_missing(db_path, "evidently:", set())
        # No summary is NOT evidence that drift resolved; leave state untouched.
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        LOG.warning("Skipping untrusted/stale Evidently report: %s", type(exc).__name__)
        counts["sources_failed"].append("evidently")

    try:
        alert_names = alert_reader()
        if not isinstance(alert_names, set) or not alert_names.issubset(ALERT_RULES):
            raise ValueError("Unexpected alert names")
        now = datetime.now(timezone.utc).isoformat()
        active_keys = set()
        for name in sorted(alert_names):
            key = "prometheus:iris-classifier:" + name
            active_keys.add(key)
            _, created = put_signal(db_path, key, alert_incident(name, now))
            counts["created"] += int(created)
            counts["active"] += 1
        clear_missing(db_path, "prometheus:", active_keys)
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        LOG.warning("Prometheus alerts unavailable: %s", type(exc).__name__)
        counts["sources_failed"].append("prometheus")
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Poll only once")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    db = Path(os.getenv("REVIEW_DB_PATH", ROOT / "data" / "review.sqlite3"))
    report = Path(os.getenv("DRIFT_SUMMARY_PATH", ROOT / "data" / "reports" / "iris_drift_summary.json"))
    interval = max(15, int(os.getenv("INCIDENT_POLL_SECONDS", "30")))
    if args.once:
        print(json.dumps(poll_once(db, report)))
        return
    while True:
        LOG.info("Monitoring ingestion: %s", poll_once(db, report))
        time.sleep(interval)


if __name__ == "__main__":
    main()
