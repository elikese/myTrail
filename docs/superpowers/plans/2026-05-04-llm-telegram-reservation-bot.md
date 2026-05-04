# LLM 텔레그램 예매 봇 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사용자가 텔레그램에서 자연어 한 줄로 SRT/KTX 예매 + 확인 1회 + 결제까지 끝내는 가족·지인용 소형 봇을 `srtgo/bot/` 신규 모듈로 구축한다.

**Architecture:** Claude Haiku로 자연어 → intent JSON 파싱, 기존 `srtgo/service/*`(소폭 리팩터)를 호출해 좌석 폴링·결제. asyncio 봇 위에서 동기 service 코드는 `asyncio.to_thread`로 감싸고 `threading.Event`로 취소. 사용자별 자격증명은 Fernet 암호화 JSON 파일에 격리.

**Tech Stack:** Python 3.10+, python-telegram-bot v21+, anthropic SDK, cryptography (Fernet), pytest + pytest-asyncio + freezegun.

**Spec:** `docs/superpowers/specs/2026-05-04-llm-telegram-reservation-bot-design.md`

---

## 파일 구조

**신규**
- `srtgo/bot/__init__.py`
- `srtgo/bot/main.py` — Application 부트스트랩, 핸들러 등록, polling 시작, 재시작 알림
- `srtgo/bot/handlers.py` — 명령·메시지·콜백 라우팅 (/start /setup /help /cancel + 자유메시지)
- `srtgo/bot/parser.py` — Claude API → intent JSON, jsonschema 검증
- `srtgo/bot/session.py` — 사용자별 폴링 Task + cancel_event + pending reservation
- `srtgo/bot/storage.py` — Fernet read/write/delete (사용자별 파일)
- `srtgo/bot/auth_guard.py` — `BOT_ALLOWED_IDS` 데코레이터
- `srtgo/bot/notifier.py` — 푸시 메시지 헬퍼
- `tests/conftest.py` — 공통 fixture
- `tests/bot/test_storage.py`, `test_auth_guard.py`, `test_parser.py`, `test_session.py`, `test_handlers.py`
- `tests/service/test_auth.py`, `test_payment.py`, `test_reservation.py`

**수정**
- `srtgo/service/auth.py` — `create_rail(rail_type, credentials=None, debug=False)`
- `srtgo/service/payment.py` — `pay_with_saved_card(rail, reservation, card_info=None)`
- `srtgo/service/reservation.py` — `poll_and_reserve(..., cancel_event=None)`
- `pyproject.toml` — 의존성 추가, dev extras, `srtgo-bot` 엔트리포인트
- `.gitignore` — `data/` 제외

---

## Task 1: 의존성·테스트 인프라 부트스트랩

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/__init__.py`
- Create: `tests/bot/__init__.py`
- Create: `tests/service/__init__.py`
- Create: `tests/conftest.py`
- Modify: `.gitignore`

- [ ] **Step 1: pyproject.toml 의존성·extras 추가**

`[project] dependencies` 끝에 추가:
```toml
    "anthropic>=0.40",
    "cryptography>=42",
    "jsonschema>=4",
```

`[project.optional-dependencies]`에 추가:
```toml
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.23",
    "freezegun>=1.5",
]
```

`[project.scripts]` 끝에 추가:
```toml
srtgo-bot = "srtgo.bot.main:main"
```

- [ ] **Step 2: 가상환경에 설치**

Run: `pip install -e ".[dev]"` (또는 `uv pip install -e ".[dev]"`)
Expected: 위 패키지 모두 설치, exit 0.

- [ ] **Step 3: tests 디렉토리 빈 패키지 파일 생성**

`tests/__init__.py`, `tests/bot/__init__.py`, `tests/service/__init__.py` — 각각 빈 파일.

- [ ] **Step 4: tests/conftest.py 작성**

```python
import os
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
    """테스트용 고정 Fernet 키."""
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("BOT_DB_KEY", key)
    return key
```

- [ ] **Step 5: pytest 설정 추가 (pyproject.toml)**

`pyproject.toml`에 추가:
```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 6: .gitignore에 data/ 추가**

`.gitignore` 끝에 한 줄: `data/`

- [ ] **Step 7: 빈 pytest 실행 확인**

Run: `pytest -q`
Expected: `no tests ran` 또는 0 collected, exit 5 (no tests). 실패면 설치/설정 잘못.

- [ ] **Step 8: 커밋**

```bash
git add pyproject.toml .gitignore tests/
git commit -m "chore: 봇용 의존성·테스트 인프라 추가"
```

---

## Task 2: service.auth.create_rail 명시 자격증명 인자

**Files:**
- Modify: `srtgo/service/auth.py`
- Create: `tests/service/test_auth.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/service/test_auth.py`:
```python
from unittest.mock import patch, MagicMock

import pytest


def test_create_rail_uses_explicit_credentials_over_keyring():
    """credentials 인자가 주어지면 keyring을 호출하지 않는다."""
    from srtgo.service import auth

    with patch.object(auth, "get_rail_credential") as mock_kr, \
         patch("srtgo.rail.srt.client.SRT") as mock_srt:
        mock_srt.return_value = MagicMock()
        rail = auth.create_rail("SRT", credentials={"id": "u1", "pw": "p1"})

    mock_kr.assert_not_called()
    mock_srt.assert_called_once_with("u1", "p1", verbose=False)
    assert rail is mock_srt.return_value


def test_create_rail_falls_back_to_keyring_when_no_credentials():
    """credentials=None이면 기존대로 keyring에서 읽는다."""
    from srtgo.service import auth

    with patch.object(auth, "get_rail_credential", return_value=("k_id", "k_pw")) as mock_kr, \
         patch("srtgo.rail.srt.client.SRT") as mock_srt:
        mock_srt.return_value = MagicMock()
        auth.create_rail("SRT")

    mock_kr.assert_called_once_with("SRT")
    mock_srt.assert_called_once_with("k_id", "k_pw", verbose=False)


def test_create_rail_raises_when_credentials_missing():
    from srtgo.service import auth

    with patch.object(auth, "get_rail_credential", return_value=(None, None)):
        with pytest.raises(ValueError, match="자격증명"):
            auth.create_rail("SRT")
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `pytest tests/service/test_auth.py -v`
Expected: `test_create_rail_uses_explicit_credentials_over_keyring` FAIL — 함수 시그니처에 credentials 없음.

- [ ] **Step 3: srtgo/service/auth.py 수정**

`create_rail` 시그니처와 본문 교체:
```python
def create_rail(
    rail_type: str,
    credentials: dict | None = None,
    debug: bool = False,
) -> AbstractRail:
    """rail_type에 따라 SRT 또는 Korail 인스턴스 반환 — 유일한 분기점.

    credentials: {"id": str, "pw": str}. None이면 keyring에서 fallback.
    """
    if credentials is not None:
        user_id, password = credentials["id"], credentials["pw"]
    else:
        user_id, password = get_rail_credential(rail_type)
    if not user_id or not password:
        raise ValueError(f"{rail_type} 자격증명이 설정되지 않았습니다")

    if rail_type == "SRT":
        from ..rail.srt.client import SRT
        return SRT(user_id, password, verbose=debug)
    else:
        from ..rail.ktx.client import Korail
        return Korail(user_id, password, verbose=debug)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/service/test_auth.py -v`
Expected: 3개 PASS.

- [ ] **Step 5: 기존 호출자(cli) 영향 확인**

Run: `grep -rn "create_rail(" srtgo/cli`
Expected: 호출 모두 `create_rail(rail_type)` 또는 `create_rail(rail_type, debug)` 형태 — 변경 없이도 동작 (credentials는 keyword-only가 아니지만 위치 인자는 rail_type만).

확인 후, `ensure_login` 안의 `create_rail(rail_type, debug)` 호출이 여전히 동작하는지 본다 (debug가 두 번째 위치 인자로 들어가면 credentials로 잘못 매핑됨).

- [ ] **Step 6: ensure_login 호출 수정**

`srtgo/service/auth.py`의 `ensure_login`:
```python
        new_rail = create_rail(rail_type, debug=debug)
