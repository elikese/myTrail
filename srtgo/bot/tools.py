"""LLM 도구 레지스트리 — Anthropic 도구 스키마 + DISPATCH 맵 + 시스템 프롬프트.

화이트리스트: 여기 등록된 메서드만 LLM이 호출할 수 있다.
DISPATCH 키와 TOOLS 이름은 항상 일치해야 한다(test_tools.py가 가드).
"""

from . import facade

MODEL = "claude-haiku-4-5-20251001"

_NO_ARGS = {"type": "object", "properties": {}, "additionalProperties": False}

_SEAT_PREF = {"type": "string",
              "enum": ["GENERAL_FIRST", "SPECIAL_FIRST", "GENERAL_ONLY", "SPECIAL_ONLY"]}

TOOLS = [
    {
        "name": "search_trains",
        "description": "출발지·도착지·날짜·시각이 확정되면 열차를 검색한다. 부족한 정보는 먼저 사용자에게 물어라.",
        "input_schema": {
            "type": "object",
            "required": ["rail", "dep", "arr", "date", "time"],
            "properties": {
                "rail": {"type": "string", "enum": ["SRT", "KTX"]},
                "dep": {"type": "string", "description": "출발역 한국어 이름"},
                "arr": {"type": "string", "description": "도착역 한국어 이름"},
                "date": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
                "time": {"type": "string", "pattern": r"^\d{6}$", "description": "HHMMSS, 이 시각 이후"},
                "adult": {"type": "integer", "minimum": 0},
                "child": {"type": "integer", "minimum": 0},
                "senior": {"type": "integer", "minimum": 0},
                "seat_pref": _SEAT_PREF,
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "start_booking",
        "description": "직전 search_trains 결과에서 예약할 열차를 골라 백그라운드 폴링을 시작한다. 좌석이 잡히면 별도 알림.",
        "input_schema": {
            "type": "object",
            "properties": {
                "selection": {
                    "description": "'all' 또는 1-기반 번호 배열(예: [1,3]). 생략 시 전체.",
                    "anyOf": [
                        {"type": "string", "enum": ["all"]},
                        {"type": "array", "items": {"type": "integer", "minimum": 1}},
                    ],
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_booking_progress",
        "description": "진행 중인 예매 시도의 상태를 조회한다. '아직이야?', '어떻게 됐어?', '잡았어?' 같은 질문에.",
        "input_schema": _NO_ARGS,
    },
    {
        "name": "cancel_booking",
        "description": "진행 중인 예매 시도나 결제 대기 중인 예약을 취소한다.",
        "input_schema": _NO_ARGS,
    },
    {
        "name": "list_cards",
        "description": "등록된 결제 카드 목록을 조회한다(끝 4자리만 표시).",
        "input_schema": _NO_ARGS,
    },
    {
        "name": "delete_card",
        "description": "card_id로 등록된 카드를 삭제한다(확인 버튼 표시). card_id는 list_cards로 확인.",
        "input_schema": {
            "type": "object",
            "required": ["card_id"],
            "properties": {"card_id": {"type": "string"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "pay_pending_reservation",
        "description": "좌석을 확보해 결제 대기 중인 예약을 저장된 카드로 결제한다. 카드가 여러 개면 card_id 없이 호출해 사용자가 고르게 하라.",
        "input_schema": {
            "type": "object",
            "properties": {"card_id": {"type": "string"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "get_account_status",
        "description": "어떤 철도사 자격증명과 카드가 등록돼 있는지 요약한다.",
        "input_schema": {
            "type": "object",
            "properties": {"rail": {"type": "string", "enum": ["SRT", "KTX"]}},
            "additionalProperties": False,
        },
    },
    {
        "name": "start_card_registration",
        "description": "사용자가 카드를 등록·추가하려 할 때 호출. 실제 카드번호는 보안 입력(버튼)으로 받으며 절대 대화로 받지 않는다.",
        "input_schema": _NO_ARGS,
    },
    {
        "name": "start_credential_setup",
        "description": "사용자가 철도사 로그인(아이디/비밀번호)을 등록하려 할 때 호출. 실제 비밀번호는 보안 입력(버튼)으로 받는다.",
        "input_schema": {
            "type": "object",
            "properties": {"rail": {"type": "string", "enum": ["SRT", "KTX"]}},
            "additionalProperties": False,
        },
    },
]

# 마지막 도구에 cache_control — tools 배열 전체를 프롬프트 캐시.
TOOLS[-1] = {**TOOLS[-1], "cache_control": {"type": "ephemeral"}}

DISPATCH = {
    "search_trains": facade.search_trains,
    "start_booking": facade.start_booking,
    "get_booking_progress": facade.get_booking_progress,
    "cancel_booking": facade.cancel_booking,
    "list_cards": facade.list_cards,
    "delete_card": facade.delete_card,
    "pay_pending_reservation": facade.pay_pending_reservation,
    "get_account_status": facade.get_account_status,
    "start_card_registration": facade.start_card_registration,
    "start_credential_setup": facade.start_credential_setup,
}


SYSTEM_PROMPT = """당신은 한국 SRT/KTX 기차 예매를 돕는 텔레그램 봇 에이전트입니다.
사용자와 자연스러운 한국어로 대화하면서, 필요한 도구(함수)를 호출해 실제 작업을 수행하세요.
능동적으로 사고하고, 정보가 부족하면 추측하지 말고 사용자에게 구체적으로 되물으세요.

== 사용 가능한 도구 (언제 호출하나) ==
- search_trains: 출발지·도착지·날짜·시각이 확정되면 열차를 검색. (부족하면 먼저 질문)
- start_booking: 검색 결과에서 예약할 열차가 정해지면 백그라운드 예매 시작. selection은 'all' 또는 번호 배열([1,3]).
- get_booking_progress: "아직이야?", "어떻게 됐어?", "잡았어?" 등 진행 상태를 물을 때.
- cancel_booking: 진행 중 시도나 결제 대기 예약을 취소할 때.
- pay_pending_reservation: 좌석이 확보돼 결제 대기 중일 때 결제. 카드가 여러 개면 card_id 없이 호출해 사용자가 고르게 함.
- list_cards / delete_card: 카드 목록 조회 / 삭제.
- get_account_status: 어떤 철도사·카드가 등록됐는지 확인이 필요할 때.
- start_card_registration: 사용자가 카드를 등록·추가하려 할 때. (실제 입력은 보안 버튼으로 처리)
- start_credential_setup: 사용자가 철도사 로그인을 등록하려 할 때. (보안 버튼)

== 정보 캐묻기(grilling) ==
출발지·도착지·시각 중 하나라도 불명확하면 search_trains를 호출하지 말고 한국어로 구체적으로 되물으세요.
다음은 직접 해석해 search_trains 인자를 채우세요(되묻지 말 것):
- 시각: "오후 N시"→(N+12)시 (오후 8시→"200000", 오후 1시→"130000"; 정오 12시는 그대로 "120000").
  "오전 N시"→N시("090000"), 오전 12시는 "000000". "저녁/밤"→오후, "새벽"→오전.
  "N시 M분"→"NNMMSS", "N시 반"→"NN3000". "쯤/정도/약" 같은 근사 표현도 그대로 정확 시각으로.
- 날짜: "오늘/내일/모레/다음주 X요일/이번 주말"은 today 기준 환산해 "YYYY-MM-DD"로. 언급 없으면 today.
- 철도사 미지정→"SRT". 승객 미지정→어른1. 좌석 미지정→"GENERAL_FIRST".

== 민감정보 절대 금지 ==
카드번호·카드비밀번호·생년월일·유효기간, 철도사 아이디·비밀번호를 절대 대화로 묻거나 받지 마세요.
등록이 필요하면 반드시 start_card_registration 또는 start_credential_setup만 호출하세요(보안 입력이 따로 처리합니다).

== 결과 보고 ==
도구 결과를 한국어로 간결히 요약하세요. 예매를 시작했으면 "좌석이 잡히면 알려드릴게요"처럼 비동기로
진행됨을 알리세요. 도구가 error를 반환하면 이유를 설명하고 다음 행동을 제안하세요.

오늘 날짜(today): {today}"""
