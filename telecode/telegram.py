from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str

    @property
    def api_base(self) -> str:
        return f"https://api.telegram.org/bot{self.bot_token}"

    @property
    def file_base(self) -> str:
        return f"https://api.telegram.org/file/bot{self.bot_token}"


def telegram_send_message(
    config: TelegramConfig,
    chat_id: int,
    text: str,
    reply_to_message_id: int | None = None,
    reply_markup: dict[str, Any] | None = None,
) -> int:
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
    if reply_to_message_id is not None:
        payload["reply_to_message_id"] = reply_to_message_id
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup

    data = _post_json(f"{config.api_base}/sendMessage", payload)
    return data["result"]["message_id"]


def telegram_send_audio(
    config: TelegramConfig,
    chat_id: int,
    audio_path: str,
    caption: str | None = None,
    reply_to_message_id: int | None = None,
) -> int:
    payload: dict[str, Any] = {"chat_id": chat_id}
    if caption:
        payload["caption"] = caption
    if reply_to_message_id is not None:
        payload["reply_to_message_id"] = reply_to_message_id
    with open(audio_path, "rb") as handle:
        files = {"audio": handle}
        data = _post_multipart(f"{config.api_base}/sendAudio", payload, files)
    return data["result"]["message_id"]


def telegram_answer_callback_query(
    config: TelegramConfig,
    callback_query_id: str,
    text: str | None = None,
    show_alert: bool = False,
) -> None:
    payload: dict[str, Any] = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    if show_alert:
        payload["show_alert"] = True
    _post_json(f"{config.api_base}/answerCallbackQuery", payload)


def telegram_get_my_commands(config: TelegramConfig) -> list[dict[str, Any]]:
    data = _post_json(f"{config.api_base}/getMyCommands", {})
    return data.get("result", [])


def telegram_set_my_commands(
    config: TelegramConfig,
    commands: list[dict[str, str]],
) -> None:
    payload: dict[str, Any] = {"commands": commands}
    _post_json(f"{config.api_base}/setMyCommands", payload)


def telegram_set_webhook(
    config: TelegramConfig,
    url: str,
) -> None:
    payload: dict[str, Any] = {"url": url}
    _post_json(f"{config.api_base}/setWebhook", payload)


def telegram_download_file(config: TelegramConfig, file_id: str) -> tuple[bytes, str]:
    file_info = _post_json(f"{config.api_base}/getFile", {"file_id": file_id})
    file_path = file_info["result"]["file_path"]
    url = f"{config.file_base}/{file_path}"
    return _get_bytes(url), file_path


def telegram_download_voice(config: TelegramConfig, file_id: str) -> bytes:
    data, _ = telegram_download_file(config, file_id)
    return data


def _post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    with httpx.Client(timeout=30) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API error: {data}")
        return data


def _post_multipart(url: str, payload: dict[str, Any], files: dict[str, Any]) -> dict[str, Any]:
    with httpx.Client(timeout=60) as client:
        resp = client.post(url, data=payload, files=files)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API error: {data}")
        return data


def _get_bytes(url: str) -> bytes:
    with httpx.Client(timeout=60) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.content
