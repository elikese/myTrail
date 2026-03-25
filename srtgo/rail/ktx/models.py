import itertools
from functools import reduce


# --- 예외 ---

class KorailError(Exception):
    def __init__(self, msg, code=None):
        self.msg = msg
        self.code = code

    def __str__(self):
        return f"{self.msg} ({self.code})"


class NeedToLoginError(KorailError):
    codes = {"P058"}

    def __init__(self, code=None):
        super().__init__("Need to Login", code)


class NoResultsError(KorailError):
    codes = {"P100", "WRG000000", "WRD000061", "WRT300005"}

    def __init__(self, code=None):
        super().__init__("No Results", code)


class SoldOutError(KorailError):
    codes = {"IRT010110", "ERR211161"}

    def __init__(self, code=None):
        super().__init__("Sold out", code)


class NetFunnelError(Exception):
    def __init__(self, msg):
        self.msg = msg

    def __str__(self):
        return self.msg


# --- 열차 옵션 ---

class TrainType:
    KTX = "100"
    SAEMAEUL = "101"
    MUGUNGHWA = "102"
    TONGGUEN = "103"
    NURIRO = "102"
    ALL = "109"
    AIRPORT = "105"
    KTX_SANCHEON = "100"
    ITX_SAEMAEUL = "101"
    ITX_CHEONGCHUN = "104"


class ReserveOption:
    GENERAL_FIRST = "GENERAL_FIRST"
    GENERAL_ONLY = "GENERAL_ONLY"
    SPECIAL_FIRST = "SPECIAL_FIRST"
    SPECIAL_ONLY = "SPECIAL_ONLY"


# --- 승객 ---

class Passenger:
    def __init_internal__(
        self, typecode, count=1, discount_type="000", card="", card_no="", card_pw=""
    ):
        self.typecode = typecode
        self.count = count
        self.discount_type = discount_type
        self.card = card
        self.card_no = card_no
        self.card_pw = card_pw

    @staticmethod
    def reduce(passenger_list):
        if not all(isinstance(x, Passenger) for x in passenger_list):
            raise TypeError("Passengers must be based on Passenger")
        groups = itertools.groupby(passenger_list, lambda x: x.group_key())
        return list(
            filter(
                lambda x: x.count > 0,
                [reduce(lambda a, b: a + b, g) for k, g in groups],
            )
        )

    def __add__(self, other):
        if not isinstance(other, self.__class__):
            raise TypeError("Cannot add different passenger types")
        if self.group_key() != other.group_key():
            raise TypeError(
                f"Cannot add passengers with different group keys: {self.group_key()} vs {other.group_key()}"
            )
        return self.__class__(
            count=self.count + other.count,
            discount_type=self.discount_type,
            card=self.card,
            card_no=self.card_no,
            card_pw=self.card_pw,
        )

    def group_key(self):
        return f"{self.typecode}_{self.discount_type}_{self.card}_{self.card_no}_{self.card_pw}"

    def get_dict(self, index):
        index = str(index)
        return {
            f"txtPsgTpCd{index}": self.typecode,
            f"txtDiscKndCd{index}": self.discount_type,
            f"txtCompaCnt{index}": self.count,
            f"txtCardCode_{index}": self.card,
            f"txtCardNo_{index}": self.card_no,
            f"txtCardPw_{index}": self.card_pw,
        }


class AdultPassenger(Passenger):
    def __init__(self, count=1, discount_type="000", card="", card_no="", card_pw=""):
        Passenger.__init_internal__(self, "1", count, discount_type, card, card_no, card_pw)


class ChildPassenger(Passenger):
    def __init__(self, count=1, discount_type="000", card="", card_no="", card_pw=""):
        Passenger.__init_internal__(self, "3", count, discount_type, card, card_no, card_pw)


class ToddlerPassenger(Passenger):
    def __init__(self, count=1, discount_type="321", card="", card_no="", card_pw=""):
        Passenger.__init_internal__(self, "3", count, discount_type, card, card_no, card_pw)


