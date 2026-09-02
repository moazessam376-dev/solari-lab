# solari-lab

`solab` is a command line lab for your [Solari](https://getsolari.com) account: does the setup work, how fast is it really, do sessions start clean, do the proxies route where they claim, what is running, and what did it cost.

Every command prints a verdict, and `solab report` turns the whole run into a single dark HTML page you can share.

## Install

```bash
pip install solari-lab
export SOLARI_API_KEY=slr_live_...
solab doctor
```

## Commands

| Command | Question it answers |
| --- | --- |
| `solab doctor` | Is the key valid, which plan, how many concurrent browsers, is stealth allowed, how far is the gateway? |
| `solab bench --n 20` | Session create, CDP connect, first navigation, release and replay timings: min, p50, p95, max, per-host spread. |
| `solab isolation` | Does a new session inherit the last session's cookies and localStorage? `--wipe` shows the client-side fix. |
| `solab proxy` | For each country and tier: the IP and country the wire actually sees, the owner, whether a normal page loads. |
| `solab sessions` | Open browser sessions from the local ledger and live sandboxes from the API. `--kill-stale` releases the leaks. |
| `solab cost --since 7d` | Spend estimated from the ledger and the published rate card, by day and by option. |
| `solab profiles` | List, create, delete stored profiles. |
| `solab replay <id>` | Replay URL or NDJSON file for a recorded session. |
| `solab report --html out.html` | doctor + bench + isolation + proxy into one page. |

Global flags: `--json` for machine output, `--dry-run` to render with synthetic data and spend nothing, `--plan` to skip plan detection.

## Why a lab

Solari's API has no endpoint that lists browser sessions, reports usage or shows spend, and the session response confirms options like a proxy without proving they took effect. `solab` fills those gaps from the client side:

- a local ledger (`~/.solari-lab/ledger.jsonl`, shared with [solari-browser-use](https://github.com/moazessam376-dev/solari-browser-use)) records every session the tools create, which is what makes `sessions` and `cost` possible;
- `bench` uses a raw websocket CDP client, so the numbers are Solari plus the network, not a framework's bootstrap;
- `isolation` and `proxy` are experiments, not status checks: they read the truth from inside the browser.

## Development

```bash
uv venv -p 3.12 && uv pip install -e ".[dev]"
.venv/bin/ruff check src tests
.venv/bin/pytest -q
solab --dry-run report --html /tmp/r.html
```

Unit tests mock the API. Live commands cost real credits: a 10-session bench is about one cent on Starter.

## License

MIT.
