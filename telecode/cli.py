import argparse
import atexit
import os
import re
import uuid

import uvicorn

from telecode.telegram import (
    TelegramConfig,
    telegram_get_my_commands,
    telegram_set_my_commands,
    telegram_set_webhook,
)


def _global_config_path() -> str:
    return os.path.expanduser("~/.telecode")


def _local_config_path() -> str:
    return os.path.join(os.getcwd(), ".telecode")


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


def _load_config() -> None:
    config: dict[str, str] = {}
    global_path = _global_config_path()
    local_path = _local_config_path()
    config.update(_read_kv_file(global_path))
    config.update(_read_kv_file(local_path))
    for key, value in config.items():
        os.environ.setdefault(key, value)
    if os.path.exists(local_path):
        _print_boxed_message([f"Config: {local_path}"])
    elif os.path.exists(global_path):
        _print_boxed_message([f"Config: {global_path}"])
    else:
        _print_boxed_message([f"Config: {local_path} (new)"])


def _env_path() -> str:
    return _local_config_path()


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


def _print_boxed_message(lines: list[str]) -> None:
    width = max(len(line) for line in lines)
    border = "+" + "-" * (width + 2) + "+"
    print(border)
    for line in lines:
        padding = " " * (width - len(line))
        print(f"| {line}{padding} |")
    print(border)


def _prompt_tunnel_url(current: str | None) -> str | None:
    hint = "https://<ngrok-id>.ngrok.io"
    prompt = f"Enter tunnel URL (e.g., {hint}): "
    if current:
        prompt = f"Enter tunnel URL (current: {current}) or press Enter to keep: "
    value = input(prompt).strip()
    if not value and current:
        return current
    return value or None


def _is_ngrok_enabled(disable_ngrok: bool) -> bool:
    if disable_ngrok:
        return False
    value = os.getenv("TELECODE_NGROK", "").strip().lower()
    if value in {"0", "false", "no", "off", "disable", "disabled"}:
        return False
    if value in {"1", "true", "yes", "on", "enable", "enabled"}:
        return True
    return True


def _start_ngrok_tunnel(port: str) -> str | None:
    try:
        import ngrok  # type: ignore
    except Exception:
        return None

    listener = ngrok.forward(f"localhost:{port}", authtoken_from_env=True)
    if not listener:
        return None
    url = listener.url() if hasattr(listener, "url") else getattr(listener, "url", None)
    if url and hasattr(listener, "close"):
        atexit.register(listener.close)
    return url


def _extract_urls(text: str) -> list[str]:
    if not text:
        return []
    urls = re.findall(r"https?://\\S+", text)
    cleaned = []
    for url in urls:
        cleaned.append(url.rstrip(").,"))
    return cleaned


def _prompt_ngrok_authtoken(error_text: str) -> str | None:
    urls = _extract_urls(error_text)
    lines = [
        "Failed to start ngrok tunnel.",
        "ngrok requires a verified account and authtoken.",
    ]
    lines.append("Get your authtoken here:")
    if urls:
        lines.extend(urls[:2])
    else:
        lines.append("https://dashboard.ngrok.com/get-started/your-authtoken")
    _print_boxed_message(lines)
    token = input("Enter NGROK_AUTHTOKEN (leave empty to skip): ").strip()
    return token or None


def _store_global_env_value(key: str, value: str) -> None:
    env_path = _global_config_path()
    lines = _read_env_lines(env_path)
    lines = _set_env_value(lines, key, value)
    _write_env_lines(env_path, lines)


def _ensure_tunnel_url(disable_ngrok: bool) -> str | None:
    current = os.getenv("TELEGRAM_TUNNEL_URL")
    if current:
        return current

    port = os.getenv("TELECODE_PORT", "8000")
    if _is_ngrok_enabled(disable_ngrok):
        try:
            public_url = _start_ngrok_tunnel(port)
        except ValueError as exc:
            token = _prompt_ngrok_authtoken(str(exc))
            if token:
                _store_global_env_value("NGROK_AUTHTOKEN", token)
                os.environ["NGROK_AUTHTOKEN"] = token
                public_url = _start_ngrok_tunnel(port)
            else:
                return None
        if public_url:
            os.environ["TELEGRAM_TUNNEL_URL"] = public_url
            return public_url
        _print_boxed_message(
            [
                "Failed to start ngrok tunnel.",
                "Ensure ngrok is installed and you are authenticated.",
                "Set NGROK_AUTHTOKEN and retry, or set TELEGRAM_TUNNEL_URL manually.",
            ]
        )
        return None

    _print_boxed_message(
        [
            "Tunnel URL is missing and ngrok auto-start is disabled.",
            f"Set TELEGRAM_TUNNEL_URL or enable ngrok (TELECODE_NGROK=1).",
        ]
    )
    return None


