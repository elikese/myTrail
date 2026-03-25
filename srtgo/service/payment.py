"""카드 결제 서비스."""

import logging

from ..rail.base import AbstractRail
from ..config.settings import get_card_info

logger = logging.getLogger(__name__)


def pay_with_saved_card(rail: AbstractRail, reservation) -> bool:
    """저장된 카드 정보로 결제. 카드 미설정 시 False 반환."""
    card_info = get_card_info()
    if not card_info:
        logger.debug("카드 정보 미설정 — 결제 건너뜀")
        return False
    try:
        result = rail.pay_with_card(reservation, card_info)
        logger.info("카드 결제 성공: reservation=%s", reservation)
        return result
    except Exception as e:
        logger.error("카드 결제 실패: %s", e)
        raise
