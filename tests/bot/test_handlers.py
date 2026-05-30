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
    for cmd in ["/setup", "/cards", "/cancel", "/help"]:
        assert cmd in text


@pytest.mark.asyncio
async def test_setup_full_flow_saves_credentials(monkeypatch, tmp_user_dir, fernet_key):
    monkeypatch.setenv("BOT_ALLOWED_IDS", "111")
    from srtgo.bot import handlers, storage
    storage._reset_cipher_for_tests()
    monkeypatch.setattr(storage.secrets, "token_hex", lambda n: "ab12")

    context = MagicMock()
    context.user_data = {}

    upd = _make_update(111, "/setup")
    state = await handlers.setup_entry(upd, context)
    assert state == handlers.STATE_SRT

    upd = _make_update(111, "skip")
    state = await handlers.setup_srt(upd, context)
    assert state == handlers.STATE_KTX

    upd = _make_update(111, "ktxid ktxpw")
    state = await handlers.setup_ktx(upd, context)
    assert state == handlers.STATE_CARD

    upd = _make_update(111, "1111222233334444 12 900101 1230")
    state = await handlers.setup_card(upd, context)
    assert state == handlers.STATE_CARD_LABEL

    # 별칭 입력 (skip)
    upd = _make_update(111, "skip")
    state = await handlers.setup_card_label(upd, context)
    from telegram.ext import ConversationHandler
    assert state == ConversationHandler.END

    saved = storage.load(111)
    assert saved["srt"] is None
    assert saved["ktx"] == {"id": "ktxid", "pw": "ktxpw"}
    assert saved["cards"] == [{
        "id": "ab12", "label": None,
        "number": "1111222233334444", "password": "12",
        "birthday": "900101", "expire": "1230",
    }]


@pytest.mark.asyncio
async def test_freemsg_invokes_agent_with_context(monkeypatch, tmp_user_dir, fernet_key):
    monkeypatch.setenv("BOT_ALLOWED_IDS", "111")
    monkeypatch.setenv("BOT_CLAUDE_KEY", "sk-test")
    from srtgo.bot import handlers, storage
    storage._reset_cipher_for_tests()
    storage.save(111, {"srt": {"id": "u", "pw": "p"}, "ktx": None, "cards": []})

    captured = {}

    async def fake_run_agent(ctx, text, **kw):
        captured["tid"] = ctx.tid
        captured["text"] = text
        captured["creds"] = ctx.creds

    monkeypatch.setattr(handlers.agent, "run_agent", fake_run_agent)

    update = _make_update(111, "내일 오후 6시 부산 서울")
    context = MagicMock()
    context.user_data = {}
    await handlers.on_free_message(update, context)

    assert captured["tid"] == 111
    assert captured["text"] == "내일 오후 6시 부산 서울"
    assert captured["creds"]["srt"] == {"id": "u", "pw": "p"}


@pytest.mark.asyncio
async def test_freemsg_blocks_unallowed(monkeypatch):
    monkeypatch.setenv("BOT_ALLOWED_IDS", "999")
    from srtgo.bot import handlers

    update = _make_update(111, "안녕")
    context = MagicMock()
    context.user_data = {}
    await handlers.on_free_message(update, context)

    update.message.reply_text.assert_called_once()
    assert "허용되지 않은" in update.message.reply_text.call_args.args[0]


@pytest.mark.asyncio
async def test_freemsg_without_claude_key_errors(monkeypatch, tmp_user_dir, fernet_key):
    monkeypatch.setenv("BOT_ALLOWED_IDS", "111")
    monkeypatch.delenv("BOT_CLAUDE_KEY", raising=False)
    from srtgo.bot import handlers

    update = _make_update(111, "안녕")
    context = MagicMock()
    context.user_data = {}
    await handlers.on_free_message(update, context)

    update.message.reply_text.assert_called_once()
    assert "BOT_CLAUDE_KEY" in update.message.reply_text.call_args.args[0]


@pytest.mark.asyncio
async def test_pick_callback_starts_polling(monkeypatch, tmp_user_dir, fernet_key, fake_redis):
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
    assert "예약" in text


