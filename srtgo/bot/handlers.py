"""텔레그램 봇 명령·메시지·콜백 핸들러."""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from . import auth_guard

logger = logging.getLogger(__name__)


HELP_TEXT = (
    "사용법:\n"
    "/setup — 자격증명 등록 (Claude API 키, 철도사 ID/PW, 카드)\n"
    "/cancel — 진행 중 폴링·예약 취소\n"
    "/help — 도움말\n\n"
    "그 외에는 자유롭게 말하세요. 예: '내일 오후 6시 부산에서 서울 KTX'"
)

WELCOME_TEXT = (
    "환영합니다. 먼저 /setup 으로 자격증명을 등록해주세요.\n\n"
    + HELP_TEXT
)


def _ensure_allowed(update: Update) -> bool:
    tid = update.effective_user.id
    if not auth_guard.is_allowed(tid):
        return False
    return True


async def _block_unallowed(update: Update) -> None:
    tid = update.effective_user.id
    await update.message.reply_text(
        f"허용되지 않은 사용자입니다.\n당신의 텔레그램 ID: {tid}\n"
        "관리자에게 이 ID를 전달해주세요."
    )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _ensure_allowed(update):
        await _block_unallowed(update)
        return
    await update.message.reply_text(WELCOME_TEXT)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _ensure_allowed(update):
        await _block_unallowed(update)
        return
    await update.message.reply_text(HELP_TEXT)
