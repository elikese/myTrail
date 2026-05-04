import pytest


@pytest.fixture
def tmp_user_dir(tmp_path, monkeypatch):
    """사용자별 자격증명 파일이 임시 디렉토리에 저장되도록 강제."""
    users_dir = tmp_path / "users"
    users_dir.mkdir()
    monkeypatch.setenv("BOT_USERS_DIR", str(users_dir))
    return users_dir


@pytest.fixture
def fernet_key(monkeypatch):
    """테스트용 임시 Fernet 키."""
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("BOT_DB_KEY", key)
    return key
