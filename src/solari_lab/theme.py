"""One place for how solab looks.

Solari's own surfaces are near-black with a warm orange accent and muted
grey secondary text. Pass and fail use green and red; nothing else is colored,
so the accent stays meaningful.
"""

from __future__ import annotations

from rich.console import Console
from rich.theme import Theme

ORANGE = "#ff7a1a"
ORANGE_DIM = "#b85a16"
GREY = "#8a8a8a"
GREY_DIM = "#4a4a4a"
GREEN = "#38d16a"
RED = "#ff4d4f"
YELLOW = "#f5c542"
FG = "#e8e6e1"

THEME = Theme(
    {
        "accent": f"bold {ORANGE}",
        "accent.dim": ORANGE_DIM,
        "muted": GREY,
        "muted.dim": GREY_DIM,
        "fg": FG,
        "pass": f"bold {GREEN}",
        "fail": f"bold {RED}",
        "warn": f"bold {YELLOW}",
        "key": GREY,
        "value": FG,
        "num": f"bold {FG}",
        "rule.line": GREY_DIM,
        "table.header": f"bold {GREY}",
        "table.border": GREY_DIM,
        "panel.border": ORANGE_DIM,
        "progress.percentage": ORANGE,
        "progress.elapsed": GREY,
        "bar.complete": ORANGE,
        "bar.finished": ORANGE,
        "bar.pulse": ORANGE_DIM,
    }
)

console = Console(theme=THEME, highlight=False)
err_console = Console(theme=THEME, highlight=False, stderr=True)

WORDMARK = "[accent]sol[/accent][fg]ab[/fg]"


def verdict(ok: bool | None, text_ok: str = "PASS", text_fail: str = "FAIL", text_none: str = "SKIP") -> str:
    if ok is None:
        return f"[warn] {text_none} [/warn]"
    return f"[pass] {text_ok} [/pass]" if ok else f"[fail] {text_fail} [/fail]"


def badge(text: str, style: str = "accent") -> str:
    return f"[{style}] {text} [/{style}]"


def sparkline(values: list[float]) -> str:
    """Eight-level unicode sparkline, empty string for no data."""
    bars = "▁▂▃▄▅▆▇█"
    if not values:
        return ""
    lo, hi = min(values), max(values)
    if hi == lo:
        return bars[3] * len(values)
    return "".join(bars[min(7, int((v - lo) / (hi - lo) * 7.999))] for v in values)


def ms(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    return f"{seconds * 1000:,.0f} ms" if seconds < 10 else f"{seconds:,.1f} s"
