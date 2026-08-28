"""Start the local ASGI service with validated settings."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from typing import NoReturn

import uvicorn
from fastapi import FastAPI

from ndt_agents.runtime.app import create_app
from ndt_agents.runtime.config import AppSettings
from ndt_agents.runtime.local_workbench import create_local_workbench_app


def build_application(settings: AppSettings) -> FastAPI:
    """Compose the selected application profile without contacting external services."""

    if settings.local_workbench_enabled:
        return create_local_workbench_app(settings)
    return create_app(settings)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the service without Uvicorn's separate unstructured log configuration."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    settings = AppSettings.from_environment()
    app = build_application(settings)
    if args.check:
        route_paths = (getattr(route, "path", "") for route in app.routes)
        routes = sorted(
            path
            for path in route_paths
            if path.startswith(("/health/", "/workbench", "/v1/workbench/"))
        )
        print(
            json.dumps(
                {
                    "result": "READY",
                    "local_workbench_enabled": settings.local_workbench_enabled,
                    "professional_model_delegate_enabled": (
                        settings.professional_model_delegate_enabled
                    ),
                    "routes": routes,
                }
            )
        )
        return 0
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_config=None,
        access_log=False,
    )
    return 0


def entrypoint() -> NoReturn:
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
