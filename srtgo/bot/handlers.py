"""텔레그램 봇 명령·메시지·콜백 핸들러."""

import logging
import os

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

STATE_SRT, STATE_KTX, STATE_CARD = range(3)


async def setup_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _ensure_allowed(update):
        await _block_unallowed(update)
        return ConversationHandler.END
    tid = update.effective_user.id
    if storage.exists(tid):
        await update.message.reply_text(
            "이미 등록된 자격증명이 있어요. 덮어쓰려면 다시 /setup, "
            "취소하려면 그냥 무시하세요. 계속 진행합니다 — 마지막 단계에서 저장됩니다."
        )
    context.user_data["setup"] = {}
    await update.message.reply_text(
        "자격증명 등록을 시작합니다.\n"
        "1/3: SRT 아이디·비번을 한 줄에 공백으로 구분해 보내주세요.\n"
        "사용 안 하면 'skip'. (취소: /cancel)"
    )
    return STATE_SRT


_INVALID = object()


def _parse_id_pw(text: str):
    text = text.strip()
    if text.lower() == "skip":
        return None
    parts = text.split()
    if len(parts) != 2:
        return _INVALID
    return {"id": parts[0], "pw": parts[1]}


async def setup_srt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    cred = _parse_id_pw(update.message.text)
    if cred is _INVALID:
        await update.message.reply_text("형식: 'id pw' 또는 'skip'")
        return STATE_SRT
    context.user_data["setup"]["srt"] = cred
    await update.message.reply_text(
        "2/3: KTX(코레일) 아이디·비번. 사용 안 하면 'skip'."
    )
    return STATE_KTX


