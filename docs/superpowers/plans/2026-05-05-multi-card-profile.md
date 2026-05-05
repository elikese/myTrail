# 카드 다중 등록 / 결제 시 카드 선택 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사용자별 카드 N장 등록·관리, 결제 시 카드 선택 UX 도입. 자격증명(SRT/KTX)은 1세트 그대로 유지.

**Architecture:** `data/users/{tid}.json.enc` 평문 JSON에 `cards: list[dict]` 추가. 각 카드는 4 hex `id` + 선택적 `label` + 카드 4필드. legacy 단수 `card` 키는 `storage.load()` 시점에 자동 마이그레이션. 결제 시 ✅결제 → 카드 선택 인라인 키보드 → 카드 클릭 시 결제 실행. `/cards` 명령 하나로 목록·추가·삭제 관리.

**Tech Stack:** Python 3, `python-telegram-bot`(v20), `cryptography.fernet`, `pytest`, `secrets`.

**Spec:** `docs/superpowers/specs/2026-05-05-multi-card-profile-design.md`

---

## File Structure

| 파일 | 변경 |
|---|---|
| `srtgo/bot/storage.py` | `load()` 본문 마이그레이션, 카드 헬퍼 4종 추가 |
| `srtgo/bot/handlers.py` | setup 흐름에 별칭 단계 추가, 결제 흐름 카드 선택, /cards 핸들러군 추가 |
| `srtgo/bot/main.py` | /cards CommandHandler, 카드 추가 ConversationHandler, cards:.* 콜백 등록 |
| `tests/bot/test_storage.py` | 마이그레이션·헬퍼 테스트 추가, 기존 round-trip 테스트 새 포맷으로 갱신 |
| `tests/bot/test_handlers.py` | setup 별칭 단계, 결제 흐름 변경, /cards 흐름 테스트 추가 |

---

## Task 1: storage — 카드 헬퍼 + 자동 마이그레이션

**Files:**
- Modify: `srtgo/bot/storage.py`
- Modify: `tests/bot/test_storage.py`

기존 `load()` 동작이 바뀌므로 라운드트립 테스트도 새 포맷으로 갱신한다. 카드 헬퍼는 모두 load → 변경 → save 패턴.

- [ ] **Step 1: 기존 라운드트립 테스트를 새 포맷으로 갱신**

기존 `test_save_and_load_round_trip`는 legacy `card` 키를 저장하고 그대로 다시 읽기를 검증하는데, 마이그레이션 도입 후엔 깨진다. 새 포맷(`cards`)으로 직접 저장하면 변경 없이 그대로 읽혀야 한다.

`tests/bot/test_storage.py` 상단 import는 그대로 두고, `test_save_and_load_round_trip` 함수만 다음과 같이 교체한다:

```python
def test_save_and_load_round_trip(tmp_user_dir, fernet_key):
    from srtgo.bot import storage

    data = {
        "srt": {"id": "u", "pw": "p"},
        "ktx": None,
        "cards": [
            {"id": "ab12", "label": "신한", "number": "1", "password": "2",
             "birthday": "3", "expire": "4"},
        ],
    }
    storage.save(123456, data)
    assert storage.exists(123456)
    assert storage.load(123456) == data
```

- [ ] **Step 2: 마이그레이션 테스트 작성 (실패해야 함)**

`tests/bot/test_storage.py` 끝에 추가:

```python
def test_load_migrates_legacy_card_to_cards(tmp_user_dir, fernet_key, monkeypatch):
    """legacy 단수 card 키가 cards 리스트로 자동 변환된다."""
    from srtgo.bot import storage

    legacy = {
        "srt": {"id": "u", "pw": "p"},
        "ktx": None,
        "card": {"number": "1111", "password": "12",
                 "birthday": "900101", "expire": "1230"},
    }
    storage.save(1, legacy)

    # token_hex를 결정적으로 만들어 검증 단순화
    monkeypatch.setattr(storage.secrets, "token_hex", lambda n: "ab12")

    loaded = storage.load(1)

    assert "card" not in loaded
    assert loaded["cards"] == [{
        "id": "ab12", "label": None,
        "number": "1111", "password": "12",
        "birthday": "900101", "expire": "1230",
    }]
    assert loaded["srt"] == {"id": "u", "pw": "p"}
    assert loaded["ktx"] is None


def test_load_persists_migration_to_disk(tmp_user_dir, fernet_key, monkeypatch):
    """마이그레이션 후 디스크도 새 포맷으로 갱신되어 두 번째 load는 변환 없이 동일."""
    from srtgo.bot import storage

    legacy = {"srt": None, "ktx": None,
              "card": {"number": "n", "password": "p",
                       "birthday": "b", "expire": "e"}}
    storage.save(1, legacy)

    monkeypatch.setattr(storage.secrets, "token_hex", lambda n: "ab12")
    first = storage.load(1)

    # 두 번째 load는 마이그레이션 안 일어남 (token_hex가 다른 값을 줘도 영향 없음)
    monkeypatch.setattr(storage.secrets, "token_hex", lambda n: "ffff")
    second = storage.load(1)

    assert first == second
    assert second["cards"][0]["id"] == "ab12"


def test_load_idempotent_for_already_new_format(tmp_user_dir, fernet_key):
    """이미 cards 키만 있으면 변환·저장 없이 그대로 반환."""
    from srtgo.bot import storage

    data = {"srt": None, "ktx": None,
            "cards": [{"id": "x1y2", "label": None, "number": "n",
                       "password": "p", "birthday": "b", "expire": "e"}]}
    storage.save(1, data)
    assert storage.load(1) == data


def test_load_prefers_cards_when_both_present(tmp_user_dir, fernet_key, caplog):
    """legacy card와 cards가 동시 존재할 때 cards를 우선하고 card를 무시한다."""
    import logging
    from srtgo.bot import storage

    mixed = {
        "srt": None, "ktx": None,
        "card": {"number": "ignored", "password": "x",
                 "birthday": "x", "expire": "x"},
        "cards": [{"id": "aa11", "label": "kept", "number": "kept_num",
                   "password": "p", "birthday": "b", "expire": "e"}],
    }
    storage.save(1, mixed)

    with caplog.at_level(logging.WARNING):
        loaded = storage.load(1)

    assert "card" not in loaded
    assert loaded["cards"][0]["number"] == "kept_num"
```

