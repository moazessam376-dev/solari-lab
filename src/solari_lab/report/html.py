"""Single-file dark HTML report from check results. No external assets."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from ..checks import Result
from ..theme import ms

CSS = """
:root{--bg:#0b0b0c;--panel:#141416;--line:#26262a;--fg:#e8e6e1;--muted:#8a8a8a;--dim:#4a4a4a;--accent:#ff7a1a;--green:#38d16a;--red:#ff4d4f;--yellow:#f5c542}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif}
main{max-width:1080px;margin:0 auto;padding:48px 24px 80px}
header{display:flex;align-items:baseline;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:8px}
.brand{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:22px;letter-spacing:.02em}.brand b{color:var(--accent);font-weight:600}
.meta{color:var(--muted);font-family:ui-monospace,Menlo,monospace;font-size:12px}
h1{font-size:28px;margin:24px 0 4px;font-weight:650}.sub{color:var(--muted);margin:0 0 28px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin:0 0 28px}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.tile .k{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.08em}.tile .v{font-size:22px;font-weight:650;margin-top:4px;font-variant-numeric:tabular-nums}
section{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:20px 22px;margin:0 0 18px}
section h2{margin:0 0 4px;font-size:16px;display:flex;align-items:center;gap:10px}.badge{font-family:ui-monospace,Menlo,monospace;font-size:11px;letter-spacing:.1em;padding:3px 8px;border-radius:4px;background:var(--accent);color:#111}
.v{font-family:ui-monospace,Menlo,monospace;font-size:11px;letter-spacing:.1em;padding:3px 8px;border-radius:4px;color:#111}.pass{background:var(--green)}.fail{background:var(--red)}.skip{background:var(--yellow)}
.summary{color:var(--muted);margin:0 0 14px}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums;font-size:14px}th{color:var(--muted);font-weight:500;text-align:left;font-size:12px;letter-spacing:.06em;text-transform:uppercase;padding:8px 10px;border-bottom:1px solid var(--line)}
td{padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}tr:last-child td{border-bottom:0}td.n{text-align:right;font-family:ui-monospace,Menlo,monospace}
.ok{color:var(--green)}.bad{color:var(--red)}.warn{color:var(--yellow)}.mono{font-family:ui-monospace,Menlo,monospace;font-size:13px}
.spark{color:var(--accent);font-family:ui-monospace,Menlo,monospace;letter-spacing:1px}
.method{color:var(--muted);font-size:12px;margin-top:12px}.wrap{overflow-x:auto}
footer{color:var(--dim);font-size:12px;margin-top:32px;font-family:ui-monospace,Menlo,monospace}
@media (max-width:640px){main{padding:28px 14px}h1{font-size:22px}}
"""

BARS = "▁▂▃▄▅▆▇█"


def _spark(vals: list[float | None]) -> str:
    v = [x for x in vals if x is not None]
    if not v:
        return ""
    lo, hi = min(v), max(v)
    return "".join(BARS[3] if hi == lo else BARS[min(7, int((x - lo) / (hi - lo) * 7.999))] for x in v)


def e(x: Any) -> str:
    return html.escape("" if x is None else str(x))


def _verdict(ok: bool | None, yes: str, no: str, none: str = "SKIP") -> str:
    if ok is None:
        return f'<span class="v skip">{none}</span>'
    return f'<span class="v {"pass" if ok else "fail"}">{yes if ok else no}</span>'


def _doctor(r: Result) -> str:
    rows = "".join(
        f"<tr><td>{'<span class=ok>ok</span>' if c['ok'] else ('<span class=warn>skip</span>' if c['ok'] is None else '<span class=bad>fail</span>')}</td><td>{e(c['name'])}</td><td>{e(c['detail'])}</td></tr>"
        for c in r.data.get("checks", [])
    )
    return f"<div class=wrap><table><tr><th></th><th>check</th><th>detail</th></tr>{rows}</table></div>"


def _bench(r: Result) -> str:
    d = r.data
    rows = "".join(
        f"<tr><td>{e(p)}</td><td class=n>{e(ms(s['min']))}</td><td class=n><b>{e(ms(s['p50']))}</b></td><td class=n>{e(ms(s['p95']))}</td><td class=n>{e(ms(s['max']))}</td><td class=n>{s['n']}</td><td class=spark>{_spark(d['series'][p])}</td></tr>"
        for p, s in d["phases"].items()
    )
    hosts = ", ".join(f"{e(h)} ×{c}" for h, c in d["hosts"].items()) or "-"
    fails = (
        f"<p class=bad>{len(d['failures'])} failure(s): {e('; '.join(d['failures'][:5]))}</p>"
        if d["failures"]
        else ""
    )
    env = d.get("env", {})
    return (
        f"<div class=wrap><table><tr><th>phase</th><th>min</th><th>p50</th><th>p95</th><th>max</th><th>n</th><th>trend</th></tr>{rows}</table></div>"
        f"<p class=method>hosts: {hosts}</p>{fails}"
        f"<p class=method>method: {d['n']} lifecycles, concurrency {d['concurrency']}, stealth {'on' if d['stealth'] else 'off'}, target {e(d['url'])}, raw CDP over websocket, {e(env.get('os'))}, region {e(env.get('region'))}, plan {e(env.get('plan') or '?')}, {e(env.get('time'))}, wall {d['wall_s']:.1f}s</p>"
    )


def _isolation(r: Result) -> str:
    d = r.data
    rows = "".join(
        f"<tr><td class=n>{i}</td><td class=mono>{e(x['host'])}</td><td>{'yes' if x.get('same_host') else 'no'}</td><td>{'<span class=bad>LEAKED</span> <span class=mono>' + e(x.get('origin') or '') + '</span>' if x.get('leaked') else ('<span class=ok>clean</span>' if x.get('leaked') is False else '<span class=warn>' + e(x.get('error') or '?') + '</span>')}</td></tr>"
        for i, x in enumerate(d["reads"], 1)
    )
    return (
        f"<p class=method>writer session on <span class=mono>{e(d['writer_host'])}</span> set a cookie and a localStorage key on example.com and was released; readers below were created afterwards{' and wiped cookies and storage over CDP before reading' if d.get('wipe') else ''}.</p>"
        f"<div class=wrap><table><tr><th>#</th><th>host</th><th>same host</th><th>state seen</th></tr>{rows}</table></div>"
    )


def _proxy(r: Result) -> str:
    d = r.data
    base = d.get("baseline_ip")

    def v(x: dict[str, Any]) -> str:
        if x["ok"] is None:
            return "<span class=mono>baseline</span>"
        if x["ok"]:
            return "<span class=ok>ROUTED</span>"
        if x.get("routed") and x.get("geo") is False:
            return "<span class=bad>WRONG COUNTRY</span>"
        if x.get("ip") and x.get("ip") == base:
            return "<span class=bad>NOT PROXIED</span>"
        return "<span class=bad>NO ROUTE</span>"

    rows = "".join(
        f"<tr><td>{e(x['label'])}</td><td>{e(((x.get('resolved') or {}).get('country', '') + ' ' + (x.get('resolved') or {}).get('tier', '')).strip() or '-')}</td><td class=mono>{e(x.get('ip') or '-')}</td><td>{e(x.get('loc') or '-')}</td><td>{e(x.get('org') or '-')}</td><td>{'<span class=ok>loaded</span>' if x.get('page') else ('<span class=bad>failed</span>' if x.get('page') is False else '-')}</td><td>{v(x)}</td></tr>"
        for x in d["rows"]
    )
    return (
        f"<div class=wrap><table><tr><th>requested</th><th>gateway confirmed</th><th>egress ip</th><th>loc</th><th>owner</th><th>example.com</th><th>verdict</th></tr>{rows}</table></div>"
        "<p class=method>egress read from cloudflare.com/cdn-cgi/trace inside the session; owner from ipinfo.io; baseline is a stealth session with no proxy.</p>"
    )


RENDER = {"doctor": _doctor, "bench": _bench, "isolation": _isolation, "proxy": _proxy}
LABELS = {
    "doctor": ("HEALTHY", "PROBLEMS"),
    "bench": ("CLEAN", "FAILURES"),
    "isolation": ("CLEAN", "LEAK", "INCONCLUSIVE"),
    "proxy": ("ROUTED", "BROKEN"),
}


def write_html(path: Path, results: list[Result], env: dict[str, Any]) -> None:
    tiles = []
    for r in results:
        if r.name == "bench" and r.data.get("phases", {}).get("create"):
            tiles.append(("create p50", ms(r.data["phases"]["create"]["p50"])))
            if "connect" in r.data["phases"]:
                tiles.append(("cdp connect p50", ms(r.data["phases"]["connect"]["p50"])))
        if r.name == "doctor":
            tiles.append(("plan", str(r.data.get("plan") or "?")))
            tiles.append(("concurrent browsers", str(r.data.get("cap", "?"))))
        if r.name == "isolation":
            tiles.append(("sessions start clean", {True: "yes", False: "no", None: "n/a"}[r.ok]))
        if r.name == "proxy":
            rows = [x for x in r.data["rows"] if x["ok"] is not None]
            tiles.append(("proxy tiers routing", f"{sum(1 for x in rows if x['ok'])}/{len(rows)}"))
    tiles_html = "".join(
        f"<div class=tile><div class=k>{e(k)}</div><div class=v>{e(v)}</div></div>" for k, v in tiles
    )
    sections = []
    for r in results:
        labels = LABELS.get(r.name, ("PASS", "FAIL"))
        body = RENDER.get(r.name, lambda x: f"<pre>{e(json.dumps(x.data, indent=2, default=str))}</pre>")(r)
        sections.append(
            f"<section><h2><span class=badge>{e(r.name.upper())}</span>{_verdict(r.ok, labels[0], labels[1], labels[2] if len(labels) > 2 else 'SKIP')}</h2>"
            f"<p class=summary>{e(r.summary)} · {r.duration_s:.1f}s</p>{body}</section>"
        )
    doc = f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>solab report · {e(env.get("time"))}</title><style>{CSS}</style></head>
<body><main><header><div class=brand><b>sol</b>ab</div><div class=meta>{e(env.get("time"))} · region {e(env.get("region"))} · plan {e(env.get("plan") or "?")} · key {e(env.get("key"))}</div></header>
<h1>Solari account report</h1><p class=sub>Measured from the client, against the live API. Every number below is reproducible with <span class=mono>solab report</span>.</p>
<div class=grid>{tiles_html}</div>{"".join(sections)}
<footer>generated by solari-lab {e(env.get("solab"))} · python {e(env.get("python"))} · {e(env.get("os"))}</footer></main></body></html>"""
    path.write_text(doc, encoding="utf-8")
