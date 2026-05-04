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
