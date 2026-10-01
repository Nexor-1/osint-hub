"""Safe asynchronous subprocess execution.

* Arguments are always a list — ``shell=True`` is never used, so user input
  cannot be interpreted by a shell.
* On Windows the child gets ``CREATE_NO_WINDOW`` (no console flashes).
* stdout/stderr are streamed line by line to callbacks for live logs.
* On timeout or cancellation the whole process tree is killed (SpiderFoot
  and others spawn children).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

import psutil

LineCallback = Callable[[str], None]

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if sys.platform == "win32" else 0


class ToolNotFoundError(FileNotFoundError):
    """The tool binary is missing."""


@dataclass(slots=True)
class ProcResult:
    returncode: int
    stdout: str
    stderr: str


def popen_kwargs() -> dict:
    """Keyword arguments for any child process started by the app."""
    kw: dict = {}
    if sys.platform == "win32":
        kw["creationflags"] = CREATE_NO_WINDOW
    return kw


def kill_tree(pid: int) -> None:
    """Kill ``pid`` and all of its descendants, ignoring already-dead ones."""
    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    procs = parent.children(recursive=True) + [parent]
    for p in procs:
        with contextlib.suppress(psutil.Error):
            p.kill()
    psutil.wait_procs(procs, timeout=5)


async def _pump(stream: asyncio.StreamReader | None, sink: list[str], cb: LineCallback | None) -> None:
    if stream is None:
        return
    while True:
        line = await stream.readline()
        if not line:
            break
        text = line.decode("utf-8", errors="replace")
        sink.append(text)
        if cb:
            stripped = text.rstrip("\r\n")
            if stripped:
                cb(stripped)


async def run(
    args: Sequence[str | os.PathLike[str]],
    *,
    timeout: float | None = None,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    stdin_data: bytes | None = None,
    on_stdout: LineCallback | None = None,
    on_stderr: LineCallback | None = None,
) -> ProcResult:
    """Run a program and wait for it, streaming output.

    Raises :class:`ToolNotFoundError` if the executable doesn't exist,
    :class:`asyncio.TimeoutError` on timeout (after killing the tree) and
    propagates :class:`asyncio.CancelledError` (also killing the tree).
    """
    argv = [os.fspath(a) for a in args]
    if not argv:
        raise ValueError("empty argv")
    exe = Path(argv[0])
    if exe.is_absolute() and not exe.exists():
        raise ToolNotFoundError(str(exe))

    full_env = None
    if env is not None:
        full_env = dict(os.environ)
        full_env.update(env)
        full_env.setdefault("PYTHONIOENCODING", "utf-8")

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE if stdin_data is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd) if cwd else None,
            env=full_env,
            limit=16 * 1024 * 1024,  # long JSON lines (ExifTool, SpiderFoot)
            **popen_kwargs(),
        )
    except FileNotFoundError as exc:
        raise ToolNotFoundError(argv[0]) from exc

    out: list[str] = []
    err: list[str] = []

    async def _communicate() -> int:
        if stdin_data is not None and proc.stdin is not None:
            proc.stdin.write(stdin_data)
            with contextlib.suppress(ConnectionError):
                await proc.stdin.drain()
            proc.stdin.close()
        await asyncio.gather(_pump(proc.stdout, out, on_stdout), _pump(proc.stderr, err, on_stderr))
        return await proc.wait()

    try:
        code = await asyncio.wait_for(_communicate(), timeout)
    except BaseException:
        # TimeoutError, CancelledError, anything: make sure nothing is left running.
        if proc.returncode is None:
            await asyncio.get_running_loop().run_in_executor(None, kill_tree, proc.pid)
            with contextlib.suppress(Exception):
                await asyncio.wait_for(proc.wait(), 5)
        raise
    return ProcResult(code, "".join(out), "".join(err))
