import subprocess
import threading
import time
import os
from typing import Optional


_CLAUDE_LOCK = threading.Lock()


def ask_claude_code(
    prompt: str,
    session_id: str,
    timeout_s: Optional[int],
    image_paths: Optional[list[str]] = None,
) -> str:
    """Run Claude Code CLI with a fixed session_id; serialized via global lock."""
    return _run_locked(prompt, session_id, timeout_s=timeout_s, image_paths=image_paths)


def _run_locked(
    prompt: str,
    session_id: str,
    timeout_s: Optional[int],
    image_paths: Optional[list[str]],
) -> str:
    with _CLAUDE_LOCK:
        return _run_with_fallback(prompt, session_id, timeout_s, image_paths)

def _run_with_fallback(
    prompt: str,
    session_id: str,
    timeout_s: Optional[int],
    image_paths: Optional[list[str]],
) -> str:
    cmd_resume = _build_cmd(["--resume", session_id], prompt, image_paths)
    try:
        return _run_claude(cmd_resume, timeout_s)
    except RuntimeError as exc:
        message = str(exc)
        if "No conversation found" not in message and "already in use" not in message:
            raise
        if "No conversation found" in message:
            cmd_new = _build_cmd(["--session-id", session_id], prompt, image_paths)
            return _run_claude(cmd_new, timeout_s)

    return _retry_resume(cmd_resume, timeout_s)


def _retry_resume(cmd: list[str], timeout_s: Optional[int]) -> str:
    for _ in range(5):
        time.sleep(2)
        try:
            return _run_claude(cmd, timeout_s)
        except RuntimeError as exc:
            if "already in use" not in str(exc):
                raise
    raise RuntimeError("Claude failed: Session ID is already in use.")

def _build_cmd(args: list[str], prompt: str, image_paths: Optional[list[str]]) -> list[str]:
    cmd = ["claude"] + args + ["--print"]
    if image_paths:
        dirs = sorted({os.path.dirname(path) or "." for path in image_paths})
        for directory in dirs:
            cmd.extend(["--add-dir", directory])
    cmd.append(prompt)
    return cmd


def _run_claude(cmd: list[str], timeout_s: Optional[int]) -> str:
    try:
        completed = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            timeout=timeout_s,
            check=True,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Claude timed out after {timeout_s}s") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        stdout = (exc.stdout or "").strip()
        detail = stderr or stdout or str(exc)
        raise RuntimeError(f"Claude failed: {detail}") from exc

    return completed.stdout.strip()
