import pytest


def test_save_and_load_round_trip(tmp_user_dir, fernet_key):
    from srtgo.bot import storage

    data = {"claude_key": "sk-1", "srt": {"id": "u", "pw": "p"}, "ktx": None,
            "card": {"number": "1", "password": "2", "birthday": "3", "expire": "4"}}
    storage.save(123456, data)
    assert storage.exists(123456)
    assert storage.load(123456) == data


def test_load_missing_returns_none(tmp_user_dir, fernet_key):
    from srtgo.bot import storage
    assert storage.load(999) is None
    assert not storage.exists(999)


def test_load_with_wrong_key_raises(tmp_user_dir, fernet_key, monkeypatch):
    from cryptography.fernet import Fernet
    from srtgo.bot import storage

    storage.save(1, {"a": 1})

    # 키 교체 후 읽기
    monkeypatch.setenv("BOT_DB_KEY", Fernet.generate_key().decode())
    storage._reset_cipher_for_tests()
    with pytest.raises(storage.StorageDecryptError):
        storage.load(1)


def test_delete_removes_file(tmp_user_dir, fernet_key):
    from srtgo.bot import storage
    storage.save(7, {"x": 1})
    storage.delete(7)
    assert not storage.exists(7)


def test_list_user_ids(tmp_user_dir, fernet_key):
    from srtgo.bot import storage
    storage.save(1, {"x": 1})
    storage.save(2, {"x": 2})
    assert sorted(storage.list_user_ids()) == [1, 2]
