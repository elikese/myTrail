"""CLI 진입점 및 메뉴 루프."""

import logging

import click
import inquirer

from ..logging.setup import setup_logging
from ..service.auth import create_rail
from .handlers.check import handle_check_reservation
from .handlers.reserve import handle_reserve
from .handlers.settings import (
    handle_edit_station,
    handle_set_card,
    handle_set_login,
    handle_set_options,
    handle_set_station,
    handle_set_telegram,
)
from .prompts import menu_prompt, rail_type_prompt

logger = logging.getLogger(__name__)

# 열차 선택이 필요한 메뉴 항목
_NEEDS_RAIL_TYPE = {1, 2, 3, 6, 7}


@click.command()
@click.option("--debug", is_flag=True, help="Debug mode")
def srtgo(debug: bool = False) -> None:
    setup_logging(debug=debug)
    logger.info("srtgo 시작 (debug=%s)", debug)

    while True:
        menu_result = inquirer.prompt(menu_prompt())
        if not menu_result:
            break
        choice = menu_result["choice"]

        if choice == -1:
            break

        rail_type = None
        if choice in _NEEDS_RAIL_TYPE:
            rail_result = inquirer.prompt(rail_type_prompt())
            if not rail_result or rail_result["rail_type"] is None:
                continue
            rail_type = rail_result["rail_type"]

        if choice == 1:
            _run_with_login(rail_type, debug, handle_reserve)
        elif choice == 2:
            _run_with_login(rail_type, debug, handle_check_reservation)
        elif choice == 3:
            handle_set_login(rail_type, debug)
        elif choice == 4:
            handle_set_telegram()
        elif choice == 5:
            handle_set_card()
        elif choice == 6:
            handle_set_station(rail_type)
        elif choice == 7:
            handle_edit_station(rail_type)
        elif choice == 8:
            handle_set_options()

    logger.info("srtgo 종료")


def _run_with_login(rail_type: str, debug: bool, handler) -> None:
    """로그인 후 handler(rail, rail_type) 호출."""
    try:
        rail = create_rail(rail_type, debug=debug)
    except ValueError as e:
        print(str(e))
        if inquirer.confirm(message="지금 로그인 설정하시겠습니까", default=True):
            handle_set_login(rail_type, debug)
        return
    except Exception as e:
        logger.error("로그인 실패: %s", e)
        print(str(e))
        return

    handler(rail, rail_type)
