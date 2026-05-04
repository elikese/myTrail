from unittest.mock import MagicMock, patch
import json

import pytest


def _mock_anthropic_response(intent_dict: dict):
    """Anthropic SDK 응답 객체 mock — content[0].text가 JSON 문자열."""
    msg = MagicMock()
    block = MagicMock()
    block.text = json.dumps(intent_dict)
    msg.content = [block]
    return msg


def test_parse_basic_korean(monkeypatch):
    from srtgo.bot import parser

    intent = {
        "rail": "KTX",
        "dep": "부산",
        "arr": "서울",
        "date": "2026-05-05",
        "time": "180000",
        "passengers": {"adult": 1, "child": 0, "senior": 0},
        "seat_pref": "GENERAL_FIRST",
        "needs_clarification": [],
    }
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mock_anthropic_response(intent)

    result = parser.parse(
        text="내일 오후 6시 부산에서 서울 KTX",
        today="2026-05-04",
        api_key="sk-x",
        client=fake_client,
    )
    assert result == intent


def test_parse_invalid_json_retries_once_then_raises(monkeypatch):
    from srtgo.bot import parser

    bad = MagicMock()
    bad_block = MagicMock()
    bad_block.text = "this is not json"
    bad.content = [bad_block]

    fake_client = MagicMock()
    fake_client.messages.create.return_value = bad

    with pytest.raises(parser.ParseError):
        parser.parse(text="???", today="2026-05-04", api_key="sk", client=fake_client)

    # 1회 재시도 = 총 2회 호출
    assert fake_client.messages.create.call_count == 2


def test_parse_schema_violation_raises():
    from srtgo.bot import parser

    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mock_anthropic_response(
        {"rail": "INVALID", "dep": "x"}  # 필수 필드 누락
    )

    with pytest.raises(parser.ParseError):
        parser.parse(text="x", today="2026-05-04", api_key="sk", client=fake_client)


def test_parse_propagates_needs_clarification():
    from srtgo.bot import parser

    intent = {
        "rail": "SRT",
        "dep": "부산",
        "arr": "서울",
        "date": "2026-05-05",
        "time": "000000",
        "passengers": {"adult": 1, "child": 0, "senior": 0},
        "seat_pref": "GENERAL_FIRST",
        "needs_clarification": ["time"],
    }
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mock_anthropic_response(intent)

    result = parser.parse("부산 서울 SRT", today="2026-05-04", api_key="sk", client=fake_client)
    assert result["needs_clarification"] == ["time"]
