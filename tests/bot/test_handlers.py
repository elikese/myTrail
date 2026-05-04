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
