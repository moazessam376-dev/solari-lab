"""`solab`: the command line."""

from __future__ import annotations

import asyncio
import json
import sys
import webbrowser
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

import typer
from rich.panel import Panel
from rich.rule import Rule

from . import __version__
from .checks import Result, bench, cost, doctor, isolation, proxy, sessions
from .client import SolariError
from .context import Context
from .theme import WORDMARK, badge, console, err_console

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode="rich",
    help="Diagnostics, benchmarks and cost tracking for your Solari account.",
)
state: dict[str, Any] = {"ctx": None, "json": False}


def _ctx() -> Context:
    return state["ctx"]


def _run(
    coro_fn: Callable[..., Coroutine[Any, Any, Result]],
    render: Callable[[Result], None],
    title: str,
    **kw: Any,
) -> Result:
    ctx = _ctx()

    async def go() -> Result:
        try:
            return await coro_fn(ctx, **kw)
        finally:
            await ctx.close()

    if not state["json"]:
        console.print(
            Rule(
                f"{WORDMARK} [muted]{title}[/muted]" + ("  [warn]dry run[/warn]" if ctx.dry_run else ""),
                style="rule.line",
                align="left",
            )
        )
    try:
        result = asyncio.run(go())
    except SolariError as err:
        err_console.print(f"[fail]error[/fail] {err}")
        raise typer.Exit(2)
    if state["json"]:
        print(json.dumps(result.as_dict(), indent=2, default=str))
    else:
        render(result)
    if result.ok is False:
        raise typer.Exit(1)
    return result


@app.callback()
def main(
    api_key: str | None = typer.Option(
        None, "--api-key", envvar="SOLARI_API_KEY", help="Solari API key (or SOLARI_API_KEY)."
    ),
    region: str = typer.Option("us-west", "--region", help="Solari region."),
    base_url: str | None = typer.Option(None, "--base-url", help="Override the gateway URL."),
    plan: str | None = typer.Option(
        None, "--plan", help="Skip plan detection: free, starter, professional, enterprise."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Render with synthetic data; no API calls, no spend."
    ),
    as_json: bool = typer.Option(False, "--json", help="Print the result as JSON instead of tables."),
    version: bool = typer.Option(False, "--version", is_eager=True),
) -> None:
    if version:
        print(f"solab {__version__}")
        raise typer.Exit()
    state["ctx"] = Context(api_key=api_key, region=region, base_url=base_url, dry_run=dry_run, plan_name=plan)
    state["json"] = as_json


@app.command()
def doctor_cmd(
    no_cap: bool = typer.Option(False, "--no-cap", help="Skip the concurrency cap probe."),
) -> None:
    """Check key, plan, caps, latency and local setup."""
    _run(doctor.run, doctor.render, "doctor", probe_cap=not no_cap)


@app.command()
def bench_cmd(
    n: int = typer.Option(10, "--n", min=1, max=200, help="Number of session lifecycles."),
    concurrency: int = typer.Option(1, "--concurrency", min=1, max=150),
    stealth: bool = typer.Option(False, "--stealth"),
    url: str = typer.Option("https://example.com", "--url"),
    replay: bool = typer.Option(False, "--replay", help="Also record and time replay availability."),
) -> None:
    """Time create, connect, navigate, release (and replay) over N sessions."""
    _run(
        bench.run,
        bench.render,
        "bench",
        n=n,
        concurrency=concurrency,
        stealth=stealth,
        url=url,
        replay=replay,
    )


@app.command()
def isolation_cmd(
    tries: int = typer.Option(4, "--tries", min=1, max=20, help="Reader sessions to create."),
    wipe: bool = typer.Option(
        False, "--wipe", help="Wipe cookies and storage over CDP before reading (the client-side fix)."
    ),
) -> None:
    """Does a new session inherit the previous session's cookies and storage?"""
    _run(isolation.run, isolation.render, "isolation", tries=tries, wipe=wipe)


@app.command()
def proxy_cmd(
    countries: str = typer.Option("us,gb", "--countries", help="Comma-separated ISO codes."),
    tiers: str = typer.Option(
        "residential,static", "--tiers", help="Comma-separated: residential, static, mobile."
    ),
) -> None:
    """Does each proxy tier actually route to the requested country? (needs a paid plan)"""
    _run(
        proxy.run,
        proxy.render,
        "proxy",
        countries=[c.strip() for c in countries.split(",") if c.strip()],
        tiers=[t.strip() for t in tiers.split(",") if t.strip()],
    )


@app.command()
def sessions_cmd(
    stale: int = typer.Option(
        30, "--stale", help="Minutes after which an open browser session counts as stale."
    ),
    kill_stale: bool = typer.Option(False, "--kill-stale", help="Release stale browser sessions."),
) -> None:
    """Open sessions from the ledger and live sandboxes from the API."""
    _run(sessions.run, sessions.render, "sessions", stale_minutes=stale, kill_stale=kill_stale)


