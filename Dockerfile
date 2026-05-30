FROM python:3.12-slim

# KST 타임존 — Python의 date.today()/'내일' 계산과 `date` 출력 모두 한국 시간으로.
# (컨테이너 기본 UTC면 자정 근처에 날짜가 어긋남)
ENV TZ=Asia/Seoul
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && ln -fs /usr/share/zoneinfo/Asia/Seoul /etc/localtime \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv
ENV UV_LINK_MODE=copy

WORKDIR /app

# 1) 의존성만 먼저 설치 — 소스가 바뀌어도 이 레이어는 캐시 유지
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 2) 소스 복사 후 프로젝트까지 설치 (dev 의존성 제외)
COPY srtgo ./srtgo
RUN uv sync --frozen --no-dev

# 헤드리스 컨테이너에는 GUI 키링이 없다. config.settings 의 import-time 백엔드 프로브가
# 암호화 파일 키링의 getpass 프롬프트에서 멈추지 않도록, 프롬프트 없는 PlaintextKeyring 강제.
# (봇은 자격증명·카드를 Fernet 파일(storage)로 다루므로 keyring 기능 자체는 쓰지 않음)
ENV PYTHON_KEYRING_BACKEND=keyrings.alt.file.PlaintextKeyring

# 콘솔 스크립트 트램폴린 대신 모듈 실행 (크로스플랫폼 안전)
CMD ["uv", "run", "--no-sync", "python", "-m", "srtgo.bot.main"]
