# 카드 다중 등록 / 결제 시 카드 선택 설계

- 작성일: 2026-05-05
- 상태: 설계 승인 대기
- 대상 모듈: `srtgo/bot/storage.py`, `srtgo/bot/handlers.py`, `srtgo/bot/main.py`

## 1. 목적

기존 봇은 사용자당 카드 1장만 저장 가능하고, 좌석 확보 후 ✅결제 누르면 그 카드로 자동 결제됐다. 실제로는 한 사람이 여러 장의 카드를 상황에 따라 골라 쓰고 싶다. 이 스펙은 **자격증명(SRT/KTX)은 1세트 그대로 두고 카드만 N장 등록·관리**할 수 있게 하고, 결제 시점에 카드를 선택하게 만든다.

## 2. 결정 요약

| 항목 | 결정 |
|---|---|
| 프로필 단위 | 카드 단위만 다중. SRT/KTX 자격증명은 사용자당 1세트 |
| 결제 UX | ✅결제 → 카드 선택 인라인 키보드 → 카드 클릭 시 결제 실행 |
| 카드 1장일 때 | 동일 흐름 (선택 화면 항상 표시 — 분기 없음) |
| 카드 라벨 | 별칭(선택) + 뒷자리 4자리 자동. 별칭 없으면 `*1234` |
| 카드 ID | 사용자별 4 hex (`secrets.token_hex(2)`). 콜백 데이터에 사용 |
| 관리 UX | `/cards` 명령 하나로 목록·추가·삭제 (인라인 키보드) |
| 데이터 모델 | `cards: list[dict]` (각 dict에 `id`, `label`, 카드 4필드) |
| 마이그레이션 | `storage.load()` 시점에 legacy `card` 단수 키 자동 변환 + 디스크 동기화 |

## 3. 데이터 모델

### 저장 포맷 (`data/users/{tid}.json.enc` 평문 JSON)

```json
{
  "srt": {"id": "...", "pw": "..."},
  "ktx": {"id": "...", "pw": "..."},
  "cards": [
    {
      "id": "ab12",
      "label": "신한",
      "number": "1111222233334444",
      "password": "12",
      "birthday": "900101",
      "expire": "1230"
    }
  ]
}
```

### 불변식

- `cards`는 항상 리스트. 0장 가능 (자격증명만 등록한 상태 허용)
- 각 카드의 `id`는 같은 사용자 내에서 유일. 4 hex 문자열
- `label`은 `str | None`. None이면 표시 시 `*마지막4자리`만 사용
- 별칭 길이는 입력 시 32자로 잘라냄 (운영자 본인 환경 — 빡빡할 필요 없음)

### Legacy 자동 마이그레이션 (storage.load 내부)

호출자는 마이그레이션을 의식하지 않는다. `load()`가 다음 규칙을 적용한다:

1. 디스크에서 읽은 dict에 `card`(단수) 키가 있고 `cards`(복수)가 없거나 비어 있으면:
   - `id` 새로 발급 (`secrets.token_hex(2)`)
   - `label = None`, 카드 4필드는 그대로
   - `cards = [그 카드]`로 치환, `card` 키 제거
   - 즉시 `save()` 호출하여 디스크도 새 포맷으로 영속화
2. `card`와 `cards` 둘 다 존재하는 변종은 `cards` 우선, `card`는 무시 (warning 로그)
3. 멱등성: 이미 `cards`만 있으면 변환·저장 없이 그대로 반환

마이그레이션 도중 save가 실패해도 메모리 결과는 새 포맷으로 반환됨. 다음 load 호출 시 다시 시도되며 멱등이라 안전.

## 4. 컴포넌트 변경

### `srtgo/bot/storage.py`

**기존 함수**
- `load()` — 본문에 마이그레이션 로직 추가 (위 3장 참조)

**신규 헬퍼**
- `add_card(tid: int, fields: dict, label: str | None) -> str`
  - 새 id 발급 (기존 ids와 충돌 시 재추첨, 최대 10회)
  - `cards`에 append, save, id 반환
- `remove_card(tid: int, card_id: str) -> bool`
  - 해당 id 카드 제거 + save. 없으면 False
- `get_card(tid: int, card_id: str) -> dict | None`
- `list_cards(tid: int) -> list[dict]`

모든 헬퍼는 내부에서 load → 변경 → save. 락 없음 (현행 storage 패턴 유지, 운영 규모상 무해).

### `srtgo/bot/handlers.py`

#### setup 흐름 변경

기존: `STATE_SRT → STATE_KTX → STATE_CARD → 저장 종료`

신규: `STATE_SRT → STATE_KTX → STATE_CARD → STATE_CARD_LABEL → 저장 종료`

- `STATE_CARD_LABEL` 메시지: `"카드 별칭? (예: '신한', 없으면 'skip')"`
- `'skip'` 또는 빈 문자열 → `label = None`
- 그 외 입력 → 32자 잘라 사용
- 최종 저장: 단일 `card` 키가 아니라 `storage.add_card`로 cards 리스트에 1장 추가

