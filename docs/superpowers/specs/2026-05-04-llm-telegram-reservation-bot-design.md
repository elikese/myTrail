# LLM 기반 텔레그램 예매 봇 설계

- 작성일: 2026-05-04
- 상태: 설계 승인 대기
- 대상 모듈: `srtgo/bot/` (신규)

## 1. 목적

사용자가 텔레그램에서 자연어로 한 줄 적으면 (`내일 오후 6시 부산에서 서울 KTX`) 봇이 LLM으로 의도를 파싱하고, 기존 `srtgo` 모듈로 좌석을 폴링·확보한 뒤, 사용자 확인 1회만 받고 결제까지 끝내는 가족·지인용 소형 텔레그램 봇.

## 2. 결정 요약

| 항목 | 결정 |
|---|---|
| 인터페이스 | Telegram bot (`python-telegram-bot`) |
| LLM | Anthropic Claude (사용자 본인 API 키, BYO) |
| LLM 역할 | 자연어 → intent JSON 파서 (멀티턴 에이전트 ❌) |
| 결제 확정 | 좌석 잡힘 → 인라인 버튼으로 사용자 확인 후 결제 |
| 사용자 범위 | 가족·지인 ~10명. Telegram ID allowlist |
| 좌석 미발견 시 | 백그라운드 asyncio Task로 폴링, 잡히면 푸시 알림 |
| 자격증명 저장 | 사용자별 Fernet 암호화 JSON 파일 (DB 없음) |
| 결제 마감 | 철도사 자체 마감만 사용·표시 (봇 측 인위적 TTL 없음) |
| 봇 재시작 처리 | 진행 중 폴링 영속화 ❌. 시작 시 등록 사용자 전원에게 1회 알림 푸시 |

## 3. 아키텍처

```
Telegram 사용자
       │ updates / commands / button callbacks
       ▼
srtgo/bot/                       (신규 모듈)
 ├ main.py        Application 부트스트랩, 핸들러 등록, polling 시작
 ├ handlers.py    /start /setup /help /cancel, 자유 메시지·콜백 라우팅
 ├ parser.py      Claude API → intent JSON, 스키마 검증
 ├ session.py     사용자별 진행 중 폴링 Task·확인 대기 reservation
 ├ storage.py     Fernet read/write/delete (사용자별 파일)
 ├ auth_guard.py  BOT_ALLOWED_IDS 체크 데코레이터
 └ notifier.py    봇이 사용자에게 푸시 메시지 보내는 헬퍼
       │ AbstractRail · intent dict
       ▼
srtgo/service/  (소폭 리팩터, CLI 호환 유지)
 ├ auth.create_rail(rail_type, credentials=None, debug=False)
 ├ reservation.poll_and_reserve(..., cancel_event=None)
 └ payment.pay_with_saved_card(rail, reservation, card_info=None)
       │
       ▼
srtgo/rail/  (기존, 그대로)
```

원칙:
- 신규는 `srtgo/bot/`만. 기존 `rail/` 모듈은 변경 없음.
- 기존 `srtgo/service/notification.py`는 봇과 분리 — 봇은 `bot/notifier.py`만 사용.
- 자격증명은 사용자별 격리. 호스트 keyring 미사용 (multi-user 부적합).
- **service 모듈 소폭 리팩터** (CLI 호환 유지):
  - `service/auth.create_rail(rail_type, credentials=None, debug=False)`와 `service/payment.pay_with_saved_card(rail, reservation, card_info=None)`에 명시적 자격증명 인자 추가. None이면 기존대로 keyring fallback. 봇은 항상 명시 전달.
  - `service/reservation.poll_and_reserve(..., cancel_event=None)` — `threading.Event` 옵션 추가. 루프 상단·슬립 대기에서 체크해서 즉시 종료. CLI는 None으로 호출(현행 유지).
- **Sync→async 경계**: `service/reservation.poll_and_reserve`와 `rail.*` 호출은 모두 동기(`time.sleep`, `requests`). 봇은 `asyncio.to_thread()`로 감싸 별도 스레드에서 돌리고, 결과 콜백은 `loop.call_soon_threadsafe`로 메인 루프에 전달.

## 4. 컴포넌트 책임

| 모듈 | 한 줄 책임 | 핵심 함수 / 의존 |
|---|---|---|
| `bot/main.py` | telegram Application 부트스트랩, 핸들러 등록, polling 시작 | `python-telegram-bot` |
| `bot/handlers.py` | 명령·메시지·콜백 라우팅, `/setup` 다단계 대화 상태 | session, parser, storage |
| `bot/parser.py` | 자연어 → intent dict, JSON schema 검증 | `anthropic` SDK |
| `bot/session.py` | 사용자별 진행 중 폴링 Task·확인 대기 reservation 보관 (in-memory) | asyncio Task |
| `bot/storage.py` | Fernet read/write/delete | `cryptography` |
| `bot/auth_guard.py` | allowlist 체크 데코레이터 | env var |
| `bot/notifier.py` | 사용자에게 푸시 메시지 (좌석 잡힘·결제 결과·에러·재시작) | telegram Bot |