@pytest.mark.asyncio
async def test_pay_confirm_with_no_cards_keeps_pending(monkeypatch, tmp_user_dir, fernet_key):
    monkeypatch.setenv("BOT_ALLOWED_IDS", "111")
    from srtgo.bot import handlers, storage, session as session_mod
    storage._reset_cipher_for_tests()
    handlers._SESSION = session_mod.Session()

    storage.save(111, {"srt": None, "ktx": None, "cards": []})

    rail = MagicMock()
    reservation = MagicMock()
    handlers._SESSION.set_pending(111, {"reservation": reservation, "rail": rail})

    update = MagicMock()
    update.effective_user.id = 111
    update.callback_query = MagicMock()
    update.callback_query.data = "pay:confirm"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    await handlers.on_payment_decision(update, MagicMock())

    text = update.callback_query.edit_message_text.call_args.args[0]
    assert "카드" in text and "/cards" in text
    # pending 보존
    assert handlers._SESSION.get_pending(111) is not None


@pytest.mark.asyncio
async def test_pay_confirm_with_cards_shows_select_keyboard(monkeypatch, tmp_user_dir, fernet_key):
    monkeypatch.setenv("BOT_ALLOWED_IDS", "111")
    from srtgo.bot import handlers, storage, session as session_mod
    storage._reset_cipher_for_tests()
    handlers._SESSION = session_mod.Session()

    storage.save(111, {"srt": None, "ktx": None, "cards": [
        {"id": "ab12", "label": "신한", "number": "1111222233334444",
         "password": "12", "birthday": "900101", "expire": "1230"},
        {"id": "cd34", "label": None, "number": "5555666677778888",
         "password": "34", "birthday": "900202", "expire": "0631"},
    ]})

    rail = MagicMock()
    reservation = MagicMock()
    handlers._SESSION.set_pending(111, {"reservation": reservation, "rail": rail})

    update = MagicMock()
    update.effective_user.id = 111
    update.callback_query = MagicMock()
    update.callback_query.data = "pay:confirm"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    await handlers.on_payment_decision(update, MagicMock())

    kwargs = update.callback_query.edit_message_text.call_args.kwargs
    assert "reply_markup" in kwargs
    # pending 보존
    assert handlers._SESSION.get_pending(111) is not None


@pytest.mark.asyncio
async def test_pay_card_executes_payment(monkeypatch, tmp_user_dir, fernet_key):
    monkeypatch.setenv("BOT_ALLOWED_IDS", "111")
    from srtgo.bot import handlers, storage, session as session_mod
    storage._reset_cipher_for_tests()
    handlers._SESSION = session_mod.Session()

    card = {"id": "ab12", "label": "신한", "number": "1111222233334444",
            "password": "12", "birthday": "900101", "expire": "1230"}
    storage.save(111, {"srt": None, "ktx": None, "cards": [card]})

    rail = MagicMock()
    reservation = MagicMock()
    handlers._SESSION.set_pending(111, {"reservation": reservation, "rail": rail})

    monkeypatch.setattr(
        "srtgo.service.payment.pay_with_saved_card",
        lambda r, res, c: True,
    )

    update = MagicMock()
    update.effective_user.id = 111
    update.callback_query = MagicMock()
    update.callback_query.data = "pay:card:ab12"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    await handlers.on_payment_decision(update, MagicMock())

    text = update.callback_query.edit_message_text.call_args.args[0]
    assert "결제 완료" in text
    assert handlers._SESSION.get_pending(111) is None


@pytest.mark.asyncio
async def test_pay_card_handles_deleted_card(monkeypatch, tmp_user_dir, fernet_key):
    monkeypatch.setenv("BOT_ALLOWED_IDS", "111")
    from srtgo.bot import handlers, storage, session as session_mod
    storage._reset_cipher_for_tests()
    handlers._SESSION = session_mod.Session()

    storage.save(111, {"srt": None, "ktx": None, "cards": []})  # 카드 사라진 상태

    rail = MagicMock()
    reservation = MagicMock()
    handlers._SESSION.set_pending(111, {"reservation": reservation, "rail": rail})

    update = MagicMock()
    update.effective_user.id = 111
    update.callback_query = MagicMock()
    update.callback_query.data = "pay:card:ab12"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    await handlers.on_payment_decision(update, MagicMock())

    text = update.callback_query.edit_message_text.call_args.args[0]
    assert "삭제" in text
    # pending 보존
    assert handlers._SESSION.get_pending(111) is not None


