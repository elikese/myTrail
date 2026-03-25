"""inquirer 질문 객체를 반환하는 순수 UI 함수들.

데이터 조회(keyring, rail API) 없음. 필요한 데이터는 인자로 받음.
"""

import inquirer
from termcolor import colored


def menu_prompt() -> list:
    return [
        inquirer.List(
            "choice",
            message="메뉴 선택 (↕:이동, Enter: 선택)",
            choices=[
                ("예매 시작", 1),
                ("예매 확인/결제/취소", 2),
                ("로그인 설정", 3),
                ("텔레그램 설정", 4),
                ("카드 설정", 5),
                ("역 설정", 6),
                ("역 직접 수정", 7),
                ("예매 옵션 설정", 8),
                ("나가기", -1),
            ],
        )
    ]


def rail_type_prompt() -> list:
    return [
        inquirer.List(
            "rail_type",
            message="열차 선택 (↕:이동, Enter: 선택, Ctrl-C: 취소)",
            choices=[
                (colored("SRT", "red"), "SRT"),
                (colored("KTX", "cyan"), "KTX"),
                ("취소", None),
            ],
        )
    ]


def station_checkbox_prompt(stations: list[str], default: list[str]) -> list:
    return [
        inquirer.Checkbox(
            "stations",
            message="역 선택 (↕:이동, Space: 선택, Enter: 완료, Ctrl-A: 전체선택, Ctrl-R: 선택해제, Ctrl-C: 취소)",
            choices=stations,
            default=default,
        )
    ]


def station_text_prompt(default: str) -> list:
    return [
        inquirer.Text(
            "stations",
            message="역 수정 (예: 수서,대전,동대구)",
            default=default,
        )
    ]


def options_checkbox_prompt(default: list[str]) -> list:
    return [
        inquirer.Checkbox(
            "options",
            message="예매 옵션 선택 (Space: 선택, Enter: 완료, Ctrl-A: 전체선택, Ctrl-R: 선택해제, Ctrl-C: 취소)",
            choices=[
                ("어린이", "child"),
                ("경로우대", "senior"),
                ("중증장애인", "disability1to3"),
                ("경증장애인", "disability4to6"),
                ("KTX만", "ktx"),
            ],
            default=default,
        )
    ]


def telegram_prompt(token: str, chat_id: str) -> list:
    return [
        inquirer.Text(
            "token",
            message="텔레그램 token (Enter: 완료, Ctrl-C: 취소)",
            default=token,
        ),
        inquirer.Text(
            "chat_id",
            message="텔레그램 chat_id (Enter: 완료, Ctrl-C: 취소)",
            default=chat_id,
        ),
    ]


def card_prompt(card_info: dict) -> list:
    return [
        inquirer.Password(
            "number",
            message="신용카드 번호 (하이픈 제외(-), Enter: 완료, Ctrl-C: 취소)",
            default=card_info.get("number", ""),
        ),
        inquirer.Password(
            "password",
            message="카드 비밀번호 앞 2자리 (Enter: 완료, Ctrl-C: 취소)",
            default=card_info.get("password", ""),
        ),
        inquirer.Password(
            "birthday",
            message="생년월일 (YYMMDD) / 사업자등록번호 (Enter: 완료, Ctrl-C: 취소)",
            default=card_info.get("birthday", ""),
        ),
        inquirer.Password(
            "expire",
            message="카드 유효기간 (YYMM, Enter: 완료, Ctrl-C: 취소)",
            default=card_info.get("expire", ""),
        ),
    ]


def login_prompt(rail_type: str, user_id: str, password: str) -> list:
    return [
        inquirer.Text(
            "id",
            message=f"{rail_type} 계정 아이디 (멤버십 번호, 이메일, 전화번호)",
            default=user_id,
        ),
        inquirer.Password(
            "pass",
            message=f"{rail_type} 계정 패스워드",
            default=password,
        ),
    ]


def reserve_info_prompt(
    station_key: list[str],
    options: list[str],
    defaults: dict,
    date_choices: list[tuple],
    time_choices: list[tuple],
) -> list:
    q = [
        inquirer.List(
            "departure",
            message="출발역 선택 (↕:이동, Enter: 선택, Ctrl-C: 취소)",
            choices=station_key,
            default=defaults.get("departure"),
        ),
        inquirer.List(
            "arrival",
            message="도착역 선택 (↕:이동, Enter: 선택, Ctrl-C: 취소)",
            choices=station_key,
            default=defaults.get("arrival"),
        ),
        inquirer.List(
            "date",
            message="출발 날짜 선택 (↕:이동, Enter: 선택, Ctrl-C: 취소)",
            choices=date_choices,
            default=defaults.get("date"),
        ),
        inquirer.List(
            "time",
            message="출발 시각 선택 (↕:이동, Enter: 선택, Ctrl-C: 취소)",
            choices=time_choices,
            default=defaults.get("time"),
        ),
        inquirer.List(
            "adult",
            message="성인 승객수 (↕:이동, Enter: 선택, Ctrl-C: 취소)",
            choices=list(range(10)),
            default=defaults.get("adult", 1),
        ),
    ]

    passenger_types = {
        "child": "어린이",
        "senior": "경로우대",
        "disability1to3": "1~3급 장애인",
        "disability4to6": "4~6급 장애인",
    }
    for key, label in passenger_types.items():
        if key in options:
            q.append(
                inquirer.List(
                    key,
                    message=f"{label} 승객수 (↕:이동, Enter: 선택, Ctrl-C: 취소)",
                    choices=list(range(10)),
                    default=defaults.get(key, 0),
                )
            )
    return q


def train_select_prompt(trains: list, decorator) -> list:
    return [
        inquirer.Checkbox(
            "trains",
            message="예약할 열차 선택 (↕:이동, Space: 선택, Enter: 완료, Ctrl-A: 전체선택, Ctrl-R: 선택해제, Ctrl-C: 취소)",
            choices=[(decorator(t), i) for i, t in enumerate(trains)],
            default=None,
        )
    ]


def seat_option_prompt(seat_type_class) -> list:
    return [
        inquirer.List(
            "type",
            message="선택 유형",
            choices=[
                ("일반실 우선", seat_type_class.GENERAL_FIRST),
                ("일반실만", seat_type_class.GENERAL_ONLY),
                ("특실 우선", seat_type_class.SPECIAL_FIRST),
                ("특실만", seat_type_class.SPECIAL_ONLY),
            ],
        ),
        inquirer.Confirm("pay", message="예매 시 카드 결제", default=False),
    ]


def reservation_list_prompt(all_reservations: list) -> list:
    choices = [
        (str(r), i) for i, r in enumerate(all_reservations)
    ] + [("텔레그램으로 예매 정보 전송", -2), ("돌아가기", -1)]
    return [
        inquirer.List(
            "choice",
            message="예약 취소 (Enter: 결정)",
            choices=choices,
        )
    ]


def pay_or_cancel_prompt(reservation) -> list:
    return [
        inquirer.List(
            "action",
            message=f"결재 대기 승차권: {reservation}",
            choices=[("결제하기", 1), ("취소하기", 2)],
        )
    ]


def confirm_cancel_prompt() -> list:
    return [
        inquirer.Confirm(
            "confirmed",
            message=colored("정말 취소하시겠습니까", "green", "on_red"),
        )
    ]


def confirm_continue_prompt(msg: str = "계속할까요") -> list:
    return [inquirer.Confirm("confirmed", message=msg, default=True)]
