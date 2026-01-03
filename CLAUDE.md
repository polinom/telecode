# CLAUDE.md - AI Assistant Guide for Telecode

This document provides comprehensive guidance for AI assistants (like Claude) working with the Telecode codebase. It covers the project structure, development workflows, coding conventions, and key architectural decisions.

## Project Overview

**Telecode** is a Telegram webhook server that routes messages to AI coding assistants (Claude Code or Codex) and can execute local shell commands. It enables conversational AI interactions through Telegram with support for:

- Text messages
- Voice notes (with Whisper transcription)
- Images (photos and documents)
- Text-to-Speech (TTS) responses via Fish Audio
- Per-chat engine selection (Claude or Codex)
- Shell command execution via `/cli` command
- Session persistence across conversations

**Current Version:** 0.1.4
**License:** MIT
**Python Requirements:** >=3.10
**Package Name:** telecode (on PyPI)

## Repository Structure

```
telecode/
├── .github/workflows/       # GitHub Actions CI/CD
│   ├── tests.yml           # Test suite (Python 3.10, 3.11, 3.12)
│   └── release.yml         # PyPI publishing workflow
├── telecode/               # Main Python package
│   ├── __init__.py        # Package initialization
│   ├── cli.py             # CLI entry point and configuration
│   ├── server.py          # FastAPI webhook server (main logic)
│   ├── telegram.py        # Telegram API client
│   ├── claude.py          # Claude Code integration
│   └── codex.py           # Codex integration
├── tests/                  # Test suite
│   └── test_server_messages.py
├── pyproject.toml         # Project metadata and build config
├── requirements.txt       # Python dependencies
├── Makefile              # Release automation
├── README.md             # User documentation
├── AGENTS.md             # Agent-specific guidelines (legacy)
└── .gitignore            # Git ignore patterns
```

### Runtime/Generated Files (Not in Git)

- `.telecode` - Config file (local or global `~/.telecode`)
- `.telecode_tmp/` - Temporary image storage
- `*.egg-info/` - Package metadata
- `dist/`, `build/` - Build artifacts

## Core Module Architecture

### 1. `cli.py` - CLI and Configuration Management

**Purpose:** Entry point for the `telecode` command. Handles interactive configuration, ngrok tunnel management, and server startup.

**Key Functions:**
- `main()` - CLI entry point, argument parsing, config loading
- `_load_config()` - Merges global (`~/.telecode`) and local (`./.telecode`) config
- `_ensure_bot_token()` - Interactive prompt for Telegram bot token
- `_ensure_tunnel_url()` - Auto-starts ngrok or prompts for tunnel URL
- `_start_ngrok_tunnel()` - Starts ngrok using Python SDK
- `_ensure_bot_commands()` - Registers Telegram bot commands

**Config File Format:** Simple `KEY=VALUE` format (like `.env` but custom parser)

**Environment Variables:**
- `TELEGRAM_BOT_TOKEN` - Required for Telegram API
- `TELEGRAM_TUNNEL_URL` - Public webhook URL
- `TELECODE_ENGINE` - Default engine: `claude` or `codex`
- `TELECODE_HOST` - Server bind host (default: `0.0.0.0`)
- `TELECODE_PORT` - Server port (default: `8000`)
- `TELECODE_ALLOWED_USERS` - Access control (comma-separated IDs/@usernames)
- `TELECODE_VERBOSE` - Enable verbose logging (`1`)
- `TELECODE_NGROK` - Enable/disable ngrok auto-start (`0`/`1`)
- `NGROK_AUTHTOKEN` - ngrok authentication token
- `TELECODE_TTS` - Enable TTS responses (`1`)
- `TTS_TOKEN` - Fish Audio API token
- `TTS_MODEL` - Fish Audio model (default: `s1`)
- `TELECODE_SESSION_CLAUDE` - Persistent Claude session ID
- `TELECODE_SESSION_CODEX` - Persistent Codex session ID
- `TELECODE_ENGINE_OVERRIDE_<chat_id>` - Per-chat engine override

### 2. `server.py` - FastAPI Webhook Server (Main Logic)

**Purpose:** Core application logic. Handles Telegram webhooks, message routing, AI engine integration, and session management.

**Architecture:**
- FastAPI application with async lifespan management
- Background task processing for webhook responses
- Thread-safe session locking (prevents concurrent access to same AI session)
- Option caching for numbered list responses (3600s TTL)

**Key Endpoints:**
- `GET /health` - Health check
- `POST /telegram/{secret}` - Webhook endpoint (secret for security)

**Message Handlers:**
- `handle_text_message()` - Text messages and commands
- `handle_voice_message()` - Voice notes (Whisper transcription)
- `handle_photo_message()` - Photo messages
- `handle_document_message()` - Image documents
- `handle_callback_query()` - Inline keyboard callbacks

