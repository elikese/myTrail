"""예매 흐름 핸들러."""

import logging
from datetime import datetime, timedelta

import inquirer
from termcolor import colored

from ...config.constants import DEFAULT_STATIONS, WAITING_BAR
from ...config.settings import (
    get_options, get_reserve_defaults, get_station_setting, set_reserve_default,
)
from ...rail.base import AbstractRail
from ...service.notification import send_telegram
from ...service.payment import pay_with_saved_card
from ...service.reservation import poll_and_reserve
from ..prompts import (
    confirm_continue_prompt, reserve_info_prompt,
    seat_option_prompt, train_select_prompt,
)

logger = logging.getLogger(__name__)


def handle_reserve(rail: AbstractRail, rail_type: str) -> None:
    is_srt = rail_type == "SRT"
    now = datetime.now() + timedelta(minutes=10)
    today = now.strftime("%Y%m%d")
    this_time = now.strftime("%H%M%S")

    # --- 기본값 로드 ---
    raw_defaults = get_reserve_defaults(rail_type)
    defaults = {
        "departure": raw_defaults.get("departure") or ("수서" if is_srt else "서울"),
        "arrival": raw_defaults.get("arrival") or "동대구",
        "date": raw_defaults.get("date") or today,
        "time": raw_defaults.get("time") or "120000",
        "adult": int(raw_defaults.get("adult") or 1),
        "child": int(raw_defaults.get("child") or 0),
        "senior": int(raw_defaults.get("senior") or 0),
        "disability1to3": int(raw_defaults.get("disability1to3") or 0),
        "disability4to6": int(raw_defaults.get("disability4to6") or 0),
    }

    if defaults["departure"] == defaults["arrival"]:
        defaults["arrival"] = (
            "동대구" if defaults["departure"] in ("수서", "서울") else None
        )
        if not defaults["arrival"]:
            defaults["departure"] = "수서" if is_srt else "서울"

    station_key_str = get_station_setting(rail_type)
    station_key = station_key_str.split(",") if station_key_str else DEFAULT_STATIONS[rail_type]
    options = get_options()

    # --- 예약 창 계산 ---
    if is_srt:
        max_days = 30 if now.hour >= 7 else 29
    else:
        max_days = 31 if now.hour >= 7 else 30

    date_choices = [
        (
            (now + timedelta(days=i)).strftime("%Y/%m/%d %a"),
            (now + timedelta(days=i)).strftime("%Y%m%d"),
        )
        for i in range(max_days + 1)
    ]
    time_choices = [(f"{h:02d}", f"{h:02d}0000") for h in range(24)]

    # --- 예매 정보 입력 ---
    info = inquirer.prompt(
        reserve_info_prompt(station_key, options, defaults, date_choices, time_choices)
    )
    if not info:
        print(colored("예매 정보 입력 중 취소되었습니다", "green", "on_red") + "\n")
        return

    if info["departure"] == info["arrival"]:
        print(colored("출발역과 도착역이 같습니다", "green", "on_red") + "\n")
        return

    # 기본값 저장
    for key, value in info.items():
        set_reserve_default(rail_type, key, str(value))

    # 시간 조정
    if info["date"] == today and int(info["time"]) < int(this_time):
        info["time"] = this_time

    # --- 승객 구성 ---
    passengers, total_count = _build_passengers(info, is_srt)
    if not passengers:
        print(colored("승객수는 0이 될 수 없습니다", "green", "on_red") + "\n")
        return
    if total_count >= 10:
        print(colored("승객수는 10명을 초과할 수 없습니다", "green", "on_red") + "\n")
        return

    _print_passengers(passengers, is_srt)

    # --- 열차 검색 ---
    search_params = _build_search_params(info, passengers, is_srt, options)
    trains = rail.search_train(**search_params)
    if not trains:
        print(colored("예약 가능한 열차가 없습니다", "green", "on_red") + "\n")
        return

    # --- 열차 선택 ---
    def train_decorator(train):
        msg = repr(train)
        return (
            msg.replace("예약가능", colored("가능", "green"))
               .replace("가능", colored("가능", "green"))
               .replace("신청하기", colored("가능", "green"))
        )

    choice = inquirer.prompt(train_select_prompt(trains, train_decorator))
    if not choice or not choice["trains"]:
        print(colored("선택한 열차가 없습니다!", "green", "on_red") + "\n")
        return

    selected_indices = choice["trains"]

    # --- 좌석 타입 선택 ---
    if is_srt:
        from ...rail.srt.models import SeatType as seat_type_class
    else:
        from ...rail.ktx.models import ReserveOption as seat_type_class

    options_result = inquirer.prompt(seat_option_prompt(seat_type_class))
    if options_result is None:
        print(colored("예매 정보 입력 중 취소되었습니다", "green", "on_red") + "\n")
        return

    seat_option = options_result["type"]
    do_pay = options_result["pay"]

    # --- 폴링 루프 ---
    i_try = 0

    def on_tick():
        pass  # 진행 표시는 루프 밖에서

    def on_success(reservation):
        msg = f"{reservation}"
        if hasattr(reservation, "tickets") and reservation.tickets:
            msg += "\n" + "\n".join(map(str, reservation.tickets))
        print(colored(f"\n\n🎫 🎉 예매 성공!!! 🎉 🎫\n{msg}\n", "red", "on_green"))
        if do_pay and not getattr(reservation, "is_waiting", False):
            if pay_with_saved_card(rail, reservation):
                print(colored("\n\n💳 ✨ 결제 성공!!! ✨ 💳\n\n", "green", "on_red"), end="")
                msg += "\n결제 완료"
        send_telegram(msg)

    def on_error(ex) -> bool:
        nonlocal rail
        msg = str(ex)
        _handle_session_error(ex, rail, rail_type)
        # 무시 가능한 에러
        ignorable = (
            "잔여석없음", "사용자가 많아 접속이 원활하지 않습니다",
            "예약대기 접수가 마감되었습니다", "예약대기자한도수초과",
            "Sold out", "No Results",
        )
        if any(s in msg for s in ignorable):
            return True
        logger.error("예매 중 오류: %s", ex)
        send_telegram(msg)
        result = inquirer.prompt(confirm_continue_prompt("계속할까요"))
        return bool(result and result["confirmed"])

    import time as _time
    import sys

    start_time = _time.time()
    try_count = [0]

    _original_poll = poll_and_reserve

    def wrapped_poll(rail_ref, sp, indices, opt, success_cb, error_cb):
        # 폴링 상태 표시를 위해 search_train 호출 전에 출력
        nonlocal i_try
        orig_search = rail_ref.search_train

        def search_with_display(*args, **kwargs):
            try_count[0] += 1
            elapsed = _time.time() - start_time
            h, rem = divmod(int(elapsed), 3600)
            m, s = divmod(rem, 60)
            print(
                f"\r예매 대기 중... {WAITING_BAR[try_count[0] & 3]} {try_count[0]:4d} "
                f"({h:02d}:{m:02d}:{s:02d}) ",
                end="", flush=True,
            )
            return orig_search(*args, **kwargs)

        rail_ref.search_train = search_with_display
        try:
            _original_poll(rail_ref, sp, indices, opt, success_cb, error_cb)
        finally:
            rail_ref.search_train = orig_search

    wrapped_poll(rail, search_params, selected_indices, seat_option, on_success, on_error)


