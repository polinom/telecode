import subprocess
import pytest


def test_mcp_server_initialization():
    """Test MCP server can be created."""
    from telecode.mcp_server import create_mcp_app
    app = create_mcp_app()
    assert app is not None


def test_mcp_connection_config():
    """Test connection config generation."""
    from telecode.mcp_server import get_mcp_connection_config
    config = get_mcp_connection_config("localhost", 8000)
    assert "sse_url" in config
    assert "http_url" in config
    assert "tools" in config
    assert len(config["tools"]) == 3
    assert config["http_url"] == "http://localhost:8000/mcp/"
    assert config["sse_url"] == "http://localhost:8000/mcp/sse"


def test_session_management():
    """Test MCP session storage and retrieval."""
    from telecode.mcp_server import _get_mcp_session, _set_mcp_session, _MCP_SESSIONS

    # Clear any existing sessions
    _MCP_SESSIONS.clear()

    # Initially no session
    assert _get_mcp_session("client1", "claude") is None

    # Set session
    _set_mcp_session("client1", "claude", "session-abc")

    # Retrieve session
    assert _get_mcp_session("client1", "claude") == "session-abc"

    # Different client
    assert _get_mcp_session("client2", "claude") is None

    # Different engine for same client
    assert _get_mcp_session("client1", "codex") is None

    # Set another session
    _set_mcp_session("client1", "codex", "session-xyz")
    assert _get_mcp_session("client1", "codex") == "session-xyz"

    # Original session still exists
    assert _get_mcp_session("client1", "claude") == "session-abc"


def test_get_or_create_mcp_session():
    """Test session creation on first request."""
    from telecode.mcp_server import _get_or_create_mcp_session, _MCP_SESSIONS

    _MCP_SESSIONS.clear()

    # First call creates session
    session_id = _get_or_create_mcp_session("claude")
    assert session_id is not None
    assert len(session_id) > 0

    # Second call returns same session
    session_id_2 = _get_or_create_mcp_session("claude")
    assert session_id_2 == session_id


def test_local_cli_tool(monkeypatch):
    """Test CLI tool execution."""
    class MockResult:
        stdout = "test output"
        stderr = ""
        returncode = 0

    def mock_run(cmd, **kwargs):
        return MockResult()

    monkeypatch.setattr("subprocess.run", mock_run)

    from telecode.mcp_server import _local_cli_impl
    result = _local_cli_impl("echo test")
    assert "test output" in result


def test_local_cli_tool_timeout(monkeypatch):
    """Test CLI tool handles timeout gracefully."""
    def mock_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 10)

    monkeypatch.setattr("subprocess.run", mock_run)

    from telecode.mcp_server import _local_cli_impl
    result = _local_cli_impl("sleep 100", timeout_s=10)
    assert "timed out" in result.lower()


def test_local_cli_tool_error(monkeypatch):
    """Test CLI tool handles subprocess errors."""
    def mock_run(cmd, **kwargs):
        raise Exception("command failed")

    monkeypatch.setattr("subprocess.run", mock_run)

    from telecode.mcp_server import _local_cli_impl
    result = _local_cli_impl("invalid_command")
    assert "error" in result.lower() or "failed" in result.lower()


def test_local_claude_code_tool(monkeypatch):
    """Test Claude Code tool execution."""
    def mock_ask_claude_code(prompt, session_id, timeout_s, image_paths):
        return "Mocked Claude response"

    monkeypatch.setattr("telecode.mcp_server.ask_claude_code", mock_ask_claude_code)

    from telecode.mcp_server import _local_claude_code_impl, _MCP_SESSIONS
    _MCP_SESSIONS.clear()

    result = _local_claude_code_impl("test prompt")
    assert result == "Mocked Claude response"


def test_local_claude_code_tool_with_session(monkeypatch):
    """Test Claude Code tool with explicit session."""
    def mock_ask_claude_code(prompt, session_id, timeout_s, image_paths):
        assert session_id == "my-session-123"
        return "Mocked Claude response"

    monkeypatch.setattr("telecode.mcp_server.ask_claude_code", mock_ask_claude_code)

    from telecode.mcp_server import _local_claude_code_impl
    result = _local_claude_code_impl("test prompt", session_id="my-session-123")
    assert result == "Mocked Claude response"


