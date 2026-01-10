import os
import subprocess
import threading
import traceback
import uuid
from typing import Optional

from fastmcp import FastMCP

from telecode.claude import ask_claude_code
from telecode.codex import ask_codex_exec


# In-memory session storage (independent from Telegram sessions)
_MCP_SESSIONS: dict[str, dict[str, str]] = {}
_MCP_SESSION_LOCK = threading.Lock()


def _is_verbose() -> bool:
    """Check if verbose logging is enabled."""
    value = os.getenv("TELECODE_VERBOSE", "").strip().lower()
    return value in {"1", "true", "yes", "on", "verbose", "debug"}


def _get_mcp_session(client_id: str, engine: str) -> Optional[str]:
    """Retrieve MCP session ID for a client and engine.

    Args:
        client_id: MCP client identifier
        engine: AI engine name ("claude" or "codex")

    Returns:
        Session ID if exists, None otherwise
    """
    with _MCP_SESSION_LOCK:
        return _MCP_SESSIONS.get(client_id, {}).get(engine)


def _set_mcp_session(client_id: str, engine: str, session_id: str) -> None:
    """Store MCP session ID for a client and engine.

    Args:
        client_id: MCP client identifier
        engine: AI engine name ("claude" or "codex")
        session_id: Session ID to store
    """
    with _MCP_SESSION_LOCK:
        if client_id not in _MCP_SESSIONS:
            _MCP_SESSIONS[client_id] = {}
        _MCP_SESSIONS[client_id][engine] = session_id


def _get_or_create_mcp_session(engine: str) -> str:
    """Get or create a session for MCP requests.

    Uses a global MCP client ID since we can't reliably track individual clients.

    Args:
        engine: AI engine name ("claude" or "codex")

    Returns:
        Session ID (existing or newly created)
    """
    client_id = "mcp_global"
    session_id = _get_mcp_session(client_id, engine)

    if not session_id:
        session_id = str(uuid.uuid4())
        _set_mcp_session(client_id, engine, session_id)

    return session_id


def _truncate_message(text: str, limit: int = 3500) -> str:
    """Truncate message to limit with indicator.

    Args:
        text: Text to truncate
        limit: Character limit

    Returns:
        Truncated text with indicator if needed
    """
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n...[truncated]"


# Implementation functions (for testing and reuse)
def _local_claude_code_impl(
    prompt: str,
    session_id: Optional[str] = None,
    timeout_s: Optional[int] = None,
    image_paths: Optional[list[str]] = None
) -> str:
    """Execute a prompt using Claude Code CLI.

    Args:
        prompt: The prompt to send to Claude Code
        session_id: Optional session ID for conversation continuity
        timeout_s: Optional timeout in seconds
        image_paths: Optional list of image file paths to include

    Returns:
        Claude Code response as string, or error message
    """
    try:
        # Get or create session if not provided
        effective_session_id = session_id or _get_or_create_mcp_session("claude")

        # Execute with existing function (reuses _CLAUDE_LOCK for thread safety)
        result = ask_claude_code(
            prompt=prompt,
            session_id=effective_session_id,
            timeout_s=timeout_s,
            image_paths=image_paths
        )

        # Store session for future requests
        if not session_id:
            _set_mcp_session("mcp_global", "claude", effective_session_id)

        return result

    except subprocess.TimeoutExpired as exc:
        return f"Error: Command timed out after {timeout_s}s"
    except RuntimeError as exc:
        # Claude-specific errors (session in use, not found, etc.)
        return f"Error: {exc}"
    except Exception as exc:
        # Unexpected errors
        if _is_verbose():
            traceback.print_exc()
        return f"Unexpected error: {type(exc).__name__}: {exc}"


