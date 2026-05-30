"""화이트리스트 composite 메서드 — LLM이 호출하는 도구의 구현체.

각 메서드는 기존 service/storage/handlers 저수준 함수를 조합한다.
민감정보(카드번호·비번, 철도사 ID/PW)를 인자로 받는 메서드는 없다 — 등록은
보안 입력 플로우(ConversationHandler)를 버튼으로 트리거만 한다.

handlers의 UI 헬퍼는 순환 import 방지를 위해 함수 내부에서 lazy import한다.
"""

import asyncio
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from . import storage, memory
from ..service import auth as svc_auth
from ..service import payment as svc_pay

logger = logging.getLogger(__name__)


# --- 검색 / 예약 ---

async def search_trains(ctx, *, rail, dep, arr, date, time,
                        adult=1, child=0, senior=0, seat_pref="GENERAL_FIRST"):
    """열차를 검색해 번호 매긴 후보 목록을 돌려주고, 선택용 키보드도 게시한다."""
    from . import handlers as h

    rail_type = rail.upper()
    cred = (ctx.creds or {}).get(rail_type.lower())
    if not cred:
        return {"error": f"{rail_type} 자격증명이 등록되지 않았어요.",
                "hint": "start_credential_setup"}

    try:
        rail_obj = await asyncio.to_thread(svc_auth.create_rail, rail_type, cred)
    except Exception as e:
        return {"error": f"{rail_type} 로그인 실패: {e}"}

    search_params = {
        "dep": dep, "arr": arr, "date": date.replace("-", ""), "time": time,
        "passengers": h._passengers_to_list(
            rail_type, {"adult": adult, "child": child, "senior": senior}),
        "include_no_seats": True,
    }
    try:
        trains = await asyncio.to_thread(rail_obj.search_train, **search_params)
    except Exception as e:
        return {"error": f"검색 실패: {e}"}

    if not trains:
        return {"count": 0, "trains": [], "message": "해당 시간대 열차가 없어요."}

    ctx.context.user_data["search"] = {
        "rail": rail_obj, "rail_type": rail_type,
        "trains": trains, "search_params": search_params,
        "seat_option": h._seat_option_from_intent(rail_type, seat_pref),
        "page": 0,
    }
    await ctx.send(h._format_train_page(trains, 0),
                   reply_markup=h._train_keyboard(len(trains), 0))
    return {
        "count": len(trains),
        "trains": [{"index": i + 1, "label": h._train_short_name(t)}
                   for i, t in enumerate(trains)],
    }


async def start_booking(ctx, *, selection="all"):
    """직전 검색 결과에서 열차를 골라 백그라운드 폴링을 시작(즉시 반환)."""
    from . import handlers as h

    search = ctx.context.user_data.get("search")
    if not search:
        return {"error": "검색 결과가 없어요. 먼저 search_trains로 검색하세요."}

    n = len(search["trains"])
    if selection == "all":
        indices = list(range(n))
    else:
        indices = [i - 1 for i in selection if 1 <= i <= n]
        if not indices:
            return {"error": "유효한 열차 번호가 없어요."}

    if h._SESSION.is_polling(ctx.tid):
        return {"error": "이미 진행 중인 예약 시도가 있어요. 먼저 취소(cancel_booking)하세요."}

    await h._launch_booking(ctx.tid, ctx.context, search, indices)
    ctx.context.user_data.pop("search", None)
    return {"status": "started",
            "selected": [h._train_short_name(search["trains"][i]) for i in indices]}


async def get_booking_progress(ctx):
    """진행 중인 예약 시도 상태. 라이브 세션 우선, 없으면 Redis 스냅샷."""
    from . import handlers as h

    progress = h._SESSION.get_progress(ctx.tid)
    if progress is not None:
        return {"state": "polling", "status_text": h._format_status_message(progress)}
    if h._SESSION.get_pending(ctx.tid) is not None:
        return {"state": "pending_payment", "message": "좌석을 확보해 결제 대기 중이에요."}

    snap = await memory.get_progress_snapshot(ctx.tid)
    if snap is not None:
        return {"state": "stale", "note": "재시작 전 정보일 수 있어요.",
                "dep": snap.get("dep"), "arr": snap.get("arr"),
                "selected_trains": snap.get("selected_trains")}
    if await memory.get_pending_summary(ctx.tid) is not None:
        return {"state": "pending_payment", "note": "재시작 전 정보일 수 있어요."}
    return {"state": "idle", "message": "진행 중인 작업이 없어요."}


