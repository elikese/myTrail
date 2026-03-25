import abc
from enum import Enum
from typing import Dict, List

from .constants import TRAIN_NAME, STATION_NAME, WINDOW_SEAT


# --- 예외 ---

class SRTError(Exception):
    def __init__(self, msg):
        super().__init__(msg)
        self.msg = msg

    def __str__(self):
        return self.msg


class SRTLoginError(SRTError):
    pass


class SRTResponseError(SRTError):
    pass


class SRTDuplicateError(SRTResponseError):
    pass


class SRTNotLoggedInError(SRTError):
    pass


class SRTNetFunnelError(SRTError):
    pass


# --- 승객 ---

class Passenger(metaclass=abc.ABCMeta):

    @abc.abstractmethod
    def __init__(self):
        pass

    def __init_internal__(self, name: str, type_code: str, count: int):
        self.name = name
        self.type_code = type_code
        self.count = count

    def __repr__(self) -> str:
        return f"{self.name} {self.count}명"

    def __add__(self, other: "Passenger") -> "Passenger":
        if not isinstance(other, self.__class__):
            raise TypeError("Passenger types must be the same")
        if self.type_code == other.type_code:
            return self.__class__(count=self.count + other.count)
        raise ValueError("Passenger types must be the same")

    @classmethod
    def combine(cls, passengers: List["Passenger"]) -> List["Passenger"]:
        if not all(isinstance(p, Passenger) for p in passengers):
            raise TypeError("All passengers must be based on Passenger")
        passenger_dict = {}
        for passenger in passengers:
            key = passenger.__class__
            passenger_dict[key] = (
                passenger_dict.get(key, passenger.__class__(0)) + passenger
            )
        return [p for p in passenger_dict.values() if p.count > 0]

    @staticmethod
    def total_count(passengers: List["Passenger"]) -> str:
        if not all(isinstance(p, Passenger) for p in passengers):
            raise TypeError("All passengers must be based on Passenger")
        return str(sum(p.count for p in passengers))

    @staticmethod
    def get_passenger_dict(
        passengers: List["Passenger"],
        special_seat: bool = False,
        window_seat: str = None,
    ) -> Dict[str, str]:
        if not all(isinstance(p, Passenger) for p in passengers):
            raise TypeError("All passengers must be instances of Passenger")
        combined_passengers = Passenger.combine(passengers)
        data = {
            "totPrnb": Passenger.total_count(combined_passengers),
            "psgGridcnt": str(len(combined_passengers)),
            "locSeatAttCd1": WINDOW_SEAT.get(window_seat, "000"),
            "rqSeatAttCd1": "015",
            "dirSeatAttCd1": "009",
            "smkSeatAttCd1": "000",
            "etcSeatAttCd1": "000",
            "psrmClCd1": "2" if special_seat else "1",
        }
        for i, passenger in enumerate(combined_passengers, start=1):
            data[f"psgTpCd{i}"] = passenger.type_code
            data[f"psgInfoPerPrnb{i}"] = str(passenger.count)
        return data


class Adult(Passenger):
    def __init__(self, count: int = 1):
        super().__init__()
        super().__init_internal__("어른/청소년", "1", count)


class Child(Passenger):
    def __init__(self, count: int = 1):
        super().__init__()
        super().__init_internal__("어린이", "5", count)


class Senior(Passenger):
    def __init__(self, count: int = 1):
        super().__init__()
        super().__init_internal__("경로", "4", count)


class Disability1To3(Passenger):
    def __init__(self, count: int = 1):
        super().__init__()
        super().__init_internal__("장애 1~3급", "2", count)


class Disability4To6(Passenger):
    def __init__(self, count: int = 1):
        super().__init__()
        super().__init_internal__("장애 4~6급", "3", count)


# --- 좌석 타입 ---

class SeatType(Enum):
    GENERAL_FIRST = 1   # 일반실 우선
    GENERAL_ONLY = 2    # 일반실만
    SPECIAL_FIRST = 3   # 특실 우선
    SPECIAL_ONLY = 4    # 특실만


# --- 열차 ---

class SRTTrain:
    def __init__(self, data: dict):
        self.train_code = data["stlbTrnClsfCd"]
        self.train_name = TRAIN_NAME[self.train_code]
        self.train_number = data["trnNo"]

        self.dep_date = data["dptDt"]
        self.dep_time = data["dptTm"]
        self.dep_station_code = data["dptRsStnCd"]
        self.dep_station_name = STATION_NAME[self.dep_station_code]
        self.dep_station_run_order = data["dptStnRunOrdr"]
        self.dep_station_constitution_order = data["dptStnConsOrdr"]

        self.arr_date = data["arvDt"]
        self.arr_time = data["arvTm"]
        self.arr_station_code = data["arvRsStnCd"]
        self.arr_station_name = STATION_NAME[self.arr_station_code]
        self.arr_station_run_order = data["arvStnRunOrdr"]
        self.arr_station_constitution_order = data["arvStnConsOrdr"]

        self.general_seat_state = data["gnrmRsvPsbStr"]
        self.special_seat_state = data["sprmRsvPsbStr"]
        self.reserve_wait_possible_name = data["rsvWaitPsbCdNm"]
        self.reserve_wait_possible_code = int(data["rsvWaitPsbCd"])

    def __str__(self):
        return self.dump()

    def __repr__(self):
        return self.dump()

    def dump(self):
        dep_hour, dep_min = self.dep_time[0:2], self.dep_time[2:4]
        arr_hour, arr_min = self.arr_time[0:2], self.arr_time[2:4]
        duration = (int(arr_hour) * 60 + int(arr_min)) - (
            int(dep_hour) * 60 + int(dep_min)
        )
        if duration < 0:
            duration += 24 * 60
        month, day = self.dep_date[4:6], self.dep_date[6:8]
        train_line = f"[{self.train_name} {self.train_number}]"
        msg = (
            f"{train_line:<11s}"
            f"{month}/{day}"
            f" {dep_hour}:{dep_min}~{arr_hour}:{arr_min}  "
            f"{self.dep_station_name}~{self.arr_station_name}  "
            f"특실 {self.special_seat_state}, 일반실 {self.general_seat_state}"
        )
        if self.reserve_wait_possible_code >= 0:
            msg += f", 예약대기 {self.reserve_wait_possible_name}"
        msg += f" ({duration:>3d}분)"
        return msg

    def general_seat_available(self) -> bool:
        return "예약가능" in self.general_seat_state

    def special_seat_available(self) -> bool:
        return "예약가능" in self.special_seat_state

    def reserve_standby_available(self) -> bool:
        return self.reserve_wait_possible_code == 9

    def seat_available(self) -> bool:
        return self.general_seat_available() or self.special_seat_available()


