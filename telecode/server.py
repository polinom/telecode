from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import threading
import time
import traceback
import uuid
from typing import Optional

from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from dotenv import load_dotenv
import time

from telecode.claude import ask_claude_code
from telecode.codex import ask_codex_exec
from telecode.telegram import (
    TelegramConfig,
    telegram_answer_callback_query,
    telegram_download_voice,
    telegram_download_file,
    telegram_get_my_commands,
    telegram_send_audio,
    telegram_send_message,
    telegram_set_my_commands,
)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    try:
        _, _, telegram, _, _ = get_config()
        _ensure_bot_commands(telegram)
    except Exception as exc:
        print(f"Warning: failed to register bot commands: {exc}")

    # Mount MCP server if enabled
    mcp_app = None
    mcp_lifespan_context = None
    if os.getenv("TELECODE_ENABLE_MCP", "").strip().lower() in {"1", "true", "yes"}:
        try:
            from telecode.mcp_server import create_mcp_app
            mcp_app = create_mcp_app()
            print(f"  MCP app type: {type(mcp_app).__name__}")

            # Enter the MCP app's lifespan context
            if hasattr(mcp_app, 'lifespan'):
                mcp_lifespan_context = mcp_app.lifespan(mcp_app)
                await mcp_lifespan_context.__aenter__()

            app.mount("/mcp", mcp_app)
            print("✓ MCP server mounted at /mcp")
            print("  MCP protocol endpoints available")
            print("  Use MCP clients to connect to the tools")
        except Exception as exc:
            print(f"✗ Warning: failed to mount MCP server: {exc}")
            import traceback
            traceback.print_exc()

    yield

    # Exit the MCP app's lifespan context on shutdown
    if mcp_lifespan_context is not None:
        try:
            await mcp_lifespan_context.__aexit__(None, None, None)
        except Exception as exc:
            print(f"Warning: error shutting down MCP server: {exc}")


app = FastAPI(lifespan=_lifespan)