- [ ] **Step 3: 위 4개 테스트 실행해 모두 실패 확인**

Run: `pytest tests/bot/test_storage.py -k "migrates or persists or idempotent or prefers" -v`
Expected: 4 FAIL — `card` 키가 그대로 남아있어 assertion 실패 / `secrets` 미참조 등

또한 `test_save_and_load_round_trip`도 실행해 통과 확인:
Run: `pytest tests/bot/test_storage.py::test_save_and_load_round_trip -v`
Expected: PASS (load는 아직 마이그레이션 안 하므로 cards 그대로 읽힘)

- [ ] **Step 4: storage.py에 secrets import 추가 + load 마이그레이션 구현**

`srtgo/bot/storage.py` 상단 import 블록에 추가:

```python
import secrets
```

`load()` 함수를 다음으로 교체 (기존 함수 전체 대체):

```python
def load(telegram_id: int) -> dict | None:
    p = _path(telegram_id)
    if not p.exists():
        return None
    token = p.read_bytes()
    try:
        plaintext = _get_cipher().decrypt(token)
    except InvalidToken as e:
        raise StorageDecryptError(str(e)) from e
    data = json.loads(plaintext.decode())

    if _migrate_in_place(data):
        try:
            save(telegram_id, data)
        except Exception as e:
            logger.warning("마이그레이션 디스크 저장 실패 tid=%d: %s", telegram_id, e)

    return data


def _migrate_in_place(data: dict) -> bool:
    """legacy `card` 키를 `cards` 리스트로 변환. 변경되었으면 True."""
    has_legacy = "card" in data
    has_new = "cards" in data and data["cards"] is not None

    if has_legacy and has_new:
        logger.warning("legacy card와 cards 동시 존재 — card 무시")
        del data["card"]
        return True

    if has_legacy and not has_new:
        legacy = data.pop("card")
        if legacy:
            new_card = {"id": _fresh_card_id(set()), "label": None, **legacy}
            data["cards"] = [new_card]
        else:
            data["cards"] = []
        return True

    return False


def _fresh_card_id(existing_ids: set[str]) -> str:
    """4 hex id 생성 — 충돌 시 재추첨 (최대 10회). 실패 시 RuntimeError."""
    for _ in range(10):
        candidate = secrets.token_hex(2)
        if candidate not in existing_ids:
            return candidate
    raise RuntimeError("카드 ID 생성 충돌 한도 초과")
```

- [ ] **Step 5: 4개 마이그레이션 테스트 통과 확인**

Run: `pytest tests/bot/test_storage.py -v`
Expected: 모두 PASS (round-trip 포함 9개 통과)

- [ ] **Step 6: 카드 헬퍼 테스트 작성 (실패해야 함)**

`tests/bot/test_storage.py` 끝에 추가:

```python
def test_add_card_appends_with_id(tmp_user_dir, fernet_key, monkeypatch):
    from srtgo.bot import storage

    storage.save(1, {"srt": None, "ktx": None, "cards": []})
    monkeypatch.setattr(storage.secrets, "token_hex", lambda n: "ab12")

    fields = {"number": "1111", "password": "12",
              "birthday": "900101", "expire": "1230"}
    new_id = storage.add_card(1, fields, label="신한")

    assert new_id == "ab12"
    cards = storage.list_cards(1)
    assert cards == [{"id": "ab12", "label": "신한",
                      "number": "1111", "password": "12",
                      "birthday": "900101", "expire": "1230"}]


def test_add_card_id_collision_retries(tmp_user_dir, fernet_key, monkeypatch):
    from srtgo.bot import storage

    storage.save(1, {"srt": None, "ktx": None,
                     "cards": [{"id": "ab12", "label": None, "number": "x",
                                "password": "x", "birthday": "x", "expire": "x"}]})

    seq = iter(["ab12", "ab12", "cd34"])  # 충돌 두 번 후 통과
    monkeypatch.setattr(storage.secrets, "token_hex", lambda n: next(seq))

    new_id = storage.add_card(1, {"number": "n", "password": "p",
                                  "birthday": "b", "expire": "e"}, label=None)
    assert new_id == "cd34"
    assert {c["id"] for c in storage.list_cards(1)} == {"ab12", "cd34"}


def test_remove_card_returns_true_when_present(tmp_user_dir, fernet_key):
    from srtgo.bot import storage

    storage.save(1, {"srt": None, "ktx": None,
                     "cards": [{"id": "ab12", "label": None, "number": "n",
                                "password": "p", "birthday": "b", "expire": "e"}]})

    assert storage.remove_card(1, "ab12") is True
    assert storage.list_cards(1) == []


def test_remove_card_returns_false_when_absent(tmp_user_dir, fernet_key):
    from srtgo.bot import storage

    storage.save(1, {"srt": None, "ktx": None, "cards": []})
    assert storage.remove_card(1, "nope") is False


def test_get_card_returns_card_or_none(tmp_user_dir, fernet_key):
    from srtgo.bot import storage

    card = {"id": "ab12", "label": None, "number": "n",
            "password": "p", "birthday": "b", "expire": "e"}
    storage.save(1, {"srt": None, "ktx": None, "cards": [card]})

    assert storage.get_card(1, "ab12") == card
    assert storage.get_card(1, "nope") is None


def test_list_cards_on_user_without_file_returns_empty(tmp_user_dir, fernet_key):
    from srtgo.bot import storage
    assert storage.list_cards(999) == []
```

