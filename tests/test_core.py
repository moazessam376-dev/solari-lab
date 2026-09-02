import json
import time
from pathlib import Path

import httpx
import pytest
import respx

from solari_lab import ledger, rates, theme
from solari_lab.checks import Result, bench, cost, doctor, isolation, proxy, sessions
from solari_lab.client import SolariClient, SolariError, derive_cdp_from_ws
from solari_lab.context import Context
from solari_lab.report.html import write_html

BASE = "https://api.getsolari.com"


@pytest.fixture
def ctx(monkeypatch, tmp_path):
    monkeypatch.setenv("SOLARI_API_KEY", "slr_test")
    monkeypatch.setenv("SOLARI_LAB_LEDGER", str(tmp_path / "ledger.jsonl"))
    return Context(api_key="slr_test")


def test_theme_helpers():
    assert theme.sparkline([1, 2, 3]) == "▁▄█"
    assert theme.sparkline([]) == ""
    assert theme.sparkline([2, 2]) == "▄▄"
    assert theme.ms(0.5) == "500 ms" and theme.ms(12.3) == "12.3 s" and theme.ms(None) == "-"
    assert "PASS" in theme.verdict(True) and "FAIL" in theme.verdict(False) and "SKIP" in theme.verdict(None)


def test_rates_and_costs():
    p = rates.plan("starter")
    assert p.browser_hour == 0.10 and p.concurrent_browsers == 20
    assert rates.plan(None).name == "free" and rates.plan("nope").name == "free"
    assert abs(rates.browser_cost(3600, p) - 0.10) < 1e-9
    assert abs(rates.vm_cost(3600, p) - (2 * 0.035 + 2 * 0.011)) < 1e-9


def test_ledger_fold(tmp_path, monkeypatch):
    monkeypatch.setenv("SOLARI_LAB_LEDGER", str(tmp_path / "l.jsonl"))
    now = time.time()
    ledger.record("create", product="browser", session_id="h1:abc", options={"stealth": True})
    ledger.record("release", product="browser", session_id="h1:abc")
    ledger.record("create", product="browser", session_id="h2:def")
    ledger.record("noise")
    (tmp_path / "l.jsonl").open("a").write("not json\n")
    s = ledger.sessions()
    assert [x.session_id for x in s] == ["h1:abc", "h2:def"]
    assert (
        s[0].host == "h1"
        and not s[0].open
        and s[0].options == {"stealth": True}
        and s[0].source == "solari-lab"
    )
    assert s[1].open and s[1].duration_s >= 0 and s[1].created >= now - 5


def test_derive_cdp():
    assert derive_cdp_from_ws("wss://x/ws/a:b") == "wss://x/cdp/a:b"
    assert derive_cdp_from_ws("wss://x/other") == "wss://x/other"


@respx.mock
async def test_client_create_release_and_errors():
    respx.post(f"{BASE}/sessions").mock(
        return_value=httpx.Response(
            429, json={"error": "cap", "code": "ConcurrencyLimitExceeded", "plan": "free", "cap": 3}
        )
    )
    c = SolariClient("slr_test")
    with pytest.raises(SolariError) as ei:
        await c.create_session()
    assert (
        ei.value.status == 429 and ei.value.code == "ConcurrencyLimitExceeded" and ei.value.body["cap"] == 3
    )
    respx.post(f"{BASE}/sessions").mock(
        return_value=httpx.Response(
            200, json={"sessionId": "ip-1:s", "wsEndpoint": "wss://g/ws/ip-1:s", "expiresAt": "x"}
        )
    )
    s = await c.create_session(stealth=True, proxy={"country": "gb"})
    assert s.host == "ip-1" and s.cdp_endpoint == "wss://g/cdp/ip-1:s"
    respx.delete(f"{BASE}/sessions/ip-1:s").mock(return_value=httpx.Response(404, json={"error": "gone"}))
    assert await c.release_session("ip-1:s") is False
    await c.close()


@respx.mock
async def test_detect_plan_free_and_paid(ctx):
    respx.post(f"{BASE}/sessions").mock(
        return_value=httpx.Response(
            402, json={"error": "paid", "code": "FeatureRequiresPlan", "plan": "free"}
        )
    )
    assert await ctx.detect_plan() == "free"
    ctx2 = Context(api_key="slr_test")
    respx.post(f"{BASE}/sessions").mock(
        return_value=httpx.Response(200, json={"sessionId": "h:1", "wsEndpoint": "wss://g/ws/h:1"})
    )
    respx.delete(f"{BASE}/sessions/h:1").mock(return_value=httpx.Response(204))
    assert await ctx2.detect_plan() == "starter"
    await ctx.close()
    await ctx2.close()


@respx.mock
async def test_doctor_bad_key(ctx):
    respx.get(f"{BASE}/profiles").mock(return_value=httpx.Response(401, json={"error": "unauthorized"}))
    r = await doctor.run(ctx)
    assert r.ok is False and "rejected" in r.summary
    await ctx.close()