async def setup_ktx(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    cred = _parse_id_pw(update.message.text)
    if cred is _INVALID:
        await update.message.reply_text("형식: 'id pw' 또는 'skip'")
        return STATE_KTX
    context.user_data["setup"]["ktx"] = cred
    await update.message.reply_text(
        "3/3: 카드 정보를 한 줄에 공백 4개로:\n"
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


import datetime as _dt

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from . import parser
from ..service import auth as svc_auth


def _seat_option_from_intent(rail_type: str, pref: str):
    if rail_type == "SRT":
        from ..rail.srt.models import SeatType
        return SeatType[pref]   # SeatType은 Enum이라 subscript OK
    else:
        from ..rail.ktx.models import ReserveOption
        return getattr(ReserveOption, pref)   # ReserveOption은 일반 class (str 상수)


def _train_keyboard(trains: list) -> InlineKeyboardMarkup:
    rows = []
    for i, t in enumerate(trains[:10]):
        rows.append([InlineKeyboardButton(f"{i+1}. {t}", callback_data=f"pick:{i}")])
    rows.append([
        InlineKeyboardButton("전부", callback_data="pick:all"),
        InlineKeyboardButton("취소", callback_data="pick:none"),
    ])
    return InlineKeyboardMarkup(rows)


async def on_free_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _ensure_allowed(update):
        await _block_unallowed(update)
        return

    tid = update.effective_user.id
    creds = storage.load(tid)
    if creds is None:
        await update.message.reply_text("자격증명 미등록. /setup 부터 해주세요.")
        return

    text = update.message.text
    today = _dt.date.today().isoformat()
    api_key = os.environ.get("BOT_CLAUDE_KEY")
    if not api_key:
        await update.message.reply_text("운영자 설정 오류: BOT_CLAUDE_KEY 미설정.")
        return

    # 직전 명확화 답변이면 이전 메시지와 합쳐서 재파싱
    pending = context.user_data.pop("pending_text", None)
    if pending:
        text = f"{pending} / {text}"

    try:
        intent = parser.parse(text=text, today=today, api_key=api_key)
    except parser.ParseError as e:
        await update.message.reply_text(f"이해 못 했어요. 다시 말해주세요.\n({e})")
        return

    if intent.get("needs_clarification"):
        # 다음 메시지 때 합치도록 현 텍스트 보관 (일회성)
        context.user_data["pending_text"] = text
        fields = ", ".join(intent["needs_clarification"])
        await update.message.reply_text(f"명확하게 알려주세요: {fields}")
        return

    rail_type = intent["rail"]
    cred = creds.get(rail_type.lower())
    if not cred:
        await update.message.reply_text(
            f"{rail_type} 자격증명 미등록. /setup 다시 해주세요."
        )
        return

    try:
        rail = svc_auth.create_rail(rail_type, credentials=cred)
    except Exception as e:
        await update.message.reply_text(f"{rail_type} 로그인 실패: {e}")
        return

    date = intent["date"].replace("-", "")
    search_params = {
        "dep": intent["dep"], "arr": intent["arr"],
        "date": date, "time": intent["time"],
        "passengers": _passengers_to_list(rail_type, intent["passengers"]),
        "include_no_seats": True,
    }
    try:
        trains = rail.search_train(**search_params)
    except Exception as e:
        await update.message.reply_text(f"검색 실패: {e}")
        return

    if not trains:
        await update.message.reply_text("해당 시간대 열차 없음.")
        return

    context.user_data["search"] = {
        "rail": rail, "rail_type": rail_type,
        "trains": trains, "search_params": search_params,
        "seat_option": _seat_option_from_intent(rail_type, intent["seat_pref"]),
    }
    await update.message.reply_text(
        "어떤 열차로 폴링할까요?",
        reply_markup=_train_keyboard(trains),
    )


def _passengers_to_list(rail_type: str, p: dict) -> list:
    """intent의 passengers dict → rail이 받는 Passenger 리스트."""
    out = []
    if rail_type == "SRT":
        from ..rail.srt.models import Adult, Child, Senior
        if p["adult"]: out.append(Adult(p["adult"]))
        if p["child"]: out.append(Child(p["child"]))
        if p["senior"]: out.append(Senior(p["senior"]))
    else:
        from ..rail.ktx.models import AdultPassenger, ChildPassenger, SeniorPassenger
        if p["adult"]: out.append(AdultPassenger(p["adult"]))
        if p["child"]: out.append(ChildPassenger(p["child"]))
        if p["senior"]: out.append(SeniorPassenger(p["senior"]))
    return out


import asyncio
import threading

from . import session as _session_mod
from . import notifier
from ..service import reservation as svc_resv


_SESSION = _session_mod.Session()


def _resolve_indices(data: str, n_trains: int) -> list[int] | None:
    """callback data → 인덱스 목록 또는 None(취소)."""
    if data == "pick:none":
        return None
    if data == "pick:all":
        return list(range(min(n_trains, 10)))
    return [int(data.removeprefix("pick:"))]


async def on_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cq = update.callback_query
    await cq.answer()
    tid = update.effective_user.id

    search = context.user_data.get("search")
    if not search:
        await cq.edit_message_text("세션 만료. 다시 요청해주세요.")
        return

    indices = _resolve_indices(cq.data, len(search["trains"]))
    if indices is None:
        await cq.edit_message_text("취소됨.")
        context.user_data.pop("search", None)
        return

    if _SESSION.is_polling(tid):
        await cq.edit_message_text("이미 진행 중인 폴링이 있어요. /cancel 후 다시.")
        return

    cancel_event = threading.Event()
    bot = context.application.bot
    loop = asyncio.get_running_loop()

    def on_success(reservation):
        _SESSION.clear_pending(tid)
        _SESSION.set_pending(tid, {"reservation": reservation, "rail": search["rail"]})
        asyncio.run_coroutine_threadsafe(
            notifier.send_seat_secured(bot, tid, reservation), loop
        )

    def on_error(exc):
        msg = str(exc)
        permanent = any(kw in msg for kw in ["로그인", "login", "Login", "인증", "Auth", "expired", "401", "403"])
        if permanent:
            asyncio.run_coroutine_threadsafe(
                notifier.send_text(bot, tid, f"폴링 중단: {msg}\n/setup 다시 해주세요."),
                loop,
            )
            return False
        return True

    async def runner():
        await asyncio.to_thread(
            svc_resv.poll_and_reserve,
            search["rail"], search["search_params"], indices,
            search["seat_option"], on_success, on_error, cancel_event,
        )

    task = asyncio.create_task(runner())
    _SESSION.start_poll(tid, task, cancel_event)
    context.user_data.pop("search", None)
    await cq.edit_message_text("폴링 시작. 좌석 잡히면 알림 드립니다.")


from ..service import payment as svc_pay


async def on_payment_decision(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cq = update.callback_query
    await cq.answer()
    tid = update.effective_user.id

    pending = _SESSION.get_pending(tid)
    if not pending:
        await cq.edit_message_text("대기 중인 예약이 없어요. 결제 마감이 지났을 수 있습니다.")
        return

    rail = pending["rail"]
    reservation = pending["reservation"]

    if cq.data == "pay:cancel":
        try:
            await asyncio.to_thread(rail.cancel, reservation)
        except Exception as e:
            logger.error("예약 취소 실패: %s", e)
        _SESSION.clear_pending(tid)
        await cq.edit_message_text("예약 취소됨.")
        return

    # pay:confirm
    creds = storage.load(tid)
    card = creds.get("card") if creds else None
    if not card:
        await cq.edit_message_text("카드 정보 없음. /setup 다시.")
        return

    try:
        ok = await asyncio.to_thread(
            svc_pay.pay_with_saved_card, rail, reservation, card
        )
    except Exception as e:
        logger.error("결제 예외: %s", e)
        await cq.edit_message_text(f"결제 실패: {e}")
        _SESSION.clear_pending(tid)
        return

    _SESSION.clear_pending(tid)
    if ok:
        await cq.edit_message_text("결제 완료. 승차권은 SRT/코레일 앱에서 확인해주세요.")
    else:
        await cq.edit_message_text("결제 실패 (카드 정보 확인 필요).")


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _ensure_allowed(update):
        await _block_unallowed(update)
        return

    tid = update.effective_user.id
    actions = []

    if _SESSION.cancel_poll(tid):
        actions.append("폴링 중단됨")

    pending = _SESSION.get_pending(tid)
    if pending:
        try:
            await asyncio.to_thread(pending["rail"].cancel, pending["reservation"])
            actions.append("대기 중 예약 취소됨")
        except Exception as e:
            actions.append(f"예약 취소 실패: {e}")
        _SESSION.clear_pending(tid)

    if not actions:
        await update.message.reply_text("진행 중인 작업이 없어요.")
    else:
        await update.message.reply_text("\n".join(actions))