@pytest.mark.asyncio
async def test_pay_back_returns_to_seat_keyboard(monkeypatch, tmp_user_dir, fernet_key):
    monkeypatch.setenv("BOT_ALLOWED_IDS", "111")
    from srtgo.bot import handlers, session as session_mod
    handlers._SESSION = session_mod.Session()

    rail = MagicMock()
    reservation = MagicMock()
    reservation.__str__ = lambda s: "RESV"
    handlers._SESSION.set_pending(111, {"reservation": reservation, "rail": rail})

    update = MagicMock()
    update.effective_user.id = 111
    update.callback_query = MagicMock()
    update.callback_query.data = "pay:back"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    await handlers.on_payment_decision(update, MagicMock())

    kwargs = update.callback_query.edit_message_text.call_args.kwargs
    assert "reply_markup" in kwargs
    assert handlers._SESSION.get_pending(111) is not None


@pytest.mark.asyncio
async def test_pay_cancel_calls_rail_cancel(monkeypatch, tmp_user_dir, fernet_key):
    monkeypatch.setenv("BOT_ALLOWED_IDS", "111")
    from srtgo.bot import handlers, storage, session as session_mod
    storage._reset_cipher_for_tests()
    handlers._SESSION = session_mod.Session()
    storage.save(111, {"srt": None, "ktx": None, "cards": []})

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
async def test_on_pick_permanent_error_terminates_polling(monkeypatch, tmp_user_dir, fernet_key, fake_redis):
    monkeypatch.setenv("BOT_ALLOWED_IDS", "111")
    from srtgo.bot import handlers, session as session_mod
    handlers._SESSION = session_mod.Session()

    captured = {}

    def fake_poll(rail, params, indices, seat_option, on_success, on_error, cancel_event, progress=None):
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
async def test_setup_entry_first_call_warns_and_ends(monkeypatch, tmp_user_dir, fernet_key):
    """기존 자격증명 있을 때 첫 /setup은 경고만 띄우고 대화 종료."""
    monkeypatch.setenv("BOT_ALLOWED_IDS", "111")
    from srtgo.bot import handlers, storage
    from telegram.ext import ConversationHandler
    storage._reset_cipher_for_tests()
    storage.save(111, {"srt": None, "ktx": None, "cards": [
        {"id": "ab12", "label": None, "number": "n", "password": "p",
         "birthday": "b", "expire": "e"}
    ]})
    context = MagicMock()
    context.user_data = {}
    upd = _make_update(111, "/setup")
    state = await handlers.setup_entry(upd, context)

    assert state == ConversationHandler.END
    assert upd.message.reply_text.call_count == 1
    text = upd.message.reply_text.call_args.args[0]
    assert "이미" in text and "/setup" in text
    assert context.user_data.get("setup_overwrite_armed") is True


@pytest.mark.asyncio
async def test_setup_entry_second_call_proceeds(monkeypatch, tmp_user_dir, fernet_key):
    """두 번째 /setup은 armed 플래그 보고 실제 진행."""
    monkeypatch.setenv("BOT_ALLOWED_IDS", "111")
    from srtgo.bot import handlers, storage
    storage._reset_cipher_for_tests()
    storage.save(111, {"srt": None, "ktx": None, "cards": [
        {"id": "ab12", "label": None, "number": "n", "password": "p",
         "birthday": "b", "expire": "e"}
    ]})
    context = MagicMock()
    context.user_data = {"setup_overwrite_armed": True}
    upd = _make_update(111, "/setup")
    state = await handlers.setup_entry(upd, context)

    assert state == handlers.STATE_SRT
    assert "setup_overwrite_armed" not in context.user_data  # 소비됨
    text = upd.message.reply_text.call_args.args[0]
    assert "1/4" in text


