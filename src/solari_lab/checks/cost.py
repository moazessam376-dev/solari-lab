"""`solab cost`: what did my sessions cost, estimated from the ledger and the rate card?"""

from __future__ import annotations

import time
from collections import defaultdict

from rich.table import Table

from .. import ledger
from ..context import Context
from ..rates import FETCHED, browser_cost, vm_cost
from ..theme import badge, console, verdict
from . import Result

UNITS = {"h": 3600, "d": 86400, "w": 7 * 86400, "m": 60}


def parse_since(text: str) -> float:
    n, u = float(text[:-1]), text[-1]
    return time.time() - n * UNITS[u]


async def run(ctx: Context, *, since: str = "7d") -> Result:
    started = time.time()
    rates = ctx.rates
    cutoff = parse_since(since)
    sess = [s for s in ledger.sessions() if s.created >= cutoff]
    by_day: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    by_opt: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    total = 0.0
    max_s = rates.max_session_hours * 3600
    ran_to_deadline: list[str] = []
    for s in sess:
        cost = browser_cost(s.duration_s, rates) if s.product == "browser" else vm_cost(s.duration_s, rates)
        day = time.strftime("%Y-%m-%d", time.gmtime(s.created))
        by_day[day][s.product] += cost
        by_day[day]["seconds"] += s.duration_s
        by_day[day]["sessions"] += 1
        key = (
            ",".join(k for k, v in s.options.items() if v and k not in ("bench", "isolation", "proxycheck"))
            or "plain"
        )
        by_opt[key]["cost"] += cost
        by_opt[key]["sessions"] += 1
        total += cost
        if s.open and s.duration_s >= max_s - 60:
            ran_to_deadline.append(s.session_id)
    data = {
        "since": since,
        "plan": rates.name,
        "rates_fetched": FETCHED,
        "sessions": len(sess),
        "total_usd": total,
        "by_day": {k: dict(v) for k, v in sorted(by_day.items())},
        "by_option": {k: dict(v) for k, v in by_opt.items()},
        "ran_to_deadline": ran_to_deadline,
        "open": sum(1 for s in sess if s.open),
    }
    summary = f"{len(sess)} session(s) since {since}: about ${total:.3f} on plan {rates.name}"
    return Result("cost", not ran_to_deadline, summary, data, started, time.time())


def render(r: Result) -> None:
    d = r.data
    t = Table(header_style="table.header", border_style="table.border", pad_edge=False)
    for col in ("day", "sessions", "runtime", "browser", "vm", "total"):
        t.add_column(col, justify="right" if col != "day" else "left")
    for day, v in d["by_day"].items():
        b, vm = v.get("browser", 0.0), v.get("sandbox", 0.0) + v.get("desktop", 0.0)
        t.add_row(
            day,
            f"{int(v['sessions'])}",
            f"{v['seconds'] / 60:.1f} min",
            f"${b:.4f}",
            f"${vm:.4f}",
            f"[num]${b + vm:.4f}[/num]",
        )
    console.print(t)
    if d["by_option"]:
        t2 = Table(header_style="table.header", border_style="table.border", pad_edge=False)
        t2.add_column("options")
        t2.add_column("sessions", justify="right")
        t2.add_column("cost", justify="right")
        for k, v in sorted(d["by_option"].items(), key=lambda kv: -kv[1]["cost"]):
            t2.add_row(k, f"{int(v['sessions'])}", f"${v['cost']:.4f}")
        console.print(t2)
    if d["ran_to_deadline"]:
        console.print(
            f"[fail]{len(d['ran_to_deadline'])} session(s) still open at the plan deadline: they billed the full session length[/fail]"
        )
    console.print(
        f"[muted]estimate from the local ledger × rate card fetched {d['rates_fetched']} for plan {d['plan']}; proxy GB and captcha solves are not metered here[/muted]"
    )
    console.print()
    console.print(
        f"{badge('COST')} [num]${d['total_usd']:.3f}[/num] {verdict(r.ok, 'OK', 'WASTE')} [muted]{r.summary}[/muted]"
    )
