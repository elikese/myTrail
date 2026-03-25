from abc import ABC, abstractmethod
from typing import Any


class AbstractRail(ABC):
    """SRT / KTX 공통 인터페이스.

    상위 계층(service, cli)은 이 타입으로만 rail을 다룬다.
    구체 타입(SRT, Korail)을 직접 참조하지 않는다.
    """

    @abstractmethod
    def login(self, user_id: str, password: str) -> bool: ...

    @abstractmethod
    def logout(self) -> bool: ...

    @abstractmethod
    def search_train(
        self,
        dep: str,
        arr: str,
        date: str,
        time: str,
        passengers: list,
        include_no_seats: bool = False,
    ) -> list: ...

    @abstractmethod
    def reserve(self, train: Any, passengers: list, option: Any) -> Any: ...

    @abstractmethod
    def get_reservations(self) -> list:
        """미결제 예약 목록 반환."""
        ...

    @abstractmethod
    def get_tickets(self) -> list:
        """결제 완료된 승차권 목록 반환."""
        ...

    @abstractmethod
    def cancel(self, reservation: Any) -> bool: ...

    @abstractmethod
    def refund(self, ticket: Any) -> bool: ...

    @abstractmethod
    def pay_with_card(self, reservation: Any, card_info: dict) -> bool:
        """card_info 키: number, password, birthday, expire"""
        ...

    @property
    @abstractmethod
    def is_login(self) -> bool: ...
