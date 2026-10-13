"""Local operator CLI for preparing and approving offline-only experiments."""
import argparse
from pathlib import Path

from remediation.store import (
    init_remediation_db, propose_plan, decide_plan, get_plan,
)

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "review.sqlite3")
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("propose")
    p.add_argument("--incident-id", required=True)
    p = commands.add_parser("decide")
    p.add_argument("--incident-id", required=True)
    p.add_argument("--plan-id", required=True)
    p.add_argument("--decision", choices=["approve", "reject"], required=True)
    p.add_argument("--confirm", default="")
    p = commands.add_parser("status")
    p.add_argument("--plan-id", required=True)
    args = parser.parse_args()
    init_remediation_db(args.db)
    if args.command == "propose":
        print(propose_plan(args.db, args.incident_id, "local-operator"))
    elif args.command == "decide":
        decide_plan(args.db, args.incident_id, args.plan_id, "local-operator",
                    args.decision, args.confirm)
        print("Decision recorded. Offline run must be started separately.")
    else:
        print(get_plan(args.db, args.plan_id))


if __name__ == "__main__":
    main()
