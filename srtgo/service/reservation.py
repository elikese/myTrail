"""예매 폴링 루프 및 좌석 가용성 판단.

UI 코드 없음. 콜백으로 상위 계층(cli)에 위임.
AbstractRail만 받음 — SRT/KTX 구체 타입 참조 금지.
"""

import logging
import time
from random import gammavariate

from ..rail.base import AbstractRail
from ..config.constants import (
    RESERVE_INTERVAL_SHAPE,
    RESERVE_INTERVAL_SCALE,
    RESERVE_INTERVAL_MIN,
)

logger = logging.getLogger(__name__)


def is_seat_available(train, seat_option) -> bool:
    """duck typing으로 SRT/KTX 모두 처리."""
    # SRT: seat_available(), general_seat_available(), special_seat_available(), reserve_standby_available()
    # KTX: has_seat(), has_general_seat(), has_special_seat(), has_waiting_list()
    if hasattr(train, "seat_available"):
        # SRT
        from ..rail.srt.models import SeatType
        if not train.seat_available():
            return train.reserve_standby_available()
        if seat_option in (SeatType.GENERAL_FIRST, SeatType.SPECIAL_FIRST):
            return train.seat_available()
        if seat_option == SeatType.GENERAL_ONLY:
            return train.general_seat_available()
        return train.special_seat_available()
    else:
        # KTX
        from ..rail.ktx.models import ReserveOption
        if not train.has_seat():
            return train.has_waiting_list()
        if seat_option in (ReserveOption.GENERAL_FIRST, ReserveOption.SPECIAL_FIRST):
            return train.has_seat()
        if seat_option == ReserveOption.GENERAL_ONLY:
            return train.has_general_seat()
        return train.has_special_seat()


def _sleep() -> None:
    interval = gammavariate(RESERVE_INTERVAL_SHAPE, RESERVE_INTERVAL_SCALE) + RESERVE_INTERVAL_MIN
    logger.debug("슬립: %.2fs", interval)
    time.sleep(interval)


def poll_and_reserve(
    rail: AbstractRail,
    search_params: dict,
    train_indices: list[int],
    seat_option,
    on_success,
    on_error,
) -> None:
    """폴링 루프.

    Args:
        rail: AbstractRail 인스턴스
        search_params: rail.search_train(**search_params) 인자
        train_indices: 선택된 열차 인덱스 목록
        seat_option: SeatType 또는 ReserveOption
        on_success: (reservation) → None 콜백 — 성공 시 호출
        on_error: (exception) → bool 콜백 — True면 계속, False면 중단
    """
    i_try = 0
    start_time = time.time()

    while True:
        i_try += 1
        elapsed = time.time() - start_time
        logger.debug("예매 시도 #%d (경과: %.0fs)", i_try, elapsed)

        try:
            trains = rail.search_train(**search_params)
            for idx in train_indices:
                if idx < len(trains) and is_seat_available(trains[idx], seat_option):
                    logger.info("좌석 확보: %s (시도 #%d)", trains[idx], i_try)
                    reservation = rail.reserve(trains[idx], option=seat_option)
                    on_success(reservation)
                    return
            _sleep()

        except Exception as e:
            logger.error("예매 폴링 중 오류: %s", e, exc_info=True)
            should_continue = on_error(e)
            if not should_continue:
                return
            _sleep()