def _ensure_bot_token() -> str | None:
    current = os.getenv("TELEGRAM_BOT_TOKEN")
    if current:
        return current

    _print_boxed_message(
        [
            "TELEGRAM_BOT_TOKEN is missing.",
            "Create a bot via @BotFather in Telegram.",
            "Paste the token below.",
        ]
    )
    token = input("Enter TELEGRAM_BOT_TOKEN: ").strip()
    if not token:
        return None

    scope = input("Store bot token locally (l) or globally (g)? [l]: ").strip().lower()
    env_path = _global_config_path() if scope == "g" else _env_path()
    lines = _read_env_lines(env_path)
    lines = _set_env_value(lines, "TELEGRAM_BOT_TOKEN", token)
    _write_env_lines(env_path, lines)
    os.environ["TELEGRAM_BOT_TOKEN"] = token
    return token


def _print_command_help() -> None:
    lines = [
        "Telegram bot commands:",
        "/engine            Show current engine",
        "/claude            Switch to Claude",
        "/codex             Switch to Codex",
        "/cli <cmd>         Run a shell command",
        "/tts_on            Enable TTS audio responses",
        "/tts_off           Disable TTS audio responses",
    ]
    if not os.getenv("TELECODE_ALLOWED_USERS", "").strip():
        lines.extend(
            [
                "",
                "Access control:",
                "TELECODE_ALLOWED_USERS is empty (allowing all users).",
                "Set it to comma-separated Telegram user IDs or @usernames.",
            ]
        )
    _print_boxed_message(lines)


def _ensure_bot_commands(bot_token: str) -> None:
    desired = [
        {"command": "engine", "description": "Switch engine: /engine claude|codex"},
        {"command": "claude", "description": "Use Claude for this chat"},
        {"command": "codex", "description": "Use Codex for this chat"},
        {"command": "cli", "description": "Run a shell command: /cli <cmd>"},
        {"command": "tts_on", "description": "Enable TTS audio responses"},
        {"command": "tts_off", "description": "Disable TTS audio responses"},
    ]
    telegram = TelegramConfig(bot_token=bot_token)
    existing = telegram_get_my_commands(telegram)
    existing_commands = {cmd.get("command") for cmd in existing if isinstance(cmd, dict)}
    missing = [cmd for cmd in desired if cmd["command"] not in existing_commands]
    if not missing:
        return
    telegram_set_my_commands(telegram, existing + missing)


def main() -> None:
    _load_config()

    parser = argparse.ArgumentParser(description="Telecode webhook server")
    default_host = os.getenv("TELECODE_HOST", "0.0.0.0")
    default_port = int(os.getenv("TELECODE_PORT", "8000"))
    parser.add_argument("--host", default=default_host, help="Host to bind")
    parser.add_argument("--port", type=int, default=default_port, help="Port to bind")
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload (development only)",
    )
    parser.add_argument(
        "--engine",
        choices=["claude", "codex"],
        default=os.getenv("TELECODE_ENGINE", "claude"),
        help="LLM engine to use for processing (default: claude)",
    )
    parser.add_argument(
        "--no-ngrok",
        action="store_true",
        help="Disable auto-starting ngrok when tunnel URL is missing",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Preserve user env but ensure uvicorn can resolve the module.
    os.environ.setdefault("PYTHONPATH", ".")
    os.environ["TELECODE_ENGINE"] = args.engine
    os.environ["TELECODE_HOST"] = args.host
    os.environ["TELECODE_PORT"] = str(args.port)
    if args.verbose:
        os.environ["TELECODE_VERBOSE"] = "1"

    bot_token = _ensure_bot_token()
    tunnel_url = _ensure_tunnel_url(args.no_ngrok)
    if tunnel_url:
        _print_boxed_message([f"Tunnel URL: {tunnel_url}"])
    if bot_token:
        try:
            _ensure_bot_commands(bot_token)
        except Exception as exc:
            print(f"Warning: failed to register bot commands: {exc}")
    if bot_token and tunnel_url:
        secret = str(uuid.uuid4())
        os.environ["TELEGRAM_WEBHOOK_SECRET"] = secret
        webhook_url = f"{tunnel_url.rstrip('/')}/telegram/{secret}"
        try:
            telegram_set_webhook(TelegramConfig(bot_token=bot_token), webhook_url)
        except Exception as exc:
            print(f"Warning: failed to set Telegram webhook: {exc}")

    _print_command_help()

    uvicorn.run(
        "telecode.server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
