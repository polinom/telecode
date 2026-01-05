# Telecode

[![Tests](https://github.com/polinom/telecode/actions/workflows/tests.yml/badge.svg)](https://github.com/polinom/telecode/actions/workflows/tests.yml)
[![PyPI](https://img.shields.io/pypi/v/telecode.svg)](https://pypi.org/project/telecode/)

**Your AI Terminal Inside Telegram** — Bridge Telegram with Claude Code and Codex. Execute commands, analyze images, transcribe voice, and chat with AI—all from your favorite messenger.

## ✨ Features

- 🤖 **Dual AI Engines** — Switch between Claude Code and Codex on the fly
- 📡 **MCP Server** — Expose AI tools via Model Context Protocol for remote agent access
- 🖼️ **Vision Processing** — Send screenshots and images for AI analysis
- 🎤 **Voice Transcription** — Whisper-powered voice note transcription
- 🔊 **Text-to-Speech** — Fish Audio integration for audio responses
- ⚡ **Real-time Webhooks** — Instant message processing via Telegram webhooks
- 🔒 **Access Control** — Whitelist users by ID or username
- 💬 **Persistent Sessions** — Conversations preserved across messages

## 🚀 Quick Start

### Install

```bash
pip install telecode
```

### Run

```bash
telecode
```

On first run, you'll be prompted for:
- **Telegram Bot Token** (get it from [@BotFather](https://t.me/BotFather))
- **ngrok Auth Token** (optional, for auto-tunneling)

That's it! Find your bot in Telegram and start chatting.

## 📡 MCP Server (NEW)

Telecode can expose AI tools via the Model Context Protocol, allowing remote agents to access your local AI engines:

### Enable MCP Server

```bash
telecode --enable-mcp
```

The server will display your MCP connection URL:
```
+----------------------------------------------------+
| MCP Server Configuration:                          |
|                                                    |
| URL: https://your-tunnel.ngrok-free.app/mcp/      |
| (Public ngrok URL - share with remote MCP clients)|
|                                                    |
| Available Tools:                                   |
|   - local_claude_code: Execute Claude Code CLI     |
|   - local_codex: Execute Codex CLI                 |
|   - local_cli: Execute shell commands              |
+----------------------------------------------------+
```

### MCP Tools

- **`local_claude_code`** — Execute prompts with Claude Code CLI
- **`local_codex`** — Execute prompts with Codex CLI
- **`local_cli`** — Run shell commands on your server

MCP clients can connect to your server and use these tools remotely. Sessions are independent from Telegram, allowing simultaneous use.

## 💬 Telegram Commands

| Command | Description |
|---------|-------------|
| `/engine` | Show current AI engine |
| `/claude` | Switch to Claude Code |
| `/codex` | Switch to Codex |
| `/cli <cmd>` | Execute shell command |
| `/tts_on` | Enable TTS audio responses |
| `/tts_off` | Disable TTS responses |

## 🎯 Usage Examples

### Chat with AI
Simply send any message to interact with the current engine:
```
You: Write a Python function to reverse a string

Bot: Here's a simple function:

def reverse_string(s):
    return s[::-1]
```

### Analyze Images
Send a photo with a caption:
```
[Screenshot of error]
Caption: "What's causing this bug?"

Bot: This is a NullPointerException at line 42...
```

### Execute Commands
```
/cli git status

Bot: On branch main
     Your branch is up to date...
```

### Voice Messages
Hold the mic button, speak your prompt, release. The bot transcribes and responds.

## ⚙️ Configuration

Configuration is stored in `.telecode` (local) or `~/.telecode` (global):

```bash
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
TELECODE_ENGINE=claude
TELECODE_ALLOWED_USERS=123456789,@username
TELECODE_ENABLE_MCP=1
TELECODE_VERBOSE=1
```

### Key Configuration Options

| Variable | Description | Default |
|----------|-------------|---------|
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather | *Required* |
| `TELEGRAM_TUNNEL_URL` | Public webhook URL | Auto via ngrok |
| `TELECODE_ENGINE` | Default engine: `claude` or `codex` | `claude` |
| `TELECODE_ENABLE_MCP` | Enable MCP server | `0` |
| `TELECODE_ALLOWED_USERS` | User whitelist (IDs/@usernames) | *(empty = all)* |
| `TELECODE_VERBOSE` | Enable verbose logging | `0` |
| `TELECODE_TTS` | Enable TTS responses | `0` |

## 🔐 Access Control

Restrict bot access to specific users:

```bash
# By user ID (get from @userinfobot)
TELECODE_ALLOWED_USERS=123456789,987654321

# By username
TELECODE_ALLOWED_USERS=@alice,@bob

# Mixed
TELECODE_ALLOWED_USERS=123456789,@alice
```

Leave empty to allow all users.

## 🛠️ Development

```bash
# Clone and install
git clone https://github.com/polinom/telecode.git
cd telecode
pip install -e .

# Run with auto-reload
telecode --reload -v

# Run tests
pytest -q
```

### CLI Options

```bash
telecode --help

Options:
  --host HOST          Host to bind (default: 0.0.0.0)
  --port PORT          Port to bind (default: 8000)
  --reload             Enable auto-reload (dev mode)
  --engine {claude,codex}  Default engine
  --no-ngrok           Disable ngrok auto-start
  --enable-mcp         Enable MCP server
  -v, --verbose        Enable verbose logging
```

## 🏗️ Architecture

```
┌─────────────┐
│  Telegram   │
│   Bot API   │
└──────┬──────┘
       │ HTTPS
       ▼
┌──────────────┐
│ ngrok Tunnel │
└──────┬───────┘
       │
       ▼
┌──────────────────┐     ┌─────────────┐
│  FastAPI Server  │────▶│ MCP Clients │
│  (Port 8000)     │     └─────────────┘
└──────┬───────────┘
       │
   ┌───┴───┐
   ▼       ▼
┌────────┐ ┌───────┐
│ Claude │ │ Codex │
└────────┘ └───────┘
```

## 📚 Documentation

- **[User Guide](https://polinom.github.io/telecode/)** — Website with examples
- **[CLAUDE.md](CLAUDE.md)** — Developer guide for AI assistants
- **[GitHub Issues](https://github.com/polinom/telecode/issues)** — Bug reports and feature requests

## 🔧 Troubleshooting

### Bot doesn't respond
- Check webhook URL is accessible
- Run with `-v` for verbose logs
- Verify bot token with [@userinfobot](https://t.me/userinfobot)

### Voice messages fail
```bash
pip install openai-whisper
brew install ffmpeg  # macOS
```

### Invalid bot token error
The CLI will detect invalid tokens and prompt for a new one automatically.

### ngrok authentication failed
Get your auth token from [ngrok.com](https://dashboard.ngrok.com/get-started/your-authtoken) and paste when prompted.

## 📄 License

MIT — See [LICENSE](LICENSE) for details.

---

**Contributing:** Issues and PRs welcome! • **Security:** Never commit tokens or API keys

**[⭐ Star on GitHub](https://github.com/polinom/telecode)** if you find this useful!