# Logging middleware to see all requests (including to mounted apps)
class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Always log in verbose mode (check each time since it's per-request)
        verbose = os.getenv("TELECODE_VERBOSE", "").strip().lower() in {"1", "true", "yes", "on", "verbose", "debug"}

        if verbose:
            start_time = time.time()
            print(f"→ {request.method} {request.url.path} from {request.client.host if request.client else 'unknown'}")

        response = await call_next(request)

        if verbose:
            duration = time.time() - start_time
            print(f"← {request.method} {request.url.path} → {response.status_code} ({duration:.3f}s)")

        return response

# Add logging middleware first (so it captures all requests)
app.add_middleware(LoggingMiddleware)

# Debug: Print on startup to verify verbose mode
verbose_env = os.getenv("TELECODE_VERBOSE", "NOT SET")
print(f"Debug: TELECODE_VERBOSE = {verbose_env}")
print(f"Debug: Verbose logging = {'ENABLED' if verbose_env in {'1', 'true', 'yes', 'on', 'verbose', 'debug'} else 'DISABLED'}")

# Add CORS middleware for MCP clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for MCP clients
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_SESSION_LOCKS: dict[str, threading.Lock] = {}
_SESSION_LOCKS_GUARD = threading.Lock()
_SESSIONS_FILE_GUARD = threading.Lock()
_ENV_FILE_GUARD = threading.Lock()
_OPTION_PATTERN = re.compile(r"^\s*(\d+)[\.\)]\s+(.*\S)\s*$")
_BULLET_PATTERN = re.compile(r"^\s*[-*•]\s+(.*\S)\s*$")
_OPTION_CACHE: dict[tuple[int, int], tuple[float, list[str]]] = {}
_OPTION_CACHE_GUARD = threading.Lock()
_OPTION_CACHE_TTL_S = 3600


def _get_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def _allowed_users() -> tuple[set[int], set[str]]:
    raw = os.getenv("TELECODE_ALLOWED_USERS", "").strip()
    if not raw:
        return set(), set()
    parts = [part.strip() for part in raw.replace(",", " ").split() if part.strip()]
    allowed_ids: set[int] = set()
    allowed_names: set[str] = set()
    for part in parts:
        if part.isdigit():
            allowed_ids.add(int(part))
        else:
            allowed_names.add(part.lstrip("@").lower())
    return allowed_ids, allowed_names


def _is_user_allowed(user_id: Optional[int]) -> bool:
    allowed_ids, allowed_names = _allowed_users()
    if not allowed_ids and not allowed_names:
        return True
    if user_id is not None and user_id in allowed_ids:
        return True
    return False


def _is_user_allowed_by_meta(user_id: Optional[int], username: Optional[str]) -> bool:
    allowed_ids, allowed_names = _allowed_users()
    if not allowed_ids and not allowed_names:
        return True
    if user_id is not None and user_id in allowed_ids:
        return True
    if username and username.lower() in allowed_names:
        return True
    return False


def _log_user_identity(source: str, user: Optional[dict]) -> None:
    if not user:
        print(f"User {source}: unknown")
        return
    user_id = user.get("id")
    username = user.get("username") or ""
    first_name = user.get("first_name") or ""
    last_name = user.get("last_name") or ""
    name = " ".join(part for part in [first_name, last_name] if part).strip()
    label = username or name or "unknown"
    print(f"User {source}: {label} (id={user_id})")


def _is_verbose() -> bool:
    value = os.getenv("TELECODE_VERBOSE", "").strip().lower()
    return value in {"1", "true", "yes", "on", "verbose", "debug"}


def _log(message: str) -> None:
    if _is_verbose():
        print(message)


def _log_exception(context: str, exc: Exception) -> None:
    if _is_verbose():
        print(f"Exception in {context}: {exc}")
        traceback.print_exc()


def get_config() -> tuple[str, int | None, TelegramConfig, str, str]:
    load_dotenv()
    webhook_secret = _get_env("TELEGRAM_WEBHOOK_SECRET")
    timeout_s = os.getenv("CLAUDE_TIMEOUT_S")
    timeout_val = int(timeout_s) if timeout_s else None
    telegram = TelegramConfig(bot_token=_get_env("TELEGRAM_BOT_TOKEN"))
    sessions_file = _env_path()
    engine = os.getenv("TELECODE_ENGINE", "claude").strip().lower()
    if engine not in {"claude", "codex"}:
        raise RuntimeError("TELECODE_ENGINE must be 'claude' or 'codex'")
    return webhook_secret, timeout_val, telegram, sessions_file, engine


def _ensure_bot_commands(telegram: TelegramConfig) -> None:
    desired = [
        {"command": "engine", "description": "Switch engine: /engine claude|codex"},
        {"command": "claude", "description": "Use Claude for this chat"},
        {"command": "codex", "description": "Use Codex for this chat"},
        {"command": "cli", "description": "Run a shell command: /cli <cmd>"},
        {"command": "tts_on", "description": "Enable TTS audio responses"},
        {"command": "tts_off", "description": "Disable TTS audio responses"},
    ]
    existing = telegram_get_my_commands(telegram)
    existing_commands = {cmd.get("command") for cmd in existing if isinstance(cmd, dict)}
    missing = [cmd for cmd in desired if cmd["command"] not in existing_commands]
    if not missing:
        return
    telegram_set_my_commands(telegram, existing + missing)


def _handle_engine_command(
    text: str,
    chat_id: int,
    message_id: int,
    telegram: TelegramConfig,
    sessions_file: str,
    default_engine: str,
) -> bool:
    if not text.startswith("/"):
        return False

    command, _, rest = text.partition(" ")
    command = command.split("@", 1)[0].lower()
    rest = rest.strip().lower()

    if command in {"/codex", "/claude"}:
        engine = command.lstrip("/")
        _log(f"IN command chat_id={chat_id} command={command}")
        _set_engine_for_chat(chat_id, engine, sessions_file)
        _persist_engine_default(engine)
        _send_message(
            telegram,
            chat_id,
            f"Switched engine to {engine}.",
            reply_to_message_id=message_id,
        )
        return True

    if command == "/engine":
        _log(f"IN command chat_id={chat_id} command={command} args={rest}")
        if not rest:
            current = _get_engine_for_chat(chat_id, default_engine, sessions_file)
            _send_message(
                telegram,
                chat_id,
                f"Current engine: {current}. Use /engine claude or /engine codex.",
                reply_to_message_id=message_id,
            )
            return True
        if rest not in {"claude", "codex"}:
            _send_message(
                telegram,
                chat_id,
                "Usage: /engine claude or /engine codex.",
                reply_to_message_id=message_id,
            )
            return True
        _set_engine_for_chat(chat_id, rest, sessions_file)
        _persist_engine_default(rest)
        _send_message(
            telegram,
            chat_id,
            f"Switched engine to {rest}.",
            reply_to_message_id=message_id,
        )
        return True

    if command == "/tts_on":
        _log(f"IN command chat_id={chat_id} command={command}")
        _persist_tts_enabled(True)
        if not os.getenv("TTS_TOKEN", "").strip():
            _send_message(
                telegram,
                chat_id,
                "TTS enabled, but TTS_TOKEN is missing. Add it to .telecode or ~/.telecode.",
                reply_to_message_id=message_id,
            )
        else:
            _send_message(
                telegram,
                chat_id,
                "TTS enabled.",
                reply_to_message_id=message_id,
            )
        return True

    if command == "/tts_off":
        _log(f"IN command chat_id={chat_id} command={command}")
        _persist_tts_enabled(False)
        _send_message(
            telegram,
            chat_id,
            "TTS disabled.",
            reply_to_message_id=message_id,
        )
        return True

    return False


def _handle_cli_command(
    text: str,
    chat_id: int,
    message_id: int,
    telegram: TelegramConfig,
) -> bool:
    match = re.match(r"^/cli(?:@\S+)?(?:\s+(.*))?\s*$", text)
    if not match:
        return False
    cmd = (match.group(1) or "").strip()
    if not cmd:
        _send_message(
            telegram,
            chat_id,
            "Usage: /cli <command>",
            reply_to_message_id=message_id,
        )
        return True

    _log(f"IN command chat_id={chat_id} command=/cli args={cmd}")
    output = _run_cli_command(cmd)
    _send_message(
        telegram,
        chat_id,
        output,
        reply_to_message_id=message_id,
    )
    return True


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


@app.get("/mcp-test")
async def mcp_test() -> dict:
    """Test endpoint to verify MCP server is accessible."""
    mcp_enabled = os.getenv("TELECODE_ENABLE_MCP", "").strip().lower() in {"1", "true", "yes"}
    return {
        "status": "ok",
        "mcp_enabled": mcp_enabled,
        "message": "If you see this, the server is reachable through ngrok",
        "note": "MCP clients connect to /mcp/ (not this endpoint)"
    }




@app.post("/telegram/{secret}")
async def telegram_webhook(secret: str, req: Request, background: BackgroundTasks):
    webhook_secret, timeout_s, telegram, sessions_file, engine = get_config()
    if secret != webhook_secret:
        raise HTTPException(status_code=401)

    update = await req.json()
    callback = update.get("callback_query")
    if callback:
        background.add_task(
        handle_callback_query,
        callback,
        timeout_s,
        telegram,
        sessions_file,
        engine,
    )
        return {"ok": True}

    msg = update.get("message")
    if not msg:
        return {"ok": True}

    if "voice" in msg:
        background.add_task(
            handle_voice_message,
            msg,
            timeout_s,
            telegram,
            sessions_file,
            engine,
        )
    elif "photo" in msg:
        background.add_task(
            handle_photo_message,
            msg,
            timeout_s,
            telegram,
            sessions_file,
            engine,
        )
    elif _is_image_document(msg.get("document")):
        background.add_task(
            handle_document_message,
            msg,
            timeout_s,
            telegram,
            sessions_file,
            engine,
        )
    elif "text" in msg:
        background.add_task(
            handle_text_message,
            msg,
            timeout_s,
            telegram,
            sessions_file,
            engine,
        )
    return {"ok": True}


def handle_voice_message(
    msg: dict,
    timeout_s: Optional[int],
    telegram: TelegramConfig,
    sessions_file: str,
    default_engine: str,
) -> None:
    user = msg.get("from") or {}
    _log_user_identity("voice", user)
    if not _is_user_allowed_by_meta(user.get("id"), user.get("username")):
        _send_message(
            telegram,
            msg["chat"]["id"],
            "Not authorized.",
            reply_to_message_id=msg["message_id"],
        )
        return
    chat_id = msg["chat"]["id"]
    message_id = msg["message_id"]
    file_id = msg["voice"]["file_id"]

    try:
        _log(f"IN voice chat_id={chat_id} message_id={message_id} file_id={file_id}")
        _send_message(
            telegram,
            chat_id,
            "Processing your voice note...",
            reply_to_message_id=message_id,
        )

        audio = telegram_download_voice(telegram, file_id)
        transcript = transcribe_with_whisper(audio)
        _log(f"IN transcript chat_id={chat_id} text={transcript}")
        _handle_prompt(
            transcript,
            chat_id,
            message_id,
            timeout_s,
            telegram,
            sessions_file,
            default_engine,
        )
    except Exception as exc:
        _log_exception("handle_voice_message", exc)
        _send_message(
            telegram,
            chat_id,
            f"Error: {exc}",
            reply_to_message_id=message_id,
        )


def handle_text_message(
    msg: dict,
    timeout_s: Optional[int],
    telegram: TelegramConfig,
    sessions_file: str,
    default_engine: str,
) -> None:
    user = msg.get("from") or {}
    _log_user_identity("text", user)
    if not _is_user_allowed_by_meta(user.get("id"), user.get("username")):
        _send_message(
            telegram,
            msg["chat"]["id"],
            "Not authorized.",
            reply_to_message_id=msg["message_id"],
        )
        return
    chat_id = msg["chat"]["id"]
    message_id = msg["message_id"]
    text = msg.get("text", "").strip()
    if not text:
        return

    try:
        _log(f"IN text chat_id={chat_id} message_id={message_id} text={text}")
        if _handle_cli_command(text, chat_id, message_id, telegram):
            return
        if _handle_engine_command(text, chat_id, message_id, telegram, sessions_file, default_engine):
            return
        _handle_prompt(text, chat_id, message_id, timeout_s, telegram, sessions_file, default_engine)
    except Exception as exc:
        _log_exception("handle_text_message", exc)
        _send_message(
            telegram,
            chat_id,
            f"Error: {exc}",
            reply_to_message_id=message_id,
        )


def handle_photo_message(
    msg: dict,
    timeout_s: Optional[int],
    telegram: TelegramConfig,
    sessions_file: str,
    default_engine: str,
) -> None:
    user = msg.get("from") or {}
    _log_user_identity("photo", user)
    if not _is_user_allowed_by_meta(user.get("id"), user.get("username")):
        _send_message(
            telegram,
            msg["chat"]["id"],
            "Not authorized.",
            reply_to_message_id=msg["message_id"],
        )
        return

    chat_id = msg["chat"]["id"]
    message_id = msg["message_id"]
    caption = (msg.get("caption") or "").strip()
    prompt = caption or "User sent an image."
    photo_id = _pick_best_photo_id(msg.get("photo", []))
    if not photo_id:
        _send_message(
            telegram,
            chat_id,
            "Error: No photo data found.",
            reply_to_message_id=message_id,
        )
        return

    image_path = None
    try:
        _send_message(
            telegram,
            chat_id,
            "Processing your image...",
            reply_to_message_id=message_id,
        )
        _log(f"IN photo chat_id={chat_id} message_id={message_id} caption={caption}")
        image_bytes, file_path = telegram_download_file(telegram, photo_id)
        image_path = _write_temp_image(image_bytes, file_path)
        _handle_prompt(
            prompt,
            chat_id,
            message_id,
            timeout_s,
            telegram,
            sessions_file,
            default_engine,
            image_paths=[image_path],
        )
    except Exception as exc:
        _log_exception("handle_photo_message", exc)
        _send_message(
            telegram,
            chat_id,
            f"Error: {exc}",
            reply_to_message_id=message_id,
        )
    finally:
        pass


def handle_document_message(
    msg: dict,
    timeout_s: Optional[int],
    telegram: TelegramConfig,
    sessions_file: str,
    default_engine: str,
) -> None:
    user = msg.get("from") or {}
    _log_user_identity("document", user)
    if not _is_user_allowed_by_meta(user.get("id"), user.get("username")):
        _send_message(
            telegram,
            msg["chat"]["id"],
            "Not authorized.",
            reply_to_message_id=msg["message_id"],
        )
        return

    chat_id = msg["chat"]["id"]
    message_id = msg["message_id"]
    caption = (msg.get("caption") or "").strip()
    prompt = caption or "User sent an image."
    document = msg.get("document") or {}
    file_id = document.get("file_id")
    if not file_id:
        _send_message(
            telegram,
            chat_id,
            "Error: No document data found.",
            reply_to_message_id=message_id,
        )
        return

    image_path = None
    try:
        _send_message(
            telegram,
            chat_id,
            "Processing your image...",
            reply_to_message_id=message_id,
        )
        _log(f"IN document chat_id={chat_id} message_id={message_id} caption={caption}")
        image_bytes, file_path = telegram_download_file(telegram, file_id)
        image_path = _write_temp_image(image_bytes, file_path)
        _handle_prompt(
            prompt,
            chat_id,
            message_id,
            timeout_s,
            telegram,
            sessions_file,
            default_engine,
            image_paths=[image_path],
        )
    except Exception as exc:
        _log_exception("handle_document_message", exc)
        _send_message(
            telegram,
            chat_id,
            f"Error: {exc}",
            reply_to_message_id=message_id,
        )
    finally:
        pass


def handle_callback_query(
    callback: dict,
    timeout_s: Optional[int],
    telegram: TelegramConfig,
    sessions_file: str,
    default_engine: str,
) -> None:
    user = callback.get("from") or {}
    _log_user_identity("callback", user)
    callback_id = callback.get("id")
    if callback_id:
        telegram_answer_callback_query(telegram, callback_id)

    if not _is_user_allowed_by_meta(user.get("id"), user.get("username")):
        message = callback.get("message") or {}
        chat_id = message.get("chat", {}).get("id")
        message_id = message.get("message_id")
        if chat_id is not None and message_id is not None:
            _send_message(
                telegram,
                chat_id,
                "Not authorized.",
                reply_to_message_id=message_id,
            )
        return

    data = callback.get("data", "").strip()
    message = callback.get("message") or {}
    chat_id = message.get("chat", {}).get("id")
    message_id = message.get("message_id")
    if not data or chat_id is None or message_id is None:
        return

    try:
        _log(f"IN callback chat_id={chat_id} message_id={message_id} data={data}")
        choice = _resolve_option_choice(chat_id, message_id, data)
        _handle_prompt(
            choice,
            chat_id,
            message_id,
            timeout_s,
            telegram,
            sessions_file,
            default_engine,
        )
    except Exception as exc:
        _log_exception("handle_callback_query", exc)
        _send_message(
            telegram,
            chat_id,
            f"Error: {exc}",
            reply_to_message_id=message_id,
        )


def _handle_prompt(
    prompt: str,
    chat_id: int,
    message_id: int,
    timeout_s: Optional[int],
    telegram: TelegramConfig,
    sessions_file: str,
    default_engine: str,
    image_paths: Optional[list[str]] = None,
) -> None:
    engine = _get_engine_for_chat(chat_id, default_engine, sessions_file)
    session_id = _get_or_create_session(chat_id, sessions_file, engine)
    answer, _ = _run_engine_locked(
        prompt,
        image_paths or [],
        session_id,
        timeout_s,
        engine,
        chat_id,
        sessions_file,
    )
    _send_message(telegram, chat_id, answer.strip(), reply_to_message_id=message_id)
    _maybe_send_tts(answer, chat_id, message_id, telegram)


def transcribe_with_whisper(audio_bytes: bytes) -> str:
    try:
        import whisper  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "Whisper is not installed. Run `pip install openai-whisper` and ensure ffmpeg is available."
        ) from exc

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=True) as temp:
        temp.write(audio_bytes)
        temp.flush()

        model = whisper.load_model("base")
        result = model.transcribe(temp.name)

    text = result.get("text")
    if not text:
        raise RuntimeError("Whisper returned empty transcript")
    return text.strip()