def test_local_claude_code_tool_timeout_error(monkeypatch):
    """Test Claude Code tool handles timeout gracefully."""
    def mock_ask_claude_code(*args, **kwargs):
        raise subprocess.TimeoutExpired("cmd", 10)

    monkeypatch.setattr("telecode.mcp_server.ask_claude_code", mock_ask_claude_code)

    from telecode.mcp_server import _local_claude_code_impl
    result = _local_claude_code_impl("test", timeout_s=10)
    assert "timed out" in result.lower()


def test_local_claude_code_tool_runtime_error(monkeypatch):
    """Test Claude Code tool handles RuntimeError gracefully."""
    def mock_ask_claude_code(*args, **kwargs):
        raise RuntimeError("Session not found")

    monkeypatch.setattr("telecode.mcp_server.ask_claude_code", mock_ask_claude_code)

    from telecode.mcp_server import _local_claude_code_impl
    result = _local_claude_code_impl("test")
    assert "error" in result.lower()
    assert "session not found" in result.lower()


def test_local_codex_tool(monkeypatch):
    """Test Codex tool execution."""
    def mock_ask_codex_exec(prompt, session_id, timeout_s, image_paths):
        return ("Mocked answer", "session-123", "logs")

    monkeypatch.setattr("telecode.mcp_server.ask_codex_exec", mock_ask_codex_exec)

    from telecode.mcp_server import _local_codex_impl, _MCP_SESSIONS
    _MCP_SESSIONS.clear()

    result = _local_codex_impl("test prompt")
    assert isinstance(result, dict)
    assert result["answer"] == "Mocked answer"
    assert result["session_id"] == "session-123"
    assert result["logs"] == "logs"


def test_local_codex_tool_with_session(monkeypatch):
    """Test Codex tool with explicit session."""
    def mock_ask_codex_exec(prompt, session_id, timeout_s, image_paths):
        assert session_id == "my-session-456"
        return ("Mocked answer", "my-session-456", "logs")

    monkeypatch.setattr("telecode.mcp_server.ask_codex_exec", mock_ask_codex_exec)

    from telecode.mcp_server import _local_codex_impl
    result = _local_codex_impl("test prompt", session_id="my-session-456")
    assert result["session_id"] == "my-session-456"


def test_local_codex_tool_timeout_error(monkeypatch):
    """Test Codex tool handles timeout gracefully."""
    def mock_ask_codex_exec(*args, **kwargs):
        raise subprocess.TimeoutExpired("cmd", 10)

    monkeypatch.setattr("telecode.mcp_server.ask_codex_exec", mock_ask_codex_exec)

    from telecode.mcp_server import _local_codex_impl
    result = _local_codex_impl("test", timeout_s=10)
    assert isinstance(result, dict)
    assert "timed out" in result["answer"].lower()


def test_local_codex_tool_runtime_error(monkeypatch):
    """Test Codex tool handles RuntimeError gracefully."""
    def mock_ask_codex_exec(*args, **kwargs):
        raise RuntimeError("Codex failed")

    monkeypatch.setattr("telecode.mcp_server.ask_codex_exec", mock_ask_codex_exec)

    from telecode.mcp_server import _local_codex_impl
    result = _local_codex_impl("test")
    assert isinstance(result, dict)
    assert "error" in result["answer"].lower()
    assert "codex failed" in result["answer"].lower()


def test_truncate_message():
    """Test message truncation."""
    from telecode.mcp_server import _truncate_message

    # Short message not truncated
    short = "This is short"
    assert _truncate_message(short) == short

    # Long message truncated
    long = "x" * 4000
    truncated = _truncate_message(long, limit=3500)
    assert len(truncated) < len(long)
    assert "[truncated]" in truncated


def test_session_isolation_from_telegram():
    """Test MCP sessions don't interfere with Telegram."""
    from telecode.mcp_server import _set_mcp_session, _get_mcp_session, _MCP_SESSIONS

    _MCP_SESSIONS.clear()

    # Set MCP session
    _set_mcp_session("mcp_client", "claude", "mcp-session-1")

    # Verify MCP session exists
    assert _get_mcp_session("mcp_client", "claude") == "mcp-session-1"

    # Verify it's in the MCP storage
    assert "mcp-session-1" in str(_MCP_SESSIONS.values())
