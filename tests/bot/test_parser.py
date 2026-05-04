from unittest.mock import MagicMock

import pytest


def _mock_tool_use_response(intent_dict: dict, tool_name: str = "submit_intent"):
    """Anthropic SDK 응답 mock — tool_use 블록을 반환."""
    msg = MagicMock()
    block = MagicMock()
    block.type = "tool_use"
    block.name = tool_name
    block.input = intent_dict
    msg.content = [block]
    return msg


def _mock_text_only_response(text: str):
    """tool_use 없이 텍스트만 반환하는 비정상 응답."""
    msg = MagicMock()
    block = MagicMock()
    block.type = "text"
    block.text = text
    msg.content = [block]
    return msg


def test_parse_basic_korean():
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
    fake_client.messages.create.return_value = _mock_tool_use_response(intent)

    result = parser.parse(
        text="내일 오후 6시 부산에서 서울 KTX",
        today="2026-05-04",
        api_key="sk-x",
        client=fake_client,
    )
    assert result == intent

    # tool_choice가 강제됐는지 확인
    call_kwargs = fake_client.messages.create.call_args.kwargs
    assert call_kwargs["tool_choice"] == {"type": "tool", "name": "submit_intent"}
    assert call_kwargs["tools"][0]["name"] == "submit_intent"


def test_parse_no_tool_use_block_raises():
    """모델이 tool 호출 안 하고 텍스트만 보내면 ParseError."""
    from srtgo.bot import parser

    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mock_text_only_response("그냥 답변")

    with pytest.raises(parser.ParseError, match="tool_use"):
        parser.parse(text="x", today="2026-05-04", api_key="sk", client=fake_client)


def test_parse_sdk_error_wrapped():
    """SDK 예외는 ParseError로 래핑."""
    from srtgo.bot import parser

    fake_client = MagicMock()
    fake_client.messages.create.side_effect = RuntimeError("network down")

    with pytest.raises(parser.ParseError, match="Claude API"):
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
    fake_client.messages.create.return_value = _mock_tool_use_response(intent)

    result = parser.parse("부산 서울 SRT", today="2026-05-04", api_key="sk", client=fake_client)
    assert result["needs_clarification"] == ["time"]
