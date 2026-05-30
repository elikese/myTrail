"""에이전트 도구가 텔레그램·세션에 접근하기 위한 컨텍스트 묶음."""

from dataclasses import dataclass

from telegram import Update
from telegram.ext import ContextTypes


@dataclass
class AgentContext:
    """run_agent 한 번 처리 동안 facade 메서드에 전달되는 컨텍스트.

    tid: telegram_id. context: PTB 컨텍스트(user_data, application.bot).
    creds: storage.load(tid) 결과. today: ISO 날짜 문자열.
    """

    tid: int
    update: Update
    context: ContextTypes.DEFAULT_TYPE
    creds: dict
    today: str

    async def send(self, text: str, reply_markup=None):
        """사용자에게 메시지 전송 (도구가 버튼·안내를 띄울 때 사용)."""
        return await self.context.application.bot.send_message(
            self.tid, text, reply_markup=reply_markup
        )
