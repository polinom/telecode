import os

import telecode.server as server


def _dummy_telegram():
    return server.TelegramConfig(bot_token="test-token")


def _set_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    os.environ.pop("TELEGRAM_TUNNEL_URL", None)
    os.environ.pop("TELEGRAM_BOT_TOKEN", None)


def test_handle_text_message_calls_prompt(monkeypatch, tmp_path):
    _set_cwd(tmp_path, monkeypatch)
    captured = {}

    def fake_handle_prompt(prompt, chat_id, message_id, timeout_s, telegram, sessions_file, engine):
        captured["prompt"] = prompt

    monkeypatch.setattr(server, "_handle_prompt", fake_handle_prompt)
    monkeypatch.setattr(server, "_send_message", lambda *args, **kwargs: 1)
    os.environ["TELECODE_ALLOWED_USERS"] = ""

    msg = {
        "message_id": 1,
        "chat": {"id": 111},
        "text": "hello",
        "from": {"id": 111, "username": "tester"},
    }
    server.handle_text_message(msg, None, _dummy_telegram(), ".telecode", "claude")

    assert captured["prompt"] == "hello"


def test_engine_command_persists_to_local_file(monkeypatch, tmp_path):
    _set_cwd(tmp_path, monkeypatch)
    os.environ["TELECODE_ALLOWED_USERS"] = ""
    sent = []

    def fake_send(*args, **kwargs):
        sent.append(kwargs.get("text") or args[2])
        return 1

    monkeypatch.setattr(server, "_send_message", fake_send)

    msg = {
        "message_id": 2,
        "chat": {"id": 222},
        "text": "/engine codex",
        "from": {"id": 222, "username": "tester"},
    }
    server.handle_text_message(msg, None, _dummy_telegram(), ".telecode", "claude")

    config_path = tmp_path / ".telecode"
    assert config_path.exists()
    content = config_path.read_text()
    assert "TELECODE_ENGINE=codex" in content
    assert any("Switched engine" in line for line in sent)


def test_cli_command_runs_without_prompt(monkeypatch, tmp_path):
    _set_cwd(tmp_path, monkeypatch)
    os.environ["TELECODE_ALLOWED_USERS"] = ""
    captured = {"ran": False}
    sent = []

    def fake_run(cmd):
        captured["ran"] = True
        return "ok"

    monkeypatch.setattr(server, "_run_cli_command", fake_run)
    monkeypatch.setattr(server, "_send_message", lambda *args, **kwargs: sent.append(args[2]) or 1)
    monkeypatch.setattr(server, "_handle_prompt", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError))

    msg = {
        "message_id": 3,
        "chat": {"id": 333},
        "text": "/cli pwd",
        "from": {"id": 333, "username": "tester"},
    }
    server.handle_text_message(msg, None, _dummy_telegram(), ".telecode", "claude")

    assert captured["ran"] is True
    assert sent == ["ok"]


def test_handle_photo_message_passes_image_path(monkeypatch, tmp_path):
    _set_cwd(tmp_path, monkeypatch)
    os.environ["TELECODE_ALLOWED_USERS"] = ""
    captured = {}

    def fake_download(config, file_id):
        return b"fake", "image.jpg"

    def fake_handle_prompt(prompt, chat_id, message_id, timeout_s, telegram, sessions_file, engine, image_paths=None):
        captured["paths"] = image_paths

    monkeypatch.setattr(server, "telegram_download_file", fake_download)
    monkeypatch.setattr(server, "_handle_prompt", fake_handle_prompt)
    monkeypatch.setattr(server, "_send_message", lambda *args, **kwargs: 1)

    msg = {
        "message_id": 4,
        "chat": {"id": 444},
        "caption": "What is this?",
        "photo": [{"file_id": "file1", "file_size": 10}],
        "from": {"id": 444, "username": "tester"},
    }
    server.handle_photo_message(msg, None, _dummy_telegram(), ".telecode", "claude")

    assert captured["paths"]
    assert os.path.exists(captured["paths"][0])


def test_handle_document_image_passes_image_path(monkeypatch, tmp_path):
    _set_cwd(tmp_path, monkeypatch)
    os.environ["TELECODE_ALLOWED_USERS"] = ""
    captured = {}

    def fake_download(config, file_id):
        return b"fake", "image.png"

    def fake_handle_prompt(prompt, chat_id, message_id, timeout_s, telegram, sessions_file, engine, image_paths=None):
        captured["paths"] = image_paths

    monkeypatch.setattr(server, "telegram_download_file", fake_download)
    monkeypatch.setattr(server, "_handle_prompt", fake_handle_prompt)
    monkeypatch.setattr(server, "_send_message", lambda *args, **kwargs: 1)

    msg = {
        "message_id": 5,
        "chat": {"id": 555},
        "caption": "What is this?",
        "document": {"file_id": "file2", "mime_type": "image/png"},
        "from": {"id": 555, "username": "tester"},
    }
    server.handle_document_message(msg, None, _dummy_telegram(), ".telecode", "claude")

    assert captured["paths"]
    assert os.path.exists(captured["paths"][0])


def test_disallowed_user_is_blocked(monkeypatch, tmp_path):
    _set_cwd(tmp_path, monkeypatch)
    os.environ["TELECODE_ALLOWED_USERS"] = "1234"
    sent = []

    monkeypatch.setattr(server, "_send_message", lambda *args, **kwargs: sent.append(args[2]) or 1)
    monkeypatch.setattr(server, "_handle_prompt", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError))

    msg = {
        "message_id": 6,
        "chat": {"id": 666},
        "text": "hello",
        "from": {"id": 9999, "username": "tester"},
    }
    server.handle_text_message(msg, None, _dummy_telegram(), ".telecode", "claude")

    assert sent == ["Not authorized."]


def test_allowed_username_is_accepted(monkeypatch, tmp_path):
    _set_cwd(tmp_path, monkeypatch)
    os.environ["TELECODE_ALLOWED_USERS"] = "testuser"
    captured = {}

    def fake_handle_prompt(prompt, chat_id, message_id, timeout_s, telegram, sessions_file, engine):
        captured["prompt"] = prompt

    monkeypatch.setattr(server, "_handle_prompt", fake_handle_prompt)
    monkeypatch.setattr(server, "_send_message", lambda *args, **kwargs: 1)

    msg = {
        "message_id": 7,
        "chat": {"id": 777},
        "text": "hi",
        "from": {"id": 777, "username": "TestUser"},
    }
    server.handle_text_message(msg, None, _dummy_telegram(), ".telecode", "claude")

    assert captured["prompt"] == "hi"