@pytest.mark.asyncio
async def test_setup_entry_no_existing_creds_proceeds_immediately(monkeypatch, tmp_user_dir, fernet_key):
    """기존 자격증명 없으면 첫 /setup에 바로 진행."""
    monkeypatch.setenv("BOT_ALLOWED_IDS", "111")
    from srtgo.bot import handlers, storage
    storage._reset_cipher_for_tests()
    context = MagicMock()
    context.user_data = {}
    upd = _make_update(111, "/setup")
    state = await handlers.setup_entry(upd, context)

    assert state == handlers.STATE_SRT
    text = upd.message.reply_text.call_args.args[0]
    assert "1/4" in text


@pytest.mark.asyncio
async def test_on_page_navigates_to_next_page(monkeypatch):
    """다음 페이지 콜백이 메시지·키보드를 갱신한다."""
    from srtgo.bot import handlers

    trains = [MagicMock() for _ in range(15)]
    for i, t in enumerate(trains):
        t.__repr__ = lambda s, i=i: f"train{i}"

    context = MagicMock()
    context.user_data = {
        "search": {"trains": trains, "page": 0, "rail": MagicMock(),
                   "rail_type": "SRT", "search_params": {}, "seat_option": object()},
    }

    update = MagicMock()
    update.callback_query = MagicMock()
    update.callback_query.data = "page:1"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    await handlers.on_page(update, context)

    assert context.user_data["search"]["page"] == 1
    text = update.callback_query.edit_message_text.call_args.args[0]
    assert "페이지 2/2" in text
    assert "11. train10" in text   # 두 번째 페이지의 첫 항목
    assert "15. train14" in text


@pytest.mark.asyncio
async def test_pick_all_resolves_to_current_page_indices():
    """pick:all:P 가 P 페이지의 인덱스 전부를 반환한다."""
    from srtgo.bot import handlers

    # 15개 결과, 1페이지(인덱스 10–14) 선택
    indices = handlers._resolve_indices("pick:all:1", 15)
    assert indices == [10, 11, 12, 13, 14]

    # 0페이지 (10개 가득)
    indices = handlers._resolve_indices("pick:all:0", 15)
    assert indices == [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]


@pytest.mark.asyncio
async def test_setup_card_label_with_alias_saves_label(monkeypatch, tmp_user_dir, fernet_key):
    monkeypatch.setenv("BOT_ALLOWED_IDS", "111")
    from srtgo.bot import handlers, storage
    from telegram.ext import ConversationHandler
    storage._reset_cipher_for_tests()
    monkeypatch.setattr(storage.secrets, "token_hex", lambda n: "ab12")

    context = MagicMock()
    context.user_data = {"setup": {
        "srt": None, "ktx": None,
        "_pending_card": {"number": "1111", "password": "12",
                          "birthday": "900101", "expire": "1230"},
    }}

    upd = _make_update(111, "신한")
    state = await handlers.setup_card_label(upd, context)
    assert state == ConversationHandler.END

    saved = storage.load(111)
    assert saved["cards"][0]["label"] == "신한"
    assert saved["cards"][0]["number"] == "1111"


@pytest.mark.asyncio
async def test_setup_card_label_truncates_to_32_chars(monkeypatch, tmp_user_dir, fernet_key):
    monkeypatch.setenv("BOT_ALLOWED_IDS", "111")
    from srtgo.bot import handlers, storage
    storage._reset_cipher_for_tests()
    monkeypatch.setattr(storage.secrets, "token_hex", lambda n: "ab12")

    context = MagicMock()
    context.user_data = {"setup": {
        "srt": None, "ktx": None,
        "_pending_card": {"number": "n", "password": "p",
                          "birthday": "b", "expire": "e"},
    }}

    long = "x" * 50
    upd = _make_update(111, long)
    await handlers.setup_card_label(upd, context)

    saved = storage.load(111)
    assert saved["cards"][0]["label"] == "x" * 32


def test_card_display_with_label():
    from srtgo.bot import handlers
    card = {"id": "ab12", "label": "신한", "number": "1111222233334444",
            "password": "x", "birthday": "x", "expire": "x"}
    assert handlers._card_display(card) == "신한 (*4444)"