@app.command()
def cost_cmd(since: str = typer.Option("7d", "--since", help="Window: 24h, 7d, 4w.")) -> None:
    """Estimated spend from the ledger and the rate card."""
    _run(cost.run, cost.render, "cost", since=since)


@app.command()
def profiles_cmd(
    create: str | None = typer.Option(None, "--create", help="Create a profile with this name."),
    delete: str | None = typer.Option(None, "--delete", help="Delete a profile by id."),
) -> None:
    """List, create or delete stored browser profiles."""
    ctx = _ctx()

    async def go() -> list[dict[str, Any]]:
        try:
            if create:
                p = await ctx.client.create_profile(create)
                console.print(f"[pass]created[/pass] {p.get('id')} {p.get('name')}")
            if delete:
                await ctx.client.delete_profile(delete)
                console.print(f"[pass]deleted[/pass] {delete}")
            return await ctx.client.list_profiles()
        finally:
            await ctx.close()

    rows = asyncio.run(go())
    from rich.table import Table

    t = Table(header_style="table.header", border_style="table.border", pad_edge=False)
    for col in ("id", "name", "version", "size", "last used"):
        t.add_column(col)
    for p in rows:
        t.add_row(
            str(p.get("id")),
            str(p.get("name")),
            str(p.get("version", "-")),
            f"{p.get('sizeBytes', '-')} B",
            str(p.get("lastUsedAt") or "-"),
        )
    console.print(t)


@app.command()
def replay_cmd(
    session_id: str = typer.Argument(..., help="A session created with recording on."),
    out: Path | None = typer.Option(None, "--out", help="Write the NDJSON replay here."),
    open_: bool = typer.Option(False, "--open", help="Open the presigned URL in a browser."),
    show_url: bool = typer.Option(
        False, "--show-url", help="Print the full presigned URL (it carries a token)."
    ),
) -> None:
    """Fetch the replay URL (or file) for a recorded session."""
    if not session_id.strip():
        err_console.print("[fail]error[/fail] empty session id")
        raise typer.Exit(2)
    ctx = _ctx()

    async def go() -> dict[str, Any]:
        try:
            info = await ctx.client.wait_for_replay_url(session_id)
            if out:
                out.write_bytes(await ctx.client.download_replay(session_id))
            return info
        finally:
            await ctx.close()

    try:
        info = asyncio.run(go())
    except SolariError as err:
        err_console.print(f"[fail]error[/fail] {err}")
        raise typer.Exit(2)
    console.print(f"[key]url[/key] [value]{info['url']}[/value]")
    console.print(
        f"[muted]expires in {info.get('expiresInSeconds')}s, encoding {info.get('contentEncoding')}[/muted]"
    )
    if out:
        console.print(f"[pass]saved[/pass] {out}")
    if open_:
        webbrowser.open(info["url"])


@app.command()
def report_cmd(
    html: Path = typer.Option(Path("solab-report.html"), "--html"),
    json_out: Path | None = typer.Option(None, "--json-out"),
    n: int = typer.Option(10, "--n", help="Bench sessions."),
    skip_proxy: bool = typer.Option(False, "--skip-proxy"),
    skip_isolation: bool = typer.Option(False, "--skip-isolation"),
    open_: bool = typer.Option(False, "--open"),
) -> None:
    """Run doctor, bench, isolation and proxy, then write a self-contained HTML report."""
    from .report.html import write_html

    ctx = _ctx()
    results: list[Result] = []

    async def go() -> None:
        try:
            for name, fn, kw in (
                ("doctor", doctor.run, {}),
                ("bench", bench.run, {"n": n}),
                ("isolation", isolation.run, {}),
                ("proxy", proxy.run, {}),
            ):
                if (name == "proxy" and skip_proxy) or (name == "isolation" and skip_isolation):
                    continue
                if name == "proxy" and ctx.plan_name == "free":
                    console.print("[muted]proxy check skipped: free plan[/muted]")
                    continue
                console.print(Rule(f"{WORDMARK} [muted]{name}[/muted]", style="rule.line", align="left"))
                r = await fn(ctx, **kw)
                results.append(r)
                {"doctor": doctor, "bench": bench, "isolation": isolation, "proxy": proxy}[name].render(r)
                console.print()
        finally:
            await ctx.close()

    asyncio.run(go())
    write_html(html, results, ctx.environment())
    if json_out:
        json_out.write_text(json.dumps([r.as_dict() for r in results], indent=2, default=str))
    console.print(
        Panel(
            f"[pass]report written[/pass] [value]{html}[/value]"
            + (f"\n[muted]json {json_out}[/muted]" if json_out else ""),
            border_style="panel.border",
            title=f"{badge('REPORT')}",
            title_align="left",
        )
    )
    if open_:
        webbrowser.open(html.resolve().as_uri())


# typer uses the function name; strip the _cmd suffix for the user-facing names
for _c in list(app.registered_commands):
    if _c.callback and _c.callback.__name__.endswith("_cmd"):
        _c.name = _c.callback.__name__[: -len("_cmd")]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(app())