def _get_or_create_session(chat_id: int, sessions_file: str, engine: str) -> Optional[str]:
    sessions = _load_sessions(sessions_file)
    session_id = sessions.get(engine)
    if session_id:
        return session_id

    if engine == "codex":
        return None

    session_id = str(uuid.uuid4())
    sessions[engine] = session_id
    _save_sessions(sessions_file, sessions)
    return session_id


def _run_engine_locked(
    prompt: str,
    image_paths: list[str],
    session_id: Optional[str],
    timeout_s: Optional[int],
    engine: str,
    chat_id: int,
    sessions_file: str,
) -> tuple[str, Optional[str]]:
    lock_id = session_id or f"{engine}:{chat_id}"
    session_lock = _get_session_lock(lock_id)
    with session_lock:
        if engine == "claude":
            return (
                ask_claude_code(
                    _format_prompt_with_images(prompt, image_paths),
                    session_id=session_id or "",
                    timeout_s=timeout_s,
                    image_paths=image_paths,
                ),
                None,
            )

        codex_prompt = _format_codex_prompt(prompt)
        answer, new_session_id, logs = ask_codex_exec(
            codex_prompt,
            session_id,
            timeout_s,
            image_paths=image_paths,
        )
        if new_session_id:
            _log(f"Codex session_id={new_session_id}")
        else:
            _log("Codex session_id missing; not storing session.")
        if new_session_id and new_session_id != session_id:
            _store_session(chat_id, sessions_file, engine, new_session_id)
            _log(f"Stored {engine} session_id={new_session_id}")
        return answer, logs


