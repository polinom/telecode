import json
import re
import subprocess
from typing import Optional


def ask_codex_exec(
    prompt: str,
    session_id: Optional[str],
    timeout_s: Optional[int],
    image_paths: Optional[list[str]] = None,
) -> tuple[str, Optional[str], str]:
    """Run codex exec, optionally resuming a session, and return answer + session_id + logs."""
    use_images = image_paths or []
    cmd = _build_cmd(prompt, session_id, image_paths=use_images)
    prompt_input = prompt if use_images else None
    stdout, stderr = _run_codex(cmd, timeout_s, prompt_input=prompt_input)

    new_session_id = _extract_session_id(stdout + "\n" + stderr)
    answer = _extract_last_message(stdout)
    if not new_session_id:
        new_session_id = _extract_session_id(answer)

    if not answer:
        raise RuntimeError("Codex returned empty output.")

    logs = "\n".join([stdout, stderr]).strip()
    return answer, new_session_id or session_id, logs


def _build_cmd(
    prompt: str,
    session_id: Optional[str],
    image_paths: list[str],
) -> list[str]:
    base = ["codex", "exec"]
    for path in image_paths:
        base.extend(["--image", path])
    if session_id:
        base.extend(["resume", session_id])
    if image_paths:
        return base
    base.append(prompt)
    return base


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
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        session_id = _pick_session_id(data)
        if session_id:
            return session_id
    return _extract_session_id_from_text(stdout)


def _pick_session_id(data: object, parent_key: Optional[str] = None) -> Optional[str]:
    if isinstance(data, dict):
        for key in ("session_id", "sessionId", "sessionID", "conversation_id", "conversationId", "conversationID"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
        if parent_key in {"session", "conversation"}:
            value = data.get("id")
            if isinstance(value, str) and value:
                return value
        for key, value in data.items():
            found = _pick_session_id(value, parent_key=key)
            if found:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _pick_session_id(item, parent_key=parent_key)
            if found:
                return found
    return None


def _extract_session_id_from_text(text: str) -> Optional[str]:
    patterns = [
        r'"(?:session_id|sessionId|sessionID|conversation_id|conversationId|conversationID)"\s*:\s*"([^"]+)"',
        r'"session"\s*:\s*{[^}]*"id"\s*:\s*"([^"]+)"',
        r'"conversation"\s*:\s*{[^}]*"id"\s*:\s*"([^"]+)"',
        r'(?:session_id|sessionId|sessionID|conversation_id|conversationId|conversationID)\s*[:=]\s*([A-Za-z0-9_-]+)',
        r'session\s+id\s*[:=]\s*([A-Za-z0-9_-]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return None


def _extract_last_message(output: str) -> str:
    if not output:
        return ""
    lines = [line.rstrip() for line in output.splitlines()]
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return ""
    role_markers = {"assistant", "codex"}
    stop_prefixes = (
        "tokens used",
        "mcp startup",
        "reasoning summaries",
        "reasoning effort",
        "workdir:",
        "model:",
        "provider:",
        "approval:",
        "sandbox:",
        "session id:",
        "user",
        "thinking",
    )
    start_index = None
    for idx, line in enumerate(lines):
        if line.strip().lower() in role_markers:
            start_index = idx
    if start_index is None:
        return "\n".join(lines).strip()
    message_lines: list[str] = []
    for line in lines[start_index + 1 :]:
        stripped = line.strip()
        lowered = stripped.lower()
        if lowered in role_markers:
            break
        if any(lowered.startswith(prefix) for prefix in stop_prefixes):
            break
        message_lines.append(line)
    return "\n".join(message_lines).strip()
