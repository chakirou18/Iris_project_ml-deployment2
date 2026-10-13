"""CLI-only guarded incident import. Never accept arbitrary upload in the web UI."""
import argparse
import json
from pathlib import Path

from review.store import init_db, import_incident


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/reports/iris_incident.json"))
    parser.add_argument("--db", type=Path, default=Path("data/review.sqlite3"))
    args = parser.parse_args()
    if args.input.stat().st_size > 32000:
        raise ValueError("Incident file too large")
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    init_db(args.db)
    print("Imported incident ID:", import_incident(args.db, payload))


if __name__ == "__main__":
    main()
