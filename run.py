"""Startup script for NetEase Cloud Music API."""

import asyncio
import sys

import uvicorn
from app.config import HOST, PORT


def _configure_windows_event_loop() -> None:
    if sys.platform != "win32":
        return
    try:
        policy = asyncio.get_event_loop_policy()
        if isinstance(policy, asyncio.WindowsProactorEventLoopPolicy):
            return
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

if __name__ == "__main__":
    _configure_windows_event_loop()
    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=True)
