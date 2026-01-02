import json
import subprocess
import tempfile
from typing import Optional


def ask_codex_exec(
    prompt: str,
    session_id: Optional[str],
    timeout_s: Optional[int],
    image_paths: Optional[list[str]] = None,
) -> tuple[str, Optional[str], str]:
    """Run codex exec, optionally resuming a session, and return answer + session_id + logs."""
    with tempfile.NamedTemporaryFile("w+", delete=False) as output_file:
        output_path = output_file.name

    use_images = image_paths or []
    cmd = _build_cmd(prompt, session_id, output_path, image_paths=use_images)
    prompt_input = prompt if use_images else None
    stdout, stderr = _run_codex(cmd, timeout_s, prompt_input=prompt_input)
    new_session_id = _extract_session_id(stdout + "\n" + stderr)

    with open(output_path, "r", encoding="utf-8") as handle:
        answer = handle.read().strip()

    if not answer:
        raise RuntimeError("Codex returned empty output.")

    logs = "\n".join([stdout, stderr]).strip()
    return answer, new_session_id or session_id, logs


def _build_cmd(
    prompt: str,
    session_id: Optional[str],
    output_path: str,
    image_paths: list[str],
) -> list[str]:
    base = [
        "codex",
        "exec",
        "--json",
        "--skip-git-repo-check",
        "--output-last-message",
        output_path,
    ]
    for path in image_paths:
        base.extend(["--image", path])
    if image_paths:
        return base
    if session_id:
        return base[:2] + ["resume", session_id] + base[2:] + [prompt]
    return base + [prompt]


def _run_codex(
    cmd: list[str],
    timeout_s: Optional[int],
    prompt_input: Optional[str] = None,
) -> tuple[str, str]:
    try:
        completed = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            input=prompt_input,
            timeout=timeout_s,
            check=True,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Codex timed out after {timeout_s}s") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        stdout = (exc.stdout or "").strip()
        detail = stderr or stdout or str(exc)
        raise RuntimeError(f"Codex failed: {detail}") from exc

    return completed.stdout, completed.stderr


def _extract_session_id(stdout: str) -> Optional[str]:
    session_id = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        session_id = session_id or _pick_session_id(data)
        if session_id:
            break
    return session_id


def _pick_session_id(data: dict) -> Optional[str]:
    for key in ("session_id", "sessionId", "conversation_id", "conversationId"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    session = data.get("session")
    if isinstance(session, dict):
        value = session.get("id")
        if isinstance(value, str) and value:
            return value
    return None
