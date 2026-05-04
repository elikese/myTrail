"""봇이 사용자에게 푸시 메시지 보낼 때 쓰는 헬퍼.

핸들러는 telegram Update가 있어 reply_text를 쓰면 되지만,
폴링 콜백처럼 update가 없는 경로에서는 이 모듈로 보낸다.
"""

import logging
from typing import Any

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)


def _payment_deadline_str(reservation: Any) -> str | None:
    """SRT/KTX 양쪽에서 결제 마감 시각을 추출. 없으면 None."""
    # SRT
    pd = getattr(reservation, "payment_date", None)
    pt = getattr(reservation, "payment_time", None)
    # KTX는 buy_limit_*
    if pd is None:
        pd = getattr(reservation, "buy_limit_date", None)
        pt = getattr(reservation, "buy_limit_time", None)
    if not pd or not pt or pd == "00000000":
        return None
    try:
        return f"{int(pd[4:6])}/{int(pd[6:8])} {pt[:2]}:{pt[2:4]}"
    except (ValueError, IndexError):
        return None


def format_seat_secured_message(reservation: Any) -> str:
    deadline = _payment_deadline_str(reservation)
    base = f"좌석 확보!\n{reservation}"
    if deadline:
        base += f"\n결제마감: {deadline}"
    return base


def confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ 결제", callback_data="pay:confirm"),
        InlineKeyboardButton("❌ 취소", callback_data="pay:cancel"),
    ]])


async def send_seat_secured(bot: Bot, telegram_id: int, reservation: Any) -> int:
    msg = await bot.send_message(
        chat_id=telegram_id,
        text=format_seat_secured_message(reservation),
        reply_markup=confirm_keyboard(),
    )
    return msg.message_id


async def send_text(bot: Bot, telegram_id: int, text: str) -> None:
    try:
        await bot.send_message(chat_id=telegram_id, text=text)
    except Exception as e:
        logger.error("푸시 실패 tid=%d: %s", telegram_id, e)
