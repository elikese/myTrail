import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_update(user_id: int, text: str = ""):
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.id = user_id
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


@pytest.mark.asyncio
async def test_start_replies_to_allowed_user(monkeypatch):
    monkeypatch.setenv("BOT_ALLOWED_IDS", "111")
    from srtgo.bot import handlers

    update = _make_update(111)
    context = MagicMock()
    await handlers.cmd_start(update, context)
    update.message.reply_text.assert_called_once()
    assert "안녕" in update.message.reply_text.call_args.args[0] or \
           "환영" in update.message.reply_text.call_args.args[0]


@pytest.mark.asyncio
async def test_start_blocks_unallowed_user(monkeypatch):
    monkeypatch.setenv("BOT_ALLOWED_IDS", "111")
    from srtgo.bot import handlers

    update = _make_update(999)
    context = MagicMock()
    await handlers.cmd_start(update, context)
    update.message.reply_text.assert_called_once()
    text = update.message.reply_text.call_args.args[0]
    assert "허용" in text and "999" in text


@pytest.mark.asyncio
async def test_help_lists_commands(monkeypatch):
    monkeypatch.setenv("BOT_ALLOWED_IDS", "111")
    from srtgo.bot import handlers

    update = _make_update(111)
    await handlers.cmd_help(update, MagicMock())
    text = update.message.reply_text.call_args.args[0]
    for cmd in ["/setup", "/cancel", "/help"]:
        assert cmd in text


@pytest.mark.asyncio
async def test_setup_full_flow_saves_credentials(monkeypatch, tmp_user_dir, fernet_key):
    monkeypatch.setenv("BOT_ALLOWED_IDS", "111")
    from srtgo.bot import handlers, storage
    storage._reset_cipher_for_tests()

    context = MagicMock()
    context.user_data = {}

    # /setup 시작 → 첫 단계 SRT
    upd = _make_update(111, "/setup")
    state = await handlers.setup_entry(upd, context)
    assert state == handlers.STATE_SRT

    # SRT (skip)
    upd = _make_update(111, "skip")
    state = await handlers.setup_srt(upd, context)
    assert state == handlers.STATE_KTX

    # KTX
    upd = _make_update(111, "ktxid ktxpw")
    state = await handlers.setup_ktx(upd, context)
    assert state == handlers.STATE_CARD

    # 카드
    upd = _make_update(111, "1111222233334444 12 900101 1230")
    state = await handlers.setup_card(upd, context)
    from telegram.ext import ConversationHandler
    assert state == ConversationHandler.END

    saved = storage.load(111)
    assert "claude_key" not in saved
    assert saved["srt"] is None
    assert saved["ktx"] == {"id": "ktxid", "pw": "ktxpw"}
    assert saved["card"]["number"] == "1111222233334444"


@pytest.mark.asyncio
async def test_freemsg_parses_and_searches(monkeypatch, tmp_user_dir, fernet_key):
    monkeypatch.setenv("BOT_ALLOWED_IDS", "111")
    from srtgo.bot import handlers, storage
    storage._reset_cipher_for_tests()

    monkeypatch.setenv("BOT_CLAUDE_KEY", "sk-test")
    storage.save(111, {
        "srt": {"id": "u", "pw": "p"},
        "ktx": None,
        "card": {"number": "1", "password": "2", "birthday": "3", "expire": "4"},
    })

    intent = {
        "rail": "SRT", "dep": "부산", "arr": "서울",
        "date": "2026-05-05", "time": "180000",
        "passengers": {"adult": 1, "child": 0, "senior": 0},
        "seat_pref": "GENERAL_FIRST", "needs_clarification": [],
    }
    monkeypatch.setattr("srtgo.bot.parser.parse",
                        lambda **_kw: intent)

    train1 = MagicMock(); train1.__repr__ = lambda s: "SRT 123 18:00"
    train2 = MagicMock(); train2.__repr__ = lambda s: "SRT 125 18:30"
    rail = MagicMock(); rail.search_train.return_value = [train1, train2]
    monkeypatch.setattr("srtgo.service.auth.create_rail",
                        lambda rail_type, credentials, debug=False: rail)

    update = _make_update(111, "내일 오후 6시 부산 서울")
    context = MagicMock()
    context.user_data = {}
    await handlers.on_free_message(update, context)

    # 후보 메시지 + 인라인 키보드 호출됨
    update.message.reply_text.assert_called()
    kwargs = update.message.reply_text.call_args.kwargs
    assert "reply_markup" in kwargs
    # 세션에 검색 결과 저장
    assert context.user_data["search"]["rail"] is rail
    assert len(context.user_data["search"]["trains"]) == 2


