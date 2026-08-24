"""Injectable dependency readiness checks kept separate from process liveness."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from ndt_agents.runtime.models import HealthCheck
from ndt_agents.storage.errors import StorageError


@dataclass(frozen=True, slots=True)
class DependencyProbe:
    """A named asynchronous dependency check."""

    name: str
    check: Callable[[], Awaitable[None]]

    async def evaluate(self) -> HealthCheck:
        try:
            await self.check()
        except StorageError as error:
            return HealthCheck(name=self.name, status="FAIL", error_code=error.code)
        except Exception:
            return HealthCheck(
                name=self.name,
                status="FAIL",
                error_code="DEPENDENCY_CHECK_FAILED",
            )
        return HealthCheck(name=self.name, status="PASS")
