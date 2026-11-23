"""Concurrency limits read from the environment.

    MM_JOB_LIMIT_PROVIDER   "claude=4,openai=8,*=4"   running jobs per model provider (default *=4)
    MM_JOB_LIMIT_WORKSPACE  "acme=6,*=2"              running jobs per workspace (default *=2, and no cap for
                                                      the local app's own workspace "local")
    MM_JOB_LIMIT_LANE       "oasis=2"                 running jobs per lane; 0 or missing = no lane limit

A job waits in the queue (it is never refused) until every limit that applies to it has room. Limits are counted
from the jobs table, so they hold across worker processes that share one database. The OASIS lane is also gated by
the live round count of the single simulation runner (see app/jobs/__init__.py).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Optional


def parse(spec: str, default: int) -> Dict[str, int]:
    out: Dict[str, int] = {"*": default}
    for part in (spec or "").split(","):
        if "=" not in part:
            continue
        key, _, val = part.partition("=")
        try:
            out[key.strip().lower() or "*"] = max(0, int(val.strip()))
        except ValueError:
            continue
    return out


@dataclass
class Limits:
    provider: Dict[str, int]
    workspace: Dict[str, int]
    lane: Dict[str, int]

    @staticmethod
    def _get(table: Dict[str, int], key: str) -> Optional[int]:
        n = table.get((key or "").lower(), table.get("*", 0))
        return n if n and n > 0 else None      # 0 = unlimited

    def provider_limit(self, provider: str) -> Optional[int]:
        return self._get(self.provider, provider) if provider else None

    def workspace_limit(self, workspace: str) -> Optional[int]:
        return self._get(self.workspace, workspace)

    def lane_limit(self, lane: str) -> Optional[int]:
        return self._get(self.lane, lane)

    def allows(self, job: dict, running: Dict[str, Dict[str, int]]) -> Optional[str]:
        """None when the job may start now; otherwise the reason it waits."""
        for kind, key, limit in (("provider", job.get("provider") or "", self.provider_limit(job.get("provider") or "")),
                                 ("workspace", job.get("workspace") or "local", self.workspace_limit(job.get("workspace") or "local")),
                                 ("lane", job.get("lane") or "default", self.lane_limit(job.get("lane") or "default"))):
            if limit is not None and running[kind].get(key, 0) >= limit:
                return f"waiting: {kind} {key} has {limit} job(s) running"
        return None

    def to_dict(self) -> dict:
        return {"provider": self.provider, "workspace": self.workspace, "lane": self.lane}


def from_env() -> Limits:
    return Limits(
        provider=parse(os.environ.get("MM_JOB_LIMIT_PROVIDER", ""), 4),
        # the local app's single workspace is held only by the provider limit unless the variable says otherwise
        workspace=parse(os.environ.get("MM_JOB_LIMIT_WORKSPACE") or "local=0", 2),
        lane=parse(os.environ.get("MM_JOB_LIMIT_LANE", ""), 0),
    )