@pytest.mark.asyncio
async def test_pick_callback_starts_polling(monkeypatch, tmp_user_dir, fernet_key):
    monkeypatch.setenv("BOT_ALLOWED_IDS", "111")
    from srtgo.bot import handlers, session as session_mod

    handlers._SESSION = session_mod.Session()  # 테스트 격리

    rail = MagicMock()
    train = MagicMock()
    context = MagicMock()
    context.user_data = {
        "search": {
            "rail": rail, "rail_type": "SRT",
            "trains": [train, train],
            "search_params": {"dep": "x", "arr": "y", "date": "20260505",
                              "time": "180000", "passengers": []},
            "seat_option": object(),
        }
    }
    context.application.bot = MagicMock()

    update = MagicMock()
    update.effective_user.id = 111
    update.effective_chat.id = 111
    update.callback_query = MagicMock()
    update.callback_query.data = "pick:0"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    # poll_and_reserve를 모킹해서 즉시 종료시킴
    monkeypatch.setattr(
        "srtgo.service.reservation.poll_and_reserve",
        lambda *a, **kw: None,
    )

    await handlers.on_pick(update, context)

    update.callback_query.edit_message_text.assert_called_once()
    text = update.callback_query.edit_message_text.call_args.args[0]
    assert "폴링" in text


@pytest.mark.asyncio
async def test_pay_confirm_charges_card(monkeypatch, tmp_user_dir, fernet_key):
    monkeypatch.setenv("BOT_ALLOWED_IDS", "111")
    from srtgo.bot import handlers, storage, session as session_mod
    storage._reset_cipher_for_tests()
    handlers._SESSION = session_mod.Session()

    storage.save(111, {
        "srt": None, "ktx": None,
        "card": {"number": "n", "password": "p", "birthday": "b", "expire": "e"},
    })

    rail = MagicMock()
    rail.pay_with_card.return_value = True
    reservation = MagicMock()
    handlers._SESSION.set_pending(111, {"reservation": reservation, "rail": rail})

    update = MagicMock()
    update.effective_user.id = 111
    update.callback_query = MagicMock()
    update.callback_query.data = "pay:confirm"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    await handlers.on_payment_decision(update, MagicMock())

    rail.pay_with_card.assert_called_once_with(reservation,
        {"number": "n", "password": "p", "birthday": "b", "expire": "e"})
    text = update.callback_query.edit_message_text.call_args.args[0]
    assert "결제 완료" in text
    assert handlers._SESSION.get_pending(111) is None


@pytest.mark.asyncio
async def test_pay_cancel_calls_rail_cancel(monkeypatch, tmp_user_dir, fernet_key):
    monkeypatch.setenv("BOT_ALLOWED_IDS", "111")
    from srtgo.bot import handlers, storage, session as session_mod
    storage._reset_cipher_for_tests()
    handlers._SESSION = session_mod.Session()
    storage.save(111, {"srt": None, "ktx": None,
                       "card": {"number": "n", "password": "p",
                                "birthday": "b", "expire": "e"}})

    rail = MagicMock()
    reservation = MagicMock()
    handlers._SESSION.set_pending(111, {"reservation": reservation, "rail": rail})

    update = MagicMock()
    update.effective_user.id = 111
    update.callback_query = MagicMock()
    update.callback_query.data = "pay:cancel"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    await handlers.on_payment_decision(update, MagicMock())

    rail.cancel.assert_called_once_with(reservation)
    assert handlers._SESSION.get_pending(111) is None