class SeniorPassenger(Passenger):
    def __init__(self, count=1, discount_type="131", card="", card_no="", card_pw=""):
        Passenger.__init_internal__(self, "1", count, discount_type, card, card_no, card_pw)


class Disability1To3Passenger(Passenger):
    def __init__(self, count=1, discount_type="111", card="", card_no="", card_pw=""):
        Passenger.__init_internal__(self, "1", count, discount_type, card, card_no, card_pw)


class Disability4To6Passenger(Passenger):
    def __init__(self, count=1, discount_type="112", card="", card_no="", card_pw=""):
        Passenger.__init_internal__(self, "1", count, discount_type, card, card_no, card_pw)


# --- 스케줄/열차 ---

class Schedule:
    def __init__(self, data):
        self.train_type = data.get("h_trn_clsf_cd")
        self.train_type_name = data.get("h_trn_clsf_nm")
        self.train_group = data.get("h_trn_gp_cd")
        self.train_no = data.get("h_trn_no")
        self.delay_time = data.get("h_expct_dlay_hr")

        self.dep_name = data.get("h_dpt_rs_stn_nm")
        self.dep_code = data.get("h_dpt_rs_stn_cd")
        self.dep_date = data.get("h_dpt_dt")
        self.dep_time = data.get("h_dpt_tm")

        self.arr_name = data.get("h_arv_rs_stn_nm")
        self.arr_code = data.get("h_arv_rs_stn_cd")
        self.arr_date = data.get("h_arv_dt")
        self.arr_time = data.get("h_arv_tm")

        self.run_date = data.get("h_run_dt")

    def __repr__(self):
        dep_time = f"{self.dep_time[:2]}:{self.dep_time[2:4]}"
        arr_time = f"{self.arr_time[:2]}:{self.arr_time[2:4]}"
        dep_date = f"{int(self.dep_date[4:6]):02d}/{int(self.dep_date[6:]):02d}"
        train_line = f"[{self.train_type_name[:3]} {self.train_no}]"
        return (
            f"{train_line:<11s}"
            f"{dep_date} {dep_time}~{arr_time}  "
            f"{self.dep_name}~{self.arr_name}"
        )


class Train(Schedule):
    def __init__(self, data):
        super().__init__(data)
        self.reserve_possible = data.get("h_rsv_psb_flg")
        self.reserve_possible_name = data.get("h_rsv_psb_nm")
        self.special_seat = data.get("h_spe_rsv_cd")
        self.general_seat = data.get("h_gen_rsv_cd")
        self.wait_reserve_flag = data.get("h_wait_rsv_flg")
        if self.wait_reserve_flag:
            self.wait_reserve_flag = int(self.wait_reserve_flag)

    def __repr__(self):
        repr_str = super().__repr__()
        duration = (int(self.arr_time[:2]) * 60 + int(self.arr_time[2:4])) - (
            int(self.dep_time[:2]) * 60 + int(self.dep_time[2:4])
        )
        if duration < 0:
            duration += 24 * 60
        if self.reserve_possible_name:
            repr_str += f"  특실 {'가능' if self.has_special_seat() else '매진'}"
            repr_str += f", 일반실 {'가능' if self.has_general_seat() else '매진'}"
            if self.wait_reserve_flag >= 0:
                repr_str += f", 예약대기 {'가능' if self.has_general_waiting_list() else '매진'}"
        repr_str += f" ({duration:>3d}분)"
        return repr_str

    def has_special_seat(self) -> bool:
        return self.special_seat == "11"

    def has_general_seat(self) -> bool:
        return self.general_seat == "11"

    def has_seat(self) -> bool:
        return self.has_general_seat() or self.has_special_seat()

    def has_waiting_list(self) -> bool:
        return self.has_general_waiting_list()

    def has_general_waiting_list(self) -> bool:
        return self.wait_reserve_flag == 9


