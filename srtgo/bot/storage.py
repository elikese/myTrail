"""사용자별 자격증명을 Fernet로 암호화하여 파일에 저장."""

import json
import logging
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


class StorageDecryptError(Exception):
    """복호화 실패 (마스터 키 변경·파일 손상)."""


_cipher: Fernet | None = None


def _get_cipher() -> Fernet:
    global _cipher
    if _cipher is None:
        key = os.environ.get("BOT_DB_KEY")
        if not key:
            raise RuntimeError("BOT_DB_KEY 환경변수 미설정")
        _cipher = Fernet(key.encode() if isinstance(key, str) else key)
    return _cipher


def _reset_cipher_for_tests() -> None:
    """테스트 전용 — env 바뀐 후 cipher 재생성."""
    global _cipher
    _cipher = None


def _users_dir() -> Path:
    d = Path(os.environ.get("BOT_USERS_DIR", "data/users"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(telegram_id: int) -> Path:
    return _users_dir() / f"{telegram_id}.json.enc"


def exists(telegram_id: int) -> bool:
    return _path(telegram_id).exists()


def save(telegram_id: int, data: dict) -> None:
    plaintext = json.dumps(data, ensure_ascii=False).encode()
    token = _get_cipher().encrypt(plaintext)
    _path(telegram_id).write_bytes(token)
    logger.info("자격증명 저장: tid=%d", telegram_id)


def load(telegram_id: int) -> dict | None:
    p = _path(telegram_id)
    if not p.exists():
        return None
    token = p.read_bytes()
    try:
        plaintext = _get_cipher().decrypt(token)
    except InvalidToken as e:
        raise StorageDecryptError(str(e)) from e
    return json.loads(plaintext.decode())


def delete(telegram_id: int) -> None:
    p = _path(telegram_id)
    if p.exists():
        p.unlink()
        logger.info("자격증명 삭제: tid=%d", telegram_id)


def list_user_ids() -> list[int]:
    out = []
    for p in _users_dir().iterdir():
        if p.suffix == ".enc" and p.stem.endswith(".json"):
            try:
                out.append(int(p.stem.removesuffix(".json")))
            except ValueError:
                continue
    return out