@respx.mock
async def test_doctor_cap_probe(ctx):
    respx.get(f"{BASE}/profiles").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{BASE}/sandboxes").mock(return_value=httpx.Response(200, json={"sandboxes": []}))
    respx.get(f"{BASE}/templates").mock(
        return_value=httpx.Response(200, json={"templates": [{"templateId": "base"}]})
    )
    calls = {"n": 0}

    def create(request):
        body = json.loads(request.content or b"{}") if request.content else {}
        if body.get("stealth"):
            return httpx.Response(402, json={"code": "FeatureRequiresPlan", "plan": "free"})
        calls["n"] += 1
        if calls["n"] > 4:  # 1 timed create + 3 cap sessions
            return httpx.Response(429, json={"code": "ConcurrencyLimitExceeded", "plan": "free", "cap": 3})
        return httpx.Response(
            200, json={"sessionId": f"h:{calls['n']}", "wsEndpoint": f"wss://g/ws/h:{calls['n']}"}
        )

    respx.post(f"{BASE}/sessions").mock(side_effect=create)
    respx.delete(url__regex=rf"{BASE}/sessions/.*").mock(return_value=httpx.Response(204))
    r = await doctor.run(ctx)
    assert r.ok is True and r.data["plan"] == "free" and r.data["cap"] == 3 and r.data["stealth"] is False
    names = [c["name"] for c in r.data["checks"]]
    assert "concurrency cap" in names and "cap matches pricing page" not in names
    await ctx.close()


async def test_bench_dry_run_stats(ctx):
    ctx.dry_run = True
    r = await bench.run(ctx, n=8)
    assert r.ok and r.data["phases"]["create"]["n"] == 8 and set(r.data["hosts"]) and r.data["failures"] == []
    s = bench._stats([3.0, 1.0, 2.0])
    assert s["min"] == 1.0 and s["p50"] == 2.0 and s["max"] == 3.0


def test_proxy_trace_parse():
    t = proxy.parse_trace("fl=1\nip=1.2.3.4\nloc=GB\n")
    assert t["ip"] == "1.2.3.4" and t["loc"] == "GB"
    assert proxy.parse_trace(None) == {}
    assert proxy._requested_country({"country": "us"}) == "us" and proxy._requested_country("smart") is None


async def test_isolation_and_proxy_dry_run(ctx):
    ctx.dry_run = True
    r = await isolation.run(ctx)
    assert r.ok is False and r.data["leaks"] == 1
    r2 = await isolation.run(ctx, wipe=True)
    assert r2.ok is True
    p = await proxy.run(ctx)
    assert p.ok is False and len(p.data["rows"]) == 3


@respx.mock
async def test_sessions_and_cost_from_ledger(ctx, tmp_path):
    respx.get(f"{BASE}/sandboxes").mock(
        return_value=httpx.Response(200, json={"sandboxes": [{"sandboxId": "sb1", "status": "running"}]})
    )
    old = time.time() - 3600
    path = Path(ledger.ledger_path(create=True))
    path.write_text(
        json.dumps({"ts": old, "event": "create", "product": "browser", "session_id": "h:old", "source": "t"})
        + "\n"
        + json.dumps(
            {
                "ts": old + 120,
                "event": "create",
                "product": "browser",
                "session_id": "h:new",
                "source": "t",
                "options": {"stealth": True},
            }
        )
        + "\n"
        + json.dumps({"ts": old + 180, "event": "release", "product": "browser", "session_id": "h:new"})
        + "\n"
    )
    ctx.plan_name = "starter"
    r = await sessions.run(ctx, stale_minutes=30)
    assert r.ok is False and r.data["stale"] == 1 and len(r.data["sandboxes"]) == 1
    respx.delete(f"{BASE}/sessions/h:old").mock(return_value=httpx.Response(204))
    r = await sessions.run(ctx, stale_minutes=30, kill_stale=True)
    assert r.data["killed"] == ["h:old"]
    c = await cost.run(ctx, since="24h")
    assert c.data["sessions"] == 2
    # h:old ran ~3600s then was released just now; h:new ran 60s. Both at $0.10/h.
    assert 0.10 <= c.data["total_usd"] <= 0.11
    assert c.data["by_option"]["stealth"]["sessions"] == 1
    await ctx.close()


def test_html_report(tmp_path, ctx):
    ctx.dry_run = True
    import asyncio

    results = [
        asyncio.run(doctor.run(ctx)),
        asyncio.run(bench.run(ctx, n=5)),
        asyncio.run(isolation.run(ctx)),
        asyncio.run(proxy.run(ctx)),
        Result("custom", None, "x", {"a": 1}),
    ]
    out = tmp_path / "r.html"
    write_html(out, results, ctx.environment())
    html = out.read_text()
    assert (
        "<!doctype html>" in html
        and "solab" in html
        and "LEAK" in html
        and "ROUTED" in html
        and "BROKEN" in html
    )
    assert "<script" not in html and "http://" not in html.replace("http://", "", 0)  # self-contained
