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

    # /setup 시작
    upd = _make_update(111, "/setup")
    state = await handlers.setup_entry(upd, context)
    assert state == handlers.STATE_CLAUDE_KEY

    # Claude key
    upd = _make_update(111, "sk-claude")
    state = await handlers.setup_claude_key(upd, context)
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
    assert saved["claude_key"] == "sk-claude"
    assert saved["srt"] is None
    assert saved["ktx"] == {"id": "ktxid", "pw": "ktxpw"}
    assert saved["card"]["number"] == "1111222233334444"