@pytest.mark.asyncio
async def test_cancel_stops_active_polling(monkeypatch):
    monkeypatch.setenv("BOT_ALLOWED_IDS", "111")
    from srtgo.bot import handlers, session as session_mod

    handlers._SESSION = session_mod.Session()

    cancel_event = threading.Event()
    async def dummy():
        await asyncio.sleep(1)
    task = asyncio.create_task(dummy())
    handlers._SESSION.start_poll(111, task, cancel_event)

    update = _make_update(111, "/cancel")
    await handlers.cmd_cancel(update, MagicMock())

    assert cancel_event.is_set()
    update.message.reply_text.assert_called()
    task.cancel()


@pytest.mark.asyncio
async def test_cancel_with_nothing_active(monkeypatch):
    monkeypatch.setenv("BOT_ALLOWED_IDS", "111")
    from srtgo.bot import handlers, session as session_mod
    handlers._SESSION = session_mod.Session()

    update = _make_update(111, "/cancel")
    await handlers.cmd_cancel(update, MagicMock())
    text = update.message.reply_text.call_args.args[0]
    assert "없습니다" in text or "없어요" in text


@pytest.mark.asyncio
async def test_setup_srt_rejects_invalid_format(monkeypatch, tmp_user_dir, fernet_key):
    monkeypatch.setenv("BOT_ALLOWED_IDS", "111")
    from srtgo.bot import handlers
    context = MagicMock()
    context.user_data = {"setup": {}}
    upd = _make_update(111, "garbage_no_space")
    state = await handlers.setup_srt(upd, context)
    assert state == handlers.STATE_SRT
    assert "형식" in upd.message.reply_text.call_args.args[0]
    assert "srt" not in context.user_data["setup"]


@pytest.mark.asyncio
async def test_on_pick_permanent_error_terminates_polling(monkeypatch, tmp_user_dir, fernet_key):
    monkeypatch.setenv("BOT_ALLOWED_IDS", "111")
    from srtgo.bot import handlers, session as session_mod
    handlers._SESSION = session_mod.Session()

    captured = {}

    def fake_poll(rail, params, indices, seat_option, on_success, on_error, cancel_event):
        # 영구 오류 테스트: on_error에 인증 관련 예외 전달
        result = on_error(Exception("Login failed"))
        captured["on_error_result"] = result

    monkeypatch.setattr("srtgo.service.reservation.poll_and_reserve", fake_poll)

    rail = MagicMock()
    train = MagicMock()
    context = MagicMock()
    context.user_data = {
        "search": {
            "rail": rail, "rail_type": "SRT",
            "trains": [train],
            "search_params": {"dep": "x", "arr": "y", "date": "20260505",
                              "time": "180000", "passengers": []},
            "seat_option": object(),
        }
    }
    context.application.bot = MagicMock()

    update = MagicMock()
    update.effective_user.id = 111
    update.callback_query = MagicMock()
    update.callback_query.data = "pick:0"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    await handlers.on_pick(update, context)
    # poll_and_reserve를 비동기로 to_thread에서 실행하기에 잠시 대기
    import asyncio as _aio
    await _aio.sleep(0.1)
    assert captured.get("on_error_result") is False


@pytest.mark.asyncio
async def test_setup_entry_warns_when_credentials_exist(monkeypatch, tmp_user_dir, fernet_key):
    monkeypatch.setenv("BOT_ALLOWED_IDS", "111")
    from srtgo.bot import handlers, storage
    storage._reset_cipher_for_tests()
    storage.save(111, {"srt": None, "ktx": None,
                       "card": {"number": "n", "password": "p",
                                "birthday": "b", "expire": "e"}})
    context = MagicMock()
    context.user_data = {}
    upd = _make_update(111, "/setup")
    state = await handlers.setup_entry(upd, context)
    assert state == handlers.STATE_SRT
    assert upd.message.reply_text.call_count == 2
    first_text = upd.message.reply_text.call_args_list[0].args[0]
    assert "이미" in first_text or "덮어" in first_text
