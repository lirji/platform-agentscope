import uvicorn

from agentscope_platform.api.app import create_app
from agentscope_platform.core.config import get_settings

app = create_app()


def run() -> None:
    settings = get_settings()
    uvicorn.run(
        "agentscope_platform.main:app",
        host=settings.app_host,
        port=settings.app_port,
        log_level=settings.app_log_level.lower(),
    )


if __name__ == "__main__":
    run()
