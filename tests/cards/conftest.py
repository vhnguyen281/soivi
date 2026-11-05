"""A fake Anthropic client that answers each page from saved JSON (no network, no key)."""

import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "techcombank"
TARIFF_PDF = FIXTURES / "card_tariff_2026-10-28.pdf"
PRODUCTS_HTML = FIXTURES / "card_products_2026-10-28.html"


def saved_answers(name: str) -> dict[int, dict[str, Any]]:
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return {a.pop("page"): a for a in data}


def message(data: Any, stop_reason: str = "end_turn") -> Any:
    text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return SimpleNamespace(
        stop_reason=stop_reason,
        model="claude-opus-5-5",
        content=[
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text=text),
        ],
    )


class _Stream:
    def __init__(self, reply: Any) -> None:
        self.reply = reply

    def __enter__(self) -> "_Stream":
        if isinstance(self.reply, Exception):
            raise self.reply
        return self

    def __exit__(self, *exc: object) -> None:
        pass

    def get_final_message(self) -> Any:
        return self.reply


class FakeClient:
    """Answers by the page number in the request; pages without an answer get none."""

    def __init__(self, answers: dict[int, Any]) -> None:
        self.answers = answers
        self.requests: list[dict[str, Any]] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self.stream))

    def stream(self, **kwargs: Any) -> _Stream:
        self.requests.append(kwargs)
        content = kwargs["messages"][0]["content"]
        page = int(re.findall(r'<page number="(\d+)">', content)[-1])
        reply = self.answers.get(page, {"cards": [], "rewards": [], "unlisted_cards": []})
        if isinstance(reply, Exception):
            return _Stream(reply)
        return _Stream(reply if hasattr(reply, "stop_reason") else message(reply))
