"""Each check exposes `async def run(ctx, **opts) -> Result` and `def render(result)`.

A `Result` is plain data (dict-shaped) so the HTML and JSON reports can reuse it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Result:
    name: str
    ok: bool | None  # None = not applicable / skipped
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    started: float = 0.0
    finished: float = 0.0

    @property
    def duration_s(self) -> float:
        return max(0.0, self.finished - self.started)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "summary": self.summary,
            "duration_s": round(self.duration_s, 3),
            "data": self.data,
        }
