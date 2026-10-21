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

Прокси (раздел "почему в РФ без прокси/VPN Telegram Bot API часто не
отвечает напрямую"): по умолчанию используется системный прокси
(urllib.request.getproxies() — переменные окружения HTTP_PROXY/HTTPS_PROXY,
а на Windows ещё и реестровые настройки IE). Этого достаточно, если VPN на
компьютере работает "системно" (через сетевой адаптер или системный
прокси). Если же прокси настроен только ВНУТРИ самого Telegram (частая
практика в РФ — SOCKS5-прокси, прописанный в самом Telegram-клиенте) —
такая настройка другим программам, включая эту CRM, не видна в принципе,
её нужно указать отдельно. Для этого предусмотрен явный ProxyConfig ниже,
который можно передать вторым аргументом — тогда он используется ВМЕСТО
системного прокси.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional

API_URL_TMPL = "https://api.telegram.org/bot{token}/{method}"


@dataclass
class ProxyConfig:
    """Настройки явного прокси для обращений к Telegram Bot API.

    kind — "http" (обычный HTTP(S)-прокси) или "socks5" (в т.ч. часто
    используемый для Telegram SOCKS5 с логином/паролем)."""
    kind: str  # "http" | "socks5"
    host: str
    port: int
    username: Optional[str] = None
    password: Optional[str] = None


def _build_opener(proxy: Optional[ProxyConfig]) -> urllib.request.OpenerDirector:
    if proxy is None:
        # Системный прокси/VPN (переменные окружения или реестр Windows).
        return urllib.request.build_opener(urllib.request.ProxyHandler(urllib.request.getproxies()))

    if proxy.kind == "http":
        auth = f"{proxy.username}:{proxy.password}@" if proxy.username else ""
        proxy_url = f"http://{auth}{proxy.host}:{proxy.port}"
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
        )

    if proxy.kind == "socks5":
        # Стандартный urllib не умеет SOCKS сам по себе — нужен PySocks
        # (пакет pysocks; модуль sockshandler идёт вместе с ним).
        try:
            import socks
            from sockshandler import SocksiPyHandler
        except ImportError as exc:
            raise TelegramAPIError(
                "Для SOCKS5-прокси нужен пакет PySocks. Установите его: "
                "pip install pysocks (или обратитесь за помощью, если не знаете, как это сделать)."
            ) from exc
        handler = SocksiPyHandler(
            socks.SOCKS5, proxy.host, proxy.port,
            username=proxy.username or None, password=proxy.password or None,
            rdns=True,
        )
        return urllib.request.build_opener(handler)

    raise TelegramAPIError(f"Неизвестный тип прокси: {proxy.kind!r}")


class TelegramAPIError(Exception):
    """Ошибка обращения к Telegram Bot API — сетевая или логическая (ok=false)."""


def _call(
    token: str,
    method: str,
    params: Optional[dict] = None,
    *,
    timeout: int = 10,
    proxy: Optional[ProxyConfig] = None,
) -> Any:
    if not token or not token.strip():
        raise TelegramAPIError("Bot Token не задан")

    opener = _build_opener(proxy)

    url = API_URL_TMPL.format(token=token.strip(), method=method)
    body = json.dumps(params or {}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})

    try:
        with opener.open(req, timeout=timeout) as resp:
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


def get_me(token: str, *, proxy: Optional[ProxyConfig] = None) -> dict:
    """Проверка валидности токена (и заодно — работоспособности прокси).
    Возвращает информацию о боте (username и т.п.)."""
    return _call(token, "getMe", timeout=30, proxy=proxy)


def get_updates(
    token: str, *, offset: Optional[int] = None, timeout: int = 25, proxy: Optional[ProxyConfig] = None,
) -> list[dict]:
    """
    Long-polling получение новых сообщений. offset — id последнего уже
    обработанного update+1 (Telegram-конвенция: offset подтверждает получение
    всех updates с id < offset, они не будут присланы повторно).
    """
    params: dict = {"timeout": timeout}
    if offset is not None:
        params["offset"] = offset
    return _call(token, "getUpdates", params, timeout=timeout + 10, proxy=proxy)


def extract_message_text(update: dict) -> Optional[str]:
    """Достаёт текст сообщения из update, если он там есть (игнорирует
    не-текстовые апдейты — стикеры, фото без подписи и т.п.)."""
    message = update.get("message") or update.get("channel_post")
    if not message:
        return None
    return message.get("text")