# --- 티켓 ---

class SRTTicket:
    SEAT_TYPE = {"1": "일반실", "2": "특실"}
    PASSENGER_TYPE = {
        "1": "어른/청소년",
        "2": "장애 1~3급",
        "3": "장애 4~6급",
        "4": "경로",
        "5": "어린이",
    }
    DISCOUNT_TYPE = {
        "000": "어른/청소년",
        "101": "탄력운임기준할인",
        "105": "자유석 할인",
        "106": "입석 할인",
        "107": "역방향석 할인",
        "108": "출입구석 할인",
        "109": "가족석 일반전환 할인",
        "111": "구간별 특정운임",
        "112": "열차별 특정운임",
        "113": "구간별 비율할인(기준)",
        "114": "열차별 비율할인(기준)",
        "121": "공항직결 수색연결운임",
        "131": "구간별 특별할인(기준)",
        "132": "열차별 특별할인(기준)",
        "133": "기본 특별할인(기준)",
        "191": "정차역 할인",
        "192": "매체 할인",
        "201": "어린이",
        "202": "동반유아 할인",
        "204": "경로",
        "205": "1~3급 장애인",
        "206": "4~6급 장애인",
    }

    def __init__(self, data: dict) -> None:
        self.car = data.get("scarNo")
        self.seat = data.get("seatNo")
        self.seat_type_code = data.get("psrmClCd")
        self.seat_type = self.SEAT_TYPE[self.seat_type_code]
        self.passenger_type_code = data.get("dcntKndCd")
        self.passenger_type = self.DISCOUNT_TYPE.get(self.passenger_type_code, "기타 할인")
        self.price = int(data.get("rcvdAmt"))
        self.original_price = int(data.get("stdrPrc"))
        self.discount = int(data.get("dcntPrc"))
        self.is_waiting = self.seat == ""

    def __str__(self) -> str:
        return self.dump()

    __repr__ = __str__

    def dump(self) -> str:
        if self.is_waiting:
            return (
                f"예약대기 ({self.seat_type}) {self.passenger_type}"
                f"[{self.price}원({self.discount}원 할인)]"
            )
        return (
            f"{self.car}호차 {self.seat} ({self.seat_type}) {self.passenger_type} "
            f"[{self.price}원({self.discount}원 할인)]"
        )


# --- 예약 ---

class SRTReservation:
    def __init__(self, train: dict, pay: dict, tickets: list):
        self.reservation_number = train.get("pnrNo")
        self.total_cost = int(train.get("rcvdAmt"))
        self.seat_count = train.get("tkSpecNum") or int(train.get("seatNum"))

        self.train_code = pay.get("stlbTrnClsfCd")
        self.train_name = TRAIN_NAME[self.train_code]
        self.train_number = pay.get("trnNo")

        self.dep_date = pay.get("dptDt")
        self.dep_time = pay.get("dptTm")
        self.dep_station_code = pay.get("dptRsStnCd")
        self.dep_station_name = STATION_NAME[self.dep_station_code]

        self.arr_time = pay.get("arvTm")
        self.arr_station_code = pay.get("arvRsStnCd")
        self.arr_station_name = STATION_NAME[self.arr_station_code]

        self.payment_date = pay.get("iseLmtDt")
        self.payment_time = pay.get("iseLmtTm")
        self.paid = pay.get("stlFlg") == "Y"
        self.is_running = "tkSpecNum" not in train
        self.is_waiting = not (self.paid or self.payment_date or self.payment_time)

        self._tickets = tickets

    def __str__(self):
        return self.dump()

    __repr__ = __str__

    def dump(self):
        base = (
            f"[{self.train_name}] "
            f"{self.dep_date[4:6]}월 {self.dep_date[6:8]}일, "
            f"{self.dep_station_name}~{self.arr_station_name}"
            f"({self.dep_time[:2]}:{self.dep_time[2:4]}~{self.arr_time[:2]}:{self.arr_time[2:4]}) "
            f"{self.total_cost}원({self.seat_count}석)"
        )
        if not self.paid:
            if not self.is_waiting:
                base += (
                    f", 구입기한 {self.payment_date[4:6]}월 {self.payment_date[6:8]}일 "
                    f"{self.payment_time[:2]}:{self.payment_time[2:4]}"
                )
            elif not self.is_running:
                base += ", 예약대기"
        if self.is_running:
            base += " (운행중)"
        return base

    @property
    def tickets(self):
        return self._tickets
