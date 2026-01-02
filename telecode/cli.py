import argparse
import os
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


def _ensure_tunnel_url() -> str | None:
    current = os.getenv("TELEGRAM_TUNNEL_URL")
    if current:
        return current

    port = os.getenv("TELECODE_PORT", "8000")
    _print_boxed_message(
        [
            "Tunnel URL is missing.",
            f"Please start a local tunnel on port {port}.",
            f"Example: ngrok http {port}",
            "Paste the public URL, e.g.:",
            "https://1fb55617a6b2.ngrok-free.app",
        ]
    )
    value = _prompt_tunnel_url(current)
    if not value:
        return None

    env_path = _env_path()
    lines = _read_env_lines(env_path)
    lines = _set_env_value(lines, "TELEGRAM_TUNNEL_URL", value)
    _write_env_lines(env_path, lines)
    os.environ["TELEGRAM_TUNNEL_URL"] = value
    return value


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

    env_path = _env_path()
    lines = _read_env_lines(env_path)
    lines = _set_env_value(lines, "TELEGRAM_BOT_TOKEN", token)
    _write_env_lines(env_path, lines)
    os.environ["TELEGRAM_BOT_TOKEN"] = token
    return token


def _print_command_help() -> None:
    lines = [
        "Telegram bot commands:",
        "/engine            Show current engine",
        "/engine claude     Switch to Claude",
        "/engine codex      Switch to Codex",
        "/claude            Switch to Claude",
        "/codex             Switch to Codex",
        "/cli <cmd>         Run a shell command",
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
    tunnel_url = _ensure_tunnel_url()
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
    )


if __name__ == "__main__":
    main()
