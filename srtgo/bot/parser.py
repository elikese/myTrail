"""Claude API로 자연어를 intent JSON으로 파싱."""

import json
import logging

import jsonschema
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

SYSTEM_PROMPT = """당신은 한국 철도 예매 봇의 의도 파서입니다.
사용자의 한국어 자연어 입력을 아래 JSON 스키마에 맞춰 변환합니다.
오로지 JSON 객체 하나만 반환하고, 다른 텍스트는 절대 포함하지 마세요.

스키마:
- rail: "SRT" | "KTX" (사용자가 명시 안 했고 추론 불가하면 "SRT" 기본)
- dep, arr: 한국어 역명 (예: "부산", "서울", "동대구")
- date: "YYYY-MM-DD" (상대 표현은 today 기준으로 환산)
- time: "HHMMSS" (분 모르면 "000000", 시간만 있으면 시각만 채움)
- passengers: {{adult, child, senior}} (명시 없으면 adult=1)
- seat_pref: GENERAL_FIRST(일반우선) | SPECIAL_FIRST(특실우선) | GENERAL_ONLY(일반만) | SPECIAL_ONLY(특실만). 명시 없으면 GENERAL_FIRST.
- needs_clarification: 모호하거나 누락된 필드명을 배열로. 모든 게 명확하면 빈 배열 [].

today: {today}"""


class ParseError(Exception):
    """파싱 실패 (JSON 위반·스키마 위반·LLM 거부)."""


def parse(
    text: str,
    today: str,
    api_key: str,
    client: Anthropic | None = None,
) -> dict:
    """자연어 → intent dict. JSON/스키마 위반 시 1회 재시도."""
    if client is None:
        client = Anthropic(api_key=api_key)

    system = SYSTEM_PROMPT.format(today=today)
    last_err: Exception | None = None

    for attempt in range(2):
        try:
            resp = client.messages.create(
                model=MODEL,
                max_tokens=512,
                system=[
                    {"type": "text", "text": system,
                     "cache_control": {"type": "ephemeral"}},
                ],
                messages=[{"role": "user", "content": text}],
            )
            raw = resp.content[0].text
            data = json.loads(raw)
            jsonschema.validate(data, INTENT_SCHEMA)
            return data
        except (json.JSONDecodeError, jsonschema.ValidationError) as e:
            logger.warning("파싱 실패 (시도 %d): %s", attempt + 1, e)
            last_err = e

    raise ParseError(f"intent 파싱 실패: {last_err}")
