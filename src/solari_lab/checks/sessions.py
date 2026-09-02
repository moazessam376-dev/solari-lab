"""`solab sessions`: what is running now, and what looks leaked?"""

from __future__ import annotations

import time
from typing import Any

from .. import ledger
from ..client import SolariError
from ..context import Context
from ..rates import browser_cost
from ..theme import console, footer, kv, method, pill, table
from . import Result


def _age(seconds: float) -> str:
    if seconds < 90:
        return f"{seconds:.0f}s"
    if seconds < 5400:
        return f"{seconds / 60:.0f}m"
    return f"{seconds / 3600:.1f}h"


async def run(ctx: Context, *, stale_minutes: int = 30, kill_stale: bool = False) -> Result:
    started = time.time()
    rates = ctx.rates
    open_browsers = [s for s in ledger.sessions() if s.product == "browser" and s.open]
    stale = [s for s in open_browsers if s.duration_s > stale_minutes * 60]
    sandboxes: list[dict[str, Any]] = []
    error = None
    if not ctx.dry_run:
        try:
            sandboxes = await ctx.client.list_sandboxes()
        except SolariError as err:
            error = f"sandboxes: {err.status} {err.code or ''}"
    killed: list[str] = []
    if kill_stale and not ctx.dry_run:
        for s in stale:
            try:
                await ctx.client.release_session(s.session_id)
                ledger.record(
                    "release", product="browser", session_id=s.session_id, ok=True, killed_by="solab"
                )
                killed.append(s.session_id)
            except SolariError:
                pass
    rows = [
        {
            "id": s.session_id,
            "host": s.host,
            "age_s": s.duration_s,
            "source": s.source,
            "options": s.options,
            "cost_so_far": browser_cost(s.duration_s, rates),
            "stale": s in stale,
            "killed": s.session_id in killed,
        }
        for s in open_browsers
    ]
    data = {
        "browsers": rows,
        "sandboxes": sandboxes,
        "stale": len(stale),
        "killed": killed,
        "stale_minutes": stale_minutes,
        "error": error,
    }
    ok = not [r for r in rows if r["stale"] and not r["killed"]] and error is None
    summary = f"{len(rows)} open browser session(s) in ledger, {len(stale)} older than {stale_minutes}m, {len(sandboxes)} sandbox(es) live"
    if killed:
        summary += f", released {len(killed)}"
    return Result("sessions", ok, summary, data, started, time.time())


def render(r: Result) -> None:
    d = r.data
    if d["browsers"]:
        t = table(
            ("session", "left"),
            ("host", "left"),
            ("age", "left"),
            ("source", "left"),
            ("options", "left"),
            ("est. cost", "right"),
            ("status", "left"),
        )
        for x in d["browsers"]:
            status = (
                pill("RELEASED", "pass")
                if x["killed"]
                else (pill("STALE", "fail") if x["stale"] else "[muted]open[/muted]")
            )
            opts = ",".join(k for k, v in x["options"].items() if v) or "-"
            t.add_row(
                x["id"][-12:],
                x["host"],
                _age(x["age_s"]),
                x["source"],
                opts,
                f"${x['cost_so_far']:.4f}",
                status,
            )
        console.print(t)
    else:
        console.print("  [muted]no open browser sessions in the ledger[/muted]")
    console.print()
    if d["sandboxes"]:
        t = table(("sandbox", "left"), ("status", "left"), ("template", "left"), ("created", "left"))
        for s in d["sandboxes"]:
            t.add_row(
                str(s.get("sandboxId") or s.get("id"))[-12:],
                str(s.get("status", "?")),
                str(s.get("template", "?")),
                str(s.get("createdAt", "?")),
            )
        console.print(t)
    else:
        kv("sandboxes", "none live")
    method(
        "browser sessions come from the local ledger (Solari has no list endpoint) · sandboxes from the API"
    )
    footer("sessions", r.ok, ("TIDY", "LEAKS", "SKIP"), r.summary)
