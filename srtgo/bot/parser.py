"""Claude API로 자연어를 intent JSON으로 파싱.

tool use + 강제 tool_choice로 구조화된 출력을 보장한다.
"""

import logging

from anthropic import Anthropic

logger = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5-20251001"

INTENT_SCHEMA = {
    "type": "object",
    "required": ["rail", "dep", "arr", "date", "time", "passengers",
                 "seat_pref", "needs_clarification"],
    "properties": {
        "rail": {"enum": ["SRT", "KTX"]},
        "dep": {"type": "string", "minLength": 1},
        "arr": {"type": "string", "minLength": 1},
        "date": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
        "time": {"type": "string", "pattern": r"^\d{6}$"},
        "passengers": {
            "type": "object",
            "required": ["adult", "child", "senior"],
            "properties": {
                "adult": {"type": "integer", "minimum": 0},
                "child": {"type": "integer", "minimum": 0},
                "senior": {"type": "integer", "minimum": 0},
            },
        },
        "seat_pref": {"enum": ["GENERAL_FIRST", "SPECIAL_FIRST",
                                "GENERAL_ONLY", "SPECIAL_ONLY"]},
        "needs_clarification": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}

TOOL_NAME = "submit_intent"

INTENT_TOOL = {
    "name": TOOL_NAME,
    "description": "사용자가 요청한 한국 철도 예매 의도를 구조화해 제출한다.",
    "input_schema": INTENT_SCHEMA,
}

SYSTEM_PROMPT = """당신은 한국 철도 예매 봇의 의도 파서입니다.
사용자의 한국어 자연어 입력을 submit_intent 도구로 제출하세요.
도구를 반드시 호출해야 하며, 다른 형태의 응답은 허용되지 않습니다.

스키마 가이드:
- rail: "SRT" | "KTX" (사용자가 명시 안 했고 추론 불가하면 "SRT" 기본)
- dep, arr: 한국어 역명 (예: "부산", "서울", "동대구")
- date: "YYYY-MM-DD" (상대 표현은 today 기준으로 환산)
- time: "HHMMSS" (분 모르면 "000000", 시간만 있으면 시각만 채움)
- passengers: {{adult, child, senior}} (명시 없으면 adult=1)
- seat_pref: GENERAL_FIRST(일반우선) | SPECIAL_FIRST(특실우선) | GENERAL_ONLY(일반만) | SPECIAL_ONLY(특실만). 명시 없으면 GENERAL_FIRST.
- needs_clarification: 모호하거나 누락된 필드명을 배열로. 모든 게 명확하면 빈 배열 [].

today: {today}"""


class ParseError(Exception):
    """파싱 실패 (tool 미호출·SDK 거부 등)."""


def parse(
    text: str,
    today: str,
    api_key: str,
    client: Anthropic | None = None,
) -> dict:
    """자연어 → intent dict. tool use로 스키마 보장."""
    if client is None:
        client = Anthropic(api_key=api_key)

    system = SYSTEM_PROMPT.format(today=today)

    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=512,
            system=[
                {"type": "text", "text": system,
                 "cache_control": {"type": "ephemeral"}},
            ],
            tools=[INTENT_TOOL],
            tool_choice={"type": "tool", "name": TOOL_NAME},
            messages=[{"role": "user", "content": text}],
        )
    except Exception as e:
        raise ParseError(f"Claude API 호출 실패: {e}") from e

    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and block.name == TOOL_NAME:
            return dict(block.input)

    raise ParseError(f"tool_use 블록 미발견: {resp.content!r}")