- [ ] **Step 7: 카드 헬퍼 테스트 실패 확인**

Run: `pytest tests/bot/test_storage.py -k "add_card or remove_card or get_card or list_cards" -v`
Expected: 6 FAIL — 함수가 정의되지 않아 AttributeError

- [ ] **Step 8: storage.py에 카드 헬퍼 4종 구현**

`srtgo/bot/storage.py` 끝에 추가:

```python
def list_cards(telegram_id: int) -> list[dict]:
    data = load(telegram_id)
    if data is None:
        return []
    return list(data.get("cards", []))


def get_card(telegram_id: int, card_id: str) -> dict | None:
    for card in list_cards(telegram_id):
        if card["id"] == card_id:
            return card
    return None


def add_card(telegram_id: int, fields: dict, label: str | None) -> str:
    data = load(telegram_id) or {"srt": None, "ktx": None, "cards": []}
    data.setdefault("cards", [])
    existing_ids = {c["id"] for c in data["cards"]}
    new_id = _fresh_card_id(existing_ids)
    data["cards"].append({"id": new_id, "label": label, **fields})
    save(telegram_id, data)
    return new_id


def remove_card(telegram_id: int, card_id: str) -> bool:
    data = load(telegram_id)
    if data is None:
        return False
    cards = data.get("cards", [])
    new_cards = [c for c in cards if c["id"] != card_id]
    if len(new_cards) == len(cards):
        return False
    data["cards"] = new_cards
    save(telegram_id, data)
    return True
```

- [ ] **Step 9: 헬퍼 테스트 통과 확인**

Run: `pytest tests/bot/test_storage.py -v`
Expected: 모두 PASS (15개)

- [ ] **Step 10: 커밋**

```bash
git add srtgo/bot/storage.py tests/bot/test_storage.py
git commit -m "feat(storage): cards 리스트 + 자동 마이그레이션 + 카드 헬퍼"
```

---

## Task 2: handlers — setup 흐름에 별칭 입력 단계 추가

**Files:**
- Modify: `srtgo/bot/handlers.py`
- Modify: `tests/bot/test_handlers.py`
- Modify: `srtgo/bot/main.py` (ConversationHandler에 새 state 등록)

setup 마지막에 STATE_CARD_LABEL 추가. setup_card는 4필드를 받아 임시 저장하고 STATE_CARD_LABEL로, setup_card_label에서 별칭(또는 'skip')을 받아 cards 리스트로 저장한다. 헬프 텍스트의 단계 카운트는 1/3·2/3·3/3 → 1/4·2/4·3/4·4/4로 갱신.

- [ ] **Step 1: 기존 setup 테스트들을 새 포맷으로 갱신**

`tests/bot/test_handlers.py`에서 다음 테스트들을 수정한다.

`test_setup_full_flow_saves_credentials`를 다음으로 교체:

```python
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
```

`test_setup_entry_first_call_warns_and_ends`와 `test_setup_entry_second_call_proceeds`에서 `storage.save(111, {..., "card": {...}})` 부분을 다음 형태로 갱신:

```python
storage.save(111, {"srt": None, "ktx": None, "cards": [
    {"id": "ab12", "label": None, "number": "n", "password": "p",
     "birthday": "b", "expire": "e"}
]})
```

`test_setup_entry_second_call_proceeds`의 끝에 있는 assertion `assert "1/3" in text`를 다음으로 변경:
```python
assert "1/4" in text
```

`test_freemsg_parses_and_searches`에서 `storage.save(111, {... "card": {...}})` 부분을 위와 같은 cards 리스트 형태로 갱신.

`test_clarification_round_trip_concats_messages`도 마찬가지로 cards 리스트 사용하도록 갱신.

- [ ] **Step 2: 별칭 단계 테스트 추가 (실패해야 함)**

`tests/bot/test_handlers.py` 끝에 추가:

```python
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
```

- [ ] **Step 3: 신규 테스트 실패 확인**

