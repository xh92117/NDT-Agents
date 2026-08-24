"""Start the local ASGI service with validated settings."""

from __future__ import annotations

import uvicorn

from ndt_agents.runtime.app import create_app
from ndt_agents.runtime.config import AppSettings


def main() -> None:
    """Run the service without Uvicorn's separate unstructured log configuration."""

    settings = AppSettings.from_environment()
    app = create_app(settings)
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_config=None,
        access_log=False,
    )


if __name__ == "__main__":
    main()