def test_card_display_without_label():
    from srtgo.bot import handlers
    card = {"id": "ab12", "label": None, "number": "1111222233334444",
            "password": "x", "birthday": "x", "expire": "x"}
    assert handlers._card_display(card) == "*4444"


@pytest.mark.asyncio
async def test_cmd_cards_blocks_unallowed(monkeypatch):
    monkeypatch.setenv("BOT_ALLOWED_IDS", "111")
    from srtgo.bot import handlers
    update = _make_update(999)
    await handlers.cmd_cards(update, MagicMock())
    text = update.message.reply_text.call_args.args[0]
    assert "허용" in text


@pytest.mark.asyncio
async def test_cmd_cards_requires_setup(monkeypatch, tmp_user_dir, fernet_key):
    monkeypatch.setenv("BOT_ALLOWED_IDS", "111")
    from srtgo.bot import handlers, storage
    storage._reset_cipher_for_tests()
    update = _make_update(111)
    await handlers.cmd_cards(update, MagicMock())
    text = update.message.reply_text.call_args.args[0]
    assert "/setup" in text


@pytest.mark.asyncio
async def test_cmd_cards_lists_existing_cards(monkeypatch, tmp_user_dir, fernet_key):
    monkeypatch.setenv("BOT_ALLOWED_IDS", "111")
    from srtgo.bot import handlers, storage
    storage._reset_cipher_for_tests()

    storage.save(111, {"srt": None, "ktx": None, "cards": [
        {"id": "ab12", "label": "신한", "number": "1111222233334444",
         "password": "12", "birthday": "900101", "expire": "1230"},
        {"id": "cd34", "label": None, "number": "5555666677778888",
         "password": "34", "birthday": "900202", "expire": "0631"},
    ]})

    update = _make_update(111)
    await handlers.cmd_cards(update, MagicMock())

    kwargs = update.message.reply_text.call_args.kwargs
    assert "reply_markup" in kwargs
    text = update.message.reply_text.call_args.args[0]
    # 화면에 표시된 라벨이 양쪽 카드 모두 포함
    btn_texts = " ".join(
        b.text for row in kwargs["reply_markup"].inline_keyboard for b in row
    )
    combined = text + " " + btn_texts
    assert "신한" in combined
    assert "*4444" in combined
    assert "*8888" in combined


@pytest.mark.asyncio
async def test_cmd_cards_with_zero_cards_shows_only_add(monkeypatch, tmp_user_dir, fernet_key):
    monkeypatch.setenv("BOT_ALLOWED_IDS", "111")
    from srtgo.bot import handlers, storage
    storage._reset_cipher_for_tests()
    storage.save(111, {"srt": None, "ktx": None, "cards": []})

    update = _make_update(111)
    await handlers.cmd_cards(update, MagicMock())

    kwargs = update.message.reply_text.call_args.kwargs
    keyboard = kwargs["reply_markup"].inline_keyboard
    # 마지막 행에 ➕ 카드 추가 버튼
    last_row = keyboard[-1]
    assert any("추가" in btn.text for btn in last_row)


@pytest.mark.asyncio
async def test_on_cards_del_shows_confirmation(monkeypatch, tmp_user_dir, fernet_key):
    monkeypatch.setenv("BOT_ALLOWED_IDS", "111")
    from srtgo.bot import handlers, storage
    storage._reset_cipher_for_tests()
    storage.save(111, {"srt": None, "ktx": None, "cards": [
        {"id": "ab12", "label": "신한", "number": "1111222233334444",
         "password": "12", "birthday": "900101", "expire": "1230"},
    ]})

    update = MagicMock()
    update.effective_user.id = 111
    update.callback_query = MagicMock()
    update.callback_query.data = "cards:del:ab12"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    await handlers.on_cards_callback(update, MagicMock())

    text = update.callback_query.edit_message_text.call_args.args[0]
    kwargs = update.callback_query.edit_message_text.call_args.kwargs
    assert "삭제" in text
    # 카드는 아직 그대로 (확인 단계만)
    assert len(storage.list_cards(111)) == 1
    assert "reply_markup" in kwargs
    buttons = [
        b.callback_data
        for row in kwargs["reply_markup"].inline_keyboard
        for b in row
    ]
    assert "cards:del_confirm:ab12" in buttons
    assert "cards:noop" in buttons