```
(키워드로 명시.)

- [ ] **Step 7: 전체 테스트 재실행**

Run: `pytest -q`
Expected: 3 PASS, 0 FAIL.

- [ ] **Step 8: 커밋**

```bash
git add srtgo/service/auth.py tests/service/test_auth.py
git commit -m "refactor: create_rail에 명시 credentials 인자 추가"
```

---

## Task 3: service.payment.pay_with_saved_card 명시 card_info 인자

**Files:**
- Modify: `srtgo/service/payment.py`
- Create: `tests/service/test_payment.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/service/test_payment.py`:
```python
from unittest.mock import MagicMock, patch


def test_pay_uses_explicit_card_info_over_keyring():
    from srtgo.service import payment

    rail = MagicMock()
    rail.pay_with_card.return_value = True
    reservation = MagicMock()
    card = {"number": "1", "password": "2", "birthday": "3", "expire": "4"}

    with patch.object(payment, "get_card_info") as mock_kr:
        result = payment.pay_with_saved_card(rail, reservation, card_info=card)

    mock_kr.assert_not_called()
    rail.pay_with_card.assert_called_once_with(reservation, card)
    assert result is True


def test_pay_falls_back_to_keyring_when_no_card_info():
    from srtgo.service import payment

    rail = MagicMock()
    rail.pay_with_card.return_value = True
    reservation = MagicMock()
    kr_card = {"number": "9", "password": "8", "birthday": "7", "expire": "6"}

    with patch.object(payment, "get_card_info", return_value=kr_card) as mock_kr:
        result = payment.pay_with_saved_card(rail, reservation)

    mock_kr.assert_called_once()
    rail.pay_with_card.assert_called_once_with(reservation, kr_card)
    assert result is True


def test_pay_returns_false_when_no_card_anywhere():
    from srtgo.service import payment

    rail = MagicMock()
    reservation = MagicMock()

    with patch.object(payment, "get_card_info", return_value=None):
        result = payment.pay_with_saved_card(rail, reservation)

    assert result is False
    rail.pay_with_card.assert_not_called()
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `pytest tests/service/test_payment.py -v`
Expected: card_info 인자 없음으로 FAIL.

- [ ] **Step 3: srtgo/service/payment.py 수정**

```python
def pay_with_saved_card(rail: AbstractRail, reservation, card_info: dict | None = None) -> bool:
    """카드 결제. card_info=None이면 keyring fallback. 카드 없으면 False."""
    if card_info is None:
        card_info = get_card_info()
    if not card_info:
        logger.debug("카드 정보 미설정 — 결제 건너뜀")
        return False
    try:
        result = rail.pay_with_card(reservation, card_info)
        logger.info("카드 결제 성공: reservation=%s", reservation)
        return result
    except Exception as e:
        logger.error("카드 결제 실패: %s", e)
        raise
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/service/test_payment.py -v`
Expected: 3 PASS.

- [ ] **Step 5: 커밋**

```bash
git add srtgo/service/payment.py tests/service/test_payment.py
git commit -m "refactor: pay_with_saved_card에 명시 card_info 인자 추가"
```

---

## Task 4: service.reservation.poll_and_reserve cancel_event 인자

**Files:**
- Modify: `srtgo/service/reservation.py`
- Create: `tests/service/test_reservation.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/service/test_reservation.py`:
```python
import threading
from unittest.mock import MagicMock

from srtgo.service.reservation import poll_and_reserve


def test_cancel_event_stops_polling_loop():
    """cancel_event.set() 후에는 다음 루프 진입 시점에 종료한다."""
    rail = MagicMock()
    rail.search_train.return_value = []  # 좌석 없음 → 슬립 후 재시도

    cancel_event = threading.Event()

    on_success = MagicMock()
    on_error = MagicMock(return_value=True)

    # 별도 스레드에서 폴링 시작
    def run():
        poll_and_reserve(
            rail,
            search_params={"dep": "x", "arr": "y", "date": "20260505",
                           "time": "180000", "passengers": []},
            train_indices=[0],
            seat_option=None,
            on_success=on_success,
            on_error=on_error,
            cancel_event=cancel_event,
        )

    t = threading.Thread(target=run, daemon=True)
    t.start()

    # 잠깐 후 cancel
    cancel_event.set()
    t.join(timeout=10)

    assert not t.is_alive(), "cancel 후 폴링이 종료되어야 함"
    on_success.assert_not_called()


def test_cancel_event_none_keeps_existing_behavior():
    """cancel_event=None이면 기존처럼 동작 (좌석 잡으면 종료)."""
    from srtgo.rail.srt.models import SeatType

    train = MagicMock()
    train.seat_available.return_value = True

    rail = MagicMock()
    rail.search_train.return_value = [train]
    rail.reserve.return_value = "RES"

    on_success = MagicMock()
    on_error = MagicMock()

    poll_and_reserve(
        rail,
        search_params={"dep": "x", "arr": "y", "date": "20260505",
                       "time": "180000", "passengers": []},
        train_indices=[0],
        seat_option=SeatType.GENERAL_FIRST,
        on_success=on_success,
        on_error=on_error,
    )

    on_success.assert_called_once_with("RES")
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `pytest tests/service/test_reservation.py -v`
Expected: cancel_event 인자 없음으로 FAIL.

- [ ] **Step 3: srtgo/service/reservation.py 수정**

`_sleep`을 cancel-aware로 교체하고 `poll_and_reserve` 시그니처·루프 수정:

```python
import threading

def _sleep(cancel_event: threading.Event | None = None) -> None:
    interval = gammavariate(RESERVE_INTERVAL_SHAPE, RESERVE_INTERVAL_SCALE) + RESERVE_INTERVAL_MIN
    logger.debug("슬립: %.2fs", interval)
    if cancel_event is None:
        time.sleep(interval)
    else:
        # Event.wait는 set 시 즉시 반환
        cancel_event.wait(timeout=interval)