async def cancel_booking(ctx):
    """진행 중 시도 중단 + 결제 대기 예약 취소."""
    from . import handlers as h

    actions = []
    if h._SESSION.cancel_poll(ctx.tid):
        actions.append("예약 시도 중단")
    await memory.clear_progress_snapshot(ctx.tid)

    pending = h._SESSION.get_pending(ctx.tid)
    if pending:
        try:
            await asyncio.to_thread(pending["rail"].cancel, pending["reservation"])
            actions.append("대기 중 예약 취소")
        except Exception as e:
            actions.append(f"예약 취소 실패: {e}")
        h._SESSION.clear_pending(ctx.tid)
        await memory.clear_pending_summary(ctx.tid)

    if not actions:
        return {"status": "nothing", "message": "진행 중인 작업이 없어요."}
    return {"status": "cancelled", "actions": actions}


# --- 카드 / 결제 ---

async def list_cards(ctx):
    """등록된 카드 목록 (마스킹 — 끝 4자리만)."""
    from . import handlers as h
    cards = storage.list_cards(ctx.tid)
    return {"cards": [{"id": c["id"], "display": h._card_display(c)} for c in cards]}


async def delete_card(ctx, *, card_id):
    """카드 삭제 — 확인 버튼을 띄운다(기존 cards:del_confirm 플로우 재사용)."""
    from . import handlers as h
    card = storage.get_card(ctx.tid, card_id)
    if card is None:
        return {"error": "해당 카드를 찾을 수 없어요.", "card_id": card_id}
    await ctx.send(f"정말 삭제할까요?\n  {h._card_display(card)}",
                   reply_markup=h._del_confirm_keyboard(card_id))
    return {"status": "awaiting_confirm", "card": h._card_display(card)}


async def pay_pending_reservation(ctx, *, card_id=None):
    """결제 대기 예약을 저장된 카드로 결제. card_id 없으면 선택 키보드를 띄운다."""
    from . import handlers as h

    pending = h._SESSION.get_pending(ctx.tid)
    if not pending:
        return {"error": "대기 중인 예약이 없어요. 결제 마감이 지났을 수 있어요."}

    cards = storage.list_cards(ctx.tid)
    if not cards:
        return {"error": "등록된 카드가 없어요.", "hint": "start_card_registration"}

    cards_view = [{"id": c["id"], "display": h._card_display(c)} for c in cards]
    if card_id is None:
        await ctx.send("어느 카드로 결제할까요?",
                       reply_markup=h._card_select_keyboard(cards))
        return {"status": "choose_card", "cards": cards_view}

    card = storage.get_card(ctx.tid, card_id)
    if card is None:
        return {"error": "그 카드는 없어요. 다시 선택해주세요.", "cards": cards_view}

    try:
        ok = await asyncio.to_thread(
            svc_pay.pay_with_saved_card, pending["rail"], pending["reservation"], card)
    except Exception as e:
        h._SESSION.clear_pending(ctx.tid)
        await memory.clear_pending_summary(ctx.tid)
        return {"error": f"결제 실패: {e}"}

    h._SESSION.clear_pending(ctx.tid)
    await memory.clear_pending_summary(ctx.tid)
    return {"paid": bool(ok)}


# --- 계정 상태 ---

async def get_account_status(ctx, *, rail=None):
    """등록된 철도사·카드 수 요약 — 에이전트가 가능한 작업을 파악하는 용도."""
    creds = ctx.creds or {}
    return {
        "srt_registered": bool(creds.get("srt")),
        "ktx_registered": bool(creds.get("ktx")),
        "card_count": len(storage.list_cards(ctx.tid)),
    }


# --- 민감정보 트리거 전용 (인자로 민감정보를 받지 않음) ---

async def start_card_registration(ctx):
    """카드 등록 — 보안 입력 버튼만 띄운다(카드번호는 LLM을 거치지 않음)."""
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("➕ 카드 추가", callback_data="cards:add")]])
    await ctx.send("카드 정보는 보안을 위해 아래 버튼으로 직접 입력받아요. "
                   "대화창에 카드번호를 적지 마세요.", reply_markup=kb)
    return {"status": "prompt_sent"}


async def start_credential_setup(ctx, *, rail=None):
    """철도사 로그인 등록 — 보안 입력 버튼만 띄운다(비밀번호는 LLM을 거치지 않음)."""
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔐 로그인 등록 시작", callback_data="setup:start")]])
    await ctx.send("철도사 아이디·비밀번호는 보안 입력으로 받아요. 아래 버튼을 눌러주세요.",
                   reply_markup=kb)
    return {"status": "prompt_sent"}