신규 의존성:
- `anthropic` (신규)
- `cryptography` (신규, Fernet)
- `python-telegram-bot` (이미 있음)

환경변수:
- `BOT_TOKEN` — 텔레그램 봇 토큰
- `BOT_ALLOWED_IDS` — 콤마 구분 텔레그램 user ID 화이트리스트
- `BOT_DB_KEY` — Fernet 마스터 키 (base64)

자격증명 파일 위치: `data/users/<telegram_id>.json.enc`
- 평문 스키마 (복호화 후): `{claude_key, srt:{id,pw}|null, ktx:{id,pw}|null, card:{number,pw,birthday,expire}}`

## 5. Intent JSON 스키마 (parser 출력)

```json
{
  "rail": "SRT" | "KTX",
  "dep": "부산",
  "arr": "서울",
  "date": "2026-05-05",       // ISO 날짜, 상대표현은 today 기준 환산
  "time": "180000",            // HHMMSS, 분 모르면 "000000" 절상
  "passengers": {"adult": 1, "child": 0, "senior": 0},
  "seat_pref": "GENERAL_FIRST" | "SPECIAL_FIRST" | "GENERAL_ONLY" | "SPECIAL_ONLY",
  "needs_clarification": ["passengers" | "time" | ...]   // 모호하면 채움
}
```

Claude 호출:
- 모델: `claude-haiku-4-5-20251001` (저렴·빠름, 파싱 충분)
- 시스템 프롬프트에 today 주입(예: `오늘은 2026-05-04`)
- tool_use 또는 JSON-only 응답 강제, `jsonschema`로 검증
- 1회 재시도 (스키마 위반 시)
- 프롬프트 캐싱 활용 (시스템 프롬프트 부분)

## 6. 데이터 흐름

### 6.1 최초 셋업 (`/setup`)

```
사용자 → /setup
  └ storage.exists(tid)? 있으면 "덮어쓸까요?" 확인
순차 질문 (대화 상태 유지):
  1. Claude API key
  2. SRT ID / PW (skip 가능)
  3. KTX ID / PW (skip 가능)
  4. 카드: 번호 / 비번 / 생년월일 / 만료
  └ storage.save(tid, dict) → Fernet → data/users/<tid>.json.enc
"등록 완료" 안내
```

### 6.2 예매 요청 (자유 메시지)

```
사용자 → "내일 오후 6시 부산→서울 KTX"
  └ auth_guard 통과
  └ parser.parse(text, today) → Claude API → intent
  └ needs_clarification 있으면 1턴 되묻기 (최대 2턴)
  └ storage.load(tid) → 자격증명
  └ service.auth.create_rail(rail, credentials={id, pw})
  └ rail.search_train(...) → 후보를 인라인 키보드 버튼으로 표시
       (열차별 [선택] 버튼 + [전부] + [취소]. 다중 선택 시 토글 → [확정])
  └ session.start_poll(tid, asyncio.create_task(_run_poll))
       _run_poll = asyncio.to_thread(
           service.reservation.poll_and_reserve,
           rail, params, indices, seat_option,
           on_success=success_cb,
           on_error=error_cb)
       콜백은 loop.call_soon_threadsafe로 notifier.send_*를 invoke
```

### 6.3 좌석 잡힘 → 결제

```
on_success 콜백 호출
  └ session.set_pending(tid, reservation)
  └ notifier: "[KTX 123 부산→서울 18:00 47000원
               결제마감 MM/DD HH:MM]   ← reservation에 결제마감 있을 때만
               [✅ 결제]  [❌ 취소]"
  (SRT는 SRTReservation.payment_date/payment_time 제공.
   KTX는 구현 시 확인. 없으면 마감 줄 생략.)
사용자 ✅ 누름 → callback handler
  └ card = storage.load(tid).card
  └ service.payment.pay_with_saved_card(rail, reservation, card_info=card)
  └ 성공: "결제 완료. 승차권은 SRT/코레일 앱에서 확인."
  └ 실패: 에러 + [재시도] 버튼
사용자 ❌ 누름
  └ rail.cancel(reservation)
사용자가 마감 후 누름
  └ pay_with_saved_card 실패 → "결제 마감이 지났습니다" 안내
```

### 6.4 진행 중 작업 취소 (`/cancel`)

```
session.active_polls[tid] 존재?
  → cancel_event.set()  (poll_and_reserve가 다음 체크에서 종료)
  → asyncio Task는 to_thread 완료 후 자연 종결
session.pending[tid] 존재? → rail.cancel(reservation)
"폴링 중단/예약 취소 완료"
```

