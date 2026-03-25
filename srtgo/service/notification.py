"""텔레그램 알림 서비스."""

import asyncio
import logging

import telegram

from ..config.settings import get_telegram_config

logger = logging.getLogger(__name__)


async def _send(token: str, chat_id: str, text: str) -> None:
    bot = telegram.Bot(token=token)
    async with bot:
        await bot.send_message(chat_id=chat_id, text=text)


def send_telegram(text: str) -> None:
    """텔레그램으로 메시지 전송. 설정이 없거나 실패해도 예외 발생 안 함."""
    token, chat_id = get_telegram_config()
    if not (token and chat_id):
        return
    try:
        asyncio.run(_send(token, chat_id, text))
    except Exception as e:
        logger.warning("텔레그램 전송 실패: %s", e)