def _load_sessions(sessions_file: str) -> dict[str, Optional[str]]:
    with _SESSIONS_FILE_GUARD:
        if sessions_file.endswith(".json"):
            return _load_sessions_from_json(sessions_file)
        return _load_sessions_from_kv(sessions_file)


def _save_sessions(sessions_file: str, sessions: dict[str, Optional[str]]) -> None:
    with _SESSIONS_FILE_GUARD:
        if sessions_file.endswith(".json"):
            _save_sessions_to_json(sessions_file, sessions)
        else:
            _save_sessions_to_kv(sessions_file, sessions)


def _get_session_lock(session_id: str) -> threading.Lock:
    with _SESSION_LOCKS_GUARD:
        lock = _SESSION_LOCKS.get(session_id)
        if lock is None:
            lock = threading.Lock()
            _SESSION_LOCKS[session_id] = lock
        return lock


def _normalize_session_value(value: object) -> Optional[str]:
    if isinstance(value, str) and value:
        return value
    return None


def _read_kv_file(path: str) -> dict[str, str]:
    if not os.path.exists(path):
        return {}
    data: dict[str, str] = {}
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            data[key.strip()] = value.strip()
    return data


def _load_sessions_data_json(path: str) -> dict[str, object] | None:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError:
        return None


def _load_sessions_from_json(path: str) -> dict[str, Optional[str]]:
    if not os.path.exists(path):
        return {"claude": None, "codex": None}
    data = _load_sessions_data_json(path)
    if data is None or not isinstance(data, dict):
        return {"claude": None, "codex": None}

    claude_session = _normalize_session_value(data.get("claude_session") or data.get("claude"))
    codex_session = _normalize_session_value(data.get("codex_session") or data.get("codex"))
    return {"claude": claude_session, "codex": codex_session}


