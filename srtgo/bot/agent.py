"""에이전트 루프 — LLM이 화이트리스트 도구를 실제로 호출하고 결과를 받아 종합.

단일 사용자 메시지(턴) 한 번을 처리한다. 도구를 부르면 실행해 결과를 다시 모델에
먹이고, 모델이 텍스트만 응답하면(=도구 호출 없음) 그 텍스트를 사용자에게 보낸다.
오래 걸리는 예매 폴링은 start_booking이 백그라운드 태스크로 띄우고 즉시 반환하므로
이 루프는 폴링을 기다리지 않는다.
"""

import asyncio
import json
import logging
import os

from anthropic import Anthropic

from . import tools, memory

logger = logging.getLogger(__name__)

MAX_ITERS = 8
MAX_TOKENS = 1024


def _blocks_to_dicts(content) -> list[dict]:
    """SDK 응답 블록 → Anthropic messages에 다시 넣을 수 있는 dict 리스트."""
    out: list[dict] = []
    for b in content:
        btype = getattr(b, "type", None)
        if btype == "text":
            out.append({"type": "text", "text": getattr(b, "text", "")})
        elif btype == "tool_use":
            out.append({"type": "tool_use", "id": b.id, "name": b.name,
                        "input": dict(b.input)})
    return out


async def run_agent(ctx, user_text: str, *, client: Anthropic | None = None) -> None:
    if client is None:
        client = Anthropic(api_key=os.environ["BOT_CLAUDE_KEY"])
    system = tools.SYSTEM_PROMPT.format(today=ctx.today)

    history = await memory.get_history(ctx.tid)
    history.append({"role": "user", "content": user_text})

    for _ in range(MAX_ITERS):
        try:
            resp = await asyncio.to_thread(
                client.messages.create,
                model=tools.MODEL,
                max_tokens=MAX_TOKENS,
                system=[{"type": "text", "text": system,
                         "cache_control": {"type": "ephemeral"}}],
                tools=tools.TOOLS,
                tool_choice={"type": "auto"},
                messages=history,
            )
        except Exception:
            logger.exception("Claude 호출 실패")
            await ctx.send("처리 중 오류가 났어요. 잠시 후 다시 시도해주세요.")
            break

        history.append({"role": "assistant", "content": _blocks_to_dicts(resp.content)})
        tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]

        if not tool_uses:
            final = "".join(
                getattr(b, "text", "") for b in resp.content
                if getattr(b, "type", None) == "text"
            ).strip()
            if final:
                await ctx.send(final)
            break

        results = []
        for tu in tool_uses:
            fn = tools.DISPATCH.get(tu.name)
            if fn is None:
                out = {"error": f"unknown tool: {tu.name}"}
            else:
                try:
                    out = await fn(ctx, **dict(tu.input))
                except Exception as e:
                    logger.exception("도구 %s 실행 실패", tu.name)
                    out = {"error": str(e)}
            results.append({"type": "tool_result", "tool_use_id": tu.id,
                            "content": json.dumps(out, ensure_ascii=False)})
        history.append({"role": "user", "content": results})
    else:
        await ctx.send("처리가 길어지고 있어요. 잠시 후 다시 시도해주세요.")

    await memory.save_history(ctx.tid, history)