@pytest.mark.asyncio
async def test_on_cards_del_confirm_removes_card(monkeypatch, tmp_user_dir, fernet_key):
    monkeypatch.setenv("BOT_ALLOWED_IDS", "111")
    from srtgo.bot import handlers, storage
    storage._reset_cipher_for_tests()
    storage.save(111, {"srt": None, "ktx": None, "cards": [
        {"id": "ab12", "label": "신한", "number": "1111222233334444",
         "password": "12", "birthday": "900101", "expire": "1230"},
    ]})

    update = MagicMock()
    update.effective_user.id = 111
    update.callback_query = MagicMock()
    update.callback_query.data = "cards:del_confirm:ab12"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    await handlers.on_cards_callback(update, MagicMock())

    assert storage.list_cards(111) == []
    # 화면이 목록으로 갱신됨 (카드 0장 → 추가 버튼만)
    kwargs = update.callback_query.edit_message_text.call_args.kwargs
    assert "reply_markup" in kwargs


@pytest.mark.asyncio
async def test_on_cards_noop_returns_to_list(monkeypatch, tmp_user_dir, fernet_key):
    monkeypatch.setenv("BOT_ALLOWED_IDS", "111")
    from srtgo.bot import handlers, storage
    storage._reset_cipher_for_tests()
    storage.save(111, {"srt": None, "ktx": None, "cards": [
        {"id": "ab12", "label": None, "number": "1111222233334444",
         "password": "12", "birthday": "900101", "expire": "1230"},
    ]})

    update = MagicMock()
    update.effective_user.id = 111
    update.callback_query = MagicMock()
    update.callback_query.data = "cards:noop"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    await handlers.on_cards_callback(update, MagicMock())

    # 카드 그대로 + 화면이 목록으로 복귀
    assert len(storage.list_cards(111)) == 1
    kwargs = update.callback_query.edit_message_text.call_args.kwargs
    assert "reply_markup" in kwargs


@pytest.mark.asyncio
async def test_cards_add_entry_starts_conversation(monkeypatch, tmp_user_dir, fernet_key):
    monkeypatch.setenv("BOT_ALLOWED_IDS", "111")
    from srtgo.bot import handlers, storage
    storage._reset_cipher_for_tests()
    storage.save(111, {"srt": None, "ktx": None, "cards": []})

    update = MagicMock()
    update.effective_user.id = 111
    update.callback_query = MagicMock()
    update.callback_query.data = "cards:add"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    context = MagicMock()
    context.user_data = {}

    state = await handlers.cards_add_entry(update, context)
    assert state == handlers.STATE_CARDS_NEW_FIELDS


@pytest.mark.asyncio
async def test_cards_add_full_flow(monkeypatch, tmp_user_dir, fernet_key):
    monkeypatch.setenv("BOT_ALLOWED_IDS", "111")
    from srtgo.bot import handlers, storage
    from telegram.ext import ConversationHandler
    storage._reset_cipher_for_tests()
    monkeypatch.setattr(storage.secrets, "token_hex", lambda n: "ab12")
    storage.save(111, {"srt": None, "ktx": None, "cards": []})

    context = MagicMock()
    context.user_data = {}

    # 진입 (콜백)
    cb_update = MagicMock()
    cb_update.effective_user.id = 111
    cb_update.callback_query = MagicMock()
    cb_update.callback_query.data = "cards:add"
    cb_update.callback_query.answer = AsyncMock()
    cb_update.callback_query.edit_message_text = AsyncMock()
    state = await handlers.cards_add_entry(cb_update, context)
    assert state == handlers.STATE_CARDS_NEW_FIELDS

    # 카드 4필드 입력
    upd1 = _make_update(111, "1111222233334444 12 900101 1230")
    state = await handlers.cards_add_fields(upd1, context)
    assert state == handlers.STATE_CARDS_NEW_LABEL

    # 별칭 입력
    upd2 = _make_update(111, "회사")
    state = await handlers.cards_add_label(upd2, context)
    assert state == ConversationHandler.END

    cards = storage.list_cards(111)
    assert len(cards) == 1
    assert cards[0]["label"] == "회사"
    assert cards[0]["number"] == "1111222233334444"