def _save_sessions_to_json(path: str, sessions: dict[str, Optional[str]]) -> None:
    data = _load_sessions_data_json(path) or {}
    if not isinstance(data, dict):
        data = {}
    data["claude_session"] = sessions.get("claude")
    data["codex_session"] = sessions.get("codex")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)


def _load_sessions_from_kv(path: str) -> dict[str, Optional[str]]:
    data = _read_kv_file(path)
    return {
        "claude": _normalize_session_value(data.get("TELECODE_SESSION_CLAUDE")),
        "codex": _normalize_session_value(data.get("TELECODE_SESSION_CODEX")),
    }


def _save_sessions_to_kv(path: str, sessions: dict[str, Optional[str]]) -> None:
    lines = _read_env_lines(path)
    filtered: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("TELECODE_SESSION_CLAUDE=") or stripped.startswith(
            "TELECODE_SESSION_CODEX="
        ):
            continue
        filtered.append(line)
    if sessions.get("claude"):
        filtered.append(f"TELECODE_SESSION_CLAUDE={sessions['claude']}")
    if sessions.get("codex"):
        filtered.append(f"TELECODE_SESSION_CODEX={sessions['codex']}")
    _write_env_lines(path, filtered)


def _get_engine_for_chat(chat_id: int, default_engine: str, sessions_file: str) -> str:
    overrides = _load_engine_overrides(sessions_file)
    engine = overrides.get(str(chat_id), default_engine)
    return engine if engine in {"claude", "codex"} else default_engine