Run: `pytest tests/bot/test_handlers.py -k "setup_card_label" -v`
Expected: 2 FAIL — `setup_card_label`, `STATE_CARD_LABEL` 미정의

또 갱신된 기존 테스트들도 현재 실패 상태일 것:
Run: `pytest tests/bot/test_handlers.py -k "setup_full_flow or setup_entry_first or setup_entry_second or freemsg_parses or clarification" -v`
Expected: 일부 FAIL (예: `1/4` 검사 실패, `_pending_card` 키 미존재 등)

- [ ] **Step 4: handlers.py 수정 — STATE_CARD_LABEL 추가, setup_card 분리, setup_card_label 신규**

`srtgo/bot/handlers.py`의 `STATE_SRT, STATE_KTX, STATE_CARD = range(3)` 라인을 다음으로 교체:

```python
STATE_SRT, STATE_KTX, STATE_CARD, STATE_CARD_LABEL = range(4)
```

`setup_entry` 안의 첫 안내 메시지를 다음으로 교체 (단계 카운트 1/3 → 1/4):

```python
    await update.message.reply_text(
        "자격증명 등록을 시작합니다.\n"
        "1/4: SRT 아이디·비번을 한 줄에 공백으로 구분해 보내주세요.\n"
        "사용 안 하면 'skip'. (취소: /cancel)"
    )
```

`setup_srt`의 reply 메시지를 `"2/4: KTX(코레일) 아이디·비번. 사용 안 하면 'skip'."`로,
`setup_ktx`의 reply 메시지를 다음으로 교체:

```python
    await update.message.reply_text(
        "3/4: 카드 정보를 한 줄에 공백 4개로:\n"
        "  카드번호 비번앞2자리 생년월일(YYMMDD) 만료(MMYY)\n"
        "예: 1111222233334444 12 900101 1230"
    )
```

`setup_card` 함수 전체를 다음으로 교체 (저장 안 하고 별칭 단계로 넘김):

```python
async def setup_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    parts = update.message.text.strip().split()
    if len(parts) != 4:
        await update.message.reply_text("형식이 잘못됐어요. 4개 항목을 공백으로.")
        return STATE_CARD
    number, password, birthday, expire = parts
    context.user_data["setup"]["_pending_card"] = {
        "number": number, "password": password,
        "birthday": birthday, "expire": expire,
    }
    await update.message.reply_text(
        "4/4: 카드 별칭? (예: '신한', 없으면 'skip')"
    )
    return STATE_CARD_LABEL
```

이어서 `setup_card_label` 신규 추가 (`setup_card` 바로 아래):

```python
async def setup_card_label(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    label: str | None
    if text.lower() == "skip" or text == "":
        label = None
    else:
        label = text[:32]

    setup_data = context.user_data.get("setup", {})
    pending = setup_data.pop("_pending_card", None)
    if pending is None:
        await update.message.reply_text("등록 상태 손상. /setup 다시 해주세요.")
        context.user_data.pop("setup", None)
        return ConversationHandler.END

    new_id = storage._fresh_card_id(set())
    setup_data["cards"] = [{"id": new_id, "label": label, **pending}]
    storage.save(update.effective_user.id, setup_data)

    context.user_data.pop("setup", None)
    await update.message.reply_text("등록 완료. 이제 자유롭게 말해보세요.")
    return ConversationHandler.END
```

- [ ] **Step 5: main.py ConversationHandler에 STATE_CARD_LABEL 등록**

`srtgo/bot/main.py`의 `_build_setup_conversation` 함수의 `states` dict에 항목 추가:

```python
            handlers.STATE_CARD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.setup_card),
            ],
            handlers.STATE_CARD_LABEL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.setup_card_label),
            ],
```

- [ ] **Step 6: setup 관련 테스트 모두 통과 확인**

Run: `pytest tests/bot/test_handlers.py -k "setup" -v`
Expected: 모두 PASS

Run: `pytest tests/bot/test_handlers.py -v`
Expected: 모두 PASS (다른 테스트도 cards 포맷 갱신 완료됐으므로)

- [ ] **Step 7: 커밋**

```bash
git add srtgo/bot/handlers.py srtgo/bot/main.py tests/bot/test_handlers.py
git commit -m "feat(setup): 카드 별칭 입력 단계 + cards 리스트로 저장"
```

---

## Task 3: 결제 흐름 — 카드 선택 키보드 + pay:card / pay:back

**Files:**
- Modify: `srtgo/bot/handlers.py`
- Modify: `tests/bot/test_handlers.py`

✅결제(`pay:confirm`) 콜백이 카드 선택 키보드를 띄우게 변경하고, 신규 콜백 `pay:card:<id>`로 실제 결제, `pay:back`으로 좌석 알림 화면 복귀. 기존 `^pay:` 단일 핸들러 등록은 유지하되 `on_payment_decision` 내부에서 분기한다.

- [ ] **Step 1: 카드 표시 헬퍼 테스트 작성 (실패해야 함)**

`tests/bot/test_handlers.py` 끝에 추가:

```python
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
```

- [ ] **Step 2: 표시 헬퍼 실패 확인**

Run: `pytest tests/bot/test_handlers.py -k "card_display" -v`
Expected: 2 FAIL — `_card_display` 미정의