주의: `asyncio.Task.cancel()`만으로는 `to_thread` 안의 동기 코드를 즉시 중단할 수 없음. 그래서 `cancel_event` 사용 — 다음 슬립/루프 체크 시점(최대 ~수 초 지연)에 종료.

### 6.5 봇 재시작

```
main.py 부팅 직후
  └ data/users/*.json.enc 순회 → 등록 사용자 ID 수집
  └ 각자에게 "봇 재시작. 진행 중이던 요청은 다시 보내주세요" 1회 푸시
```

## 7. 에러 처리

| 시나리오 | 대처 |
|---|---|
| LLM 파싱 실패 / 필수 필드 누락 | 1턴 되묻기. 2턴 안에 안 풀리면 "다시 시도해주세요" |
| LLM JSON 스키마 위반 | 1회 재호출, 또 실패면 "이해 못 했어요" |
| Claude API 키 오류 / 만료 | "API 키 오류. /setup 다시" |
| 자격증명 파일 복호화 실패 | "저장된 정보를 읽지 못했어요. /setup 다시" |
| 철도사 로그인 실패 | "SRT/KTX 로그인 실패. /setup" |
| 검색 결과 0건 | "해당 시간대 열차 없음" |
| 폴링 중 일시 오류 | `on_error` → True 반환 → 재시도 (감마 슬립) |
| 폴링 중 영구 오류 (인증 만료 등) | `on_error` → False → 폴링 종료 + 사용자 알림 |
| 결제 카드 거절 | 메시지 + [재시도][취소] 버튼 |
| 결제 마감 후 결제 시도 | "결제 마감 지남" 안내 |
| Telegram API rate limit | python-telegram-bot 내장 백오프 신뢰 |
| 봇 크래시 | systemd `Restart=on-failure` 권장 (운영 가이드) |
| 미허용 사용자 | "허용되지 않은 사용자입니다. ID: N — 관리자에게 전달" |
| 동일 사용자 동시 폴링 시도 | "이미 진행 중. /cancel 후 재요청" |

원칙:
- 실패는 항상 사용자에게 한 줄로 알린다 (침묵 ❌).
- 자격증명 관련 에러는 "무엇을 할지" 명확히 안내.
- 일시 오류는 자동 재시도, 영구 오류는 사용자 개입 필요.

## 8. 테스트

| 레이어 | 테스트 대상 | 방법 |
|---|---|---|
| `bot/parser.py` | 자연어 → intent 매핑 | Claude 클라이언트 모킹. 케이스 ~15개 (상대시간, 모호 입력, 누락 필드, 영어 혼용 등) |
| `bot/storage.py` | Fernet 암호화 round-trip, 손상·키 오류 처리 | tmp 디렉토리 + 테스트 마스터키 |
| `bot/auth_guard.py` | allowlist 통과·차단 | env monkeypatch |
| `bot/handlers.py` | 명령·콜백 라우팅, `/setup` 다단계 대화 | `python-telegram-bot` Application + `pytest-asyncio` + Update mock. 시나리오 5개 |
| `bot/session.py` | 사용자당 폴링 1개 제한, cancel_event 신호 전달 | asyncio Task + Event 검증 |
| `service/auth.create_rail` | 명시 credentials 전달 시 keyring 우회, None 시 keyring fallback | monkeypatch keyring |
| `service/payment.pay_with_saved_card` | 명시 card_info 전달 시 그대로 사용, None 시 keyring fallback | rail.pay_with_card 모킹 |
| `service/reservation.poll_and_reserve` | cancel_event.set() 시 다음 체크에서 종료 | Event + dummy rail |
| E2E (수동) | 실제 호출 결제 직전까지 | 운영자가 자기 계정으로 dry-run |

원칙:
- 외부 호출(LLM, 철도사) 전부 모킹.
- 결제 호출은 단위 테스트에서 절대 진짜로 가지 않음.
- pytest + pytest-asyncio + freezegun.
- 커버리지 강제 없음 — 새 봇 모듈 핵심 경로만 확실히.

## 9. 운영 가이드 (요약)

- 호스트: 가벼운 VPS (1 vCPU / 512MB) 충분.
- systemd unit으로 띄우고 `Restart=on-failure` 설정.
- `BOT_TOKEN` / `BOT_ALLOWED_IDS` / `BOT_DB_KEY` 환경변수 주입 (e.g. EnvironmentFile).
- 마스터키 분실 = 모든 사용자 자격증명 복호화 불가 → 백업 필수.
- `data/users/` 디렉토리도 정기 백업 권장.

## 10. 비범위 (Out of scope)

- 진행 중 폴링 영속화·재개
- 환승 / 다구간 / 왕복 자동 예매
- 다국어 (한국어만)
- 웹 대시보드
- 사용자별 사용량·비용 추적
- 환불·승차권 변경 (별도 명령으로 추후)
