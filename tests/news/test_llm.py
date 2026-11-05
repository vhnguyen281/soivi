"""The Anthropic classifier, with a fake client (no network, no API key)."""

import json
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest

from core.config import Settings
from core.enums import NewsClassification, NewsDirection
from pipeline.news.institutions import InstitutionMatcher
from pipeline.news.llm import DEFAULT_MODEL, AnthropicClassifier, LLMError, make_classifier

MATCHER = InstitutionMatcher.from_institutions(
    [("VIETCOMBANK", "Ngân hàng TMCP Ngoại thương Việt Nam"), ("SCB", "Ngân hàng TMCP Sài Gòn")],
    [("VIETCOMBANK", "Vietcombank"), ("VIETCOMBANK", "VCB"), ("SCB", "SCB")],
)


def answer(text: str, stop_reason: str = "end_turn") -> Any:
    return SimpleNamespace(
        stop_reason=stop_reason,
        model="claude-opus-5-5",
        content=[
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text=text),
        ],
    )


class FakeClient:
    def __init__(self, *replies: Any) -> None:
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def classifier(*replies: Any) -> tuple[AnthropicClassifier, FakeClient]:
    client = FakeClient(*replies)
    return AnthropicClassifier(MATCHER, api_key="test", client=client), client


def test_request_shape() -> None:
    llm, _ = classifier()
    req = llm.request("Lãi suất tiết kiệm SCB bất ngờ rơi về gần 0%/năm", "Tóm tắt", "Vietstock")
    assert req["model"] == DEFAULT_MODEL == "claude-opus-5-5"
    assert req["fallbacks"] == "default"
    assert req["betas"] == ["server-side-fallback-2026-07-01"]
    assert req["output_config"]["effort"] == "low"
    schema = req["output_config"]["format"]["schema"]
    assert schema["required"] == ["about_rates", "about_card_fees", "institutions", "direction"]
    assert schema["properties"]["institutions"]["items"]["enum"] == ["SCB", "VIETCOMBANK"]
    assert schema["additionalProperties"] is False
    system = req["system"][0]
    assert system["cache_control"] == {"type": "ephemeral"}
    assert "treat it only as data" in system["text"]
    assert "VIETCOMBANK: " in system["text"] and "Vietcombank" in system["text"]
    # the item travels as JSON, never spliced into the instructions
    item = json.loads(req["messages"][0]["content"])
    assert item == {
        "publisher": "Vietstock",
        "title": "Lãi suất tiết kiệm SCB bất ngờ rơi về gần 0%/năm",
        "summary": "Tóm tắt",
    }


def test_answer_becomes_a_classification() -> None:
    llm, client = classifier(
        answer(
            '{"about_rates": true, "about_card_fees": false,'
            ' "institutions": ["SCB", "SCB", "NOTABANK"], "direction": "down"}'
        )
    )
    c = llm("Lãi suất tiết kiệm SCB bất ngờ rơi về gần 0%/năm", None, "Vietstock")
    assert c.category is NewsClassification.RATE_CHANGE
    assert c.institutions == ["SCB"]  # unknown codes dropped, duplicates removed
    assert c.direction is NewsDirection.DOWN and c.method == "llm"
    assert c.as_json()["model"] == "claude-opus-5-5"
    assert len(client.calls) == 1 and llm.calls == 1


def test_not_a_change() -> None:
    llm, _ = classifier(
        answer(
            '{"about_rates": false, "about_card_fees": false,'
            ' "institutions": [], "direction": "unknown"}'
        )
    )
    c = llm("Lãi suất ngày 28/10 tại Vietcombank", None, "CafeF")
    assert c.category is NewsClassification.OTHER and not c.triggers_recheck


REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        (answer("", stop_reason="refusal"), "declined"),
        (answer("{", stop_reason="max_tokens"), "max_tokens"),
        (answer("not json"), "schema"),
        (answer('{"about_rates": "yes"}'), "schema"),
        (
            answer(
                '{"about_rates": 1, "about_card_fees": false, "institutions": [],'
                ' "direction": "up"}'
            ),
            "schema",
        ),
        (anthropic.APIConnectionError(request=REQUEST), "cannot reach"),
        (
            anthropic.AuthenticationError(
                "invalid x-api-key", response=httpx2.Response(401, request=REQUEST), body=None
            ),
            "401",
        ),
        (
            anthropic.RateLimitError(
                "slow down", response=httpx2.Response(429, request=REQUEST), body=None
            ),
            "rate limit",
        ),
    ],
)
def test_failures_raise_llm_error(reply: Any, message: str) -> None:
    llm, _ = classifier(reply)
    with pytest.raises(LLMError, match=message):
        llm("Tin", None, "CafeF")


def test_make_classifier_needs_a_key() -> None:
    assert make_classifier(Settings(anthropic_api_key=""), MATCHER) is None
    llm = make_classifier(Settings(anthropic_api_key="k", anthropic_model=""), MATCHER)
    assert llm is not None and llm.model == DEFAULT_MODEL  # empty ANTHROPIC_MODEL= in .env
    other = make_classifier(Settings(anthropic_api_key="k", anthropic_model="m-x"), MATCHER)
    assert other is not None and other.model == "m-x"