def poll_and_reserve(
    rail: AbstractRail,
    search_params: dict,
    train_indices: list[int],
    seat_option,
    on_success,
    on_error,
    cancel_event: threading.Event | None = None,
) -> None:
    i_try = 0
    start_time = time.time()

    while True:
        if cancel_event is not None and cancel_event.is_set():
            logger.info("cancel_event 감지 — 폴링 종료")
            return

        i_try += 1
        elapsed = time.time() - start_time
        logger.debug("예매 시도 #%d (경과: %.0fs)", i_try, elapsed)

        try:
            trains = rail.search_train(**search_params)
            for idx in train_indices:
                if idx < len(trains) and is_seat_available(trains[idx], seat_option):
                    logger.info("좌석 확보: %s (시도 #%d)", trains[idx], i_try)
                    reservation = rail.reserve(trains[idx], option=seat_option)
                    on_success(reservation)
                    return
            _sleep(cancel_event)

        except Exception as e:
            logger.error("예매 폴링 중 오류: %s", e, exc_info=True)
            should_continue = on_error(e)
            if not should_continue:
                return
            _sleep(cancel_event)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/service/test_reservation.py -v`
Expected: 2 PASS.

- [ ] **Step 5: 전체 테스트 회귀 확인**

Run: `pytest -q`
Expected: 8 PASS (Task 2: 3, Task 3: 3, Task 4: 2).

- [ ] **Step 6: 커밋**

```bash
git add srtgo/service/reservation.py tests/service/test_reservation.py
git commit -m "refactor: poll_and_reserve에 cancel_event 인자 추가"
```

---

## Task 5: bot/storage.py — Fernet 사용자별 파일 저장

**Files:**
- Create: `srtgo/bot/__init__.py` (빈 파일)
- Create: `srtgo/bot/storage.py`
- Create: `tests/bot/test_storage.py`

- [ ] **Step 1: srtgo/bot/__init__.py 빈 파일 생성**

- [ ] **Step 2: 실패 테스트 작성**

`tests/bot/test_storage.py`:
```python
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
```

- [ ] **Step 3: 테스트 실행 → 실패 확인**

Run: `pytest tests/bot/test_storage.py -v`
Expected: ImportError.

- [ ] **Step 4: srtgo/bot/storage.py 작성**

```python
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
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `pytest tests/bot/test_storage.py -v`
Expected: 5 PASS.

- [ ] **Step 6: 커밋**

```bash
git add srtgo/bot/__init__.py srtgo/bot/storage.py tests/bot/test_storage.py
git commit -m "feat(bot): Fernet 사용자별 자격증명 저장소"
```

---

## Task 6: bot/auth_guard.py — allowlist 데코레이터

**Files:**
- Create: `srtgo/bot/auth_guard.py`
- Create: `tests/bot/test_auth_guard.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/bot/test_auth_guard.py`:
```python
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
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `pytest tests/bot/test_auth_guard.py -v`
Expected: ImportError.

- [ ] **Step 3: srtgo/bot/auth_guard.py 작성**

```python
"""텔레그램 사용자 ID 화이트리스트."""

import os


def get_allowed_ids() -> set[int]:
    raw = os.environ.get("BOT_ALLOWED_IDS", "")
    out = set()
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            out.add(int(chunk))
        except ValueError:
            continue
    return out


def is_allowed(telegram_id: int) -> bool:
    return telegram_id in get_allowed_ids()
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/bot/test_auth_guard.py -v`
Expected: 5 PASS.

- [ ] **Step 5: 커밋**

```bash
git add srtgo/bot/auth_guard.py tests/bot/test_auth_guard.py
git commit -m "feat(bot): allowlist 가드"
```

---

## Task 7: bot/parser.py — Claude 자연어 파서

**Files:**
- Create: `srtgo/bot/parser.py`
- Create: `tests/bot/test_parser.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/bot/test_parser.py`:
```python
from unittest.mock import MagicMock, patch
import json

import pytest


def _mock_anthropic_response(intent_dict: dict):
    """Anthropic SDK 응답 객체 mock — content[0].text가 JSON 문자열."""
    msg = MagicMock()
    block = MagicMock()
    block.text = json.dumps(intent_dict)
    msg.content = [block]
    return msg


def test_parse_basic_korean(monkeypatch):
    from srtgo.bot import parser

    intent = {
        "rail": "KTX",
        "dep": "부산",
        "arr": "서울",
        "date": "2026-05-05",
        "time": "180000",
        "passengers": {"adult": 1, "child": 0, "senior": 0},
        "seat_pref": "GENERAL_FIRST",
        "needs_clarification": [],
    }
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mock_anthropic_response(intent)

    result = parser.parse(
        text="내일 오후 6시 부산에서 서울 KTX",
        today="2026-05-04",
        api_key="sk-x",
        client=fake_client,
    )
    assert result == intent


def test_parse_invalid_json_retries_once_then_raises(monkeypatch):
    from srtgo.bot import parser

    bad = MagicMock()
    bad_block = MagicMock()
    bad_block.text = "this is not json"
    bad.content = [bad_block]

    fake_client = MagicMock()
    fake_client.messages.create.return_value = bad

    with pytest.raises(parser.ParseError):
        parser.parse(text="???", today="2026-05-04", api_key="sk", client=fake_client)

    # 1회 재시도 = 총 2회 호출
    assert fake_client.messages.create.call_count == 2


def test_parse_schema_violation_raises():
    from srtgo.bot import parser

    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mock_anthropic_response(
        {"rail": "INVALID", "dep": "x"}  # 필수 필드 누락
    )

    with pytest.raises(parser.ParseError):
        parser.parse(text="x", today="2026-05-04", api_key="sk", client=fake_client)


def test_parse_propagates_needs_clarification():
    from srtgo.bot import parser

    intent = {
        "rail": "SRT",
        "dep": "부산",
        "arr": "서울",
        "date": "2026-05-05",
        "time": "000000",
        "passengers": {"adult": 1, "child": 0, "senior": 0},
        "seat_pref": "GENERAL_FIRST",
        "needs_clarification": ["time"],
    }
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mock_anthropic_response(intent)

    result = parser.parse("부산 서울 SRT", today="2026-05-04", api_key="sk", client=fake_client)
    assert result["needs_clarification"] == ["time"]
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `pytest tests/bot/test_parser.py -v`
Expected: ImportError.

- [ ] **Step 3: srtgo/bot/parser.py 작성**

