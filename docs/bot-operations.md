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
- `BOT_CLAUDE_KEY` — Anthropic API 키 (모든 봇 사용자 공통 — 운영자가 비용 부담)
- `BOT_ALLOWED_IDS` — 콤마 구분 ID (예: `111111,222222`)
- `BOT_USERS_DIR` — 자격증명 디렉토리 (기본: `data/users`)

## 로컬 실행 (`.env` 자동 로드)
프로젝트 루트에 `.env` 파일을 만들어두면 `srtgo-bot` 실행 시 자동으로 읽음 (python-dotenv).
`.env`는 `.gitignore`에 등록돼 있음.

`.env` 예시:
```
BOT_TOKEN=1234567890:AA...
BOT_DB_KEY=wW2lFiec...
BOT_CLAUDE_KEY=sk-ant-api03-...
BOT_ALLOWED_IDS=111111,222222
```

이후엔 그냥:
```
srtgo-bot
```

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

## 카드 다중 등록

- `/setup`은 SRT/KTX 자격증명과 첫 카드 1장을 받음. 별칭 입력 단계 포함.
- 추가 카드는 `/cards` 명령에서 ➕ 카드 추가로 등록.
- 카드 삭제도 `/cards`에서 🗑 버튼 → 확인 단계.
- 결제 시(✅결제 클릭) 등록된 카드 목록이 인라인 키보드로 표시되며 사용자가 선택.

## legacy 마이그레이션

이전 단일 카드 포맷(`card` 단수 키)으로 저장된 사용자 파일은 다음 `storage.load()` 호출 시 자동으로 `cards` 리스트 포맷으로 변환되며, 디스크 파일도 새 포맷으로 갱신된다. 사용자는 별도 작업 없이 그대로 봇을 사용하면 된다.

## 백업
- `data/users/` 전체 디렉토리 + `BOT_DB_KEY`를 함께 보관.
- 마스터키 분실 = 모든 사용자 자격증명 복호화 불가.

## E2E 수동 검증 (배포 전)
1. 본인 계정만 allowlist에 두고 봇 가동.
2. `/setup` 으로 본인 SRT/KTX 자격증명·실제 카드 등록.
3. 빈 시간대에 자유 메시지 전송 → 폴링 시작 알림 확인.
4. 좌석 잡힐 때까지 대기 → ❌ 취소로 종료 (실제 결제 회피).
5. 한 번은 ✅ 결제까지 가서 실제 결제·환불 흐름 확인.