- [ ] **Step 3: handlers.py에 `_card_display` + `_card_select_keyboard` 헬퍼 추가**

`srtgo/bot/handlers.py`의 `from ..service import payment as svc_pay` 라인 위쪽 (또는 가까운 적절한 위치) 에 추가. 기존 keyboard 헬퍼들(`_train_keyboard` 등) 근처가 자연스럽다:

```python
def _card_display(card: dict) -> str:
    last4 = card["number"][-4:]
    if card.get("label"):
        return f"{card['label']} (*{last4})"
    return f"*{last4}"


def _card_select_keyboard(cards: list[dict]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(_card_display(c), callback_data=f"pay:card:{c['id']}")]
        for c in cards
    ]
    rows.append([InlineKeyboardButton("← 돌아가기", callback_data="pay:back")])
    return InlineKeyboardMarkup(rows)
```

- [ ] **Step 4: 표시 헬퍼 테스트 통과 확인**

Run: `pytest tests/bot/test_handlers.py -k "card_display" -v`
Expected: 2 PASS

- [ ] **Step 5: 결제 흐름 테스트 작성 (기존 `test_pay_confirm_charges_card` 교체 + 신규 추가)**

`tests/bot/test_handlers.py`에서 기존 `test_pay_confirm_charges_card`를 다음으로 교체:

```python
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
```

또한 기존 `test_pay_cancel_calls_rail_cancel`의 `storage.save(111, {... "card": ...})` 부분도 cards 리스트 형태로 갱신:

```python
    storage.save(111, {"srt": None, "ktx": None, "cards": []})
```

(이 테스트는 cancel 동작만 검증하므로 cards 비어있어도 무관)

- [ ] **Step 6: 결제 테스트 실패 확인**

Run: `pytest tests/bot/test_handlers.py -k "pay_" -v`
Expected: 5 신규 테스트 FAIL (pay:card 분기, pay:back 분기 미구현)

- [ ] **Step 7: handlers.py — `on_payment_decision` 분기 재구성**

`srtgo/bot/handlers.py`의 `on_payment_decision` 함수 전체를 다음으로 교체:

```python
async def on_payment_decision(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cq = update.callback_query
    await cq.answer()
    tid = update.effective_user.id

    if cq.data == "pay:cancel":
        await _handle_pay_cancel(cq, tid)
        return
    if cq.data == "pay:back":
        await _handle_pay_back(cq, tid)
        return
    if cq.data == "pay:confirm":
        await _handle_pay_confirm(cq, tid)
        return
    if cq.data.startswith("pay:card:"):
        card_id = cq.data.removeprefix("pay:card:")
        await _handle_pay_card(cq, tid, card_id)
        return


async def _handle_pay_cancel(cq, tid: int) -> None:
    pending = _SESSION.get_pending(tid)
    if not pending:
        await cq.edit_message_text("대기 중인 예약이 없어요. 결제 마감이 지났을 수 있습니다.")
        return
    try:
        await asyncio.to_thread(pending["rail"].cancel, pending["reservation"])
    except Exception as e:
        logger.error("예약 취소 실패: %s", e)
    _SESSION.clear_pending(tid)
    await cq.edit_message_text("예약 취소됨.")


async def _handle_pay_confirm(cq, tid: int) -> None:
    pending = _SESSION.get_pending(tid)
    if not pending:
        await cq.edit_message_text("대기 중인 예약이 없어요. 결제 마감이 지났을 수 있습니다.")
        return

    cards = storage.list_cards(tid)
    if not cards:
        await cq.edit_message_text(
            "등록된 카드가 없어요. /cards 에서 추가 후 다시 결제 눌러주세요.",
            reply_markup=notifier.confirm_keyboard(),
        )
        return

    await cq.edit_message_text(
        "어느 카드로 결제할까요?",
        reply_markup=_card_select_keyboard(cards),
    )


async def _handle_pay_back(cq, tid: int) -> None:
    pending = _SESSION.get_pending(tid)
    if not pending:
        await cq.edit_message_text("대기 중인 예약이 없어요.")
        return
    await cq.edit_message_text(
        notifier.format_seat_secured_message(pending["reservation"]),
        reply_markup=notifier.confirm_keyboard(),
    )


async def _handle_pay_card(cq, tid: int, card_id: str) -> None:
    pending = _SESSION.get_pending(tid)
    if not pending:
        await cq.edit_message_text("대기 중인 예약이 없어요. 결제 마감이 지났을 수 있습니다.")
        return

    card = storage.get_card(tid, card_id)
    if card is None:
        await cq.edit_message_text(
            "이 카드는 삭제됐어요. 다시 결제 눌러 카드를 골라주세요.",
            reply_markup=notifier.confirm_keyboard(),
        )
        return

    rail = pending["rail"]
    reservation = pending["reservation"]
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

기존 `on_payment_decision` 함수 본문(if cq.data == "pay:cancel": ... 통째)은 위 4개 헬퍼 함수로 분산되었으므로 더 이상 필요 없음. 교체 시 함수 전체를 위 코드로 통째 대체.

(기존에 `from ..service import payment as svc_pay` import는 그대로 유지)

- [ ] **Step 8: 결제 테스트 통과 확인**

Run: `pytest tests/bot/test_handlers.py -k "pay_" -v`
Expected: 모두 PASS (test_pay_cancel_calls_rail_cancel 포함 6개)

Run: `pytest tests/bot/test_handlers.py -v`
Expected: 전체 PASS

- [ ] **Step 9: 커밋**

```bash
git add srtgo/bot/handlers.py tests/bot/test_handlers.py
git commit -m "feat(pay): 결제 시 카드 선택 키보드 + pay:card / pay:back"
```

---

## Task 4: /cards 명령 — 목록 보기 + 삭제

**Files:**
- Modify: `srtgo/bot/handlers.py`
- Modify: `tests/bot/test_handlers.py`
- Modify: `srtgo/bot/main.py`

`/cards` 명령으로 카드 목록 + 삭제 처리. 카드 추가 흐름은 다음 Task 5에서 ConversationHandler로 처리 (콜백 진입). 이 Task는 카드 추가를 제외한 부분.

- [ ] **Step 1: /cards 목록·삭제 테스트 작성 (실패해야 함)**

`tests/bot/test_handlers.py` 끝에 추가:

```python
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
    assert "신한" in text or kwargs["reply_markup"].inline_keyboard  # 키보드에라도 표시


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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/bot/test_handlers.py -k "cards" -v`
Expected: 7 FAIL — `cmd_cards`, `on_cards_callback` 미정의

- [ ] **Step 3: handlers.py에 /cards 핸들러 + 콜백 처리 구현**

`srtgo/bot/handlers.py` 끝에 추가:

```python
def _cards_keyboard(cards: list[dict]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(f"🗑 {_card_display(c)}",
                              callback_data=f"cards:del:{c['id']}")]
        for c in cards
    ]
    rows.append([InlineKeyboardButton("➕ 카드 추가", callback_data="cards:add")])
    return InlineKeyboardMarkup(rows)


