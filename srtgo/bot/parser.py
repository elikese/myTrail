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

해석 규칙 (적극적으로 추론·기본값 채우기):
- 시각 표현
  - "오후 N시" → (N+12):00 (예: 오후 8시 → 200000, 오후 1시 → 130000). N이 12면 그대로 12 (정오).
  - "오전 N시" → N:00 (예: 오전 9시 → 090000). 오전 12시는 0시 (000000).
  - "저녁/밤 N시" → 오후 취급. "새벽 N시" → 오전 취급.
  - "N시 M분" → NNMMSS. "N시 반" → NN3000.
  - "쯤", "정도", "근처", "즈음", "약", "한" 같은 근사 표현은 그대로 정확한 시각으로 처리 (모호함 ❌).
  - 시각 없이 "낮", "저녁", "밤" 같은 막연한 표현만 있을 때만 needs_clarification에 "time" 추가.
- 날짜 표현
  - "오늘"·"내일"·"모레"·"다음주 X요일"·"이번 주말" 모두 today 기준으로 환산해서 명확한 날짜로 채움.
  - 날짜 언급 없으면 today 그대로 사용 (clarification 불필요).
- 출발지·도착지
  - "부산에서 대전", "부산 → 대전", "부산서 대전", "부산 대전" 모두 dep=부산, arr=대전.
  - "찾아줘", "예매해줘", "잡아줘" 같은 동사는 무시.
  - 둘 중 하나라도 진짜 누락됐을 때만 needs_clarification.
- 철도사
  - 명시 없으면 "SRT" (clarification 불필요).
- 승객
  - 언급 없으면 adult=1, child=0, senior=0 (clarification 불필요).
- 좌석
  - 언급 없으면 GENERAL_FIRST (clarification 불필요).

needs_clarification은 진짜 정보가 없는 경우에만 채움 — 출발지·도착지·시각이 입력에 전혀 안 보일 때만.
근사 표현·기본값으로 메울 수 있는 건 절대 clarification에 넣지 마세요.

스키마 필드:
- rail: "SRT" | "KTX"
- dep, arr: 한국어 역명 (예: "부산", "서울", "동대구")
- date: "YYYY-MM-DD"
- time: "HHMMSS"
- passengers: {{adult, child, senior}}
- seat_pref: GENERAL_FIRST | SPECIAL_FIRST | GENERAL_ONLY | SPECIAL_ONLY
- needs_clarification: 빈 배열 기본, 진짜 누락된 필드명만 배열로

today: {today}

예시:
- "오늘 오후 8시쯤 부산에서 대전" → time="200000", date=today, dep="부산", arr="대전", needs_clarification=[]
- "내일 7시 반 서울→부산 KTX" → rail="KTX", date=내일, time="073000", needs_clarification=[]
- "표 잡아줘" → needs_clarification=["dep", "arr", "time"]"""


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
