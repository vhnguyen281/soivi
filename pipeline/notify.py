"""Messages to the operator: Telegram if configured, otherwise printed.

Every attempt is recorded in the `notification` table (and sending never raises:
a Telegram outage must not stop the pipeline).
"""

import datetime as dt
from typing import Protocol

import httpx
from sqlalchemy.orm import Session

from core.config import Settings
from core.models import Notification


class Notifier(Protocol):
    channel: str

    def send(self, text: str) -> None:
        """Deliver the message or raise."""


class TelegramNotifier:
    """Bot API sendMessage. Text is Telegram HTML (escape dynamic parts)."""

    channel = "telegram"

    def __init__(
        self, token: str, chat_id: str, transport: httpx.BaseTransport | None = None
    ) -> None:
        if not token or not chat_id:
            raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are both required")
        self._url = f"https://api.telegram.org/bot{token}/sendMessage"
        self._chat_id = chat_id
        self._client = httpx.Client(timeout=15, transport=transport)

    def send(self, text: str) -> None:
        last: Exception | None = None
        for _ in range(2):
            try:
                response = self._client.post(
                    self._url,
                    json={
                        "chat_id": self._chat_id,
                        "text": text[:4000],  # Telegram's limit is 4096
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    },
                )
                body = response.json() if response.content else {}
                if response.is_success and body.get("ok"):
                    return
                # The token is in the URL: never echo the URL in errors.
                last = RuntimeError(
                    f"Telegram HTTP {response.status_code}: {body.get('description')}"
                )
            except (httpx.HTTPError, ValueError) as exc:
                last = RuntimeError(f"Telegram request failed: {type(exc).__name__}")
        assert last is not None
        raise last


class PrintNotifier:
    """Used when no Telegram bot is configured."""

    channel = "log"

    def send(self, text: str) -> None:
        print(f"[notify] {text}", flush=True)


def make_notifier(settings: Settings) -> Notifier:
    if settings.telegram_bot_token and settings.telegram_chat_id:
        return TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
    return PrintNotifier()


def notify(
    session: Session,
    notifier: Notifier,
    kind: str,
    text: str,
    *,
    source_id: int | None = None,
    now: dt.datetime | None = None,
) -> bool:
    """Send and record. Returns whether it was delivered."""
    error = None
    try:
        notifier.send(text)
    except Exception as exc:
        error = str(exc)[:500]
    session.add(
        Notification(
            kind=kind,
            channel=notifier.channel,
            text=text,
            sent_at=now or dt.datetime.now(dt.UTC),
            ok=error is None,
            error=error,
            source_id=source_id,
        )
    )
    session.flush()
    return error is None