@pytest.mark.asyncio
async def test_cards_add_fields_rejects_bad_format(monkeypatch, tmp_user_dir, fernet_key):
    monkeypatch.setenv("BOT_ALLOWED_IDS", "111")
    from srtgo.bot import handlers
    context = MagicMock()
    context.user_data = {"cards_new": {}}
    upd = _make_update(111, "garbage")
    state = await handlers.cards_add_fields(upd, context)
    assert state == handlers.STATE_CARDS_NEW_FIELDS
    assert "형식" in upd.message.reply_text.call_args.args[0]


@pytest.mark.asyncio
async def test_cards_add_label_skip_saves_none(monkeypatch, tmp_user_dir, fernet_key):
    monkeypatch.setenv("BOT_ALLOWED_IDS", "111")
    from srtgo.bot import handlers, storage
    storage._reset_cipher_for_tests()
    monkeypatch.setattr(storage.secrets, "token_hex", lambda n: "ab12")
    storage.save(111, {"srt": None, "ktx": None, "cards": []})

    context = MagicMock()
    context.user_data = {"cards_new": {
        "number": "1111", "password": "12",
        "birthday": "900101", "expire": "1230",
    }}

    upd = _make_update(111, "skip")
    await handlers.cards_add_label(upd, context)

    cards = storage.list_cards(111)
    assert cards[0]["label"] is None
    assert "cards_new" not in context.user_data


def test_format_elapsed_seconds_minutes_hours():
    from srtgo.bot import handlers
    assert handlers._format_elapsed(0) == "0초"
    assert handlers._format_elapsed(45) == "45초"
    assert handlers._format_elapsed(312) == "5분 12초"
    assert handlers._format_elapsed(3700) == "1시간 1분 40초"


def test_format_status_message_contains_key_fields():
    """status 메시지에 경로/날짜/시도수/경과/ETA가 모두 포함된다."""
    import time as _time
    from srtgo.bot import handlers

    now = _time.time()
    progress = {
        "rail_type": "SRT",
        "dep": "부산", "arr": "서울",
        "date": "20260505", "time": "180000",
        "selected_trains": ["SRT 1810 (18:00)", "SRT 1825 (18:25)"],
        "start_time": now - 312,
        "attempts": 142,
        "last_sleep": 5.0,
        "last_sleep_set_at": now - 2,
    }
    msg = handlers._format_status_message(progress)
    assert "부산 → 서울" in msg
    assert "5/5" in msg and "SRT" in msg
    assert "18:00" in msg
    assert "SRT 1810" in msg
    assert "#142" in msg
    assert "5분 12초" in msg
    assert "다음 시도까지 ~3초" in msg


def test_cancel_registration_after_conversations():
    """Regression: cmd_cancel must be registered after both ConversationHandlers.

    Previously CommandHandler('cancel', ...) was registered before the setup and
    cards_add ConversationHandlers, so /cancel during a conversation hit the
    global cmd_cancel first and never cleared the conversation's state map.
    """
    import inspect
    from srtgo.bot import main as botmain

    source = inspect.getsource(botmain.main)
    cancel_pos = source.find('CommandHandler("cancel"')
    setup_conv_pos = source.find("_build_setup_conversation()")
    cards_conv_pos = source.find("_build_cards_add_conversation()")

    assert cancel_pos > 0, "cmd_cancel registration not found"
    assert setup_conv_pos > 0, "_build_setup_conversation registration not found"
    assert cards_conv_pos > 0, "_build_cards_add_conversation registration not found"
    assert cancel_pos > setup_conv_pos, \
        "CommandHandler('cancel', ...) must be registered AFTER _build_setup_conversation()"
    assert cancel_pos > cards_conv_pos, \
        "CommandHandler('cancel', ...) must be registered AFTER _build_cards_add_conversation()"
