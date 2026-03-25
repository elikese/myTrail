"""HTTP 응답(JSON 문자열 또는 dict) → 모델 변환.

HTTP 요청 코드 없음. 파싱 실패 시 logger.error로 필드명과 raw 응답을 기록하고 예외 발생.
"""

import json
import logging

from .models import (
    KorailError, NeedToLoginError, NoResultsError, SoldOutError,
    Train, Ticket, Reservation, Seat,
)

logger = logging.getLogger(__name__)


def _load(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error("JSON 파싱 실패: %s | raw=%s", e, raw[:200])
        raise


def check_result(j: dict) -> bool:
    """응답 dict의 strResult 검사. FAIL이면 적절한 예외 발생."""
    if j.get("strResult") == "FAIL":
        h_msg_cd = j.get("h_msg_cd")
        h_msg_txt = j.get("h_msg_txt")
        logger.error("Korail API 오류: code=%s msg=%s", h_msg_cd, h_msg_txt)
        for error_cls in (NoResultsError, NeedToLoginError, SoldOutError):
            if h_msg_cd in error_cls.codes:
                raise error_cls(h_msg_cd)
        raise KorailError(h_msg_txt, h_msg_cd)
    return True


# --- 열차 ---

def parse_train(data: dict) -> Train:
    try:
        return Train(data)
    except (KeyError, TypeError) as e:
        logger.error(
            "열차 파싱 실패 - 필드명 변경 가능성: missing_field=%s raw=%s", e, data
        )
        raise


def parse_trains(raw: str, include_no_seats: bool = False, include_waiting_list: bool = False) -> list[Train]:
    j = _load(raw)
    check_result(j)

    trains = [
        parse_train(info)
        for info in j.get("trn_infos", {}).get("trn_info", [])
    ]
    logger.debug("열차 파싱: total=%d", len(trains))

    filter_fns = [lambda x: x.has_seat()]
    if include_no_seats:
        filter_fns.append(lambda x: not x.has_seat())
    if include_waiting_list:
        filter_fns.append(lambda x: x.has_waiting_list())

    result = [t for t in trains if any(f(t) for f in filter_fns)]
    if not result:
        raise NoResultsError()
    return result


# --- 티켓 ---

def parse_ticket(data: dict) -> Ticket:
    try:
        return Ticket(data)
    except (KeyError, TypeError) as e:
        logger.error(
            "티켓 파싱 실패 - 필드명 변경 가능성: missing_field=%s raw=%s", e, data
        )
        raise


def parse_tickets(raw: str) -> list[Ticket]:
    j = _load(raw)
    try:
        check_result(j)
    except NoResultsError:
        return []
    tickets = [parse_ticket(info) for info in j.get("reservation_list", [])]
    logger.debug("티켓 파싱: count=%d", len(tickets))
    return tickets


# --- 좌석 ---

def parse_seats(raw: str) -> tuple[list[Seat], str | None]:
    """(seats, wct_no) 반환."""
    j = _load(raw)
    try:
        check_result(j)
    except NoResultsError:
        return [], None

    wct_no = j.get("h_wct_no")
    seats = []
    if jrny_info := j.get("jrny_infos", {}).get("jrny_info", []):
        if seat_info := jrny_info[0].get("seat_infos", {}).get("seat_info", []):
            seats = [Seat(s) for s in seat_info]
    logger.debug("좌석 파싱: count=%d", len(seats))
    return seats, wct_no


# --- 예약 ---

def parse_reservation(data: dict) -> Reservation:
    try:
        return Reservation(data)
    except (KeyError, TypeError) as e:
        logger.error(
            "예약 파싱 실패 - 필드명 변경 가능성: missing_field=%s raw=%s", e, data
        )
        raise


def parse_reservations(raw: str) -> list[Reservation]:
    j = _load(raw)
    try:
        check_result(j)
    except NoResultsError:
        return []

    reservations = []
    for info in j.get("jrny_infos", {}).get("jrny_info", []):
        for tinfo in info.get("train_infos", {}).get("train_info", []):
            reservations.append(parse_reservation(tinfo))
    logger.debug("예약 파싱: count=%d", len(reservations))
    return reservations


def get_reservation_id(raw: str) -> str | None:
    j = _load(raw)
    check_result(j)
    return j.get("h_pnr_no")
