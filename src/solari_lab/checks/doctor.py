"""`solab doctor`: does this Solari setup work, and what am I allowed to do?"""

from __future__ import annotations

import asyncio
import importlib.metadata as md
import time
from typing import Any

from rich.table import Table

from ..client import SolariError
from ..context import Context
from ..ledger import ledger_path
from ..rates import PLANS
from ..theme import badge, console, ms, verdict
from . import Result

MAX_CAP_PROBE = 25


def _pkg(name: str) -> str | None:
    try:
        return md.version(name)
    except md.PackageNotFoundError:
        return None


async def _run(ctx: Context, *, probe_cap: bool = True) -> Result:
    started = time.time()
    d: dict[str, Any] = {"checks": []}
    ok = True

    def add(name: str, passed: bool | None, detail: str) -> None:
        nonlocal ok
        d["checks"].append({"name": name, "ok": passed, "detail": detail})
        if passed is False:
            ok = False

    if ctx.dry_run:
        for name, detail in (
            ("api key", "valid (dry run)"),
            ("plan", "starter: 20 browsers, stealth allowed (dry run)"),
            ("gateway latency", "182 ms"),
            ("session create", "640 ms"),
        ):
            add(name, True, detail)
        d.update(
            {"plan": "starter", "cap": 20, "stealth": True, "packages": {}, "ledger": str(ledger_path())}
        )
        return Result("doctor", True, "dry run: setup looks fine", d, started, time.time())

    # 1. key
    t0 = time.perf_counter()
    try:
        profiles = await ctx.client.list_profiles()
        gw = time.perf_counter() - t0
        add("api key", True, f"valid, {len(profiles)} profile(s)")
        add("gateway latency", gw < 2, ms(gw))
        d["gateway_s"] = gw
    except SolariError as err:
        add("api key", False, f"rejected: {err.status} {err.code or ''}".strip())
        d["error"] = str(err)
        return Result("doctor", False, "API key rejected", d, started, time.time())

    # 2. plan via stealth probe
    plan_name = await ctx.detect_plan()
    d["plan"] = plan_name
    d["stealth"] = plan_name != "free"
    add("stealth", True if d["stealth"] else None, "allowed" if d["stealth"] else "needs a paid plan (free)")

    # 3. one timed create/release
    t0 = time.perf_counter()
    try:
        s = await ctx.client.create_session()
        create_s = time.perf_counter() - t0
        t0 = time.perf_counter()
        await ctx.client.release_session(s.id)
        release_s = time.perf_counter() - t0
        d.update({"create_s": create_s, "release_s": release_s, "host": s.host, "expires_at": s.expires_at})
        add("session create", create_s < 5, f"{ms(create_s)} on {s.host}, release {ms(release_s)}")
    except SolariError as err:
        add("session create", False, f"{err.status} {err.code or ''}: {str(err)[:80]}")

    # 4. concurrency cap
    if probe_cap:
        ids: list[str] = []
        cap: int | None = None
        try:
            for _ in range(MAX_CAP_PROBE):
                try:
                    ids.append((await ctx.client.create_session()).id)
                except SolariError as err:
                    body = err.body if isinstance(err.body, dict) else {}
                    if err.code == "ConcurrencyLimitExceeded":
                        cap = int(body.get("cap") or len(ids))
                        if body.get("plan"):
                            d["plan"] = plan_name = body["plan"]
                    break
        finally:
            await asyncio.gather(*(ctx.client.release_session(i) for i in ids), return_exceptions=True)
        d["cap"] = cap if cap is not None else f">{len(ids)}"
        expected = PLANS.get(plan_name or "", None)
        add(
            "concurrency cap",
            True,
            f"{d['cap']} concurrent browsers" + (f" (plan {plan_name})" if plan_name else ""),
        )
        if expected and cap is not None and cap != expected.concurrent_browsers:
            add(
                "cap matches pricing page",
                False,
                f"pricing says {expected.concurrent_browsers}, gateway says {cap}",
            )

    # 5. VM products reachable
    try:
        sb = await ctx.client.list_sandboxes()
        tp = await ctx.client.list_templates()
        add("sandboxes api", True, f"{len(sb)} running, {len(tp)} template(s)")
    except SolariError as err:
        add("sandboxes api", False, f"{err.status} {err.code or ''}")

    # 6. local packages and ledger
    d["packages"] = {
        n: _pkg(n)
        for n in (
            "solari-lab",
            "solari-browser-use",
            "browser-use",
            "solari-browser",
            "solari-sandbox",
            "playwright",
        )
    }
    installed = ", ".join(f"{k} {v}" for k, v in d["packages"].items() if v) or "none"
    add("local packages", True, installed)
    d["ledger"] = str(ledger_path())
    add("ledger", True, d["ledger"])

    summary = (
        f"plan {d.get('plan') or '?'}, cap {d.get('cap', '?')}, stealth {'on' if d.get('stealth') else 'off'}"
    )
    return Result("doctor", ok, summary, d, started, time.time())


def render(r: Result) -> None:
    t = Table(box=None, pad_edge=False, show_header=False, padding=(0, 2))
    t.add_column("status", width=6)
    t.add_column("check", style="key", width=22)
    t.add_column("detail", style="value")
    for c in r.data["checks"]:
        t.add_row(verdict(c["ok"], "ok", "fail", "skip"), c["name"], c["detail"])
    console.print(t)
    console.print()
    console.print(
        f"{badge('DOCTOR')} {verdict(r.ok, 'HEALTHY', 'PROBLEMS')} [muted]{r.summary} · {r.duration_s:.1f}s[/muted]"
    )


async def run(ctx: Context, **kw: Any) -> Result:
    if ctx.dry_run:
        return await _run(ctx, **kw)
    with console.status(
        "[muted]probing key, plan, caps and latency[/muted]", spinner="dots", spinner_style="accent"
    ):
        return await _run(ctx, **kw)
