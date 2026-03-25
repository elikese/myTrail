"""예매 확인 / 결제 / 취소 핸들러."""

import logging

import inquirer
from termcolor import colored

from ...rail.base import AbstractRail
from ...service.notification import send_telegram
from ...service.payment import pay_with_saved_card
from ..prompts import (
    confirm_cancel_prompt, pay_or_cancel_prompt, reservation_list_prompt,
)

logger = logging.getLogger(__name__)


def handle_check_reservation(rail: AbstractRail, rail_type: str) -> None:
    while True:
        reservations = rail.get_reservations()
        tickets = rail.get_tickets()

        # SRT: get_reservations()에 유/무료 모두 포함, get_tickets()는 paid_only
        # KTX: reservations=미결제, tickets=결제완료
        # 통합 뷰 구성
        all_items = []
        for t in tickets:
            t.is_ticket = True
            all_items.append(t)
        for r in reservations:
            if hasattr(r, "paid") and r.paid:
                r.is_ticket = True
            else:
                r.is_ticket = False
            if r not in all_items:
                all_items.append(r)

        if not all_items:
            print(colored("예약 내역이 없습니다", "green", "on_red") + "\n")
            return

        result = inquirer.prompt(reservation_list_prompt(all_items))
        if not result:
            return
        choice = result["choice"]

        if choice in (None, -1):
            return

        if choice == -2:
            _send_reservations_telegram(all_items, rail_type)
            return

        item = all_items[choice]

        if not item.is_ticket and not getattr(item, "is_waiting", False):
            action_result = inquirer.prompt(pay_or_cancel_prompt(item))
            if not action_result:
                return
            if action_result["action"] == 1:
                if pay_with_saved_card(rail, item):
                    print(colored("\n\n💳 ✨ 결제 성공!!! ✨ 💳\n\n", "green", "on_red"), end="")
            elif action_result["action"] == 2:
                rail.cancel(item)
            return

        confirm_result = inquirer.prompt(confirm_cancel_prompt())
        if confirm_result and confirm_result["confirmed"]:
            try:
                if item.is_ticket:
                    rail.refund(item)
                else:
                    rail.cancel(item)
            except Exception as e:
                logger.error("취소/환불 실패: %s", e)
                raise
        return


def _send_reservations_telegram(all_items: list, rail_type: str) -> None:
    out = ["[ 예매 내역 ]"]
    for item in all_items:
        out.append(f"🚅{item}")
        if rail_type == "SRT" and hasattr(item, "tickets") and item.tickets:
            out.extend(map(str, item.tickets))
    if out:
        send_telegram("\n".join(out))