def _set_engine_for_chat(chat_id: int, engine: str, sessions_file: str) -> None:
    if engine not in {"claude", "codex"}:
        return
    with _SESSIONS_FILE_GUARD:
        if sessions_file.endswith(".json"):
            data = _load_sessions_data_json(sessions_file) or {}
            if not isinstance(data, dict):
                data = {}
            overrides = data.get("engine_overrides")
            if not isinstance(overrides, dict):
                overrides = {}
            overrides[str(chat_id)] = engine
            data["engine_overrides"] = overrides
            with open(sessions_file, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, sort_keys=True)
        else:
            _save_engine_override_kv(sessions_file, chat_id, engine)


def _env_path() -> str:
    return os.path.join(os.getcwd(), ".telecode")


def _read_env_lines(path: str) -> list[str]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read().splitlines()


def _write_env_lines(path: str, lines: list[str]) -> None:
    content = "\n".join(lines).rstrip() + "\n"
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)


def _set_env_value(lines: list[str], key: str, value: str) -> list[str]:
    prefix = f"{key}="
    updated = False
    new_lines: list[str] = []
    for line in lines:
        if line.startswith(prefix):
            new_lines.append(f"{key}={value}")
            updated = True
        else:
            new_lines.append(line)
    if not updated:
        new_lines.append(f"{key}={value}")
    return new_lines


def _persist_engine_default(engine: str) -> None:
    if engine not in {"claude", "codex"}:
        return
    os.environ["TELECODE_ENGINE"] = engine
    env_path = _env_path()
    with _ENV_FILE_GUARD:
        lines = _read_env_lines(env_path)
        lines = _set_env_value(lines, "TELECODE_ENGINE", engine)
        _write_env_lines(env_path, lines)


def _load_engine_overrides(sessions_file: str) -> dict[str, str]:
    if sessions_file.endswith(".json"):
        data = _load_sessions_data_json(sessions_file)
        if not isinstance(data, dict):
            return {}
        overrides = data.get("engine_overrides")
        if not isinstance(overrides, dict):
            return {}
        return {str(k): str(v) for k, v in overrides.items() if isinstance(v, str)}
    return _load_engine_overrides_kv(sessions_file)


def _load_engine_overrides_kv(path: str) -> dict[str, str]:
    data = _read_kv_file(path)
    prefix = "TELECODE_ENGINE_OVERRIDE_"
    overrides: dict[str, str] = {}
    for key, value in data.items():
        if key.startswith(prefix):
            overrides[key[len(prefix):]] = value
    return overrides


def _save_engine_override_kv(path: str, chat_id: int, engine: str) -> None:
    prefix = "TELECODE_ENGINE_OVERRIDE_"
    lines = _read_env_lines(path)
    target = f"{prefix}{chat_id}="
    updated = False
    new_lines: list[str] = []
    for line in lines:
        if line.startswith(target):
            new_lines.append(f"{prefix}{chat_id}={engine}")
            updated = True
        else:
            new_lines.append(line)
    if not updated:
        new_lines.append(f"{prefix}{chat_id}={engine}")
    _write_env_lines(path, new_lines)


def _store_session(
    chat_id: int,
    sessions_file: str,
    engine: str,
    session_id: str,
) -> None:
    sessions = _load_sessions(sessions_file)
    sessions[engine] = session_id
    _save_sessions(sessions_file, sessions)


