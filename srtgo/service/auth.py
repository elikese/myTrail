"""로그인 / 재로그인 처리.

rail 팩토리 함수(create_rail)가 유일한 SRT/KTX 분기점.
이후 모든 계층은 AbstractRail 타입으로만 다룬다.
"""

import logging

from ..rail.base import AbstractRail
from ..config.settings import get_rail_credential, set_rail_credential

logger = logging.getLogger(__name__)


def create_rail(
    rail_type: str,
    credentials: dict | None = None,
    debug: bool = False,
) -> AbstractRail:
    """rail_type에 따라 SRT 또는 Korail 인스턴스 반환 — 유일한 분기점.

    credentials: {"id": str, "pw": str}. None이면 keyring에서 fallback.
    """
    if credentials is not None:
        user_id, password = credentials["id"], credentials["pw"]
    else:
        user_id, password = get_rail_credential(rail_type)
    if not user_id or not password:
        raise ValueError(f"{rail_type} 자격증명이 설정되지 않았습니다")

    if rail_type == "SRT":
        from ..rail.srt.client import SRT
        return SRT(user_id, password, verbose=debug)
    else:
        from ..rail.ktx.client import Korail
        return Korail(user_id, password, verbose=debug)


def ensure_login(rail: AbstractRail, rail_type: str, debug: bool = False) -> AbstractRail:
    """세션이 만료된 경우 재로그인하여 유효한 인스턴스를 반환."""
    if rail.is_login:
        return rail
    logger.warning("세션 만료 감지, 재로그인 시도: rail_type=%s", rail_type)
    try:
        new_rail = create_rail(rail_type, debug=debug)
        logger.info("재로그인 성공: rail_type=%s", rail_type)
        return new_rail
    except Exception as e:
        logger.error("재로그인 실패: %s", e)
        raise
