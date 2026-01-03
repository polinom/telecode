# Telecode

[![Tests](https://github.com/polinom/telecode/actions/workflows/tests.yml/badge.svg)](https://github.com/polinom/telecode/actions/workflows/tests.yml)
[![PyPI](https://img.shields.io/pypi/v/telecode.svg)](https://pypi.org/project/telecode/)

Telegram webhook server that routes messages to Claude or Codex and can execute local shell commands via a slash command.

## Install

From PyPI:
```
pip install telecode
```

From source:
```
pip install -e .
```

## Quick Start

1) Run the server.
```
telecode
```

The CLI will prompt for missing config (bot token) and save it to `./.telecode`. If `TELEGRAM_TUNNEL_URL` is missing, it will auto-start ngrok by default.

## Tunnel + Webhook

You need a public tunnel to your local port (default `8000`). By default, Telecode will start ngrok for you (requires `ngrok` Python SDK + a valid `NGROK_AUTHTOKEN`). To disable auto-start, use `--no-ngrok` or set `TELECODE_NGROK=0`.
If ngrok isn't authenticated yet, Telecode will prompt for the authtoken and save it to `~/.telecode`.
Auto-started tunnels are subject to ngrok free plan limits: https://ngrok.com/docs/pricing-limits/free-plan-limits
```
ngrok http 8000
```

Telecode will generate a fresh webhook secret on each startup and set the webhook automatically using your bot token.

## Configuration

Config is read from:

1) `~/.telecode` (global)
2) `./.telecode` (local, overrides global)

When Telecode prompts interactively or you change engine via slash command, it writes to the local `./.telecode`.

Common keys:

- `TELEGRAM_BOT_TOKEN` - Telegram bot token from @BotFather.
- `TELEGRAM_TUNNEL_URL` - Public tunnel URL (e.g., `https://xxxx.ngrok-free.app`).
- `TELECODE_ENGINE` - Default engine: `claude` or `codex`.
- `TELECODE_HOST` - Server host (default `0.0.0.0`).
- `TELECODE_PORT` - Server port (default `8000`).
- `TELECODE_ALLOWED_USERS` - Comma/space-separated user IDs or usernames (e.g., `12345,@name`).
- `TELECODE_VERBOSE` - Set to `1` for verbose console logging.
- `TELECODE_NGROK` - Set to `0` to disable auto-starting ngrok.
- `NGROK_AUTHTOKEN` - ngrok auth token for auto-started tunnels.
- `TELECODE_TTS` - Set to `1` to enable TTS audio responses.
- `TTS_TOKEN` - Fish Audio API token (optional; can be stored in `.telecode`).
- `TTS_MODEL` - Fish Audio model (default: `s1`).
- `TELECODE_SESSION_CLAUDE` - Stored session id for Claude.
- `TELECODE_SESSION_CODEX` - Stored session id for Codex.
- `TELECODE_ENGINE_OVERRIDE_<chat_id>` - Per-chat engine override.

Example `./.telecode`:
```
TELEGRAM_BOT_TOKEN=123456:ABCDEF...
TELEGRAM_TUNNEL_URL=https://xxxx.ngrok-free.app
TELECODE_ENGINE=claude
TELECODE_ALLOWED_USERS=12345678,@myuser
```

## Telegram Commands

- `/engine` - show current engine.
- `/engine claude` - switch to Claude.
- `/engine codex` - switch to Codex.
- `/claude` - shortcut to Claude.
- `/codex` - shortcut to Codex.
- `/cli <cmd>` - run a shell command on the server (uses current working directory).
- `/tts_on` - enable TTS audio responses (global).
- `/tts_off` - disable TTS audio responses (global).

## Images

## Voice Messages

Voice notes require Whisper. Install it and ensure ffmpeg is available:
```
pip install openai-whisper
```

Install ffmpeg (macOS):
```
brew install ffmpeg
```


- Photos and image documents are supported.
- Images are downloaded to `./.telecode_tmp/` and passed to the active engine.
- Codex receives images via `--image`.
- Claude receives image file paths in the prompt (and the directory is allowed via `--add-dir`).

## Logging

Run with `-v` for verbose logging:
```
telecode -v
```

This prints inbound/outbound messages, commands, and exceptions.