def _local_codex_impl(
    prompt: str,
    session_id: Optional[str] = None,
    timeout_s: Optional[int] = None,
    image_paths: Optional[list[str]] = None
) -> dict:
    """Execute a prompt using Codex CLI.

    Args:
        prompt: The prompt to send to Codex
        session_id: Optional session ID for conversation continuity
        timeout_s: Optional timeout in seconds
        image_paths: Optional list of image file paths to include

    Returns:
        Dictionary with 'answer', 'session_id', and 'logs' keys
    """
    try:
        # Execute with existing function
        answer, new_session_id, logs = ask_codex_exec(
            prompt=prompt,
            session_id=session_id,
            timeout_s=timeout_s,
            image_paths=image_paths
        )

        # Store session if returned
        if new_session_id:
            _set_mcp_session("mcp_global", "codex", new_session_id)

        return {
            "answer": answer,
            "session_id": new_session_id or session_id or "",
            "logs": logs
        }

    except subprocess.TimeoutExpired as exc:
        return {
            "answer": f"Error: Command timed out after {timeout_s}s",
            "session_id": session_id or "",
            "logs": str(exc)
        }
    except RuntimeError as exc:
        # Codex-specific errors
        return {
            "answer": f"Error: {exc}",
            "session_id": session_id or "",
            "logs": str(exc)
        }
    except Exception as exc:
        # Unexpected errors
        if _is_verbose():
            traceback.print_exc()
        return {
            "answer": f"Unexpected error: {type(exc).__name__}: {exc}",
            "session_id": session_id or "",
            "logs": traceback.format_exc()
        }


def _local_cli_impl(command: str, timeout_s: int = 30) -> str:
    """Execute a shell command locally.

    Security Warning:
        This tool executes arbitrary shell commands. Use with caution.

    Args:
        command: Shell command to execute
        timeout_s: Timeout in seconds (default: 30)

    Returns:
        Command output (stdout + stderr), or error message
    """
    try:
        completed = subprocess.run(
            command,
            shell=True,
            text=True,
            capture_output=True,
            timeout=timeout_s,
            cwd=os.getcwd(),
        )

        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()
        output = "\n".join(part for part in [stdout, stderr] if part)

        if not output:
            output = "Command finished with no output."

        return _truncate_message(output)

    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {timeout_s}s."
    except Exception as exc:
        if _is_verbose():
            traceback.print_exc()
        return f"Error: Command failed: {exc}"


# Initialize FastMCP server
mcp = FastMCP("Telecode MCP Server")


# MCP tool wrappers (delegate to implementation functions)
@mcp.tool()
def local_claude_code(
    prompt: str,
    session_id: Optional[str] = None,
    timeout_s: Optional[int] = None,
    image_paths: Optional[list[str]] = None
) -> str:
    """Execute a prompt using Claude Code CLI."""
    return _local_claude_code_impl(prompt, session_id, timeout_s, image_paths)


@mcp.tool()
def local_codex(
    prompt: str,
    session_id: Optional[str] = None,
    timeout_s: Optional[int] = None,
    image_paths: Optional[list[str]] = None
) -> dict:
    """Execute a prompt using Codex CLI."""
    return _local_codex_impl(prompt, session_id, timeout_s, image_paths)


@mcp.tool()
def local_cli(command: str, timeout_s: int = 30) -> str:
    """Execute a shell command locally."""
    return _local_cli_impl(command, timeout_s)


def create_mcp_app():
    """Create and configure MCP server app.

    Returns:
        ASGI app ready for mounting in FastAPI
    """
    # FastMCP provides http_app() method to create an ASGI application
    # Pass path="/" so the MCP endpoints are at the mount root (not /mcp/mcp/)
    # See: https://gofastmcp.com/integrations/fastapi
    return mcp.http_app(path="/")


def get_mcp_connection_config(host: str, port: int) -> dict:
    """Generate MCP connection configuration for clients.

    Args:
        host: Server host address
        port: Server port number

    Returns:
        Dictionary with connection URLs and tool information
    """
    base_url = f"http://{host}:{port}"

    return {
        "name": "Telecode MCP Server",
        "version": "1.0",
        "sse_url": f"{base_url}/mcp/sse",
        "http_url": f"{base_url}/mcp/",
        "tools": [
            {
                "name": "local_claude_code",
                "description": "Execute prompts with Claude Code CLI"
            },
            {
                "name": "local_codex",
                "description": "Execute prompts with Codex CLI"
            },
            {
                "name": "local_cli",
                "description": "Execute shell commands"
            }
        ]
    }
