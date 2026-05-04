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


from telegram.ext import ConversationHandler

from . import storage

STATE_CLAUDE_KEY, STATE_SRT, STATE_KTX, STATE_CARD = range(4)


async def setup_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _ensure_allowed(update):
        await _block_unallowed(update)
        return ConversationHandler.END
    context.user_data["setup"] = {}
    await update.message.reply_text(
        "자격증명 등록을 시작합니다.\n"
        "1/4: Anthropic Claude API 키를 보내주세요. (취소: /cancel)"
    )
    return STATE_CLAUDE_KEY


async def setup_claude_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["setup"]["claude_key"] = update.message.text.strip()
    await update.message.reply_text(
        "2/4: SRT 아이디·비번을 한 줄에 공백으로 구분해 보내주세요.\n"
        "사용 안 하면 'skip'."
    )
    return STATE_SRT


def _parse_id_pw(text: str) -> dict | None:
    text = text.strip()
    if text.lower() == "skip":
        return None
    parts = text.split()
    if len(parts) != 2:
        return None
    return {"id": parts[0], "pw": parts[1]}


async def setup_srt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    cred = _parse_id_pw(update.message.text)
    if cred is False:  # 형식 잘못
        await update.message.reply_text("형식: 'id pw' 또는 'skip'")
        return STATE_SRT
    context.user_data["setup"]["srt"] = cred
    await update.message.reply_text(
        "3/4: KTX(코레일) 아이디·비번. 사용 안 하면 'skip'."
    )
    return STATE_KTX


async def setup_ktx(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["setup"]["ktx"] = _parse_id_pw(update.message.text)
    await update.message.reply_text(
        "4/4: 카드 정보를 한 줄에 공백 4개로:\n"
        "  카드번호 비번앞2자리 생년월일(YYMMDD) 만료(MMYY)\n"
        "예: 1111222233334444 12 900101 1230"
    )
    return STATE_CARD


async def setup_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    parts = update.message.text.strip().split()
    if len(parts) != 4:
        await update.message.reply_text("형식이 잘못됐어요. 4개 항목을 공백으로.")
        return STATE_CARD
    number, password, birthday, expire = parts
    context.user_data["setup"]["card"] = {
        "number": number, "password": password,
        "birthday": birthday, "expire": expire,
    }
    storage.save(update.effective_user.id, context.user_data["setup"])
    context.user_data.pop("setup", None)
    await update.message.reply_text("등록 완료. 이제 자유롭게 말해보세요.")
    return ConversationHandler.END


async def setup_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("setup", None)
    await update.message.reply_text("등록 취소됨.")
    return ConversationHandler.END
