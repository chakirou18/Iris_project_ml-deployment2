"""Local demonstration traffic only; use saved training features."""
import argparse
import random
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import joblib

from scripts.export_reference import FEATURE_NAMES, PROJECT_ROOT


def generate(scenario, count):
    if count < 1:
        raise ValueError("count must be positive")
    training = joblib.load(PROJECT_ROOT / "artifacts/processed/X_train.pkl")
    rng = random.Random(42)
    for _ in range(count):
        row = training.iloc[rng.randrange(len(training))]
        features = {name: float(row[name]) for name in FEATURE_NAMES}
        if scenario == "drift":
            features["PetalLengthCm"] += 3.0
        body = urlencode(features).encode("utf-8")
        with urlopen(Request("http://127.0.0.1:5000/", data=body), timeout=10) as response:
            if response.status != 200:
                raise RuntimeError("Failed to submit demonstration prediction")
    print("Sent", count, scenario, "local demonstration predictions")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", required=True, choices=["baseline", "drift"])
    parser.add_argument("--count", type=int, default=120)
    args = parser.parse_args()
    generate(args.scenario, args.count)
