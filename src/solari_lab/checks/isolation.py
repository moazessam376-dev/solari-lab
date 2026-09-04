"""`solab isolation`: does a new session start clean, or inherit the last one's state?"""

from __future__ import annotations

import time
from typing import Any

from .. import ledger
from ..cdp import CDP
from ..client import SolariError
from ..context import Context
from ..theme import console, footer, kv, method, pill, table
from . import Result

MARK = "solab-isolation-marker"
SET_JS = f"localStorage.setItem('{MARK}', String(Date.now())); document.cookie='{MARK}=1; path=/'; 'set'"
GET_JS = (
    f"JSON.stringify({{ls: localStorage.getItem('{MARK}'), cookie: document.cookie.includes('{MARK}=1')}})"
)
TARGET = "https://example.com"


async def _session(ctx: Context, js: str, *, wipe: bool) -> dict[str, Any]:
    s = await ctx.client.create_session()
    ledger.record("create", product="browser", session_id=s.id, host=s.host, options={"isolation": True})
    out: dict[str, Any] = {"host": s.host, "id": s.id, "value": None, "error": None}
    try:
        async with CDP(s.cdp_endpoint) as cdp:
            page = await cdp.new_page()
            if wipe:
                await cdp.wipe(page)
            await cdp.navigate(page, TARGET, settle_s=1.0)
            out["value"] = await cdp.evaluate(page, js)
    except Exception as err:  # noqa: BLE001
        out["error"] = str(err)[:120]
    finally:
        try:
            await ctx.client.release_session(s.id)
        except SolariError as err:
            out["error"] = out["error"] or f"release {err.status}"
        ledger.record("release", product="browser", session_id=s.id, ok=out["error"] is None)
    return out


async def _run(ctx: Context, *, tries: int = 4, wipe: bool = False) -> Result:
    started = time.time()
    if ctx.dry_run:
        reads = [
            {
                "host": "host-a",
                "same_host": True,
                "leaked": not wipe,
                "origin": None if wipe else "this run",
            },
            {"host": "host-b", "same_host": False, "leaked": False},
        ]
        data = {
            "writer_host": "host-a",
            "reads": reads,
            "same_host": 1,
            "leaks": 0 if wipe else 1,
            "wipe": wipe,
        }
        return Result("isolation", wipe, "dry run", data, started, time.time())
    writer = await _session(ctx, SET_JS, wipe=False)
    reads: list[dict[str, Any]] = []
    for _ in range(tries):
        r = await _session(ctx, GET_JS, wipe=wipe)
        leaked = None
        if r["value"]:
            import json

            v = json.loads(r["value"])
            leaked = bool(v.get("ls")) or bool(v.get("cookie"))
        reads.append(
            {
                "host": r["host"],
                "same_host": r["host"] == writer["host"],
                "leaked": leaked,
                "error": r["error"],
            }
        )
    same = [r for r in reads if r["same_host"]]
    leaks = [r for r in same if r["leaked"]]
    if not same:
        ok, summary = None, f"never landed on writer host {writer['host']} in {tries} tries; inconclusive"
    elif leaks:
        ok, summary = (
            False,
            f"{len(leaks)}/{len(same)} same-host sessions saw the previous session's cookies and localStorage",
        )
    else:
        ok, summary = (
            True,
            f"{len(same)} same-host session(s) started clean" + (" (with wipe)" if wipe else ""),
        )
    data = {
        "writer_host": writer["host"],
        "reads": reads,
        "same_host": len(same),
        "leaks": len(leaks),
        "wipe": wipe,
        "tries": tries,
    }
    return Result("isolation", ok, summary, data, started, time.time())


def render(r: Result) -> None:
    d = r.data
    kv(
        "writer",
        f"{d['writer_host']}   [muted]set a cookie and a localStorage key on example.com, then released[/muted]",
    )
    console.print()
    t = table(("#", "right"), ("host", "left"), ("same host", "left"), ("state seen", "left"))
    for i, x in enumerate(d["reads"], 1):
        if x.get("leaked"):
            seen = f"{pill('LEAKED', 'fail')} [muted]{x.get('origin') or ''}[/muted]"
        elif x.get("leaked") is False:
            seen = "[pass]clean[/pass]"
        else:
            seen = f"[warn]{x.get('error') or '?'}[/warn]"
        t.add_row(str(i), x["host"], "yes" if x.get("same_host") else "no", seen)
    console.print(t)
    if d.get("wipe"):
        method("readers wiped cookies and site storage over CDP before reading")
    footer("isolation", r.ok, ("CLEAN", "LEAK", "INCONCLUSIVE"), r.summary)
    if r.ok is False and not d.get("wipe"):
        console.print(
            "           [muted.dim]fix on the client: SolariBrowser(clean_start=True) · solab isolation --wipe[/muted.dim]"
        )


async def run(ctx: Context, **kw: Any) -> Result:
    if ctx.dry_run:
        return await _run(ctx, **kw)
    with console.status(
        "[muted]writing a marker, then reading it back from fresh sessions[/muted]",
        spinner="dots",
        spinner_style="accent",
    ):
        return await _run(ctx, **kw)
