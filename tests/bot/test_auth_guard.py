import pytest


def test_allowed_returns_true_for_listed_id(monkeypatch):
    from srtgo.bot import auth_guard
    monkeypatch.setenv("BOT_ALLOWED_IDS", "111,222,333")
    assert auth_guard.is_allowed(222)


def test_allowed_returns_false_for_unlisted(monkeypatch):
    from srtgo.bot import auth_guard
    monkeypatch.setenv("BOT_ALLOWED_IDS", "111,222")
    assert not auth_guard.is_allowed(999)


def test_empty_allowlist_blocks_everyone(monkeypatch):
    from srtgo.bot import auth_guard
    monkeypatch.setenv("BOT_ALLOWED_IDS", "")
    assert not auth_guard.is_allowed(111)


def test_missing_env_blocks_everyone(monkeypatch):
    from srtgo.bot import auth_guard
    monkeypatch.delenv("BOT_ALLOWED_IDS", raising=False)
    assert not auth_guard.is_allowed(111)


def test_get_allowed_ids_handles_whitespace(monkeypatch):
    from srtgo.bot import auth_guard
    monkeypatch.setenv("BOT_ALLOWED_IDS", " 1 , 2 ,3 ")
    assert auth_guard.get_allowed_ids() == {1, 2, 3}