#### `/cards` 명령 (신규 ConversationHandler)

진입: `/cards`

- 자격증명 미등록 사용자 → "/setup 먼저 해주세요" + 종료
- 등록 사용자 → 카드 목록 메시지 + 인라인 키보드:
  - 각 카드별 한 행: `[🗑 신한 (*1234)]` 또는 `[🗑 *5678]`
  - 마지막 행: `[➕ 카드 추가]`
- 0장 상태에서도 `[➕ 카드 추가]` 버튼만 보여줌

콜백:
- `cards:add` → 카드 4필드 입력 상태로 (setup 카드 단계와 동일 입력 형식). 별칭 입력 단계 거쳐 `add_card` 호출 후 다시 목록 화면 갱신
- `cards:del:<id>` → "정말 삭제? `[예]` `[아니오]`" 확인 키보드 (`cards:del_confirm:<id>` / `cards:noop`)
- `cards:del_confirm:<id>` → `remove_card` 호출, 목록 화면 갱신
- `cards:noop` → 목록 화면 복귀 (변화 없음)

진입 시 `context.user_data.pop("cards_new", None)`로 이전 미완 상태 정리.

#### 결제 흐름 변경 (`on_payment_decision`)

`pay:confirm` 콜백 처리 변경:

```
pending = _SESSION.get_pending(tid)
cards = storage.list_cards(tid)

if not cards:
    # 좌석 알림 키보드(✅/❌) 다시 붙여서 안내
    edit("등록된 카드 없음. /cards 에서 추가 후 다시 결제 눌러주세요.")
    return  # pending 보존

# 카드 선택 키보드 표시
edit("어느 카드로 결제할까요?", reply_markup=card_select_keyboard(cards))
# pending 보존
```

`card_select_keyboard`는 카드별 한 행 `[신한 (*1234)] callback=pay:card:ab12` + 마지막 행 `[← 돌아가기] callback=pay:back`.

#### 신규 콜백 핸들러

**`pay:card:<id>` → `on_payment_card`**

```
pending = _SESSION.get_pending(tid)
if not pending: edit("대기 중 예약 없음 (결제 마감 경과 가능)"); return
card = storage.get_card(tid, card_id)
if card is None:
    edit("이 카드는 삭제됐어요. 다시 결제 눌러주세요.",
         reply_markup=notifier.confirm_keyboard())
    return  # pending 보존
ok = await asyncio.to_thread(svc_pay.pay_with_saved_card, rail, reservation, card)
_SESSION.clear_pending(tid)
edit(성공/실패 메시지)
```

**`pay:back` → 좌석 알림 키보드 복귀**

```
edit(notifier.format_seat_secured_message(pending["reservation"]),
     reply_markup=notifier.confirm_keyboard())
```

`pay:cancel`은 기존 그대로.

### `srtgo/bot/main.py`

- `/cards` ConversationHandler 등록
- `pay:card:.*`, `pay:back` 콜백 핸들러 등록
- `cards:.*` 콜백 핸들러 등록 (ConversationHandler 내부)

### 헬프 텍스트

`/cards — 카드 목록·추가·삭제` 한 줄 추가.

## 5. 콜백 데이터 사양

| 콜백 | 의미 |
|---|---|
| `pay:confirm` | (기존) 결제 시작 — 카드 선택 화면으로 전환 |
| `pay:cancel` | (기존) 예약 취소 |
| `pay:card:<id>` | 신규. 특정 카드로 결제 실행 |
| `pay:back` | 신규. 카드 선택 화면 → 좌석 알림 화면 복귀 |
| `cards:add` | /cards에서 카드 추가 시작 |
| `cards:del:<id>` | 삭제 확인 키보드 띄우기 |
| `cards:del_confirm:<id>` | 실제 삭제 |
| `cards:noop` | 삭제 확인에서 [아니오] — 목록 복귀 |

콜백 페이로드는 모두 64바이트 한도 내. id가 4 hex라 여유 충분.

## 6. 데이터 흐름 (시나리오)

### 신규 사용자 첫 setup

```
/setup
 → SRT id pw
 → KTX id pw
 → 카드 4필드
 → 별칭 ("신한" 또는 "skip")
 → storage.add_card(tid, fields, label) → cards: [{id="ab12", ...}]
 → "등록 완료"
```

### 카드 추가

```
/cards
 → [🗑 신한 (*1234)] [➕ 카드 추가]
 → "카드 추가" 클릭
 → 카드 4필드 + 별칭
 → storage.add_card → cards 끝에 append
 → 목록 갱신: [🗑 신한 (*1234)] [🗑 *5678] [➕ 카드 추가]
```

### 카드 삭제

