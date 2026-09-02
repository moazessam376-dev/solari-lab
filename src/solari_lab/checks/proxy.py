"""`solab proxy`: does the egress the wire sees match the proxy the gateway confirmed?"""

from __future__ import annotations

import re
import time
from typing import Any

import httpx
from rich.table import Table

from .. import ledger
from ..cdp import CDP
from ..client import SolariError
from ..context import Context
from ..theme import badge, console, verdict
from . import Result

TRACE = "https://www.cloudflare.com/cdn-cgi/trace"
PAGE = "https://example.com"


def parse_trace(text: str | None) -> dict[str, str]:
    if not text:
        return {}
    return dict(re.findall(r"^([a-z_]+)=(.*)$", text, re.MULTILINE))


async def whois(ip: str | None) -> str:
    if not ip:
        return "-"
    try:
        async with httpx.AsyncClient(timeout=8) as h:
            r = await h.get(f"https://ipinfo.io/{ip}/json")
            j = r.json()
            return f"{j.get('org', '?')} · {j.get('city', '?')}, {j.get('country', '?')}"
    except Exception:  # noqa: BLE001
        return "?"


async def _probe(ctx: Context, *, proxy: Any, stealth: bool) -> dict[str, Any]:
    out: dict[str, Any] = {
        "proxy": proxy,
        "resolved": None,
        "ip": None,
        "loc": None,
        "tz": None,
        "page": None,
        "error": None,
        "host": None,
    }
    try:
        s = await ctx.client.create_session(stealth=stealth, proxy=proxy)
    except SolariError as err:
        out["error"] = f"create {err.status} {err.code or ''}"
        return out
    out["resolved"], out["host"] = s.proxy, s.host
    ledger.record(
        "create",
        product="browser",
        session_id=s.id,
        host=s.host,
        options={"stealth": stealth, "proxy": proxy, "proxycheck": True},
    )
    try:
        async with CDP(s.cdp_endpoint) as cdp:
            page = await cdp.new_page()
            await cdp.navigate(page, TRACE, settle_s=2.0)
            tr = parse_trace(await cdp.evaluate(page, "document.body ? document.body.innerText : ''"))
            out["ip"], out["loc"] = tr.get("ip"), tr.get("loc")
            out["tz"] = await cdp.evaluate(page, "Intl.DateTimeFormat().resolvedOptions().timeZone")
            await cdp.navigate(page, PAGE, settle_s=1.5)
            title = await cdp.evaluate(page, "document.title")
            out["page"] = bool(title and "Example" in title)
    except Exception as err:  # noqa: BLE001
        out["error"] = str(err)[:100]
    finally:
        try:
            await ctx.client.release_session(s.id)
        except SolariError:
            pass
        ledger.record("release", product="browser", session_id=s.id)
    return out


def _requested_country(proxy: Any) -> str | None:
    if isinstance(proxy, dict):
        return proxy.get("country")
    if isinstance(proxy, str) and proxy not in ("smart", "off"):
        return proxy
    return None


async def run(ctx: Context, *, countries: list[str] | None = None, tiers: list[str] | None = None) -> Result:
    started = time.time()
    countries = countries or ["us", "gb"]
    tiers = tiers or ["residential", "static"]
    if ctx.dry_run:
        rows = [
            {
                "label": "none",
                "resolved": None,
                "ip": "18.144.157.51",
                "loc": "US",
                "org": "Amazon.com, Inc. · San Jose, US",
                "routed": None,
                "geo": None,
                "page": True,
                "ok": None,
            },
            {
                "label": "gb residential",
                "resolved": {"country": "gb", "tier": "residential"},
                "ip": None,
                "loc": None,
                "org": "-",
                "routed": False,
                "geo": None,
                "page": False,
                "ok": False,
            },
            {
                "label": "gb static",
                "resolved": {"country": "gb", "tier": "static"},
                "ip": "212.102.124.86",
                "loc": "GB",
                "org": "LonConnect Ltd · London, GB",
                "routed": True,
                "geo": True,
                "page": True,
                "ok": True,
            },
        ]
        return Result(
            "proxy", False, "dry run", {"rows": rows, "baseline_ip": "18.144.157.51"}, started, time.time()
        )
    base = await _probe(ctx, proxy=None, stealth=True)
    base_ip = base["ip"]
    rows: list[dict[str, Any]] = [
        {"label": "none", **base, "org": await whois(base_ip), "routed": None, "geo": None, "ok": None}
    ]
    for c in countries:
        for tier in tiers:
            p = {"country": c, "tier": tier}
            r = await _probe(ctx, proxy=p, stealth=True)
            routed = (r["ip"] is not None and r["ip"] != base_ip) if r["ip"] or r["page"] else False
            geo = (r["loc"] or "").upper() == c.upper() if r["loc"] else None
            ok = bool(routed and geo and r["page"])
            rows.append(
                {
                    "label": f"{c} {tier}",
                    **r,
                    "org": await whois(r["ip"]),
                    "routed": routed,
                    "geo": geo,
                    "ok": ok,
                }
            )
    tested = [x for x in rows if x["ok"] is not None]
    bad = [x for x in tested if not x["ok"]]
    ok = not bad
    summary = (
        f"{len(tested) - len(bad)}/{len(tested)} proxy configurations routed to the requested country"
        if tested
        else "nothing tested"
    )
    if bad:
        summary += "; failing: " + ", ".join(x["label"] for x in bad)
    return Result(
        "proxy",
        ok,
        summary,
        {"rows": rows, "baseline_ip": base_ip, "env": ctx.environment()},
        started,
        time.time(),
    )


def render(r: Result) -> None:
    t = Table(header_style="table.header", border_style="table.border", pad_edge=False)
    for col in ("requested", "gateway confirmed", "egress ip", "loc", "owner", "page", "verdict"):
        t.add_column(col)
    for x in r.data["rows"]:
        res = x.get("resolved") or {}
        conf = f"{res.get('country', '')} {res.get('tier', '')}".strip() or "-"
        page = (
            "[pass]loaded[/pass]"
            if x.get("page")
            else ("[fail]failed[/fail]" if x.get("page") is False else "-")
        )
        if x["ok"] is None:
            v = "[muted]baseline[/muted]"
        elif x["ok"]:
            v = "[pass]ROUTED[/pass]"
        elif x.get("routed") and x.get("geo") is False:
            v = "[fail]WRONG COUNTRY[/fail]"
        elif x.get("ip") == r.data.get("baseline_ip") and x.get("ip"):
            v = "[fail]NOT PROXIED[/fail]"
        else:
            v = "[fail]NO ROUTE[/fail]"
        t.add_row(x["label"], conf, x.get("ip") or "-", x.get("loc") or "-", x.get("org") or "-", page, v)
    console.print(t)
    console.print(
        "[muted]egress read from cloudflare.com/cdn-cgi/trace inside the session; owner from ipinfo.io; baseline is a stealth session with no proxy[/muted]"
    )
    console.print()
    console.print(f"{badge('PROXY')} {verdict(r.ok, 'ROUTED', 'BROKEN')} [muted]{r.summary}[/muted]")
