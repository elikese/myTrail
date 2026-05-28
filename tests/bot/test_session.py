import asyncio
import threading

import pytest


@pytest.mark.asyncio
async def test_start_poll_rejects_concurrent_request():
    from srtgo.bot import session

    sess = session.Session()
    cancel_event = threading.Event()

    async def dummy():
        await asyncio.sleep(0.5)

    sess.start_poll(1, asyncio.create_task(dummy()), cancel_event)
    with pytest.raises(session.AlreadyPolling):
        sess.start_poll(1, asyncio.create_task(dummy()), threading.Event())

    sess.cancel_poll(1)
    await asyncio.sleep(0.1)


@pytest.mark.asyncio
async def test_cancel_poll_sets_event_and_clears():
    from srtgo.bot import session

    sess = session.Session()
    cancel_event = threading.Event()

    async def dummy():
        await asyncio.sleep(0.5)

    sess.start_poll(1, asyncio.create_task(dummy()), cancel_event)
    sess.cancel_poll(1)

    assert cancel_event.is_set()
    assert not sess.is_polling(1)


def test_pending_set_get_clear():
    from srtgo.bot import session

    sess = session.Session()
    sess.set_pending(1, {"reservation": "X", "rail": object()})
    assert sess.get_pending(1)["reservation"] == "X"
    sess.clear_pending(1)
    assert sess.get_pending(1) is None


@pytest.mark.asyncio
async def test_get_progress_returns_dict_during_polling():
    from srtgo.bot import session

    sess = session.Session()
    cancel_event = threading.Event()
    progress = {"attempts": 5, "start_time": 100.0,
                "last_sleep": 3.0, "last_sleep_set_at": 102.0}

    async def dummy():
        await asyncio.sleep(0.5)

    sess.start_poll(1, asyncio.create_task(dummy()), cancel_event, progress)
    assert sess.get_progress(1) is progress

    sess.cancel_poll(1)
    await asyncio.sleep(0.1)
    # 폴링 종료 후엔 None
    assert sess.get_progress(1) is None


def test_get_progress_returns_none_when_no_polling():
    from srtgo.bot import session

    sess = session.Session()
    assert sess.get_progress(999) is None


@pytest.mark.asyncio
async def test_finished_task_clears_polling_slot():
    from srtgo.bot import session

    sess = session.Session()
    cancel_event = threading.Event()

    async def quick():
        return

    task = asyncio.create_task(quick())
    sess.start_poll(1, task, cancel_event)
    await task
    # task done callback이 슬롯 정리
    await asyncio.sleep(0)
    assert not sess.is_polling(1)
