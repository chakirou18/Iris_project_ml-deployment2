"""Create a reviewable incident with the read-only phase-3 LangGraph workflow."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, default=Path("data/reports/iris_drift_summary.json"))
    parser.add_argument("--output", type=Path, default=Path("data/reports/iris_review_ready.json"))
    args = parser.parse_args()
    # Import lazily so the web app has no runtime dependency on LangGraph.
    from agents.llm_workflow import analyze

    # Missing telemetry remains explicit; never invent healthy metrics.
    def offline():
        return {"status": "partial", "metrics": {}, "unavailable": {"prometheus": "not_collected"}}

    result = analyze(args.summary, model=None, metrics_collector=offline)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Generated human-review incident:", args.output)


if __name__ == "__main__":
    main()
