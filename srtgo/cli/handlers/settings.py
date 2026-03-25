"""로그인/텔레그램/카드/역/옵션 설정 핸들러."""

import logging
import re

import inquirer

from ...config.constants import DEFAULT_STATIONS, STATIONS
from ...config.settings import (
    delete_rail_credential, delete_telegram_config,
    get_card_info, get_options, get_rail_credential,
    get_station_setting, get_telegram_config,
    set_card_info, set_options, set_rail_credential,
    set_station_setting, set_telegram_config,
)
from ...service.notification import send_telegram
from ..prompts import (
    card_prompt, login_prompt, options_checkbox_prompt,
    station_checkbox_prompt, station_text_prompt, telegram_prompt,
)

logger = logging.getLogger(__name__)


def _create_with_creds(rail_type: str, user_id: str, password: str, debug: bool):
    if rail_type == "SRT":
        from ...rail.srt.client import SRT
        return SRT(user_id, password, verbose=debug)
    else:
        from ...rail.ktx.client import Korail
        return Korail(user_id, password, verbose=debug)


def handle_set_login(rail_type: str, debug: bool = False) -> bool:
    user_id, password = get_rail_credential(rail_type)
    result = inquirer.prompt(login_prompt(rail_type, user_id or "", password or ""))
    if not result:
        return False
    try:
        rail = _create_with_creds(rail_type, result["id"], result["pass"], debug)
        if not rail.is_login:
            raise RuntimeError("로그인에 실패했습니다. 아이디/비밀번호를 확인하세요.")
        set_rail_credential(rail_type, result["id"], result["pass"])
        logger.info("로그인 설정 완료: rail_type=%s", rail_type)
        return True
    except Exception as e:
        logger.error("로그인 설정 실패: %s", e)
        print(str(e))
        delete_rail_credential(rail_type)
        return False


def handle_set_telegram() -> bool:
    token, chat_id = get_telegram_config()
    result = inquirer.prompt(telegram_prompt(token or "", chat_id or ""))
    if not result:
        return False
    try:
        set_telegram_config(result["token"], result["chat_id"])
        send_telegram("[SRTGO] 텔레그램 설정 완료")
        return True
    except Exception as e:
        logger.error("텔레그램 설정 실패: %s", e)
        print(str(e))
        delete_telegram_config()
        return False


def handle_set_card() -> bool:
    existing = get_card_info() or {}
    result = inquirer.prompt(card_prompt(existing))
    if not result:
        return False
    set_card_info(result["number"], result["password"], result["birthday"], result["expire"])
    logger.info("카드 설정 완료")
    return True


def handle_set_station(rail_type: str) -> bool:
    stations = STATIONS[rail_type]
    station_key_str = get_station_setting(rail_type)
    default = station_key_str.split(",") if station_key_str else DEFAULT_STATIONS[rail_type]

    result = inquirer.prompt(station_checkbox_prompt(stations, default))
    if not result:
        return False
    selected = result["stations"]
    if not selected:
        print("선택된 역이 없습니다.")
        return False
    set_station_setting(rail_type, ",".join(selected))
    print(f"선택된 역: {','.join(selected)}")
    return True


def handle_edit_station(rail_type: str) -> bool:
    station_key_str = get_station_setting(rail_type) or ""
    result = inquirer.prompt(station_text_prompt(station_key_str))
    if not result:
        return False
    raw = result["stations"]
    if not raw:
        print("선택된 역이 없습니다.")
        return False

    selected = [s.strip() for s in raw.split(",")]
    hangul = re.compile("[가-힣]+")
    for station in selected:
        if not hangul.search(station):
            print(f"'{station}'는 잘못된 입력입니다. 기본 역으로 설정합니다.")
            selected = DEFAULT_STATIONS[rail_type]
            break

    set_station_setting(rail_type, ",".join(selected))
    print(f"선택된 역: {','.join(selected)}")
    return True


def handle_set_options() -> bool:
    current = get_options()
    result = inquirer.prompt(options_checkbox_prompt(current))
    if result is None:
        return False
    set_options(result.get("options", []))
    return True