```python
"""Claude API로 자연어를 intent JSON으로 파싱."""

import json
import logging

import jsonschema
from anthropic import Anthropic

logger = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5-20251001"

INTENT_SCHEMA = {
    "type": "object",
    "required": ["rail", "dep", "arr", "date", "time", "passengers",
                 "seat_pref", "needs_clarification"],
    "properties": {
        "rail": {"enum": ["SRT", "KTX"]},
        "dep": {"type": "string", "minLength": 1},
        "arr": {"type": "string", "minLength": 1},
        "date": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
        "time": {"type": "string", "pattern": r"^\d{6}$"},
        "passengers": {
            "type": "object",
            "required": ["adult", "child", "senior"],
            "properties": {
                "adult": {"type": "integer", "minimum": 0},
                "child": {"type": "integer", "minimum": 0},
                "senior": {"type": "integer", "minimum": 0},
            },
        },
        "seat_pref": {"enum": ["GENERAL_FIRST", "SPECIAL_FIRST",
                                "GENERAL_ONLY", "SPECIAL_ONLY"]},
        "needs_clarification": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}

SYSTEM_PROMPT = """당신은 한국 철도 예매 봇의 의도 파서입니다.
사용자의 한국어 자연어 입력을 아래 JSON 스키마에 맞춰 변환합니다.
오로지 JSON 객체 하나만 반환하고, 다른 텍스트는 절대 포함하지 마세요.

스키마:
- rail: "SRT" | "KTX" (사용자가 명시 안 했고 추론 불가하면 "SRT" 기본)
- dep, arr: 한국어 역명 (예: "부산", "서울", "동대구")
- date: "YYYY-MM-DD" (상대 표현은 today 기준으로 환산)
- time: "HHMMSS" (분 모르면 "000000", 시간만 있으면 시각만 채움)
- passengers: {adult, child, senior} (명시 없으면 adult=1)
- seat_pref: GENERAL_FIRST(일반우선) | SPECIAL_FIRST(특실우선) | GENERAL_ONLY(일반만) | SPECIAL_ONLY(특실만). 명시 없으면 GENERAL_FIRST.
- needs_clarification: 모호하거나 누락된 필드명을 배열로. 모든 게 명확하면 빈 배열 [].

today: {today}"""


class ParseError(Exception):
    """파싱 실패 (JSON 위반·스키마 위반·LLM 거부)."""


def parse(
    text: str,
    today: str,
    api_key: str,
    client: Anthropic | None = None,
) -> dict:
    """자연어 → intent dict. JSON/스키마 위반 시 1회 재시도."""
    if client is None:
        client = Anthropic(api_key=api_key)

    system = SYSTEM_PROMPT.format(today=today)
    last_err: Exception | None = None

    for attempt in range(2):
        try:
            resp = client.messages.create(
                model=MODEL,
                max_tokens=512,
                system=[
                    {"type": "text", "text": system,
                     "cache_control": {"type": "ephemeral"}},
                ],
                messages=[{"role": "user", "content": text}],
            )
            raw = resp.content[0].text
            data = json.loads(raw)
            jsonschema.validate(data, INTENT_SCHEMA)
            return data
        except (json.JSONDecodeError, jsonschema.ValidationError) as e:
            logger.warning("파싱 실패 (시도 %d): %s", attempt + 1, e)
            last_err = e

    raise ParseError(f"intent 파싱 실패: {last_err}")
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/bot/test_parser.py -v`
Expected: 4 PASS.

- [ ] **Step 5: 커밋**

```bash
git add srtgo/bot/parser.py tests/bot/test_parser.py
git commit -m "feat(bot): Claude 기반 자연어 intent 파서"
```

---

## Task 8: bot/session.py — 사용자별 폴링 Task·pending 관리

**Files:**
- Create: `srtgo/bot/session.py`
- Create: `tests/bot/test_session.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/bot/test_session.py`:
```python
import asyncio
import threading

import pytest


@pytest.mark.asyncio
async def test_start_poll_rejects_concurrent_request():
    from srtgo.bot import session

    sess = session.Session()
    cancel_event = threading.Event()

    async def dummy():
        await asyncio.sleep(0.5)

    sess.start_poll(1, asyncio.create_task(dummy()), cancel_event)
    with pytest.raises(session.AlreadyPolling):
        sess.start_poll(1, asyncio.create_task(dummy()), threading.Event())

    sess.cancel_poll(1)
    await asyncio.sleep(0.1)


@pytest.mark.asyncio
async def test_cancel_poll_sets_event_and_clears():
    from srtgo.bot import session

    sess = session.Session()
    cancel_event = threading.Event()

    async def dummy():
        await asyncio.sleep(0.5)

    sess.start_poll(1, asyncio.create_task(dummy()), cancel_event)
    sess.cancel_poll(1)

    assert cancel_event.is_set()
    assert not sess.is_polling(1)


def test_pending_set_get_clear():
    from srtgo.bot import session

    sess = session.Session()
    sess.set_pending(1, {"reservation": "X", "rail": object()})
    assert sess.get_pending(1)["reservation"] == "X"
    sess.clear_pending(1)
    assert sess.get_pending(1) is None


@pytest.mark.asyncio
async def test_finished_task_clears_polling_slot():
    from srtgo.bot import session

    sess = session.Session()
    cancel_event = threading.Event()

    async def quick():
        return

    task = asyncio.create_task(quick())
    sess.start_poll(1, task, cancel_event)
    await task
    # task done callback이 슬롯 정리
    await asyncio.sleep(0)
    assert not sess.is_polling(1)
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `pytest tests/bot/test_session.py -v`
Expected: ImportError.

- [ ] **Step 3: srtgo/bot/session.py 작성**

```python
"""사용자별 진행 중 폴링 Task와 결제 대기 reservation 추적."""

import asyncio
import threading
from typing import Any


class AlreadyPolling(Exception):
    """동일 사용자에게 진행 중 폴링이 이미 있음."""


class Session:
    def __init__(self) -> None:
        self._polls: dict[int, tuple[asyncio.Task, threading.Event]] = {}
        self._pending: dict[int, dict] = {}

    def start_poll(
        self,
        telegram_id: int,
        task: asyncio.Task,
        cancel_event: threading.Event,
    ) -> None:
        if self.is_polling(telegram_id):
            raise AlreadyPolling(f"tid={telegram_id} 이미 폴링 중")
        self._polls[telegram_id] = (task, cancel_event)
        task.add_done_callback(lambda _t: self._polls.pop(telegram_id, None))

    def is_polling(self, telegram_id: int) -> bool:
        entry = self._polls.get(telegram_id)
        return entry is not None and not entry[0].done()

    def cancel_poll(self, telegram_id: int) -> bool:
        entry = self._polls.pop(telegram_id, None)
        if entry is None:
            return False
        task, event = entry
        event.set()
        # task 자체는 to_thread 종료 후 자연 완료 — 강제 cancel은 불필요
        return True

    def set_pending(self, telegram_id: int, payload: dict) -> None:
        """payload 키: {reservation, rail, intent, message_id}"""
        self._pending[telegram_id] = payload

    def get_pending(self, telegram_id: int) -> dict | None:
        return self._pending.get(telegram_id)

    def clear_pending(self, telegram_id: int) -> None:
        self._pending.pop(telegram_id, None)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/bot/test_session.py -v`
Expected: 4 PASS.

- [ ] **Step 5: 커밋**

```bash
git add srtgo/bot/session.py tests/bot/test_session.py
git commit -m "feat(bot): 사용자별 폴링·pending 세션 관리자"
```

---

## Task 9: bot/notifier.py — 푸시 메시지 헬퍼

**Files:**
- Create: `srtgo/bot/notifier.py`
- (테스트는 handlers 통합 테스트에서 함께 검증 — 노티파이어 자체는 thin wrapper라 단위 테스트 생략)

- [ ] **Step 1: srtgo/bot/notifier.py 작성**

```python
"""봇이 사용자에게 푸시 메시지 보낼 때 쓰는 헬퍼.

핸들러는 telegram Update가 있어 reply_text를 쓰면 되지만,
폴링 콜백처럼 update가 없는 경로에서는 이 모듈로 보낸다.
"""