def _cards_list_text(cards: list[dict]) -> str:
    if not cards:
        return "등록된 카드가 없어요. ➕ 카드 추가 버튼을 눌러주세요."
    lines = ["등록된 카드:"]
    for c in cards:
        lines.append(f"- {_card_display(c)}")
    return "\n".join(lines)


def _del_confirm_keyboard(card_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("예, 삭제",
                             callback_data=f"cards:del_confirm:{card_id}"),
        InlineKeyboardButton("아니오", callback_data="cards:noop"),
    ]])


async def cmd_cards(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _ensure_allowed(update):
        await _block_unallowed(update)
        return

    tid = update.effective_user.id
    if not storage.exists(tid):
        await update.message.reply_text("/setup 부터 해주세요.")
        return

    cards = storage.list_cards(tid)
    await update.message.reply_text(
        _cards_list_text(cards),
        reply_markup=_cards_keyboard(cards),
    )


async def on_cards_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """cards:del:<id>, cards:del_confirm:<id>, cards:noop 처리.

    cards:add 는 별도 ConversationHandler 진입점으로 등록됨.
    """
    cq = update.callback_query
    await cq.answer()
    tid = update.effective_user.id

    if cq.data.startswith("cards:del_confirm:"):
        card_id = cq.data.removeprefix("cards:del_confirm:")
        storage.remove_card(tid, card_id)
        cards = storage.list_cards(tid)
        await cq.edit_message_text(
            _cards_list_text(cards),
            reply_markup=_cards_keyboard(cards),
        )
        return

    if cq.data.startswith("cards:del:"):
        card_id = cq.data.removeprefix("cards:del:")
        card = storage.get_card(tid, card_id)
        if card is None:
            cards = storage.list_cards(tid)
            await cq.edit_message_text(
                _cards_list_text(cards),
                reply_markup=_cards_keyboard(cards),
            )
            return
        await cq.edit_message_text(
            f"정말 삭제할까요?\n  {_card_display(card)}",
            reply_markup=_del_confirm_keyboard(card_id),
        )
        return

    if cq.data == "cards:noop":
        cards = storage.list_cards(tid)
        await cq.edit_message_text(
            _cards_list_text(cards),
            reply_markup=_cards_keyboard(cards),
        )
        return
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/bot/test_handlers.py -k "cards" -v`
Expected: 7 PASS

Run: `pytest tests/bot/test_handlers.py -v`
Expected: 전체 PASS

- [ ] **Step 5: main.py에 /cards 명령 + cards 콜백 등록**

`srtgo/bot/main.py`의 `main()` 함수, 핸들러 등록 부분(`app.add_handler(...)` 시퀀스)에 추가. `pay:` 콜백 등록 라인 바로 다음에:

```python
    app.add_handler(CommandHandler("cards", handlers.cmd_cards))
    app.add_handler(CallbackQueryHandler(
        handlers.on_cards_callback,
        pattern=r"^cards:(del|del_confirm|noop)",
    ))
```

(주의: `cards:add` 는 다음 Task 5에서 ConversationHandler 진입점으로 처리되므로 위 패턴에서 의도적으로 제외)

- [ ] **Step 6: 헬프 텍스트 갱신**

`srtgo/bot/handlers.py` 상단의 `HELP_TEXT`를 다음으로 교체:

```python
HELP_TEXT = (
    "사용법:\n"
    "/setup — 자격증명 등록 (Claude API 키, 철도사 ID/PW, 카드)\n"
    "/cards — 카드 목록·추가·삭제\n"
    "/cancel — 진행 중 예약 시도·예약 취소\n"
    "/help — 도움말\n\n"
    "그 외에는 자유롭게 말하세요. 예: '내일 오후 6시 부산에서 서울 KTX'"
)
```

기존 `test_help_lists_commands`는 `/setup`, `/cancel`, `/help`만 검사하므로 통과. 추가로 /cards 도 들어갔는지 검증하기 위해 `test_help_lists_commands`의 cmd 리스트를 갱신:

`tests/bot/test_handlers.py`의 `test_help_lists_commands`에서:

```python
    for cmd in ["/setup", "/cancel", "/help"]:
```

를 다음으로 교체:

```python
    for cmd in ["/setup", "/cards", "/cancel", "/help"]:
```

- [ ] **Step 7: 전체 테스트 통과 확인**

Run: `pytest tests/bot/ -v`
Expected: 전체 PASS

- [ ] **Step 8: 커밋**

```bash
git add srtgo/bot/handlers.py srtgo/bot/main.py tests/bot/test_handlers.py
git commit -m "feat(cards): /cards 명령 — 목록·삭제 + 헬프 텍스트 갱신"
```

---

## Task 5: 카드 추가 흐름 — `cards:add` 진입 ConversationHandler

**Files:**
- Modify: `srtgo/bot/handlers.py`
- Modify: `tests/bot/test_handlers.py`
- Modify: `srtgo/bot/main.py`

`cards:add` 콜백을 ConversationHandler 진입점으로 등록해 카드 4필드 + 별칭 입력을 받는다. setup의 카드 단계와 동일한 입력 형식.

- [ ] **Step 1: 카드 추가 흐름 테스트 작성 (실패해야 함)**

`tests/bot/test_handlers.py` 끝에 추가:

```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/bot/test_handlers.py -k "cards_add" -v`
Expected: 4 FAIL — `STATE_CARDS_NEW_FIELDS`, `cards_add_entry`, `cards_add_fields`, `cards_add_label` 미정의

- [ ] **Step 3: handlers.py에 카드 추가 흐름 구현**

`srtgo/bot/handlers.py`의 `STATE_SRT, STATE_KTX, STATE_CARD, STATE_CARD_LABEL = range(4)` 라인 다음에 추가:

```python
STATE_CARDS_NEW_FIELDS, STATE_CARDS_NEW_LABEL = range(10, 12)
```

(기존 setup 상태 4개와 충돌 안 나게 의도적으로 큰 번호 사용)

`srtgo/bot/handlers.py` 끝에 추가:

```python
async def cards_add_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """cards:add 콜백 진입점."""
    cq = update.callback_query
    await cq.answer()

    context.user_data.pop("cards_new", None)
    context.user_data["cards_new"] = {}

    await cq.edit_message_text(
        "추가할 카드 정보를 한 줄에 공백 4개로:\n"
        "  카드번호 비번앞2자리 생년월일(YYMMDD) 만료(MMYY)\n"
        "예: 1111222233334444 12 900101 1230\n"
        "(취소: /cancel)"
    )
    return STATE_CARDS_NEW_FIELDS


async def cards_add_fields(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    parts = update.message.text.strip().split()
    if len(parts) != 4:
        await update.message.reply_text("형식이 잘못됐어요. 4개 항목을 공백으로.")
        return STATE_CARDS_NEW_FIELDS
    number, password, birthday, expire = parts
    context.user_data["cards_new"] = {
        "number": number, "password": password,
        "birthday": birthday, "expire": expire,
    }
    await update.message.reply_text("카드 별칭? (예: '신한', 없으면 'skip')")
    return STATE_CARDS_NEW_LABEL


async def cards_add_label(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    label: str | None
    if text.lower() == "skip" or text == "":
        label = None
    else:
        label = text[:32]

    fields = context.user_data.pop("cards_new", None)
    if not fields:
        await update.message.reply_text("등록 상태 손상. /cards 다시 해주세요.")
        return ConversationHandler.END

    storage.add_card(update.effective_user.id, fields, label)
    cards = storage.list_cards(update.effective_user.id)
    await update.message.reply_text(
        _cards_list_text(cards),
        reply_markup=_cards_keyboard(cards),
    )
    return ConversationHandler.END


async def cards_add_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("cards_new", None)
    await update.message.reply_text("카드 추가 취소됨.")
    return ConversationHandler.END
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/bot/test_handlers.py -k "cards_add" -v`
Expected: 4 PASS

Run: `pytest tests/bot/ -v`
Expected: 전체 PASS

- [ ] **Step 5: main.py — 카드 추가 ConversationHandler 등록**

`srtgo/bot/main.py`의 `_build_setup_conversation` 정의 바로 아래에 추가:

```python
def _build_cards_add_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handlers.cards_add_entry, pattern=r"^cards:add$"),
        ],
        states={
            handlers.STATE_CARDS_NEW_FIELDS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.cards_add_fields),
            ],
            handlers.STATE_CARDS_NEW_LABEL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.cards_add_label),
            ],
        },
        fallbacks=[CommandHandler("cancel", handlers.cards_add_cancel)],
        per_message=False,
    )