**Commands Handled:**
- `/engine` - Show/switch AI engine
- `/claude` - Switch to Claude
- `/codex` - Switch to Codex
- `/cli <cmd>` - Execute shell command
- `/tts_on` - Enable TTS
- `/tts_off` - Disable TTS

**Session Management:**
- Per-chat session persistence (stored in `.telecode` with keys like `TELECODE_SESSION_CLAUDE`)
- Thread locks prevent concurrent requests to same session
- Session IDs are extracted from AI engine responses

**Image Handling:**
- Downloads images to `.telecode_tmp/`
- Passes file paths to AI engines
- Claude receives paths via `--add-dir` flag
- Codex receives paths via `--image` flag

**Access Control:**
- `TELECODE_ALLOWED_USERS` can be user IDs or @usernames
- Empty = allow all users
- Case-insensitive username matching

### 3. `telegram.py` - Telegram API Client

**Purpose:** Clean abstraction over Telegram Bot API using `httpx`.

**Key Functions:**
- `telegram_send_message()` - Send text messages
- `telegram_send_audio()` - Send TTS audio
- `telegram_download_file()` - Download files by file_id
- `telegram_download_voice()` - Download voice notes
- `telegram_set_webhook()` - Configure webhook URL
- `telegram_get_my_commands()` / `telegram_set_my_commands()` - Bot command management
- `telegram_answer_callback_query()` - Respond to inline keyboard clicks