import logging
from typing import Any

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)


def _payment_deadline_str(reservation: Any) -> str | None:
    """SRT/KTX 양쪽에서 결제 마감 시각을 추출. 없으면 None."""
    # SRT
    pd = getattr(reservation, "payment_date", None)
    pt = getattr(reservation, "payment_time", None)
    # KTX는 buy_limit_*
    if pd is None:
        pd = getattr(reservation, "buy_limit_date", None)
        pt = getattr(reservation, "buy_limit_time", None)
    if not pd or not pt or pd == "00000000":
        return None
    try:
        return f"{int(pd[4:6])}/{int(pd[6:8])} {pt[:2]}:{pt[2:4]}"
    except (ValueError, IndexError):
        return None


def format_seat_secured_message(reservation: Any) -> str:
    deadline = _payment_deadline_str(reservation)
    base = f"좌석 확보!\n{reservation}"
    if deadline:
        base += f"\n결제마감: {deadline}"
    return base


def confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ 결제", callback_data="pay:confirm"),
        InlineKeyboardButton("❌ 취소", callback_data="pay:cancel"),
    ]])


async def send_seat_secured(bot: Bot, telegram_id: int, reservation: Any) -> int:
    msg = await bot.send_message(
        chat_id=telegram_id,
        text=format_seat_secured_message(reservation),
        reply_markup=confirm_keyboard(),
    )
    return msg.message_id


async def send_text(bot: Bot, telegram_id: int, text: str) -> None:
    try:
        await bot.send_message(chat_id=telegram_id, text=text)
    except Exception as e:
        logger.error("푸시 실패 tid=%d: %s", telegram_id, e)
```

- [ ] **Step 2: 임포트만 확인**

Run: `python -c "from srtgo.bot import notifier; print(notifier.format_seat_secured_message.__name__)"`
Expected: `format_seat_secured_message`

- [ ] **Step 3: 커밋**

```bash
git add srtgo/bot/notifier.py
git commit -m "feat(bot): 푸시 메시지·인라인 키보드 헬퍼"
```

---

## Task 10: bot/handlers.py — /start, /help, allowlist 게이팅

**Files:**
- Create: `srtgo/bot/handlers.py`
- Create: `tests/bot/test_handlers.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/bot/test_handlers.py`:
```python
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
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `pytest tests/bot/test_handlers.py -v`
Expected: ImportError.

- [ ] **Step 3: srtgo/bot/handlers.py 초기 작성 (Task 10 범위)**

```python
"""텔레그램 봇 명령·메시지·콜백 핸들러."""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from . import auth_guard

logger = logging.getLogger(__name__)


HELP_TEXT = (
    "사용법:\n"
    "/setup — 자격증명 등록 (Claude API 키, 철도사 ID/PW, 카드)\n"
    "/cancel — 진행 중 폴링·예약 취소\n"
    "/help — 도움말\n\n"
    "그 외에는 자유롭게 말하세요. 예: '내일 오후 6시 부산에서 서울 KTX'"
)

WELCOME_TEXT = (
    "환영합니다. 먼저 /setup 으로 자격증명을 등록해주세요.\n\n"
    + HELP_TEXT
)


def _ensure_allowed(update: Update) -> bool:
    tid = update.effective_user.id
    if not auth_guard.is_allowed(tid):
        return False
    return True


async def _block_unallowed(update: Update) -> None:
    tid = update.effective_user.id
    await update.message.reply_text(
        f"허용되지 않은 사용자입니다.\n당신의 텔레그램 ID: {tid}\n"
        "관리자에게 이 ID를 전달해주세요."
    )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _ensure_allowed(update):
        await _block_unallowed(update)
        return
    await update.message.reply_text(WELCOME_TEXT)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _ensure_allowed(update):
        await _block_unallowed(update)
        return
    await update.message.reply_text(HELP_TEXT)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/bot/test_handlers.py -v`
Expected: 3 PASS.

- [ ] **Step 5: 커밋**

```bash
git add srtgo/bot/handlers.py tests/bot/test_handlers.py
git commit -m "feat(bot): /start /help 핸들러와 allowlist 게이팅"
```

---

## Task 11: handlers — /setup 다단계 ConversationHandler

**Files:**
- Modify: `srtgo/bot/handlers.py`
- Modify: `tests/bot/test_handlers.py`

- [ ] **Step 1: 실패 테스트 추가**

`tests/bot/test_handlers.py` 끝에 추가:
```python
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
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `pytest tests/bot/test_handlers.py::test_setup_full_flow_saves_credentials -v`
Expected: AttributeError (setup_* 미정의).

- [ ] **Step 3: handlers.py에 /setup 핸들러 추가**

`srtgo/bot/handlers.py` 끝에 추가:
```python
from telegram.ext import ConversationHandler

from . import storage

STATE_CLAUDE_KEY, STATE_SRT, STATE_KTX, STATE_CARD = range(4)


async def setup_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _ensure_allowed(update):
        await _block_unallowed(update)
        return ConversationHandler.END
    context.user_data["setup"] = {}
    await update.message.reply_text(
        "자격증명 등록을 시작합니다.\n"
        "1/4: Anthropic Claude API 키를 보내주세요. (취소: /cancel)"
    )
    return STATE_CLAUDE_KEY


async def setup_claude_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["setup"]["claude_key"] = update.message.text.strip()
    await update.message.reply_text(
        "2/4: SRT 아이디·비번을 한 줄에 공백으로 구분해 보내주세요.\n"
        "사용 안 하면 'skip'."
    )
    return STATE_SRT


def _parse_id_pw(text: str) -> dict | None:
    text = text.strip()
    if text.lower() == "skip":
        return None
    parts = text.split()
    if len(parts) != 2:
        return None
    return {"id": parts[0], "pw": parts[1]}


async def setup_srt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    cred = _parse_id_pw(update.message.text)
    if cred is False:  # 형식 잘못
        await update.message.reply_text("형식: 'id pw' 또는 'skip'")
        return STATE_SRT
    context.user_data["setup"]["srt"] = cred
    await update.message.reply_text(
        "3/4: KTX(코레일) 아이디·비번. 사용 안 하면 'skip'."
    )
    return STATE_KTX