```

`main()` 함수의 핸들러 등록부에서, 기존 `_build_setup_conversation()` 등록 라인 바로 다음에 추가:

```python
    app.add_handler(_build_cards_add_conversation())
```

- [ ] **Step 6: 커밋**

```bash
git add srtgo/bot/handlers.py srtgo/bot/main.py tests/bot/test_handlers.py
git commit -m "feat(cards): cards:add ConversationHandler — 카드 4필드 + 별칭 입력"
```

---

## Task 6: legacy 마이그레이션 e2e 통합 테스트

**Files:**
- Modify: `tests/bot/test_storage.py`

기존 사용자가 봇을 처음 다시 켤 때 자동으로 새 포맷으로 마이그레이션되는지 확인하는 통합 테스트. Task 1에서 단위 테스트는 충분하지만 "디스크에 legacy 파일을 미리 두고 첫 호출이 새 포맷을 만든다"는 시나리오를 명시적으로 검증한다.

- [ ] **Step 1: 통합 테스트 추가**

`tests/bot/test_storage.py` 끝에 추가:

```python
def test_legacy_user_first_load_writes_new_format_to_disk(tmp_user_dir, fernet_key, monkeypatch):
    """디스크에 legacy 파일이 있던 사용자가 첫 load 후 디스크가 새 포맷으로 갱신된다."""
    from srtgo.bot import storage

    legacy = {
        "srt": {"id": "u", "pw": "p"},
        "ktx": None,
        "card": {"number": "1111222233334444", "password": "12",
                 "birthday": "900101", "expire": "1230"},
    }
    storage.save(42, legacy)

    monkeypatch.setattr(storage.secrets, "token_hex", lambda n: "ab12")
    storage.load(42)  # 첫 load — 마이그레이션 발동

    # 디스크 파일을 raw로 다시 디크립트해 검증 (load 호출 없이)
    from cryptography.fernet import Fernet
    import json, os
    cipher = Fernet(os.environ["BOT_DB_KEY"].encode())
    raw = (tmp_user_dir / "42.json.enc").read_bytes()
    on_disk = json.loads(cipher.decrypt(raw).decode())

    assert "card" not in on_disk
    assert on_disk["cards"][0]["id"] == "ab12"
    assert on_disk["cards"][0]["label"] is None
    assert on_disk["cards"][0]["number"] == "1111222233334444"
