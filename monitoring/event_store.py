"""Development event storage with a replaceable adapter interface.

JSON Lines is suitable for a single-process proof of concept. For replicas and
multiple worker processes, use a database or durable ingestion queue instead.
"""
import json
import threading
from pathlib import Path
from typing import Mapping, Protocol


class PredictionEventStore(Protocol):
    def append(self, event: Mapping[str, object]) -> None:
        """Persist one prediction event."""


class JsonlPredictionEventStore:
    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def append(self, event: Mapping[str, object]) -> None:
        data = json.dumps(dict(event), allow_nan=False, ensure_ascii=False)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(data + "\n")
