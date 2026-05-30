"""srtgo.bot.agent — 다단계 도구 실행 루프 테스트 (Anthropic mock)."""

from unittest.mock import AsyncMock, MagicMock


def _ctx(tid=1):
    from srtgo.bot.agent_context import AgentContext
    context = MagicMock()
    context.user_data = {}
    ctx = AgentContext(tid=tid, update=MagicMock(), context=context,
                       creds={}, today="2026-06-01")
    ctx.send = AsyncMock()
    return ctx


def _text(t):
    b = MagicMock(); b.type = "text"; b.text = t
    return b


def _tool(name, inp=None, id="t1"):
    b = MagicMock(); b.type = "tool_use"; b.name = name; b.input = inp or {}; b.id = id
    return b


def _resp(*blocks):
    m = MagicMock(); m.content = list(blocks)
    return m


def _client(*responses):
    c = MagicMock()
    c.messages.create.side_effect = list(responses)
    return c


async def test_text_only_sends_and_stops(fake_redis):
    from srtgo.bot import agent
    ctx = _ctx()
    client = _client(_resp(_text("안녕하세요!")))
    await agent.run_agent(ctx, "안녕", client=client)
    ctx.send.assert_awaited_once_with("안녕하세요!")
    assert client.messages.create.call_count == 1


async def test_single_tool_then_text(fake_redis, monkeypatch):
    from srtgo.bot import agent, tools
    fake = AsyncMock(return_value={"count": 2})
    monkeypatch.setitem(tools.DISPATCH, "search_trains", fake)
    ctx = _ctx()
    client = _client(
        _resp(_tool("search_trains", {"rail": "SRT", "dep": "부산", "arr": "서울",
                                      "date": "2026-06-01", "time": "180000"})),
        _resp(_text("2편 찾았어요")),
    )
    await agent.run_agent(ctx, "부산 서울 오늘 6시", client=client)

    fake.assert_awaited_once()
    assert fake.await_args.args[0] is ctx            # ctx 전달
    assert fake.await_args.kwargs["rail"] == "SRT"   # input 언팩
    ctx.send.assert_awaited_once_with("2편 찾았어요")
    assert client.messages.create.call_count == 2


async def test_multi_step_two_tools(fake_redis, monkeypatch):
    from srtgo.bot import agent, tools
    search = AsyncMock(return_value={"count": 1})
    book = AsyncMock(return_value={"status": "started"})
    monkeypatch.setitem(tools.DISPATCH, "search_trains", search)
    monkeypatch.setitem(tools.DISPATCH, "start_booking", book)
    ctx = _ctx()
    client = _client(
        _resp(_tool("search_trains", {"rail": "SRT", "dep": "부산", "arr": "서울",
                                      "date": "2026-06-01", "time": "180000"}, id="t1")),
        _resp(_tool("start_booking", {"selection": "all"}, id="t2")),
        _resp(_text("예매 시작했어요. 좌석 잡히면 알려드릴게요.")),
    )
    await agent.run_agent(ctx, "부산 서울 오늘 6시 예약", client=client)

    search.assert_awaited_once()
    book.assert_awaited_once()
    ctx.send.assert_awaited_once()
    assert client.messages.create.call_count == 3


async def test_max_iters_guard(fake_redis, monkeypatch):
    from srtgo.bot import agent, tools
    monkeypatch.setattr(agent, "MAX_ITERS", 3)
    monkeypatch.setitem(tools.DISPATCH, "list_cards", AsyncMock(return_value={"ok": True}))
    ctx = _ctx()
    client = MagicMock()
    client.messages.create.side_effect = lambda *a, **k: _resp(_tool("list_cards", {}, id="t"))

    await agent.run_agent(ctx, "x", client=client)

    assert client.messages.create.call_count == 3
    last = ctx.send.await_args.args[0]
    assert "길어" in last or "다시" in last


async def test_tool_exception_becomes_tool_result(fake_redis, monkeypatch):
    from srtgo.bot import agent, tools
    monkeypatch.setitem(tools.DISPATCH, "list_cards", AsyncMock(side_effect=RuntimeError("boom")))
    ctx = _ctx()
    client = _client(
        _resp(_tool("list_cards", {}, id="t1")),
        _resp(_text("카드 조회 중 문제가 있었어요")),
    )
    await agent.run_agent(ctx, "카드 보여줘", client=client)

    ctx.send.assert_awaited_once_with("카드 조회 중 문제가 있었어요")
    assert client.messages.create.call_count == 2


async def test_unknown_tool_name_does_not_crash(fake_redis):
    from srtgo.bot import agent
    ctx = _ctx()
    client = _client(
        _resp(_tool("does_not_exist", {}, id="t1")),
        _resp(_text("처리했어요")),
    )
    await agent.run_agent(ctx, "x", client=client)
    ctx.send.assert_awaited_once_with("처리했어요")
    assert client.messages.create.call_count == 2


async def test_history_persisted_text_turns(fake_redis):
    from srtgo.bot import agent, memory
    ctx = _ctx(tid=7)
    client = _client(_resp(_text("네!")))
    await agent.run_agent(ctx, "안녕", client=client)

    assert await memory.get_history(7) == [
        {"role": "user", "content": "안녕"},
        {"role": "assistant", "content": "네!"},
    ]


async def test_history_loaded_and_prepended(fake_redis, monkeypatch):
    """이전 히스토리가 messages 앞에 실려 다단계 맥락이 이어진다."""
    from srtgo.bot import agent, memory
    await memory.save_history(7, [
        {"role": "user", "content": "부산에서 서울"},
        {"role": "assistant", "content": "언제 출발하세요?"},
    ])
    ctx = _ctx(tid=7)
    client = _client(_resp(_text("알겠어요")))
    await agent.run_agent(ctx, "내일 저녁 6시", client=client)

    sent_messages = client.messages.create.call_args.kwargs["messages"]
    roles_contents = [(m["role"], m["content"]) for m in sent_messages]
    assert ("user", "부산에서 서울") in roles_contents
    assert ("user", "내일 저녁 6시") in roles_contents
