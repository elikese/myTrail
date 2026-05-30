"""Redis 기반 대화 히스토리 + 진행상태 스냅샷.

로그인/회원 개념 없음 — 전부 telegram_id 기준. Redis가 없거나 다운이어도
봇은 죽지 않고 단일턴으로 degrade한다(히스토리 비었다고 간주).

저장하는 것:
- 대화 히스토리: 최근 N개 메시지(텍스트 턴만). 도구 호출 플럼빙(tool_use/tool_result)은
  저장하지 않는다 — 매 턴 새로 추론하므로 불필요하고, 재생 시 항상 유효한 메시지열이 된다.
- 진행상태/결제대기 스냅샷: 표시·재시작 폴백용 직렬화 가능한 요약(살아있는 객체 아님).
"""

import json
import logging
import os

import redis.asyncio as aioredis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

DEFAULT_URL = "redis://localhost:6379/0"

# Redis 미가용 시 무시할 예외 (OSError는 소켓/TimeoutError 포함)
_DEGRADE = (RedisError, OSError)

_client: aioredis.Redis | None = None


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _url() -> str:
    return os.environ.get("REDIS_URL", DEFAULT_URL)


def _max_turns() -> int:
    return _env_int("HISTORY_MAX_TURNS", 8)


def _ttl() -> int:
    return _env_int("HISTORY_TTL_SECONDS", 3600)


def _snap_ttl() -> int:
    return _env_int("SNAPSHOT_TTL_SECONDS", 21600)


def _max_chars() -> int:
    return _env_int("HISTORY_MAX_MSG_CHARS", 4000)


def get_async_client() -> aioredis.Redis:
    """지연 생성되는 단일 async 클라이언트."""
    global _client
    if _client is None:
        _client = aioredis.from_url(
            _url(),
            decode_responses=True,
            socket_connect_timeout=1.0,
            socket_timeout=1.0,
            retry_on_timeout=False,
        )
    return _client


def reset_clients_for_tests() -> None:
    global _client
    _client = None


async def ping() -> bool:
    """헬스 프로브 — 절대 예외를 던지지 않음."""
    try:
        await get_async_client().ping()
        return True
    except Exception as e:  # noqa: BLE001 - 헬스 체크는 광범위 캐치
        logger.warning("Redis ping 실패: %s", e)
        return False


def _history_key(tid: int) -> str:
    return f"chat:{tid}:history"


def _progress_key(tid: int) -> str:
    return f"chat:{tid}:progress"


def _pending_key(tid: int) -> str:
    return f"chat:{tid}:pending"


# --- 대화 히스토리 ---

def _block_text(block) -> str:
    """assistant content 블록(dict 또는 SDK 객체)에서 text만 추출."""
    if isinstance(block, dict):
        if block.get("type") == "text":
            return block.get("text", "") or ""
        return ""
    if getattr(block, "type", None) == "text":
        return getattr(block, "text", "") or ""
    return ""


def _extract_text(role: str, content) -> str:
    """메시지를 텍스트로 환원. user의 list(content)=tool_result → 버림."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        if role == "user":
            return ""  # tool_result 묶음 — 실제 사용자 발화 아님
        parts = [t for t in (_block_text(b) for b in content) if t]
        return "\n".join(parts).strip()
    return ""


def _sanitize(messages: list, max_turns: int, max_chars: int) -> list[dict]:
    entries: list[dict] = []
    for m in messages:
        role = m.get("role")
        text = _extract_text(role, m.get("content"))
        if text:
            entries.append({"role": role, "content": text})

    # 연속 동일 role 병합 → 깔끔한 교대 보장
    merged: list[dict] = []
    for e in entries:
        if merged and merged[-1]["role"] == e["role"]:
            merged[-1]["content"] = (merged[-1]["content"] + "\n" + e["content"])[:max_chars]
        else:
            merged.append({"role": e["role"], "content": e["content"][:max_chars]})

    merged = merged[-max_turns:]
    while merged and merged[0]["role"] != "user":
        merged.pop(0)
    return merged


async def get_history(tid: int) -> list[dict]:
    try:
        items = await get_async_client().lrange(_history_key(tid), 0, -1)
    except _DEGRADE as e:
        logger.warning("Redis get_history 실패 tid=%s: %s", tid, e)
        return []
    out = []
    for x in items:
        try:
            out.append(json.loads(x))
        except (ValueError, TypeError):
            continue
    return out


async def save_history(tid: int, messages: list) -> None:
    clean = _sanitize(messages, _max_turns(), _max_chars())
    key = _history_key(tid)
    client = get_async_client()
    try:
        await client.delete(key)
        if clean:
            await client.rpush(key, *[json.dumps(m, ensure_ascii=False) for m in clean])
            await client.expire(key, _ttl())
    except _DEGRADE as e:
        logger.warning("Redis save_history 실패 tid=%s: %s", tid, e)


async def clear_history(tid: int) -> None:
    await _del(_history_key(tid))


# --- 스냅샷 (progress / pending) ---

async def _set_json(key: str, value: dict) -> None:
    try:
        await get_async_client().set(key, json.dumps(value, ensure_ascii=False), ex=_snap_ttl())
    except _DEGRADE as e:
        logger.warning("Redis set 실패 key=%s: %s", key, e)


async def _get_json(key: str) -> dict | None:
    try:
        raw = await get_async_client().get(key)
    except _DEGRADE as e:
        logger.warning("Redis get 실패 key=%s: %s", key, e)
        return None
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


async def _del(key: str) -> None:
    try:
        await get_async_client().delete(key)
    except _DEGRADE as e:
        logger.warning("Redis delete 실패 key=%s: %s", key, e)


async def set_progress_snapshot(tid: int, progress: dict) -> None:
    await _set_json(_progress_key(tid), progress)


async def get_progress_snapshot(tid: int) -> dict | None:
    return await _get_json(_progress_key(tid))


async def clear_progress_snapshot(tid: int) -> None:
    await _del(_progress_key(tid))


async def set_pending_summary(tid: int, summary: dict) -> None:
    await _set_json(_pending_key(tid), summary)


async def get_pending_summary(tid: int) -> dict | None:
    return await _get_json(_pending_key(tid))


async def clear_pending_summary(tid: int) -> None:
    await _del(_pending_key(tid))


async def clear_all_transient() -> None:
    """재시작 시 고아 진행상태/결제대기 스냅샷 정리(히스토리는 보존)."""
    client = get_async_client()
    try:
        keys: list[str] = []
        async for k in client.scan_iter(match="chat:*:progress"):
            keys.append(k)
        async for k in client.scan_iter(match="chat:*:pending"):
            keys.append(k)
        if keys:
            await client.delete(*keys)
    except _DEGRADE as e:
        logger.warning("Redis clear_all_transient 실패: %s", e)