async def setup_ktx(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["setup"]["ktx"] = _parse_id_pw(update.message.text)
    await update.message.reply_text(
        "4/4: 카드 정보를 한 줄에 공백 4개로:\n"
        "  카드번호 비번앞2자리 생년월일(YYMMDD) 만료(MMYY)\n"
        "예: 1111222233334444 12 900101 1230"
    )
    return STATE_CARD


async def setup_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    parts = update.message.text.strip().split()
    if len(parts) != 4:
        await update.message.reply_text("형식이 잘못됐어요. 4개 항목을 공백으로.")
        return STATE_CARD
    number, password, birthday, expire = parts
    context.user_data["setup"]["card"] = {
        "number": number, "password": password,
        "birthday": birthday, "expire": expire,
    }
    storage.save(update.effective_user.id, context.user_data["setup"])
    context.user_data.pop("setup", None)
    await update.message.reply_text("등록 완료. 이제 자유롭게 말해보세요.")
    return ConversationHandler.END


async def setup_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("setup", None)
    await update.message.reply_text("등록 취소됨.")
    return ConversationHandler.END
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/bot/test_handlers.py -v`
Expected: 4 PASS (3 기존 + 1 신규).

- [ ] **Step 5: 커밋**

```bash
git add srtgo/bot/handlers.py tests/bot/test_handlers.py
git commit -m "feat(bot): /setup 4단계 ConversationHandler"
```

---

## Task 12: handlers — 자유 메시지 → 파싱 → 검색 → 열차 선택

**Files:**
- Modify: `srtgo/bot/handlers.py`
- Modify: `tests/bot/test_handlers.py`

- [ ] **Step 1: 실패 테스트 추가**

`tests/bot/test_handlers.py` 끝에 추가:
```python
@pytest.mark.asyncio
async def test_freemsg_parses_and_searches(monkeypatch, tmp_user_dir, fernet_key):
    monkeypatch.setenv("BOT_ALLOWED_IDS", "111")
    from srtgo.bot import handlers, storage
    storage._reset_cipher_for_tests()

    storage.save(111, {
        "claude_key": "sk", "srt": {"id": "u", "pw": "p"},
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
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `pytest tests/bot/test_handlers.py::test_freemsg_parses_and_searches -v`
Expected: AttributeError (on_free_message 미정의).

- [ ] **Step 3: handlers.py에 자유 메시지 핸들러 추가**

`srtgo/bot/handlers.py` 끝에 추가:
```python
import datetime as _dt

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from . import parser
from ..service import auth as svc_auth


def _seat_option_from_intent(rail_type: str, pref: str):
    if rail_type == "SRT":
        from ..rail.srt.models import SeatType
        return SeatType[pref]   # SeatType은 Enum이라 subscript OK
    else:
        from ..rail.ktx.models import ReserveOption
        return getattr(ReserveOption, pref)   # ReserveOption은 일반 class (str 상수)


def _train_keyboard(trains: list) -> InlineKeyboardMarkup:
    rows = []
    for i, t in enumerate(trains[:10]):
        rows.append([InlineKeyboardButton(f"{i+1}. {t}", callback_data=f"pick:{i}")])
    rows.append([
        InlineKeyboardButton("전부", callback_data="pick:all"),
        InlineKeyboardButton("취소", callback_data="pick:none"),
    ])
    return InlineKeyboardMarkup(rows)


async def on_free_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _ensure_allowed(update):
        await _block_unallowed(update)
        return

    tid = update.effective_user.id
    creds = storage.load(tid)
    if creds is None:
        await update.message.reply_text("자격증명 미등록. /setup 부터 해주세요.")
        return

    text = update.message.text
    today = _dt.date.today().isoformat()
    try:
        intent = parser.parse(text=text, today=today, api_key=creds["claude_key"])
    except parser.ParseError as e:
        await update.message.reply_text(f"이해 못 했어요. 다시 말해주세요.\n({e})")
        return

    if intent.get("needs_clarification"):
        fields = ", ".join(intent["needs_clarification"])
        await update.message.reply_text(f"명확하게 알려주세요: {fields}")
        return

    rail_type = intent["rail"]
    cred = creds.get(rail_type.lower())
    if not cred:
        await update.message.reply_text(
            f"{rail_type} 자격증명 미등록. /setup 다시 해주세요."
        )
        return

    try:
        rail = svc_auth.create_rail(rail_type, credentials=cred)
    except Exception as e:
        await update.message.reply_text(f"{rail_type} 로그인 실패: {e}")
        return

    date = intent["date"].replace("-", "")
    search_params = {
        "dep": intent["dep"], "arr": intent["arr"],
        "date": date, "time": intent["time"],
        "passengers": _passengers_to_list(rail_type, intent["passengers"]),
        "include_no_seats": True,
    }
    try:
        trains = rail.search_train(**search_params)
    except Exception as e:
        await update.message.reply_text(f"검색 실패: {e}")
        return

    if not trains:
        await update.message.reply_text("해당 시간대 열차 없음.")
        return

    context.user_data["search"] = {
        "rail": rail, "rail_type": rail_type,
        "trains": trains, "search_params": search_params,
        "seat_option": _seat_option_from_intent(rail_type, intent["seat_pref"]),
    }
    await update.message.reply_text(
        "어떤 열차로 폴링할까요?",
        reply_markup=_train_keyboard(trains),
    )


def _passengers_to_list(rail_type: str, p: dict) -> list:
    """intent의 passengers dict → rail이 받는 Passenger 리스트."""
    out = []
    if rail_type == "SRT":
        from ..rail.srt.models import Adult, Child, Senior
        if p["adult"]: out.append(Adult(p["adult"]))
        if p["child"]: out.append(Child(p["child"]))
        if p["senior"]: out.append(Senior(p["senior"]))
    else:
        from ..rail.ktx.models import AdultPassenger, ChildPassenger, SeniorPassenger
        if p["adult"]: out.append(AdultPassenger(p["adult"]))
        if p["child"]: out.append(ChildPassenger(p["child"]))
        if p["senior"]: out.append(SeniorPassenger(p["senior"]))
    return out
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/bot/test_handlers.py::test_freemsg_parses_and_searches -v`
Expected: PASS. (전체 회귀: `pytest -q` 모두 PASS.)

만약 Passenger 클래스명이 SRT/KTX에서 다르면 (`rail/srt/models.py`, `rail/ktx/models.py` 직접 확인) 위 import를 실제 이름으로 수정.

- [ ] **Step 5: 커밋**

```bash
git add srtgo/bot/handlers.py tests/bot/test_handlers.py
git commit -m "feat(bot): 자유 메시지 → 파싱 → 검색 → 열차 후보 표시"
```

---

## Task 13: handlers — 열차 선택 콜백 → 폴링 시작

**Files:**
- Modify: `srtgo/bot/handlers.py`
- Modify: `tests/bot/test_handlers.py`

- [ ] **Step 1: 실패 테스트 추가**

`tests/bot/test_handlers.py` 끝에 추가:
```python
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
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `pytest tests/bot/test_handlers.py::test_pick_callback_starts_polling -v`
Expected: AttributeError.

- [ ] **Step 3: handlers.py에 콜백·폴링 시작 추가**

`srtgo/bot/handlers.py` 끝에 추가:
```python
import asyncio
import threading

from . import session as _session_mod
from . import notifier
from ..service import reservation as svc_resv


_SESSION = _session_mod.Session()


def _resolve_indices(data: str, n_trains: int) -> list[int] | None:
    """callback data → 인덱스 목록 또는 None(취소)."""
    if data == "pick:none":
        return None
    if data == "pick:all":
        return list(range(min(n_trains, 10)))
    return [int(data.removeprefix("pick:"))]


async def on_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cq = update.callback_query
    await cq.answer()
    tid = update.effective_user.id

    search = context.user_data.get("search")
    if not search:
        await cq.edit_message_text("세션 만료. 다시 요청해주세요.")
        return

    indices = _resolve_indices(cq.data, len(search["trains"]))
    if indices is None:
        await cq.edit_message_text("취소됨.")
        context.user_data.pop("search", None)
        return

    if _SESSION.is_polling(tid):
        await cq.edit_message_text("이미 진행 중인 폴링이 있어요. /cancel 후 다시.")
        return

    cancel_event = threading.Event()
    bot = context.application.bot
    loop = asyncio.get_running_loop()

    def on_success(reservation):
        _SESSION.clear_pending(tid)
        _SESSION.set_pending(tid, {"reservation": reservation, "rail": search["rail"]})
        asyncio.run_coroutine_threadsafe(
            notifier.send_seat_secured(bot, tid, reservation), loop
        )

    def on_error(exc):
        # 일시 오류로 간주, 계속 시도
        return True

    async def runner():
        await asyncio.to_thread(
            svc_resv.poll_and_reserve,
            search["rail"], search["search_params"], indices,
            search["seat_option"], on_success, on_error, cancel_event,
        )

    task = asyncio.create_task(runner())
    _SESSION.start_poll(tid, task, cancel_event)
    context.user_data.pop("search", None)
    await cq.edit_message_text("폴링 시작. 좌석 잡히면 알림 드립니다.")
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/bot/test_handlers.py::test_pick_callback_starts_polling -v`
Expected: PASS.

- [ ] **Step 5: 커밋**

```bash
git add srtgo/bot/handlers.py tests/bot/test_handlers.py
git commit -m "feat(bot): 열차 선택 콜백 → 백그라운드 폴링 시작"
```

---

## Task 14: handlers — 결제 확인 콜백 (✅ 결제 / ❌ 취소)

**Files:**
- Modify: `srtgo/bot/handlers.py`
- Modify: `tests/bot/test_handlers.py`

- [ ] **Step 1: 실패 테스트 추가**

`tests/bot/test_handlers.py` 끝에 추가:
```python
@pytest.mark.asyncio
async def test_pay_confirm_charges_card(monkeypatch, tmp_user_dir, fernet_key):
    monkeypatch.setenv("BOT_ALLOWED_IDS", "111")
    from srtgo.bot import handlers, storage, session as session_mod
    storage._reset_cipher_for_tests()
    handlers._SESSION = session_mod.Session()

    storage.save(111, {
        "claude_key": "sk",
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
    storage.save(111, {"claude_key": "sk", "srt": None, "ktx": None,
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
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `pytest tests/bot/test_handlers.py -k payment -v`
Expected: AttributeError.

- [ ] **Step 3: handlers.py에 결제 콜백 추가**

`srtgo/bot/handlers.py` 끝에 추가:
```python
from ..service import payment as svc_pay


async def on_payment_decision(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cq = update.callback_query
    await cq.answer()
    tid = update.effective_user.id

    pending = _SESSION.get_pending(tid)
    if not pending:
        await cq.edit_message_text("대기 중인 예약이 없어요. 결제 마감이 지났을 수 있습니다.")
        return

    rail = pending["rail"]
    reservation = pending["reservation"]

    if cq.data == "pay:cancel":
        try:
            await asyncio.to_thread(rail.cancel, reservation)
        except Exception as e:
            logger.error("예약 취소 실패: %s", e)
        _SESSION.clear_pending(tid)
        await cq.edit_message_text("예약 취소됨.")
        return

    # pay:confirm
    creds = storage.load(tid)
    card = creds.get("card") if creds else None
    if not card:
        await cq.edit_message_text("카드 정보 없음. /setup 다시.")
        return

    try:
        ok = await asyncio.to_thread(
            svc_pay.pay_with_saved_card, rail, reservation, card
        )
    except Exception as e:
        logger.error("결제 예외: %s", e)
        await cq.edit_message_text(f"결제 실패: {e}")
        _SESSION.clear_pending(tid)
        return

    _SESSION.clear_pending(tid)
    if ok:
        await cq.edit_message_text("결제 완료. 승차권은 SRT/코레일 앱에서 확인해주세요.")
    else:
        await cq.edit_message_text("결제 실패 (카드 정보 확인 필요).")
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/bot/test_handlers.py -v`
Expected: 모든 테스트 PASS.

- [ ] **Step 5: 커밋**

```bash
git add srtgo/bot/handlers.py tests/bot/test_handlers.py
git commit -m "feat(bot): 결제 확인·취소 콜백 처리"
```

---

## Task 15: handlers — /cancel 명령

**Files:**
- Modify: `srtgo/bot/handlers.py`
- Modify: `tests/bot/test_handlers.py`

- [ ] **Step 1: 실패 테스트 추가**

`tests/bot/test_handlers.py` 끝에:
```python
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
```

테스트 파일 상단에 `import asyncio, threading` 추가.

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `pytest tests/bot/test_handlers.py -k cancel -v`
Expected: AttributeError.

- [ ] **Step 3: handlers.py에 /cancel 추가**

```python
async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _ensure_allowed(update):
        await _block_unallowed(update)
        return

    tid = update.effective_user.id
    actions = []

    if _SESSION.cancel_poll(tid):
        actions.append("폴링 중단됨")

    pending = _SESSION.get_pending(tid)
    if pending:
        try:
            await asyncio.to_thread(pending["rail"].cancel, pending["reservation"])
            actions.append("대기 중 예약 취소됨")
        except Exception as e:
            actions.append(f"예약 취소 실패: {e}")
        _SESSION.clear_pending(tid)

    if not actions:
        await update.message.reply_text("진행 중인 작업이 없어요.")
    else:
        await update.message.reply_text("\n".join(actions))
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/bot/test_handlers.py -v`
Expected: 모두 PASS.

- [ ] **Step 5: 커밋**

```bash
git add srtgo/bot/handlers.py tests/bot/test_handlers.py
git commit -m "feat(bot): /cancel 명령 — 폴링·예약 일괄 정리"
```

---

## Task 16: bot/main.py — Application 부트스트랩 + 재시작 알림

**Files:**
- Create: `srtgo/bot/main.py`

- [ ] **Step 1: srtgo/bot/main.py 작성**

```python
"""텔레그램 봇 엔트리포인트."""

import asyncio
import logging
import os
import sys

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from . import handlers, storage
from ..logging.setup import setup_logging

logger = logging.getLogger(__name__)


def _build_setup_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("setup", handlers.setup_entry)],
        states={
            handlers.STATE_CLAUDE_KEY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.setup_claude_key),
            ],
            handlers.STATE_SRT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.setup_srt),
            ],
            handlers.STATE_KTX: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.setup_ktx),
            ],
            handlers.STATE_CARD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.setup_card),
            ],
        },
        fallbacks=[CommandHandler("cancel", handlers.setup_cancel)],
    )


async def _send_restart_notice(app: Application) -> None:
    for tid in storage.list_user_ids():
        try:
            await app.bot.send_message(
                chat_id=tid,
                text="봇이 재시작됐어요. 진행 중이던 요청이 있었다면 다시 보내주세요.",
            )
        except Exception as e:
            logger.warning("재시작 알림 실패 tid=%d: %s", tid, e)


def main() -> None:
    setup_logging(debug=False)

    token = os.environ.get("BOT_TOKEN")
    if not token:
        print("BOT_TOKEN 환경변수 미설정", file=sys.stderr)
        sys.exit(1)
    if not os.environ.get("BOT_DB_KEY"):
        print("BOT_DB_KEY 환경변수 미설정 (Fernet 키)", file=sys.stderr)
        sys.exit(1)
    if not os.environ.get("BOT_ALLOWED_IDS"):
        print("경고: BOT_ALLOWED_IDS 비어있음 — 모든 사용자 차단됨", file=sys.stderr)

    app = Application.builder().token(token).post_init(_send_restart_notice).build()

    app.add_handler(CommandHandler("start", handlers.cmd_start))
    app.add_handler(CommandHandler("help", handlers.cmd_help))
    app.add_handler(CommandHandler("cancel", handlers.cmd_cancel))
    app.add_handler(_build_setup_conversation())
    app.add_handler(CallbackQueryHandler(handlers.on_pick, pattern=r"^pick:"))
    app.add_handler(CallbackQueryHandler(handlers.on_payment_decision, pattern=r"^pay:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.on_free_message))

    logger.info("봇 polling 시작")
    app.run_polling()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 임포트 sanity check**

Run: `python -c "from srtgo.bot import main; print('ok')"`
Expected: `ok`. 임포트 에러 시 누락된 함수·이름 보고 수정.

- [ ] **Step 3: 엔트리포인트 인식 확인**

Run: `pip install -e .` (재설치) 후 `srtgo-bot --help` 또는 `which srtgo-bot`
Expected: 명령 찾힘. (`--help` 미구현이라 그냥 토큰 없다고 종료해도 OK.)

- [ ] **Step 4: 커밋**

```bash
git add srtgo/bot/main.py
git commit -m "feat(bot): main 엔트리포인트·핸들러 등록·재시작 알림"
```

---

## Task 17: 운영 가이드 문서

**Files:**
- Create: `docs/bot-operations.md`

- [ ] **Step 1: docs/bot-operations.md 작성**

```markdown
# 텔레그램 봇 운영 가이드

## 사전 준비
1. 텔레그램에서 BotFather로 봇 생성 → 토큰 확보.
2. Fernet 마스터 키 생성:
   ```
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
3. 허용할 텔레그램 사용자 ID 수집. (각 사용자는 봇에 /start 한 번 보내면 차단 메시지에서 자기 ID 확인 가능.)

## 환경 변수
- `BOT_TOKEN` — BotFather 토큰
- `BOT_DB_KEY` — Fernet 키
- `BOT_ALLOWED_IDS` — 콤마 구분 ID (예: `111111,222222`)
- `BOT_USERS_DIR` — 자격증명 디렉토리 (기본: `data/users`)

## systemd 예시
`/etc/systemd/system/srtgo-bot.service`:
```ini
[Unit]
Description=srtgo telegram bot
After=network.target

[Service]
Type=simple
User=botuser
WorkingDirectory=/opt/srtgo
EnvironmentFile=/etc/srtgo-bot.env
ExecStart=/opt/srtgo/.venv/bin/srtgo-bot
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```
`/etc/srtgo-bot.env`:
```
BOT_TOKEN=...
BOT_DB_KEY=...
BOT_ALLOWED_IDS=...
```

## 백업
- `data/users/` 전체 디렉토리 + `BOT_DB_KEY`를 함께 보관.
- 마스터키 분실 = 모든 사용자 자격증명 복호화 불가.

## E2E 수동 검증 (배포 전)
1. 본인 계정만 allowlist에 두고 봇 가동.
2. `/setup` 으로 본인 SRT/KTX 자격증명·실제 카드 등록.
3. 빈 시간대에 자유 메시지 전송 → 폴링 시작 알림 확인.
4. 좌석 잡힐 때까지 대기 → ❌ 취소로 종료 (실제 결제 회피).
5. 한 번은 ✅ 결제까지 가서 실제 결제·환불 흐름 확인.
```

- [ ] **Step 2: 커밋**

```bash
git add docs/bot-operations.md
git commit -m "docs: 텔레그램 봇 운영 가이드"
```

---

## 최종 검증 체크리스트

- [ ] **Step 1: 전체 테스트 실행**

Run: `pytest -q`
Expected: 모든 테스트 PASS, 0 FAIL.

- [ ] **Step 2: 임포트 회귀**

Run:
```bash
python -c "from srtgo.bot import main, handlers, parser, storage, session, notifier, auth_guard; print('ok')"
python -c "from srtgo.cli.main import srtgo; print('cli ok')"
```
Expected: 둘 다 `ok`.

- [ ] **Step 3: CLI 회귀 (변경된 service가 깨지지 않았는지)**

Run: `srtgo --help`
Expected: 도움말 출력 정상.

- [ ] **Step 4: spec과 plan 정합성 최종 확인**

spec의 §6 데이터 흐름 5개(setup, 예매 요청, 좌석 잡힘 결제, /cancel, 재시작)가 모두 Task 5–17에서 구현되었는지 직접 매핑:
- §6.1 setup → Task 11
- §6.2 예매 요청 (파싱·검색·후보 표시) → Task 12 + Task 13
- §6.3 좌석 잡힘 결제 → Task 13(콜백 셋업) + Task 14(결제 확인)
- §6.4 /cancel → Task 15
- §6.5 재시작 알림 → Task 16

- [ ] **Step 5: 운영자 E2E 수동 검증 진행**

`docs/bot-operations.md` §"E2E 수동 검증" 절차 수행. 결제 한 번까지 끝.
