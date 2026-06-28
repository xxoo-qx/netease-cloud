from __future__ import annotations

import asyncio
from asyncio.subprocess import PIPE
from dataclasses import dataclass
from pathlib import Path

from app.config import NCMM_MAX_CONCURRENT, NCMM_MAX_OUTPUT_CHARS, NCMM_PROJECT_DIR


@dataclass(slots=True)
class CapturedOutput:
    text: str
    truncated: bool
    omitted_chars: int


@dataclass(slots=True)
class CapturedProcessResult:
    returncode: int
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    stdout_omitted_chars: int
    stderr_omitted_chars: int
    command: list[str]


class _OutputBuffer:
    def __init__(self, limit: int) -> None:
        self._limit = max(1024, limit)
        self._head_limit = self._limit // 2
        self._tail_limit = self._limit - self._head_limit
        self._content = ""
        self._head = ""
        self._tail = ""
        self._truncated = False
        self._omitted_chars = 0

    def append(self, text: str) -> None:
        if not text:
            return
        if not self._truncated:
            combined = self._content + text
            if len(combined) <= self._limit:
                self._content = combined
                return
            self._head = combined[: self._head_limit]
            self._tail = combined[-self._tail_limit :]
            self._omitted_chars += len(combined) - len(self._head) - len(self._tail)
            self._content = ""
            self._truncated = True
            return

        next_tail = self._tail + text
        if len(next_tail) > self._tail_limit:
            self._omitted_chars += len(next_tail) - self._tail_limit
            next_tail = next_tail[-self._tail_limit :]
        self._tail = next_tail

    def finish(self) -> CapturedOutput:
        if not self._truncated:
            return CapturedOutput(text=self._content, truncated=False, omitted_chars=0)
        marker = f"\n...[bridge truncated {self._omitted_chars} chars]...\n"
        return CapturedOutput(
            text=f"{self._head}{marker}{self._tail}",
            truncated=True,
            omitted_chars=self._omitted_chars,
        )


_NCMM_PROCESS_SEMAPHORE = asyncio.Semaphore(max(1, NCMM_MAX_CONCURRENT))


async def _drain_stream(stream: asyncio.StreamReader | None, limit: int) -> CapturedOutput:
    buffer = _OutputBuffer(limit)
    if stream is None:
        return buffer.finish()
    while True:
        chunk = await stream.read(4096)
        if not chunk:
            break
        buffer.append(chunk.decode("utf-8", errors="replace"))
    return buffer.finish()


async def run_ncmm_subprocess(command: list[str], *, cwd: Path | None = None) -> CapturedProcessResult:
    async with _NCMM_PROCESS_SEMAPHORE:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str((cwd or NCMM_PROJECT_DIR).resolve()),
            stdout=PIPE,
            stderr=PIPE,
        )
        stdout_capture, stderr_capture = await asyncio.gather(
            _drain_stream(process.stdout, NCMM_MAX_OUTPUT_CHARS),
            _drain_stream(process.stderr, NCMM_MAX_OUTPUT_CHARS),
        )
        returncode = await process.wait()
    return CapturedProcessResult(
        returncode=returncode,
        stdout=stdout_capture.text,
        stderr=stderr_capture.text,
        stdout_truncated=stdout_capture.truncated,
        stderr_truncated=stderr_capture.truncated,
        stdout_omitted_chars=stdout_capture.omitted_chars,
        stderr_omitted_chars=stderr_capture.omitted_chars,
        command=command,
    )