```
/cards에서 [🗑 신한 (*1234)] 클릭
 → "정말 삭제? [예] [아니오]"
 → [예] → storage.remove_card(tid, "ab12") → 목록 갱신
```

### 좌석 잡힌 후 결제 (핵심)

```
좌석 확보 알림 (notifier.send_seat_secured, ✅/❌ 키보드)
 → ✅결제 클릭 → on_payment_decision(pay:confirm)
 → cards 0장? 안내 + ✅/❌ 키보드 복귀, pending 보존
 → cards ≥1장? 카드 선택 키보드, pending 보존
 → 카드 클릭 (pay:card:ab12) → on_payment_card
 → get_card(ab12) None? 삭제됨 안내 + ✅/❌ 키보드 복귀
 → 정상 → pay_with_saved_card → pending clear → 성공/실패 메시지
```

### Legacy 사용자 첫 진입

```
이미 단일 card 키 갖고 있던 사용자가 어떤 작업이든 시도
 → storage.load(tid) 시점에 마이그레이션 발동
 → 디스크에 새 포맷으로 저장
 → 사용자는 아무것도 모르는 채 정상 동작
```

## 7. 에러 처리 & 엣지 케이스

### 결제 흐름

- **카드 0장에서 ✅결제**: pending 보존, 안내 + ✅/❌ 키보드 복귀. /cards로 추가 후 ✅재시도
- **카드 선택 화면 동안 그 카드 삭제됨**: `get_card` None → 안내 + ✅/❌ 키보드 복귀, pending 보존
- **카드 선택 화면 동안 결제 마감 경과**: `_SESSION.get_pending` None → 기존 만료 메시지 (pending 자체가 없으므로 자동 처리)
- **결제 실패** (`pay_with_saved_card` False/예외): 기존과 동일. pending clear, 실패 메시지. 다른 카드 자동 폴백 ❌ (yagni)

### /cards

- 자격증명 미등록 사용자 → 안내 후 종료
- 카드 0장 상태 → "등록된 카드 없음" + `[➕ 카드 추가]`만
- 카드 추가 도중 다시 /cards → 진입 시 `cards_new` 컨텍스트 정리
- `[아니오]` (`cards:noop`) → 목록 복귀

### 마이그레이션

- 마이그레이션 save 실패: 메모리 결과는 새 포맷으로 반환됨. 다음 load 시 재시도, 멱등 안전. warning 로그
- `card` + `cards` 동시 존재: cards 우선, card는 무시 + warning 로그

### 입력 검증

- 카드번호/비번/생년월일/만료일 형식: 기존과 동일 — 검증 안 함, 결제 API에 위임
- 별칭: 32자 잘라냄
- id 충돌: `add_card`에서 기존 ids와 비교 후 재추첨 (최대 10회). 4 hex × 카드 100장에서도 충돌 확률 무시 가능

### 동시성

- 한 사용자가 여러 기기에서 거의 동시에 카드 변경: last-write-wins. 락 없음 (현행 storage 패턴 유지, 운영 규모상 무해)

## 8. 테스트 전략

### 단위 — `storage`

- `load`: legacy `card` → `cards` 자동 변환 + 디스크 동기화. 두 번 부르면 두 번째는 변환 없음 (멱등)
- `add_card`: 빈 cards에 추가 → 1장. 기존 cards에 추가 → append. id 충돌 시 재추첨 (mock으로 token_hex 패치)
- `remove_card`: 존재하는 id → 삭제 + True. 없는 id → False
- `get_card` / `list_cards`: 단순 조회
- `card`와 `cards` 동시 존재 시 cards 우선

### 단위 — `handlers` (텔레그램 mock 기반)

- setup: SRT → KTX → 카드 4필드 → 별칭 'skip'/입력값 → cards 1장으로 저장
- `cmd_cards`: 미등록 사용자 안내, 0/1/N장 키보드 구성
- `on_payment_decision(pay:confirm)`:
  - 0장 → 안내, pending 보존, ✅/❌ 키보드 복귀
  - ≥1장 → 카드 선택 키보드 등장, pending 보존
- `on_payment_card(pay:card:<id>)`:
  - 정상 → `pay_with_saved_card` 호출 + pending clear
  - 카드 삭제됨 → 안내 + 키보드 복귀, pending 보존
  - pending 만료 → 만료 메시지
- `cards:del:<id>` → 확인 키보드. `cards:del_confirm:<id>` → 삭제 + 갱신. `cards:noop` → 변화 없음

### 통합 (가벼운 수준)

- 신규 사용자 /setup → /cards로 1장 추가 → 카드 2장 상태에서 결제 시뮬레이션 (rail mock)
- legacy 포맷 파일 디스크에 미리 두고 load → 새 포맷으로 갱신 확인

### 비범위

- 실제 텔레그램 API / 실제 결제 / 실제 SRT·KTX 로그인 호출 — 운영 가이드의 수동 E2E로 처리
