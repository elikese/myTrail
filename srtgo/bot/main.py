"""텔레그램 봇 엔트리포인트."""

import asyncio
import logging
import os
import sys

from dotenv import load_dotenv
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from . import handlers, storage
from ..logging.setup import setup_logging

load_dotenv()

logger = logging.getLogger(__name__)


def _build_setup_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("setup", handlers.setup_entry)],
        states={
            handlers.STATE_SRT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.setup_srt),
            ],
            handlers.STATE_KTX: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.setup_ktx),
            ],
            handlers.STATE_CARD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.setup_card),
            ],
        },
        fallbacks=[CommandHandler("cancel", handlers.setup_cancel)],
    )


async def _send_restart_notice(app: Application) -> None:
    for tid in storage.list_user_ids():
        try:
            await app.bot.send_message(
                chat_id=tid,
                text="봇이 재시작됐어요. 진행 중이던 요청이 있었다면 다시 보내주세요.",
            )
        except Exception as e:
            logger.warning("재시작 알림 실패 tid=%d: %s", tid, e)


def main() -> None:
    setup_logging(debug=False)

    token = os.environ.get("BOT_TOKEN")
    if not token:
        print("BOT_TOKEN 환경변수 미설정", file=sys.stderr)
        sys.exit(1)
    if not os.environ.get("BOT_DB_KEY"):
        print("BOT_DB_KEY 환경변수 미설정 (Fernet 키)", file=sys.stderr)
        sys.exit(1)
    if not os.environ.get("BOT_CLAUDE_KEY"):
        print("BOT_CLAUDE_KEY 환경변수 미설정 (Anthropic API 키)", file=sys.stderr)
        sys.exit(1)
    if not os.environ.get("BOT_ALLOWED_IDS"):
        print("경고: BOT_ALLOWED_IDS 비어있음 — 모든 사용자 차단됨", file=sys.stderr)

    app = Application.builder().token(token).post_init(_send_restart_notice).build()

    app.add_handler(CommandHandler("start", handlers.cmd_start))
    app.add_handler(CommandHandler("help", handlers.cmd_help))
    app.add_handler(CommandHandler("cancel", handlers.cmd_cancel))
    app.add_handler(_build_setup_conversation())
    app.add_handler(CallbackQueryHandler(handlers.on_pick, pattern=r"^pick:"))
    app.add_handler(CallbackQueryHandler(handlers.on_payment_decision, pattern=r"^pay:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.on_free_message))

    logger.info("봇 polling 시작")
    app.run_polling()


if __name__ == "__main__":
    main()
