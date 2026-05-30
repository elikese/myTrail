"""srtgo.bot.facade — 화이트리스트 composite 메서드 테스트."""

import json
import types
from unittest.mock import AsyncMock, MagicMock


def _ctx(tid=111, creds=None):
    from srtgo.bot.agent_context import AgentContext
    context = MagicMock()
    context.user_data = {}
    context.application.bot = MagicMock()
    ctx = AgentContext(tid=tid, update=MagicMock(), context=context,
                       creds=creds or {}, today="2026-06-01")
    ctx.send = AsyncMock()
    return ctx


def _train(no="101"):
    return types.SimpleNamespace(train_number=no, train_name="KTX", dep_time="1800")


def _fresh_session():
    from srtgo.bot import handlers, session as session_mod
    handlers._SESSION = session_mod.Session()
    return handlers._SESSION


# --- AgentContext.send ---

async def test_agent_context_send_uses_bot():
    from srtgo.bot.agent_context import AgentContext
    context = MagicMock()
    context.application.bot.send_message = AsyncMock()
    ctx = AgentContext(tid=42, update=MagicMock(), context=context,
                       creds={}, today="2026-06-01")
    await ctx.send("안녕", reply_markup="kb")
    context.application.bot.send_message.assert_awaited_once_with(42, "안녕", reply_markup="kb")


# --- search_trains ---

async def test_search_trains_composes_and_posts_keyboard(monkeypatch, fake_redis):
    from srtgo.bot import facade
    fake_rail = types.SimpleNamespace(search_train=lambda **kw: [_train("1"), _train("2")])
    monkeypatch.setattr(facade.svc_auth, "create_rail", lambda rt, cred, **k: fake_rail)

    ctx = _ctx(creds={"srt": {"id": "u", "pw": "p"}})
    out = await facade.search_trains(ctx, rail="SRT", dep="부산", arr="서울",
                                     date="2026-06-01", time="180000")

    assert out["count"] == 2
    assert len(out["trains"]) == 2 and out["trains"][0]["index"] == 1
    assert ctx.context.user_data["search"]["rail_type"] == "SRT"
    ctx.send.assert_awaited()  # 번호 키보드 게시


async def test_search_trains_no_creds_returns_error(fake_redis):
    from srtgo.bot import facade
    ctx = _ctx(creds={})
    out = await facade.search_trains(ctx, rail="SRT", dep="부산", arr="서울",
                                     date="2026-06-01", time="180000")
    assert "error" in out
    ctx.send.assert_not_awaited()


async def test_search_trains_no_trains(monkeypatch, fake_redis):
    from srtgo.bot import facade
    fake_rail = types.SimpleNamespace(search_train=lambda **kw: [])
    monkeypatch.setattr(facade.svc_auth, "create_rail", lambda rt, cred, **k: fake_rail)
    ctx = _ctx(creds={"srt": {"id": "u", "pw": "p"}})
    out = await facade.search_trains(ctx, rail="SRT", dep="부산", arr="서울",
                                     date="2026-06-01", time="180000")
    assert out["count"] == 0


# --- start_booking ---

async def test_start_booking_delegates_to_launch(monkeypatch, fake_redis):
    from srtgo.bot import facade, handlers
    _fresh_session()
    launched = {}

    async def fake_launch(tid, context, search, indices):
        launched["tid"] = tid
        launched["indices"] = indices

    monkeypatch.setattr(handlers, "_launch_booking", fake_launch)

    ctx = _ctx()
    ctx.context.user_data["search"] = {
        "rail_type": "SRT", "trains": [_train("1"), _train("2"), _train("3")],
        "search_params": {"dep": "x", "arr": "y", "date": "20260601", "time": "180000"},
    }
    out = await facade.start_booking(ctx, selection=[1, 3])

    assert out["status"] == "started"
    assert launched["indices"] == [0, 2]
    assert "search" not in ctx.context.user_data


async def test_start_booking_no_search_errors(fake_redis):
    from srtgo.bot import facade
    _fresh_session()
    out = await facade.start_booking(_ctx())
    assert "error" in out


async def test_start_booking_already_polling_guard(monkeypatch, fake_redis):
    from srtgo.bot import facade, handlers
    sess = _fresh_session()
    monkeypatch.setattr(sess, "is_polling", lambda tid: True)
    ctx = _ctx()
    ctx.context.user_data["search"] = {"trains": [_train()], "rail_type": "SRT",
                                       "search_params": {}}
    out = await facade.start_booking(ctx)
    assert "error" in out


# --- list_cards (masking) ---

async def test_list_cards_masks_number(tmp_user_dir, fernet_key):
    from srtgo.bot import facade, storage
    storage.save(111, {"srt": None, "ktx": None, "cards": [
        {"id": "ab12", "label": "신한", "number": "1111222233334444",
         "password": "12", "birthday": "900101", "expire": "1230"},
    ]})
    out = await facade.list_cards(_ctx())

    assert set(out["cards"][0]) == {"id", "display"}
    assert out["cards"][0]["display"] == "신한 (*4444)"
    assert "1111222233334444" not in json.dumps(out, ensure_ascii=False)


# --- delete_card ---

async def test_delete_card_posts_confirm(tmp_user_dir, fernet_key):
    from srtgo.bot import facade, storage
    storage.save(111, {"srt": None, "ktx": None, "cards": [
        {"id": "ab12", "label": None, "number": "n", "password": "p",
         "birthday": "b", "expire": "e"}]})
    ctx = _ctx()
    out = await facade.delete_card(ctx, card_id="ab12")
    assert out["status"] == "awaiting_confirm"
    markup = ctx.send.call_args.kwargs["reply_markup"]
    assert markup.inline_keyboard[0][0].callback_data == "cards:del_confirm:ab12"


