"""Solari rate card, copied from https://docs.getsolari.com/pricing on 2026-09-02.

Solari has no usage or billing API, so cost is estimated client-side from the
ledger using these numbers. Update `FETCHED` when you refresh them.
"""

from __future__ import annotations

from dataclasses import dataclass

FETCHED = "2026-09-02"


@dataclass(frozen=True)
class PlanRates:
    name: str
    monthly_usd: float
    credit_usd: float
    browser_hour: float
    concurrent_browsers: int
    concurrent_vms: int
    max_session_hours: float
    vcpu_hour: float
    gb_hour: float
    live_screen_hour: float
    captcha_solve: float | None
    proxy_gb: float | None
    stealth: bool


PLANS: dict[str, PlanRates] = {
    "free": PlanRates("free", 0, 3, 0.15, 3, 1, 1, 0.0525, 0.0165, 0.02, None, None, False),
    "starter": PlanRates("starter", 20, 20, 0.10, 20, 2, 5, 0.035, 0.011, 0.02, 0.01, 1.00, True),
    "professional": PlanRates(
        "professional", 200, 200, 0.07, 150, 10, 24, 0.0245, 0.0077, 0.02, 0.005, 0.10, True
    ),
    "enterprise": PlanRates(
        "enterprise", 0, 0, 0.05, 150, 50, 24 * 365, 0.0175, 0.0055, 0.02, 0.005, 0.10, True
    ),
}

# Defaults the SDKs use when you do not size a sandbox or desktop.
DEFAULT_VCPU = 2
DEFAULT_GB = 2


def plan(name: str | None) -> PlanRates:
    return PLANS.get((name or "free").lower(), PLANS["free"])


def browser_cost(seconds: float, p: PlanRates) -> float:
    return seconds / 3600 * p.browser_hour


def vm_cost(
    seconds: float, p: PlanRates, vcpu: int = DEFAULT_VCPU, gb: int = DEFAULT_GB, live: bool = False
) -> float:
    hours = seconds / 3600
    return hours * (vcpu * p.vcpu_hour + gb * p.gb_hour + (p.live_screen_hour if live else 0))
