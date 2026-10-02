"""独立worker入口. 不监听HTTP, 不依赖接单进程内的闭包或队列."""

import asyncio
import logging
import signal
import sys
import time
from pathlib import Path
from typing import cast

from agentscope_platform.api.app import Container, create_app
from agentscope_platform.core.config import get_settings
from agentscope_platform.infrastructure.async_worker import ReadOnlyTaskWorker
from agentscope_platform.infrastructure.http.async_task_client import HttpAsyncTaskClient


async def serve() -> None:
    settings = get_settings()
    if settings.async_task_role != "worker":
        raise ValueError("standalone worker requires ASYNC_TASK_ROLE=worker")
    app = create_app(settings)
    container = cast(Container, app.state.container)
    gateway = container.async_task_manager.gateway
    if not isinstance(gateway, HttpAsyncTaskClient):
        raise ValueError("standalone worker requires central HTTP task gateway")
    worker = ReadOnlyTaskWorker(container, gateway)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    async with app.router.lifespan_context(app):
        while not stop.is_set():
            try:
                await worker.poll_once()
                # 仅成功访问中心队列后更新健康, 不能用进程存活掩盖长期分派失败.
                await asyncio.to_thread(HEALTH_FILE.write_text, str(time.time()), encoding="ascii")
            except Exception:
                # 不记录包含任务输入或临时凭据的异常对象. 未领取/未完成的任务由租约恢复.
                logging.getLogger(__name__).warning("durable worker poll failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=settings.async_task_poll_seconds)
            except TimeoutError:
                # 轮询间隔正常结束, 下一轮再次检查停止信号和中心队列.
                continue


HEALTH_FILE = Path("/tmp/agentscope-readonly-worker-health")


def healthy() -> bool:
    try:
        age = time.time() - float(HEALTH_FILE.read_text(encoding="ascii"))
        return 0 <= age <= 90
    except (OSError, ValueError):
        return False


def main() -> None:
    if sys.argv[1:] == ["--health"]:
        raise SystemExit(0 if healthy() else 1)
    asyncio.run(serve())


if __name__ == "__main__":
    main()