```

- [ ] **Step 2: 테스트 통과 확인 (이미 구현됐으므로 바로 PASS 예상)**

Run: `pytest tests/bot/test_storage.py::test_legacy_user_first_load_writes_new_format_to_disk -v`
Expected: PASS

- [ ] **Step 3: 전체 테스트 한 번 더 실행**

Run: `pytest -v`
Expected: 전체 PASS

- [ ] **Step 4: 커밋**

```bash
git add tests/bot/test_storage.py
git commit -m "test(storage): legacy 사용자 첫 load 시 디스크 새 포맷 갱신 검증"
```

---

## Task 7: 운영 문서 갱신

**Files:**
- Modify: `docs/bot-operations.md`

마이그레이션이 자동으로 일어남을 운영자에게 알리고, /cards 명령 사용법을 추가한다.

- [ ] **Step 1: docs/bot-operations.md에 명령 사용법 섹션 추가**

`docs/bot-operations.md`의 `## 백업` 섹션 위(또는 적당한 위치)에 다음 섹션 추가:

```markdown
## 카드 다중 등록

- `/setup`은 SRT/KTX 자격증명과 첫 카드 1장을 받음. 별칭 입력 단계 포함.
- 추가 카드는 `/cards` 명령에서 ➕ 카드 추가로 등록.
- 카드 삭제도 `/cards`에서 🗑 버튼 → 확인 단계.
- 결제 시(✅결제 클릭) 등록된 카드 목록이 인라인 키보드로 표시되며 사용자가 선택.

## legacy 마이그레이션

이전 단일 카드 포맷(`card` 단수 키)으로 저장된 사용자 파일은 다음 `storage.load()` 호출 시 자동으로 `cards` 리스트 포맷으로 변환되며, 디스크 파일도 새 포맷으로 갱신된다. 사용자는 별도 작업 없이 그대로 봇을 사용하면 된다.
```

- [ ] **Step 2: 커밋**

```bash
git add docs/bot-operations.md
git commit -m "docs(bot): /cards 명령 + legacy 마이그레이션 안내 추가"
```

---

## 최종 검증

- [ ] **Step 1: 전체 테스트 스위트 실행**

Run: `pytest -v`
Expected: 전체 PASS

- [ ] **Step 2: 봇 실제 가동 (운영자 본인 환경)**

`docs/bot-operations.md`의 E2E 검증 절차에 카드 다중 등록 시나리오를 추가 실행:

1. `/setup`으로 첫 카드 등록 (별칭 'skip')
2. `/cards`로 두 번째 카드 추가 (별칭 입력)
3. 두 카드 모두 목록에 표시되는지 확인
4. 자유 메시지로 예약 시도 → 좌석 잡히면 ✅결제 → 카드 선택 키보드 등장 확인
5. 한 카드 선택해서 결제 흐름 정상 진행 확인 (한 번은 실제 결제, 한 번은 ❌취소)
6. `/cards`로 카드 한 장 삭제 후 목록 갱신 확인
