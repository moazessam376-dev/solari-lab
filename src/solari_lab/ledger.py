"""Local ledger of Solari sessions (JSONL), shared with `solari-browser-use`.

One line per event: `{"ts": epoch, "event": "create"|"release", "product":
"browser"|"sandbox"|"desktop", "session_id": ..., ...}`. `solab` writes its own
sessions here and reads everything back for `sessions` and `cost`.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_DIR = Path.home() / ".solari-lab"
DEFAULT_FILE = DEFAULT_DIR / "ledger.jsonl"


def ledger_path(create: bool = False) -> Path:
    env = os.environ.get("SOLARI_LAB_LEDGER")
    path = Path(env).expanduser() if env else DEFAULT_FILE
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)
    return path


def record(event: str, **fields: Any) -> None:
    line = {"ts": time.time(), "event": event, "source": "solari-lab", **fields}
    path = ledger_path(create=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, separators=(",", ":")) + "\n")


def read() -> list[dict[str, Any]]:
    path = ledger_path()
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


@dataclass
class Session:
    session_id: str
    product: str
    created: float
    released: float | None = None
    host: str | None = None
    options: dict[str, Any] = field(default_factory=dict)
    source: str = ""
    expires_at: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_s(self) -> float:
        end = self.released if self.released is not None else time.time()
        return max(0.0, end - self.created)

    @property
    def open(self) -> bool:
        return self.released is None


def sessions(rows: Iterable[dict[str, Any]] | None = None) -> list[Session]:
    """Fold create/release events into sessions, oldest first."""
    rows = list(rows) if rows is not None else read()
    by_id: dict[str, Session] = {}
    for r in sorted(rows, key=lambda r: r.get("ts", 0)):
        sid = r.get("session_id")
        if not sid:
            continue
        if r.get("event") == "create":
            by_id[sid] = Session(
                session_id=sid,
                product=r.get("product", "browser"),
                created=float(r.get("ts", 0)),
                host=r.get("host") or sid.split(":", 1)[0],
                options=r.get("options") or {},
                source=r.get("source", ""),
                expires_at=r.get("expires_at"),
                extra={
                    k: v
                    for k, v in r.items()
                    if k
                    not in ("ts", "event", "product", "session_id", "host", "options", "source", "expires_at")
                },
            )
        elif r.get("event") == "release" and sid in by_id:
            by_id[sid].released = float(r.get("ts", 0))
    return list(by_id.values())
