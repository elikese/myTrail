"""srtgo.bot.memory — Redis 대화 히스토리 + 진행상태 스냅샷 테스트 (fakeredis)."""

import pytest


# --- 대화 히스토리 ---

async def test_history_round_trip_plain_text(fake_redis):
    from srtgo.bot import memory
    msgs = [
        {"role": "user", "content": "안녕"},
        {"role": "assistant", "content": "네 안녕하세요"},
    ]
    await memory.save_history(1, msgs)
    assert await memory.get_history(1) == msgs


async def test_history_empty_when_absent(fake_redis):
    from srtgo.bot import memory
    assert await memory.get_history(999) == []


async def test_history_trim_to_max_turns(fake_redis, monkeypatch):
    from srtgo.bot import memory
    monkeypatch.setenv("HISTORY_MAX_TURNS", "4")
    msgs = []
    for i in range(5):
        msgs.append({"role": "user", "content": f"u{i}"})
        msgs.append({"role": "assistant", "content": f"a{i}"})
    await memory.save_history(1, msgs)
    got = await memory.get_history(1)
    assert len(got) == 4
    assert got == msgs[-4:]
    assert got[0]["role"] == "user"  # 항상 user로 시작


async def test_history_ttl_set(fake_redis, monkeypatch):
    from srtgo.bot import memory
    monkeypatch.setenv("HISTORY_TTL_SECONDS", "123")
    await memory.save_history(1, [{"role": "user", "content": "hi"}])
    ttl = await fake_redis.ttl("chat:1:history")
    assert 0 < ttl <= 123


async def test_history_strips_tool_blocks_and_merges_assistant(fake_redis):
    """tool_use/tool_result 플럼빙은 저장하지 않고 텍스트만 — 재생 안전."""
    from srtgo.bot import memory
    msgs = [
        {"role": "user", "content": "부산 서울 내일 6시 예약"},
        {"role": "assistant", "content": [
            {"type": "text", "text": "검색할게요"},
            {"type": "tool_use", "id": "t1", "name": "search_trains", "input": {"rail": "SRT"}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "3개"},
        ]},
        {"role": "assistant", "content": [{"type": "text", "text": "3편 찾았어요"}]},
    ]
    await memory.save_history(1, msgs)
    got = await memory.get_history(1)

    assert got == [
        {"role": "user", "content": "부산 서울 내일 6시 예약"},
        {"role": "assistant", "content": "검색할게요\n3편 찾았어요"},
    ]
    # 저장물에 도구 플럼빙이 전혀 없어야 함
    import json
    blob = json.dumps(got, ensure_ascii=False)
    assert "tool_use" not in blob and "tool_result" not in blob


async def test_history_starts_with_user(fake_redis):
    from srtgo.bot import memory
    msgs = [
        {"role": "assistant", "content": "고아 어시스턴트"},
        {"role": "user", "content": "진짜 시작"},
        {"role": "assistant", "content": "답"},
    ]
    await memory.save_history(1, msgs)
    got = await memory.get_history(1)
    assert got == [
        {"role": "user", "content": "진짜 시작"},
        {"role": "assistant", "content": "답"},
    ]


async def test_history_size_cap(fake_redis, monkeypatch):
    from srtgo.bot import memory
    monkeypatch.setenv("HISTORY_MAX_MSG_CHARS", "20")
    long = "가" * 100
    await memory.save_history(1, [{"role": "user", "content": long}])
    got = await memory.get_history(1)
    assert len(got) == 1
    assert len(got[0]["content"]) <= 20


# --- 진행상태/결제대기 스냅샷 ---

async def test_progress_snapshot_set_get_clear(fake_redis):
    from srtgo.bot import memory
    progress = {
        "rail_type": "SRT", "dep": "부산", "arr": "서울",
        "date": "20260601", "time": "180000",
        "selected_trains": ["KTX 101 (18:00)"],
        "start_time": 1.0, "attempts": 3, "last_sleep": 5.0, "last_sleep_set_at": 2.0,
    }
    await memory.set_progress_snapshot(1, progress)
    assert await memory.get_progress_snapshot(1) == progress
    await memory.clear_progress_snapshot(1)
    assert await memory.get_progress_snapshot(1) is None


async def test_pending_summary_set_get_clear(fake_redis):
    from srtgo.bot import memory
    summary = {
        "rail_type": "SRT", "dep": "부산", "arr": "서울",
        "date": "20260601", "time": "180000",
        "train": "KTX 101", "deadline": "18:10",
    }
    await memory.set_pending_summary(1, summary)
    assert await memory.get_pending_summary(1) == summary
    await memory.clear_pending_summary(1)
    assert await memory.get_pending_summary(1) is None


async def test_clear_all_transient_removes_snapshots_keeps_history(fake_redis):
    from srtgo.bot import memory
    await memory.save_history(1, [{"role": "user", "content": "기억"}])
    await memory.set_progress_snapshot(1, {"attempts": 1})
    await memory.set_pending_summary(2, {"train": "x"})

    await memory.clear_all_transient()

    assert await memory.get_progress_snapshot(1) is None
    assert await memory.get_pending_summary(2) is None
    assert await memory.get_history(1) == [{"role": "user", "content": "기억"}]


# --- Redis 다운 시 graceful degrade ---

class _DownClient:
    """모든 호출이 ConnectionError를 던지는 클라이언트 더블."""
    def scan_iter(self, *a, **k):
        # 실제 redis.asyncio처럼 async 이터레이터를 반환하되, 순회 시 raise.
        async def _gen():
            from redis.exceptions import ConnectionError as RedisConnError
            raise RedisConnError("redis down")
            yield  # pragma: no cover - 제너레이터로 만들기 위한 unreachable
        return _gen()

    def __getattr__(self, _name):
        async def _boom(*a, **k):
            from redis.exceptions import ConnectionError as RedisConnError
            raise RedisConnError("redis down")
        return _boom


async def test_redis_down_degrades_gracefully(monkeypatch):
    from srtgo.bot import memory
    memory.reset_clients_for_tests()
    monkeypatch.setattr(memory, "get_async_client", lambda: _DownClient())

    assert await memory.get_history(1) == []          # 빈 히스토리로 degrade
    assert await memory.get_progress_snapshot(1) is None
    assert await memory.ping() is False
    # setter/clear는 예외를 던지지 않아야 함
    await memory.save_history(1, [{"role": "user", "content": "x"}])
    await memory.set_progress_snapshot(1, {"a": 1})
    await memory.clear_all_transient()
