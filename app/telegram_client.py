"""
GENOPOISK CRM — тонкий клиент Telegram Bot API (раздел 15/28 ТЗ, этап 6).

Сознательно на стандартной библиотеке (urllib), без python-telegram-bot —
единственная задача здесь: getMe (проверка токена) и getUpdates (получение
новых сообщений long-polling'ом). Отправка сообщений ботом не требуется —
бот только ПРИНИМАЕТ уведомления о заказах.

Токен передаётся явно в каждую функцию — модуль НИКОГДА не читает его сам
из secrets_store и не хранит в памяти дольше одного вызова; кто и как
получает токен — забота вызывающего кода (settings_dialog.py, telegram_poller.py),
оба берут его исключительно через app.secrets_store.get_telegram_bot_token().
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Optional

API_URL_TMPL = "https://api.telegram.org/bot{token}/{method}"


class TelegramAPIError(Exception):
    """Ошибка обращения к Telegram Bot API — сетевая или логическая (ok=false)."""


def _call(token: str, method: str, params: Optional[dict] = None, *, timeout: int = 10) -> Any:
    if not token or not token.strip():
        raise TelegramAPIError("Bot Token не задан")

    url = API_URL_TMPL.format(token=token.strip(), method=method)
    body = json.dumps(params or {}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        # Telegram обычно возвращает JSON с описанием ошибки даже в теле 4xx/5xx
        try:
            payload = json.loads(exc.read().decode("utf-8"))
            desc = payload.get("description", str(exc))
        except Exception:  # noqa: BLE001
            desc = str(exc)
        raise TelegramAPIError(f"Telegram API HTTP {exc.code}: {desc}") from exc
    except urllib.error.URLError as exc:
        raise TelegramAPIError(f"Сетевая ошибка при обращении к Telegram: {exc.reason}") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise TelegramAPIError(f"Telegram API вернул нераспознаваемый ответ: {raw[:200]!r}") from exc

    if not payload.get("ok"):
        raise TelegramAPIError(f"Telegram API вернул ошибку: {payload.get('description', payload)}")

    return payload["result"]


def get_me(token: str) -> dict:
    """Проверка валидности токена. Возвращает информацию о боте (username и т.п.)."""
    return _call(token, "getMe")


def get_updates(token: str, *, offset: Optional[int] = None, timeout: int = 25) -> list[dict]:
    """
    Long-polling получение новых сообщений. offset — id последнего уже
    обработанного update+1 (Telegram-конвенция: offset подтверждает получение
    всех updates с id < offset, они не будут присланы повторно).
    """
    params: dict = {"timeout": timeout}
    if offset is not None:
        params["offset"] = offset
    return _call(token, "getUpdates", params, timeout=timeout + 10)


def extract_message_text(update: dict) -> Optional[str]:
    """Достаёт текст сообщения из update, если он там есть (игнорирует
    не-текстовые апдейты — стикеры, фото без подписи и т.п.)."""
    message = update.get("message") or update.get("channel_post")
    if not message:
        return None
    return message.get("text")
