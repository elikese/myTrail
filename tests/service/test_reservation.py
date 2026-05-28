import threading
from unittest.mock import MagicMock

from srtgo.service.reservation import poll_and_reserve


def test_cancel_event_stops_polling_loop():
    """cancel_event.set() 후에는 다음 루프 진입 시점에 종료한다."""
    rail = MagicMock()
    rail.search_train.return_value = []  # 좌석 없음 → 슬립 후 재시도

    cancel_event = threading.Event()

    on_success = MagicMock()
    on_error = MagicMock(return_value=True)

    # 별도 스레드에서 폴링 시작
    def run():
        poll_and_reserve(
            rail,
            search_params={"dep": "x", "arr": "y", "date": "20260505",
                           "time": "180000", "passengers": []},
            train_indices=[0],
            seat_option=None,
            on_success=on_success,
            on_error=on_error,
            cancel_event=cancel_event,
        )

    t = threading.Thread(target=run, daemon=True)
    t.start()

    # 잠깐 후 cancel
    cancel_event.set()
    t.join(timeout=10)

    assert not t.is_alive(), "cancel 후 폴링이 종료되어야 함"
    on_success.assert_not_called()


def test_cancel_event_none_keeps_existing_behavior():
    """cancel_event=None이면 기존처럼 동작 (좌석 잡으면 종료)."""
    from srtgo.rail.srt.models import SeatType

    train = MagicMock()
    train.seat_available.return_value = True

    rail = MagicMock()
    rail.search_train.return_value = [train]
    rail.reserve.return_value = "RES"

    on_success = MagicMock()
    on_error = MagicMock()

    poll_and_reserve(
        rail,
        search_params={"dep": "x", "arr": "y", "date": "20260505",
                       "time": "180000", "passengers": []},
        train_indices=[0],
        seat_option=SeatType.GENERAL_FIRST,
        on_success=on_success,
        on_error=on_error,
    )

    on_success.assert_called_once_with("RES")


def test_progress_dict_updated_each_attempt():
    """progress 인자가 매 시도마다 attempts/start_time/last_sleep을 채운다."""
    rail = MagicMock()
    rail.search_train.return_value = []  # 좌석 없음 → 슬립 후 재시도

    cancel_event = threading.Event()
    progress: dict = {}

    def cancel_after_few_attempts():
        # 짧게 기다리고 취소 — 최소 1번 이상 시도 보장
        import time as _t
        _t.sleep(0.3)
        cancel_event.set()

    canceller = threading.Thread(target=cancel_after_few_attempts, daemon=True)
    canceller.start()

    poll_and_reserve(
        rail,
        search_params={"dep": "x", "arr": "y", "date": "20260505",
                       "time": "180000", "passengers": []},
        train_indices=[0],
        seat_option=None,
        on_success=MagicMock(),
        on_error=MagicMock(return_value=True),
        cancel_event=cancel_event,
        progress=progress,
    )
    canceller.join(timeout=5)

    assert progress["attempts"] >= 1
    assert progress["start_time"] > 0
    assert progress["last_sleep"] >= 0
    assert progress["last_sleep_set_at"] >= progress["start_time"]
