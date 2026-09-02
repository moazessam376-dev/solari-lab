"""`solab bench`: session lifecycle timings measured with a raw CDP client."""

from __future__ import annotations

import asyncio
import statistics
import time
from collections import Counter
from typing import Any

from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn

from .. import ledger
from ..cdp import CDP
from ..client import SolariError
from ..context import Context
from ..theme import console, footer, kv, mark, method, ms, sparkline, table
from . import Result

PHASES = ("create", "connect", "navigate", "release", "replay")


def _stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    s = sorted(values)
    p = lambda q: s[min(len(s) - 1, int(round(q * (len(s) - 1))))]
    return {"min": s[0], "p50": statistics.median(s), "p95": p(0.95), "max": s[-1], "n": len(s)}


async def _one(ctx: Context, *, stealth: bool, url: str, replay: bool) -> dict[str, Any]:
    row: dict[str, Any] = {"phases": {}, "host": None, "error": None}
    t = time.perf_counter()
    try:
        s = await ctx.client.create_session(stealth=stealth, recording=replay)
    except SolariError as err:
        row["error"] = f"create: {err.status} {err.code or ''}"
        return row
    row["phases"]["create"] = time.perf_counter() - t
    row["host"] = s.host
    ledger.record(
        "create",
        product="browser",
        session_id=s.id,
        host=s.host,
        options={"stealth": stealth, "recording": replay, "bench": True},
        expires_at=s.expires_at,
    )
    try:
        t = time.perf_counter()
        async with CDP(s.cdp_endpoint) as cdp:
            page = await cdp.new_page()
            row["phases"]["connect"] = time.perf_counter() - t
            t = time.perf_counter()
            await cdp.navigate(page, url, settle_s=0)
            title = None
            for _ in range(40):
                title = await cdp.evaluate(page, "document.readyState === 'complete' ? document.title : null")
                if title:
                    break
                await asyncio.sleep(0.1)
            row["phases"]["navigate"] = time.perf_counter() - t
            row["title"] = title
    except Exception as err:  # noqa: BLE001
        row["error"] = f"cdp: {str(err)[:100]}"
    t = time.perf_counter()
    try:
        await ctx.client.release_session(s.id)
        row["phases"]["release"] = time.perf_counter() - t
    except SolariError as err:
        row["error"] = row["error"] or f"release: {err.status} {err.code or ''}"
    ledger.record("release", product="browser", session_id=s.id, ok=row["error"] is None)
    if replay and row["error"] is None:
        t = time.perf_counter()
        try:
            await ctx.client.wait_for_replay_url(s.id, timeout_s=60)
            row["phases"]["replay"] = time.perf_counter() - t
        except SolariError as err:
            row["error"] = f"replay: {err.status}"
    return row


async def run(
    ctx: Context,
    *,
    n: int = 10,
    concurrency: int = 1,
    stealth: bool = False,
    url: str = "https://example.com",
    replay: bool = False,
) -> Result:
    started = time.time()
    rows: list[dict[str, Any]] = []
    if ctx.dry_run:
        import random

        random.seed(7)
        for i in range(n):
            rows.append(
                {
                    "host": f"ip-10-0-1{i % 3}-1",
                    "error": None,
                    "phases": {
                        "create": random.uniform(0.2, 0.9),
                        "connect": random.uniform(0.3, 0.6),
                        "navigate": random.uniform(0.5, 0.9),
                        "release": random.uniform(0.6, 1.2),
                    },
                }
            )
    else:
        with Progress(
            TextColumn("[muted]bench[/muted]"),
            BarColumn(bar_width=30),
            TextColumn("[muted]{task.completed}/{task.total}[/muted]"),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        ) as prog:
            task = prog.add_task("bench", total=n)
            sem = asyncio.Semaphore(max(1, concurrency))

            async def guarded() -> dict[str, Any]:
                async with sem:
                    r = await _one(ctx, stealth=stealth, url=url, replay=replay)
                    prog.advance(task)
                    return r

            if concurrency > 1:
                rows = list(await asyncio.gather(*(guarded() for _ in range(n))))
            else:
                for _ in range(n):
                    rows.append(await guarded())
    wall = time.time() - started
    phases = {p: _stats([r["phases"][p] for r in rows if p in r["phases"]]) for p in PHASES}
    phases = {k: v for k, v in phases.items() if v}
    failures = [r["error"] for r in rows if r["error"]]
    hosts = Counter(r["host"] for r in rows if r["host"])
    ok = not failures
    data = {
        "n": n,
        "concurrency": concurrency,
        "stealth": stealth,
        "url": url,
        "wall_s": wall,
        "phases": phases,
        "series": {p: [r["phases"].get(p) for r in rows] for p in phases},
        "hosts": dict(hosts),
        "failures": failures,
        "env": ctx.environment(),
    }
    med = phases.get("create", {}).get("p50")
    summary = f"{n} sessions, create p50 {ms(med)}, {len(failures)} failure(s), {len(hosts)} host(s)"
    return Result("bench", ok, summary, data, started, time.time())


def render(r: Result) -> None:
    d = r.data
    t = table(
        ("", "left"),
        ("phase", "left"),
        ("min", "right"),
        ("p50", "right"),
        ("p95", "right"),
        ("max", "right"),
        ("n", "right"),
        ("trend", "left"),
    )
    for p, s in d["phases"].items():
        t.add_row(
            f"[accent]{mark('bench')}[/accent]",
            p,
            ms(s["min"]),
            f"[num]{ms(s['p50'])}[/num]",
            ms(s["p95"]),
            ms(s["max"]),
            str(s["n"]),
            f"[accent]{sparkline([v for v in d['series'][p] if v is not None])}[/accent]",
        )
    console.print(t)
    console.print()
    hosts = "   ".join(f"{h} ×{c}" for h, c in d["hosts"].items()) or "-"
    kv("hosts", hosts)
    if d["failures"]:
        console.print(
            f"  [key]FAILURES  [/key] [fail]{len(d['failures'])}[/fail] " + "; ".join(d["failures"][:5])
        )
    e = d["env"]
    method(
        f"METHOD     {d['n']} lifecycles · concurrency {d['concurrency']} · stealth {'on' if d['stealth'] else 'off'} · "
        f"{d['url']} · raw CDP over websocket · {e['os']} · {e['region']} · {e.get('plan') or '?'} · {e['time']}"
    )
    footer("bench", r.ok, ("CLEAN", "FAILURES", "SKIP"), f"{r.summary} · wall {d['wall_s']:.1f}s")
