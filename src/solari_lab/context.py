"""Shared run context: client, plan detection, dry-run switch."""

from __future__ import annotations

import os
import platform
import time
from dataclasses import dataclass, field
from typing import Any

from . import __version__
from .client import SolariClient, SolariError
from .rates import PlanRates, plan


@dataclass
class Context:
    api_key: str | None = None
    region: str = "us-west"
    base_url: str | None = None
    dry_run: bool = False
    plan_name: str | None = None
    _client: SolariClient | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def client(self) -> SolariClient:
        if self._client is None:
            self._client = SolariClient(self.api_key, region=self.region, base_url=self.base_url)
        return self._client

    @property
    def rates(self) -> PlanRates:
        return plan(self.plan_name)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def detect_plan(self) -> str | None:
        """Cheapest plan probe: a stealth create is 402 on free (body has `plan`),
        200 on paid. The paid session is released immediately."""
        if self.plan_name:
            return self.plan_name
        try:
            s = await self.client.create_session(stealth=True)
        except SolariError as err:
            body = err.body if isinstance(err.body, dict) else {}
            self.plan_name = body.get("plan") or ("free" if err.code == "FeatureRequiresPlan" else None)
            return self.plan_name
        await self.client.release_session(s.id)
        self.plan_name = "starter"  # paid; exact tier is refined by the cap probe in doctor
        return self.plan_name

    def environment(self) -> dict[str, Any]:
        return {
            "solab": __version__,
            "python": platform.python_version(),
            "os": f"{platform.system()} {platform.release()} {platform.machine()}",
            "region": self.region,
            "base_url": self.base_url or "https://api.getsolari.com",
            "plan": self.plan_name,
            "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "key": (self.api_key or os.environ.get("SOLARI_API_KEY") or "")[:9] + "…",
        }