def _handle_session_error(ex, rail, rail_type):
    """세션 만료 등 rail 재생성이 필요한 경우 처리 (best-effort)."""
    msg = str(ex)
    if "정상적인 경로로 접근 부탁드립니다" in msg or "NetFunnel" in type(ex).__name__:
        if hasattr(rail, "clear"):
            rail.clear()
    elif "로그인 후 사용하십시오" in msg or "Need to Login" in msg:
        try:
            from ...service.auth import create_rail
            new_rail = create_rail(rail_type)
            # rail 참조 교체는 클로저 밖이라 반환하지 않음 — 다음 시도에서 재시도
        except Exception:
            pass


def _build_passengers(info: dict, is_srt: bool):
    if is_srt:
        from ...rail.srt.models import Adult, Child, Senior, Disability1To3, Disability4To6
        classes = {
            "adult": Adult, "child": Child, "senior": Senior,
            "disability1to3": Disability1To3, "disability4to6": Disability4To6,
        }
    else:
        from ...rail.ktx.models import (
            AdultPassenger, ChildPassenger, SeniorPassenger,
            Disability1To3Passenger, Disability4To6Passenger,
        )
        classes = {
            "adult": AdultPassenger, "child": ChildPassenger, "senior": SeniorPassenger,
            "disability1to3": Disability1To3Passenger, "disability4to6": Disability4To6Passenger,
        }

    passengers = []
    total = 0
    for key, cls in classes.items():
        count = info.get(key, 0)
        if count and count > 0:
            passengers.append(cls(count))
            total += count
    return passengers, total


def _print_passengers(passengers, is_srt: bool):
    if is_srt:
        from ...rail.srt.models import Adult, Child, Senior, Disability1To3, Disability4To6
        labels = {
            Adult: "어른/청소년", Child: "어린이", Senior: "경로우대",
            Disability1To3: "1~3급 장애인", Disability4To6: "4~6급 장애인",
        }
    else:
        from ...rail.ktx.models import (
            AdultPassenger, ChildPassenger, SeniorPassenger,
            Disability1To3Passenger, Disability4To6Passenger,
        )
        labels = {
            AdultPassenger: "어른/청소년", ChildPassenger: "어린이",
            SeniorPassenger: "경로우대", Disability1To3Passenger: "1~3급 장애인",
            Disability4To6Passenger: "4~6급 장애인",
        }
    msgs = [f"{labels.get(type(p), '?')} {p.count}명" for p in passengers]
    print(*msgs)


def _build_search_params(info: dict, passengers: list, is_srt: bool, options: list) -> dict:
    total_count = sum(p.count for p in passengers)
    if is_srt:
        from ...rail.srt.models import Adult
        return {
            "dep": info["departure"],
            "arr": info["arrival"],
            "date": info["date"],
            "time": info["time"],
            "passengers": [Adult(total_count)],
            "available_only": False,
        }
    else:
        from ...rail.ktx.models import AdultPassenger, TrainType
        params = {
            "dep": info["departure"],
            "arr": info["arrival"],
            "date": info["date"],
            "time": info["time"],
            "passengers": [AdultPassenger(total_count)],
            "include_no_seats": True,
        }
        if "ktx" in options:
            params["train_type"] = TrainType.KTX
        return params