def _extract_options(answer: str, fallback_text: Optional[str] = None) -> tuple[str, list[str]]:
    answer_text, options_block = _split_answer_options(answer)
    if answer_text and not options_block and re.search(r"(?i)\boptions:\s*none\b", answer):
        return answer_text.strip(), []
    lines = options_block.splitlines() if options_block else answer.splitlines()
    options: list[str] = []
    text_lines: list[str] = []
    for line in lines:
        match = _OPTION_PATTERN.match(line)
        if match:
            options.append(match.group(2).strip())
            continue
        bullet = _BULLET_PATTERN.match(line)
        if bullet:
            options.append(bullet.group(1).strip())
        else:
            text_lines.append(line)

    if len(options) >= 2:
        prefix_lines = [line for line in text_lines if line.strip()]
        prefix = "\n".join(prefix_lines).strip()
        if answer_text.strip():
            prefix = (answer_text.strip() + ("\n" + prefix if prefix else "")).strip()
        if prefix:
            return prefix, options
        return answer_text.strip(), options

    if not fallback_text:
        return answer.strip(), []

    fallback_lines = fallback_text.splitlines()
    fallback_options: list[str] = []
    fallback_text_lines: list[str] = []
    for line in fallback_lines:
        match = _OPTION_PATTERN.match(line)
        if match:
            fallback_options.append(match.group(2).strip())
        else:
            fallback_text_lines.append(line)

    if len(fallback_options) < 2:
        return answer.strip(), []

    prompt_lines = [line.strip() for line in text_lines if line.strip()]
    fallback_prompt_lines = [line.strip() for line in fallback_text_lines if line.strip()]
    if not (_looks_like_option_prompt(prompt_lines) or _looks_like_option_prompt(fallback_prompt_lines)):
        return answer.strip(), []

    return answer.strip(), fallback_options


def _split_answer_options(answer: str) -> tuple[str, str]:
    answer_line = answer.strip()
    if "options:" not in answer_line.lower():
        return "", ""
    parts = re.split(r"(?i)\boptions:\s*", answer, maxsplit=1)
    if len(parts) != 2:
        return "", ""
    prefix, options_block = parts
    prefix = re.sub(r"(?i)^\s*answer:\s*", "", prefix).strip()
    if re.match(r"(?i)^none\b", options_block.strip()):
        return prefix, ""
    return prefix, options_block.strip()


def _looks_like_option_prompt(lines: list[str]) -> bool:
    if not lines:
        return False
    normalized = [line.lower() for line in lines if line.strip()]
    if any(line.endswith("?") for line in normalized):
        return True
    keywords = (
        "what do you want to do",
        "choose",
        "select",
        "pick",
        "tell me which",
        "which one",
        "which do you",
        "which would you",
    )
    return any(any(keyword in line for keyword in keywords) for line in normalized)


def _is_image_document(document: Optional[dict]) -> bool:
    if not isinstance(document, dict):
        return False
    mime = (document.get("mime_type") or "").lower()
    return mime.startswith("image/")


def _pick_best_photo_id(photos: list[dict]) -> Optional[str]:
    if not photos:
        return None
    def score(photo: dict) -> int:
        file_size = photo.get("file_size") or 0
        width = photo.get("width") or 0
        height = photo.get("height") or 0
        return file_size or (width * height)
    best = max(photos, key=score)
    return best.get("file_id")


def _write_temp_image(image_bytes: bytes, file_path: str) -> str:
    _, ext = os.path.splitext(file_path)
    suffix = ext if ext else ".jpg"
    temp_dir = _ensure_project_temp_dir()
    filename = f"image_{uuid.uuid4().hex}{suffix}"
    path = os.path.join(temp_dir, filename)
    with open(path, "wb") as handle:
        handle.write(image_bytes)
    return path


def _ensure_project_temp_dir() -> str:
    path = os.path.join(os.getcwd(), ".telecode_tmp")
    os.makedirs(path, exist_ok=True)
    return path




def _format_codex_prompt(prompt: str) -> str:
    return (
        "You are responding to a Telegram user.\n"
        "Reply with one concise paragraph.\n\n"
        f"User said:\n{prompt}\n\n"
        "Reply concisely."
    )


def _format_prompt_with_images(prompt: str, image_paths: list[str]) -> str:
    if not image_paths:
        return f"User said:\n{prompt}\n\nReply concisely."

    parts = [f"User said:\n{prompt}", "Image file path(s):"]
    for idx, path in enumerate(image_paths, start=1):
        parts.append(f"- {path}")

    parts.append("Reply concisely.")
    return "\n\n".join(parts)


def _option_label(option: str) -> str:
    raw = option.strip()
    split_label = raw
    for sep in (" - ", ": "):
        if sep in raw:
            split_label = raw.split(sep, 1)[0].strip()
            break
    split_words = split_label.split()
    if len(split_words) < 2:
        words = raw.split()
        split_label = " ".join(words[:3]) if words else raw
    label = " ".join(split_label.split()[:3]) if split_label else raw
    return _truncate_label(label)