**Design:**
- Uses `httpx` with 30s timeout (60s for uploads)
- Frozen `@dataclass` for `TelegramConfig`
- Raises `RuntimeError` on API errors
- No retry logic (handled by Telegram's webhook retries)

### 4. `claude.py` - Claude Code Integration

**Purpose:** Wrapper around the `claude` CLI (Claude Code).

**Key Features:**
- Global lock (`_CLAUDE_LOCK`) serializes all Claude requests
- Session management via `--resume {session_id}` or `--session-id {session_id}`
- Fallback: If session not found, creates new session with same ID
- Retry logic: If session "already in use", retries up to 5 times (2s delay)
- Image support via `--add-dir` for directories containing images
- Timeout handling with `subprocess.run(timeout=...)`

**Function:** `ask_claude_code(prompt, session_id, timeout_s, image_paths)`

**Claude CLI Command Structure:**
```bash
claude --resume {session_id} --print [--add-dir {dir}]... {prompt}
# OR (if session not found)
claude --session-id {session_id} --print [--add-dir {dir}]... {prompt}
```

### 5. `codex.py` - Codex Integration

**Purpose:** Wrapper around the `codex exec` CLI.

**Key Features:**
- Session management: `codex exec resume {session_id}` or plain `codex exec {prompt}`
- Image support via `--image {path}` flags (prompt passed via stdin when images present)
- Extracts session ID from JSON/text output (searches for `session_id`, `sessionId`, etc.)
- Extracts last assistant message from output (filters out metadata like "tokens used")
- Returns tuple: `(answer, session_id, logs)`

**Function:** `ask_codex_exec(prompt, session_id, timeout_s, image_paths)`

**Codex CLI Command Structure:**
```bash
codex exec [--image {path}]... resume {session_id}
# OR
codex exec {prompt}
# OR (with images, prompt via stdin)
echo {prompt} | codex exec [--image {path}]...
```

### 6. `tests/test_server_messages.py` - Test Suite

**Framework:** pytest
**Approach:** Unit tests with monkeypatching

**Test Coverage:**
- Text message handling
- Engine switching and persistence
- `/cli` command execution
- Photo/document image handling
- Access control (allowed/disallowed users)

**Running Tests:** `pytest -q`

## Development Setup

### 1. Initial Setup

```bash
# Clone repository
git clone https://github.com/polinom/telecode.git
cd telecode

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install in editable mode
pip install -e .
```

### 2. Configuration

Create `.telecode` file (local) or `~/.telecode` (global):

```
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_TUNNEL_URL=https://your-ngrok-url.ngrok-free.app
TELECODE_ENGINE=claude
TELECODE_ALLOWED_USERS=your_telegram_user_id
```

**Getting a Bot Token:**
1. Message @BotFather on Telegram
2. Send `/newbot` and follow prompts
3. Copy the token

### 3. Running the Server

```bash
# Start with default settings
telecode

# Start with verbose logging
telecode -v

# Start with custom host/port
telecode --host 127.0.0.1 --port 9000

# Start with auto-reload (development)
telecode --reload

# Disable ngrok auto-start
telecode --no-ngrok
```

The CLI will:
1. Load config from `~/.telecode` and `./.telecode`
2. Prompt for missing `TELEGRAM_BOT_TOKEN`
3. Auto-start ngrok (unless disabled)
4. Register Telegram bot commands
5. Set webhook URL
6. Start FastAPI server

### 4. Running Tests

```bash
# Run all tests
pytest -q

# Run with verbose output
pytest -v

# Run specific test
pytest tests/test_server_messages.py::test_handle_text_message_calls_prompt
```

## Coding Conventions

### Python Style

- **Indentation:** 4 spaces (consistent throughout)
- **Naming:** `lower_snake_case` for files, functions, variables
- **Type Hints:** Used extensively (Python 3.10+ syntax with `|` for unions)
- **Imports:** Standard library → third-party → local modules
- **String Quotes:** Consistent use of double quotes for strings

### Architecture Patterns

1. **Dataclasses:** Used for config objects (`TelegramConfig`)
2. **Threading:** Global locks for thread safety (`_CLAUDE_LOCK`, `_SESSION_LOCKS`)
3. **Subprocess:** Used for AI engine integration (not HTTP APIs)
4. **Error Handling:** Specific exceptions, verbose logging when enabled
5. **Config Management:** Environment variables + file-based config

### Key Principles

- **No external HTTP APIs for AI engines** - Uses local CLIs (`claude`, `codex`)
- **Session persistence** - Sessions survive server restarts (stored in `.telecode`)
- **Thread safety** - Global and per-session locks prevent race conditions
- **Background processing** - Telegram webhooks return immediately, processing happens async
- **Graceful degradation** - Missing optional features (Whisper, TTS) don't break core functionality

## Common Development Tasks

### Adding a New Telegram Command

1. **Add to bot command list:**
   - In `cli.py`: `_ensure_bot_commands()` - add to `desired` list
   - In `server.py`: `_ensure_bot_commands()` - add to `desired` list

2. **Implement handler:**
   - In `server.py`: Add handler logic in `_handle_engine_command()` or create new function
   - Call handler in `handle_text_message()`

3. **Add tests:**
   - In `tests/test_server_messages.py`: Add test function

### Adding a New Message Type

1. **Add handler function in `server.py`:**
   ```python
   def handle_new_type_message(
       msg: dict,
       timeout_s: Optional[int],
       telegram: TelegramConfig,
       sessions_file: str,
       default_engine: str,
   ) -> None:
       # Implementation
   ```

2. **Register in webhook endpoint:**
   ```python
   elif "new_type" in msg:
       background.add_task(handle_new_type_message, ...)
   ```

3. **Add test in `test_server_messages.py`**

### Changing Configuration Schema

1. **Update environment variable handling in `cli.py`:**
   - Add to argument parser if CLI flag
   - Add to `_load_config()` if file-based
   - Document in README.md

2. **Update `get_config()` in `server.py`** if server needs access

3. **Update `.gitignore`** if new files generated

### Adding a New AI Engine

1. **Create new module `telecode/{engine}.py`:**
   - Follow pattern from `claude.py` or `codex.py`
   - Implement `ask_{engine}(prompt, session_id, timeout_s, image_paths)`

2. **Update `server.py`:**
   - Import new module
   - Add engine to validation in `get_config()`
   - Update `_handle_prompt()` to route to new engine

3. **Update CLI:**
   - Add to `--engine` choices in `cli.py`
   - Update command descriptions

## Release Process

### Version Bump and Release

```bash
# Update version in Makefile
# Then run:
make release VERSION=0.1.5

# This will:
# 1. Update pyproject.toml
# 2. Create git commit
# 3. Create git tag (v0.1.5)
# 4. Push to GitHub (main + tag)
# 5. Trigger PyPI publish workflow
```

**Important:** The `release.yml` workflow auto-publishes to PyPI when a version tag is pushed.

### Manual Testing Before Release

1. Test with both engines:
   ```bash
   telecode --engine claude
   telecode --engine codex
   ```

2. Test message types:
   - Text messages
   - Commands (`/engine`, `/cli`, `/tts_on`)
   - Images (photos and documents)
   - Voice notes (if Whisper installed)

3. Run test suite:
   ```bash
   pytest -q
   ```

4. Test ngrok integration:
   ```bash
   telecode  # Should auto-start ngrok
   telecode --no-ngrok  # Should prompt for tunnel URL
   ```

## CI/CD Pipelines

### Tests Workflow (`.github/workflows/tests.yml`)

**Triggers:** Push to any branch, all PRs

**Matrix:**
- Python 3.10, 3.11, 3.12
- Ubuntu latest

**Steps:**
1. Checkout code
2. Set up Python
3. Install dependencies (`requirements.txt`)
4. Install package (`pip install -e .`)
5. Run tests (`pytest -q`)

### Publish Workflow (`.github/workflows/release.yml`)

**Triggers:** Push of version tags (`v*`)

**Steps:**
1. Checkout code
2. Set up Python 3.11
3. Build package (`python -m build`)
4. Publish to PyPI (using trusted publishing, no token needed)

**Requirements:**
- PyPI project must be configured for GitHub trusted publishing
- Repository must have proper permissions

## Important Notes for AI Assistants

### When Modifying Code

1. **Always read files before editing** - Don't assume structure
2. **Preserve thread safety** - Don't remove locks or guards
3. **Maintain backward compatibility** - Config file format must remain stable
4. **Test with both engines** - Changes should work with Claude and Codex
5. **Update documentation** - README.md and this CLAUDE.md must stay in sync

### Common Pitfalls

1. **Session locking** - Never access AI engines without proper locking
2. **Config file format** - Custom parser, not dotenv (no quotes needed)
3. **Async vs sync** - Webhook handlers are sync (run in background tasks)
4. **Image cleanup** - Images in `.telecode_tmp/` are not auto-cleaned
5. **Error handling** - Always catch exceptions in message handlers

### Security Considerations

1. **Access control** - Respect `TELECODE_ALLOWED_USERS` in all handlers
2. **Command injection** - `/cli` command has no sandboxing - document risks
3. **Webhook secret** - Generated on startup, validates requests
4. **File paths** - Sanitize image file paths to prevent directory traversal
5. **Token storage** - Bot token in plaintext in `.telecode` - warn users

### Performance Notes

1. **Thread locks** - Claude uses global lock (serial), sessions use per-chat locks
2. **Timeout defaults** - No default timeout (can run indefinitely)
3. **Image storage** - Images accumulate in `.telecode_tmp/` (manual cleanup needed)
4. **Option cache** - Numbered list responses cached for 1 hour (3600s TTL)

### Dependencies

**Core:**
- `fastapi` - Web framework
- `uvicorn` - ASGI server
- `httpx` - HTTP client for Telegram API
- `python-dotenv` - Environment loading (though custom parser used)
- `ngrok` - Tunnel management

**Optional (not in requirements.txt):**
- `openai-whisper` - Voice transcription
- `ffmpeg` - Audio processing (system dependency)

### Testing Strategy

- **Unit tests only** - No integration tests with Telegram/AI engines
- **Monkeypatching** - Mock external dependencies (Telegram API, AI engines)
- **Filesystem tests** - Use pytest `tmp_path` fixture
- **Coverage focus** - Core message routing and command handling

### Future Enhancements (Not Implemented)

These are NOT currently in the codebase but could be useful:

- Image cleanup on startup or periodic cleanup
- Webhook retry logic (currently relies on Telegram's retries)
- Rate limiting per user
- Conversation history export
- Multi-modal TTS (video, animations)
- Database storage (currently file-based)
- Docker containerization
- Metrics/monitoring endpoints
- Message queuing for high traffic

## Quick Reference

### File Locations

- **Main config:** `./.telecode` (local) or `~/.telecode` (global)
- **Temp images:** `./.telecode_tmp/`
- **Entry point:** `telecode.cli:main`
- **Server app:** `telecode.server:app`

### Key Commands

```bash
telecode              # Start server
telecode -v           # Verbose logging
pytest -q             # Run tests
make release VERSION=0.1.5  # Release new version
```

### Telegram Commands

```
/engine              # Show current engine
/engine claude       # Switch to Claude
/engine codex        # Switch to Codex
/claude              # Shortcut to Claude
/codex               # Shortcut to Codex
/cli <cmd>           # Run shell command
/tts_on              # Enable TTS
/tts_off             # Disable TTS
```

### Environment Variables Quick Reference

```bash
# Required
TELEGRAM_BOT_TOKEN=...

# Tunnel (or auto-started ngrok)
TELEGRAM_TUNNEL_URL=https://...

# Engine selection
TELECODE_ENGINE=claude|codex

# Access control
TELECODE_ALLOWED_USERS=123456,@username

# Server config
TELECODE_HOST=0.0.0.0
TELECODE_PORT=8000

# Features
TELECODE_VERBOSE=1
TELECODE_TTS=1
TTS_TOKEN=...
TTS_MODEL=s1

# Ngrok
TELECODE_NGROK=1
NGROK_AUTHTOKEN=...
```

## Changelog

This CLAUDE.md document reflects the codebase as of version 0.1.4 (January 2026).

**Recent Changes:**
- v0.1.4: Current release with PyPI publishing workflow
- Multiple cleanup and improvements leading up to v0.1.4

**Document Updates:**
- 2026-01-03: Initial comprehensive CLAUDE.md created

---

**For questions or clarifications about this codebase, refer to:**
- README.md for user-facing documentation
- AGENTS.md for legacy agent guidelines (mostly superseded by this document)
- Source code comments and docstrings
- Test files for usage examples