async def test_delete_card_unknown(tmp_user_dir, fernet_key):
    from srtgo.bot import facade, storage
    storage.save(111, {"srt": None, "ktx": None, "cards": []})
    out = await facade.delete_card(_ctx(), card_id="nope")
    assert "error" in out


# --- pay_pending_reservation ---

async def test_pay_no_pending(fake_redis):
    from srtgo.bot import facade
    _fresh_session()
    out = await facade.pay_pending_reservation(_ctx())
    assert "error" in out


async def test_pay_no_cards_hints_registration(tmp_user_dir, fernet_key, fake_redis):
    from srtgo.bot import facade, storage
    sess = _fresh_session()
    sess.set_pending(111, {"reservation": MagicMock(), "rail": MagicMock()})
    storage.save(111, {"srt": None, "ktx": None, "cards": []})
    out = await facade.pay_pending_reservation(_ctx())
    assert out.get("hint") == "start_card_registration"


async def test_pay_no_card_id_posts_select(tmp_user_dir, fernet_key, fake_redis):
    from srtgo.bot import facade, storage
    sess = _fresh_session()
    sess.set_pending(111, {"reservation": MagicMock(), "rail": MagicMock()})
    storage.save(111, {"srt": None, "ktx": None, "cards": [
        {"id": "ab12", "label": "신한", "number": "1111222233334444",
         "password": "12", "birthday": "900101", "expire": "1230"}]})
    ctx = _ctx()
    out = await facade.pay_pending_reservation(ctx)
    assert out["status"] == "choose_card"
    ctx.send.assert_awaited()


async def test_pay_with_card_executes_payment(monkeypatch, tmp_user_dir, fernet_key, fake_redis):
    from srtgo.bot import facade, storage
    sess = _fresh_session()
    rail, reservation = MagicMock(), MagicMock()
    sess.set_pending(111, {"reservation": reservation, "rail": rail})
    storage.save(111, {"srt": None, "ktx": None, "cards": [
        {"id": "ab12", "label": None, "number": "n", "password": "p",
         "birthday": "b", "expire": "e"}]})
    called = {}

    def fake_pay(r, resv, card):
        called["args"] = (r, resv, card)
        return True

    monkeypatch.setattr(facade.svc_pay, "pay_with_saved_card", fake_pay)
    out = await facade.pay_pending_reservation(_ctx(), card_id="ab12")

    assert out["paid"] is True
    assert called["args"][0] is rail
    assert sess.get_pending(111) is None  # 결제 후 정리


# --- get_account_status ---

async def test_get_account_status(tmp_user_dir, fernet_key):
    from srtgo.bot import facade, storage
    storage.save(111, {"srt": {"id": "u", "pw": "p"}, "ktx": None, "cards": [
        {"id": "ab12", "label": None, "number": "n", "password": "p",
         "birthday": "b", "expire": "e"}]})
    out = await facade.get_account_status(_ctx(creds=storage.load(111)))
    assert out["srt_registered"] is True
    assert out["ktx_registered"] is False
    assert out["card_count"] == 1


# --- get_booking_progress ---

async def test_get_booking_progress_idle(fake_redis):
    from srtgo.bot import facade
    _fresh_session()
    out = await facade.get_booking_progress(_ctx())
    assert out["state"] == "idle"


async def test_get_booking_progress_polling(monkeypatch, fake_redis):
    from srtgo.bot import facade, handlers
    sess = _fresh_session()
    progress = {
        "rail_type": "SRT", "dep": "부산", "arr": "서울",
        "date": "20260601", "time": "180000",
        "selected_trains": ["KTX 101 (18:00)"],
        "start_time": 1.0, "attempts": 7, "last_sleep": 5.0, "last_sleep_set_at": 2.0,
    }
    monkeypatch.setattr(sess, "get_progress", lambda tid: progress)
    out = await facade.get_booking_progress(_ctx())
    assert out["state"] == "polling"
    assert "status_text" in out


async def test_get_booking_progress_pending(fake_redis):
    from srtgo.bot import facade
    sess = _fresh_session()
    sess.set_pending(111, {"reservation": MagicMock(), "rail": MagicMock()})
    out = await facade.get_booking_progress(_ctx())
    assert out["state"] == "pending_payment"


# --- cancel_booking ---

async def test_cancel_booking_nothing(fake_redis):
    from srtgo.bot import facade
    _fresh_session()
    out = await facade.cancel_booking(_ctx())
    assert out["status"] == "nothing"


async def test_cancel_booking_stops_poll(monkeypatch, fake_redis):
    from srtgo.bot import facade
    sess = _fresh_session()
    monkeypatch.setattr(sess, "cancel_poll", lambda tid: True)
    out = await facade.cancel_booking(_ctx())
    assert out["status"] == "cancelled"


# --- 민감정보 트리거 (버튼만, 인자 없음) ---

async def test_start_card_registration_posts_cards_add_button():
    from srtgo.bot import facade
    ctx = _ctx()
    out = await facade.start_card_registration(ctx)
    assert out["status"] == "prompt_sent"
    markup = ctx.send.call_args.kwargs["reply_markup"]
    assert markup.inline_keyboard[0][0].callback_data == "cards:add"


async def test_start_credential_setup_posts_setup_button():
    from srtgo.bot import facade
    ctx = _ctx()
    out = await facade.start_credential_setup(ctx)
    assert out["status"] == "prompt_sent"
    markup = ctx.send.call_args.kwargs["reply_markup"]
    assert markup.inline_keyboard[0][0].callback_data == "setup:start"