def _truncate_label(text: str, limit_bytes: int = 64) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= limit_bytes:
        return text
    truncated = text
    while truncated and len(truncated.encode("utf-8")) > limit_bytes - 3:
        truncated = truncated[:-1]
    return f"{truncated}..."


def _build_inline_keyboard_numbers(labels: list[str]) -> dict[str, list[list[dict[str, str]]]]:
    return {
        "inline_keyboard": [
            [
                {
                    "text": f"{idx + 1}. {label}",
                    "callback_data": f"opt:{idx + 1}",
                }
            ]
            for idx, label in enumerate(labels)
        ]
    }


def _store_option_cache(chat_id: int, message_id: int, options: list[str]) -> None:
    now = time.time()
    with _OPTION_CACHE_GUARD:
        _OPTION_CACHE[(chat_id, message_id)] = (now, options)
        _prune_option_cache(now)


def _resolve_option_choice(chat_id: int, message_id: int, data: str) -> str:
    if data.startswith("opt:"):
        index_str = data.split(":", 1)[1]
    else:
        index_str = data

    if index_str.isdigit():
        index = int(index_str)
        with _OPTION_CACHE_GUARD:
            cached = _OPTION_CACHE.pop((chat_id, message_id), None)
        if cached:
            _, options = cached
            if 1 <= index <= len(options):
                return options[index - 1]
    return data


def _prune_option_cache(now: float) -> None:
    stale_keys = [
        key for key, (timestamp, _) in _OPTION_CACHE.items() if now - timestamp > _OPTION_CACHE_TTL_S
    ]
    for key in stale_keys:
        _OPTION_CACHE.pop(key, None)


def _send_message(
    telegram: TelegramConfig,
    chat_id: int,
    text: str,
    reply_to_message_id: int | None = None,
    reply_markup: dict | None = None,
) -> int:
    _log(f"OUT message chat_id={chat_id} text={text}")
    if reply_markup is not None:
        _log(f"OUT reply_markup chat_id={chat_id} payload={reply_markup}")
    return telegram_send_message(
        telegram,
        chat_id,
        text,
        reply_to_message_id=reply_to_message_id,
        reply_markup=reply_markup,
    )


def _run_cli_command(cmd: str, timeout_s: int = 30) -> str:
    try:
        completed = subprocess.run(
            cmd,
            shell=True,
            text=True,
            capture_output=True,
            timeout=timeout_s,
            cwd=os.getcwd(),
        )
    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout_s}s."
    except Exception as exc:
        return f"Command failed: {exc}"

    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    output = "\n".join(part for part in [stdout, stderr] if part)
    if not output:
        output = "Command finished with no output."
    return _truncate_message(output)


def _truncate_message(text: str, limit: int = 3500) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n...[truncated]"


def _is_tts_enabled() -> bool:
    value = os.getenv("TELECODE_TTS", "").strip().lower()
    return value in {"1", "true", "yes", "on", "enable", "enabled"}


def _persist_tts_enabled(enabled: bool) -> None:
    os.environ["TELECODE_TTS"] = "1" if enabled else "0"
    env_path = _env_path()
    with _ENV_FILE_GUARD:
        lines = _read_env_lines(env_path)
        lines = _set_env_value(lines, "TELECODE_TTS", os.environ["TELECODE_TTS"])
        _write_env_lines(env_path, lines)


def _maybe_send_tts(answer: str, chat_id: int, message_id: int, telegram: TelegramConfig) -> None:
    if not _is_tts_enabled():
        return
    token = os.getenv("TTS_TOKEN", "").strip()
    if not token:
        _log("TTS enabled but TTS_TOKEN is missing.")
        return
    try:
        cleaned = answer.replace("**", "").rstrip()
        cleaned = f"{cleaned} (chuckling)"
        audio_path = _synthesize_fish_tts(cleaned, token)
    except Exception as exc:
        _log(f"TTS failed: {exc}")
        return
    try:
        telegram_send_audio(telegram, chat_id, audio_path, reply_to_message_id=message_id)
    except Exception as exc:
        _log_exception("telegram_send_audio", exc)


def _synthesize_fish_tts(text: str, token: str) -> str:
    import httpx

    model = os.getenv("TTS_MODEL", "s1").strip() or "s1"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "model": model,
    }
    payload = {
        "text": text.strip(),
        "reference_id": "8ef4a238714b45718ce04243307c57a7",
    }
    with httpx.Client(timeout=60) as client:
        resp = client.post("https://api.fish.audio/v1/tts", json=payload, headers=headers)
        resp.raise_for_status()
        audio_bytes = resp.content

    temp_dir = _ensure_project_temp_dir()
    filename = f"tts_{uuid.uuid4().hex}.mp3"
    path = os.path.join(temp_dir, filename)
    with open(path, "wb") as handle:
        handle.write(audio_bytes)
    return path
