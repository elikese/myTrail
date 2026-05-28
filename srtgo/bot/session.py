"""사용자별 진행 중 폴링 Task와 결제 대기 reservation 추적."""

import asyncio
import threading
from typing import Any


class AlreadyPolling(Exception):
    """동일 사용자에게 진행 중 폴링이 이미 있음."""


class Session:
    def __init__(self) -> None:
        self._polls: dict[int, tuple[asyncio.Task, threading.Event, dict | None]] = {}
        self._pending: dict[int, dict] = {}

    def start_poll(
        self,
        telegram_id: int,
        task: asyncio.Task,
        cancel_event: threading.Event,
        progress: dict | None = None,
    ) -> None:
        if self.is_polling(telegram_id):
            raise AlreadyPolling(f"tid={telegram_id} 이미 폴링 중")
        self._polls[telegram_id] = (task, cancel_event, progress)
        task.add_done_callback(lambda _t: self._polls.pop(telegram_id, None))

    def is_polling(self, telegram_id: int) -> bool:
        entry = self._polls.get(telegram_id)
        return entry is not None and not entry[0].done()

    def cancel_poll(self, telegram_id: int) -> bool:
        entry = self._polls.pop(telegram_id, None)
        if entry is None:
            return False
        _, event, _ = entry
        event.set()
        # task 자체는 to_thread 종료 후 자연 완료 — 강제 cancel은 불필요
        return True

    def get_progress(self, telegram_id: int) -> dict | None:
        """진행 중 폴링의 progress dict (없으면 None)."""
        entry = self._polls.get(telegram_id)
        if entry is None or entry[0].done():
            return None
        return entry[2]

    def set_pending(self, telegram_id: int, payload: dict) -> None:
        """payload 키: {reservation, rail}"""
        self._pending[telegram_id] = payload

    def get_pending(self, telegram_id: int) -> dict | None:
        return self._pending.get(telegram_id)

    def clear_pending(self, telegram_id: int) -> None:
        self._pending.pop(telegram_id, None)
