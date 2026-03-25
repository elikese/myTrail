"""HTTP 응답(JSON 문자열 또는 dict) → 모델 변환.

HTTP 요청 코드 없음. 파싱 실패 시 logger.error로 필드명과 raw 응답을 기록하고 예외 발생.
"""

import json
import logging

from .models import SRTResponseError, SRTError, SRTTrain, SRTTicket, SRTReservation

logger = logging.getLogger(__name__)


# --- 응답 유효성 검사 ---

def parse_response(raw: str) -> dict:
    """raw JSON 문자열 → resultMap[0] dict 반환."""
    try:
        j = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error("JSON 파싱 실패: %s | raw=%s", e, raw[:200])
        raise

    if "resultMap" in j:
        return j["resultMap"][0]

    if "ErrorCode" in j and "ErrorMsg" in j:
        raise SRTResponseError(
            f'[{j["ErrorCode"]}]: {j["ErrorMsg"]}'
        )
    raise SRTError(f"Unexpected response structure: {j}")


def check_success(status: dict) -> bool:
    result = status.get("strResult")
    if result is None:
        raise SRTResponseError("Response status is not given")
    if result == "SUCC":
        return True
    if result == "FAIL":
        return False
    raise SRTResponseError(f'Undefined result status "{result}"')


def get_message(status: dict) -> str:
    return status.get("msgTxt", "")


def get_full_json(raw: str) -> dict:
    """raw JSON 전체를 dict로 반환 (payment, reserve_info 등 resultMap 없는 응답용)."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error("JSON 파싱 실패: %s | raw=%s", e, raw[:200])
        raise


# --- 열차 ---

def parse_train(data: dict) -> SRTTrain:
    try:
        return SRTTrain(data)
    except KeyError as e:
        logger.error(
            "열차 파싱 실패 - 필드명 변경 가능성: missing_field=%s raw=%s", e, data
        )
        raise


def parse_trains(raw: str) -> list[SRTTrain]:
    j = get_full_json(raw)
    status = parse_response(raw)

    if not check_success(status):
        raise SRTResponseError(get_message(status))

    train_list = j.get("outDataSets", {}).get("dsOutput1", [])
    logger.debug("열차 목록 파싱: count=%d", len(train_list))
    return [
        parse_train(t)
        for t in train_list
        if t.get("stlbTrnClsfCd") == "17"  # SRT만 필터
    ]


# --- 티켓 ---

def parse_ticket(data: dict) -> SRTTicket:
    try:
        return SRTTicket(data)
    except (KeyError, TypeError) as e:
        logger.error(
            "티켓 파싱 실패 - 필드명 변경 가능성: missing_field=%s raw=%s", e, data
        )
        raise


def parse_tickets(raw: str) -> list[SRTTicket]:
    status = parse_response(raw)
    if not check_success(status):
        raise SRTResponseError(get_message(status))

    j = get_full_json(raw)
    ticket_list = j.get("trainListMap", [])
    logger.debug("티켓 파싱: count=%d", len(ticket_list))
    return [parse_ticket(t) for t in ticket_list]


# --- 예약 ---

def parse_reservation(train_data: dict, pay_data: dict, tickets: list) -> SRTReservation:
    try:
        return SRTReservation(train_data, pay_data, tickets)
    except (KeyError, TypeError) as e:
        logger.error(
            "예약 파싱 실패 - 필드명 변경 가능성: missing_field=%s", e
        )
        raise


def parse_reservations(raw: str, ticket_fetcher) -> list[SRTReservation]:
    """ticket_fetcher: pnrNo → list[SRTTicket] 콜백 (client가 제공)."""
    status = parse_response(raw)
    if not check_success(status):
        raise SRTResponseError(get_message(status))

    j = get_full_json(raw)
    train_list = j.get("trainListMap", [])
    pay_list = j.get("payListMap", [])
    logger.debug("예약 파싱: count=%d", len(train_list))

    return [
        parse_reservation(train, pay, ticket_fetcher(train["pnrNo"]))
        for train, pay in zip(train_list, pay_list)
    ]


def get_reservation_number(raw: str) -> str:
    """reserve API 응답에서 예약번호 추출."""
    j = get_full_json(raw)
    status = parse_response(raw)
    if not check_success(status):
        raise SRTResponseError(get_message(status))
    return j["reservListMap"][0]["pnrNo"]
