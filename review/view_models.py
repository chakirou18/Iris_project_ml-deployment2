"""Human-readable presentation helpers for the local reviewer interface.

These are pure functions: display formatting must not change approval semantics.
"""
from datetime import datetime


STATUS = {
    "approve": ("Avis favorable", "approved"),
    "reject": ("Refusé", "rejected"),
    "request_information": ("Informations demandées", "needs-info"),
    None: ("À examiner", "pending"),
}
SEVERITY = {
    "warning": ("Attention", "warning"),
    "critical": ("Critique", "rejected"),
    "info": ("Information", "informational"),
}
CATEGORY = {
    "data_drift": "Dérive des données",
    "no_drift_detected": "Aucune dérive détectée",
    "service_unavailable": "Service indisponible",
    "monitoring_unavailable": "Monitoring indisponible",
    "monitoring_failed": "Analyse échouée",
    "prediction_errors": "Erreurs de prédiction",
    "prediction_latency": "Latence excessive",
}
DECISION = {
    "approve": "Avis favorable",
    "reject": "Refusé",
    "request_information": "Informations demandées",
}


def formatted_date(value):
    """Format an ISO datetime without silently changing its time zone."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.strftime("%d/%m/%Y à %H:%M") + (
            " UTC" if parsed.utcoffset() is not None and parsed.utcoffset().total_seconds() == 0 else ""
        )
    except (ValueError, AttributeError, TypeError):
        return str(value or "Date indisponible")[:48]


def decorate_incident(item):
    result = dict(item)
    label, css = STATUS.get(result.get("last_decision"), STATUS[None])
    result.update(
        status_label=label, status_css=css,
        severity_label=SEVERITY.get(result.get("severity"), ("Autre", "informational"))[0],
        severity_css=SEVERITY.get(result.get("severity"), ("Autre", "informational"))[1],
        category_label=CATEGORY.get(result.get("category"), "Autre incident"),
        date_display=formatted_date(result.get("created_at")),
        short_id=str(result.get("id", ""))[:8].upper(),
    )
    return result


def decorate_detail(incident):
    item = dict(incident)
    decisions = [dict(d) for d in item.get("decisions", [])]
    item["decisions"] = [
        dict(d, label=DECISION.get(d.get("decision"), "Décision"),
             css=STATUS.get(d.get("decision"), STATUS[None])[1],
             date_display=formatted_date(d.get("created_at")))
        for d in decisions
    ]
    last = decisions[-1]["decision"] if decisions else None
    item.update(
        **decorate_incident(dict(item, last_decision=last)),
        is_demo=item.get("evidence", {}).get("source") == "synthetic_local_preview",
        can_review=(
            item.get("category") not in ("no_drift_detected", None)
            and last not in ("approve", "reject")
        ),
    )
    # Explicitly avoid conflating a recorded opinion with deployment permission.
    return item


def counts(incidents):
    decisions = [item.get("last_decision") for item in incidents]
    return {
        "total": len(decisions),
        "pending": sum(x in (None, "request_information") for x in decisions),
        "approved": decisions.count("approve"),
        "rejected": decisions.count("reject"),
    }


def filter_incidents(incidents, query="", status="all"):
    query = (query or "").strip().casefold()[:80]
    if status not in ("all", "pending", "approved", "rejected"):
        status = "all"
    filtered = []
    for incident in incidents:
        decision = incident.get("last_decision")
        category = incident.get("category") not in ("no_drift_detected", None)
        if status == "pending" and (decision in ("approve", "reject") or not category):
            continue
        if status == "approved" and decision != "approve":
            continue
        if status == "rejected" and decision != "reject":
            continue
        if query and query not in " ".join([
            str(incident.get("model_id", "")),
            str(incident.get("id", "")),
            str(incident.get("category", "")),
        ]).casefold():
            continue
        filtered.append(decorate_incident(incident))
    return filtered