class Ticket(Train):
    def __init__(self, data):
        raw_data = data["ticket_list"][0]["train_info"][0]
        super().__init__(raw_data)
        self.seat_no_end = raw_data.get("h_seat_no_end")
        self.seat_no_count = int(raw_data.get("h_seat_cnt"))
        self.buyer_name = raw_data.get("h_buy_ps_nm")
        self.sale_date = raw_data.get("h_orgtk_sale_dt")
        self.pnr_no = raw_data.get("h_pnr_no")
        self.sale_info1 = raw_data.get("h_orgtk_wct_no")
        self.sale_info2 = raw_data.get("h_orgtk_ret_sale_dt")
        self.sale_info3 = raw_data.get("h_orgtk_sale_sqno")
        self.sale_info4 = raw_data.get("h_orgtk_ret_pwd")
        self.price = int(raw_data.get("h_rcvd_amt"))
        self.car_no = raw_data.get("h_srcar_no")
        self.seat_no = raw_data.get("h_seat_no")

    def __repr__(self):
        repr_str = super(Train, self).__repr__()
        repr_str += f" => {self.car_no}호"
        if int(self.seat_no_count) != 1:
            repr_str += f" {self.seat_no}~{self.seat_no_end}"
        else:
            repr_str += f" {self.seat_no}"
        repr_str += f", {self.price}원"
        return repr_str

    def get_ticket_no(self):
        return "-".join(
            map(str, (self.sale_info1, self.sale_info2, self.sale_info3, self.sale_info4))
        )


class Reservation(Train):
    def __init__(self, data):
        super().__init__(data)
        self.dep_date = data.get("h_run_dt")
        self.arr_date = data.get("h_run_dt")
        self.rsv_id = data.get("h_pnr_no")
        self.seat_no_count = int(data.get("h_tot_seat_cnt"))
        self.buy_limit_date = data.get("h_ntisu_lmt_dt")
        self.buy_limit_time = data.get("h_ntisu_lmt_tm")
        self.price = int(data.get("h_rsv_amt"))
        self.journey_no = data.get("txtJrnySqno", "001")
        self.journey_cnt = data.get("txtJrnyCnt", "01")
        self.rsv_chg_no = data.get("hidRsvChgNo", "00000")
        self.is_waiting = (
            self.buy_limit_date == "00000000" or self.buy_limit_time == "235959"
        )

    def __repr__(self):
        repr_str = super().__repr__()
        repr_str += f", {self.price}원({self.seat_no_count}석)"
        if self.is_waiting:
            repr_str += ", 예약대기"
        else:
            buy_limit_time = f"{self.buy_limit_time[:2]}:{self.buy_limit_time[2:4]}"
            buy_limit_date = (
                f"{int(self.buy_limit_date[4:6])}월 {int(self.buy_limit_date[6:])}일"
            )
            repr_str += f", 구입기한 {buy_limit_date} {buy_limit_time}"
        return repr_str


class Seat:
    def __init__(self, data: dict):
        self.car = data.get("h_srcar_no")
        self.seat = data.get("h_seat_no")
        self.seat_type = data.get("h_psrm_cl_nm")
        self.passenger_type = data.get("h_psg_tp_dv_nm")
        self.price = int(data.get("h_rcvd_amt", 0))
        self.original_price = int(data.get("h_seat_prc", 0))
        self.discount = int(data.get("h_dcnt_amt", 0))
        self.is_waiting = self.seat == ""

    def __repr__(self):
        if self.is_waiting:
            return (
                f"예약대기 ({self.seat_type}) {self.passenger_type}"
                f"[{self.price}원({self.discount}원 할인)]"
            )
        return (
            f"{self.car}호차 {self.seat} ({self.seat_type}) {self.passenger_type} "
            f"[{self.price}원({self.discount}원 할인)]"
        )
