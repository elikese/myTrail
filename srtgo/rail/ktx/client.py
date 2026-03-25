"""Korail(KTX) HTTP 클라이언트 — AbstractRail 구현체."""

import base64
import json
import logging
import random
import re
import string
import time

import requests


try:
    import tls_client
    HAS_TLS_CLIENT = True
except ImportError:
    tls_client = None
    HAS_TLS_CLIENT = False


from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from datetime import datetime, timedelta

from ..base import AbstractRail
from ...config.settings import get_or_create_device_id
from .constants import (
    API_ENDPOINTS, DEFAULT_HEADERS, DEVICE, EMAIL_REGEX,
    KEY, PHONE_NUMBER_REGEX, VERSION, NetFunnelConfig,
)
from .models import (
    AdultPassenger, KorailError, NeedToLoginError, NetFunnelError,
    NoResultsError, Passenger, Reservation, ReserveOption, SoldOutError,
    Ticket, Train,
)
from .parser import (
    check_result, get_reservation_id, parse_reservations,
    parse_seats, parse_tickets, parse_trains,
)

logger = logging.getLogger(__name__)

DYNAPATH_PATHS = [
    "/classes/com.korail.mobile.certification.TicketReservation",
    "/classes/com.korail.mobile.nonMember.NonMemTicket",
    "/classes/com.korail.mobile.seatMovie.ScheduleView",
    "/classes/com.korail.mobile.seatMovie.ScheduleViewSpecial",
    "/classes/com.korail.mobile.trn.prcFare.do",
    "/classes/com.korail.mobile.login.Login",
]


class DynaPathMasterEngine:
    APP_ID = "com.korail.talk"
    AS_VALUE = "%5B38ff229cb34c7dda8e28220a2d750cce%5D"
    DEVICE_MODEL = "SM-S928N"
    OS_TYPE = "Android"
    SDK_VERSION = "v1"

    def __init__(self):
        self.TABLE = "3FE9jgRD4KdCyuawklqGJYmvfMn15P7US8XbxeLQtWT6OicBAopINs2Vh0HZrz"
        self.I8, self.I9, self.I10 = 161, 30, 2
        self.app_start_ts = str(int(time.time() * 1000))

    def string2xA1s(self, data_str):
        result = []
        i = 0
        while i < len(data_str):
            cp = ord(data_str[i])
            i += 1
            if cp < 128:
                result.append(cp)
            elif cp < 2048:
                result.append(128 | ((cp >> 7) & 15))
                result.append(cp & 127)
            elif cp >= 262144:
                result.append(160)
                result.append((cp >> 14) & 127)
                result.append((cp >> 7) & 127)
                result.append(cp & 127)
            elif (63488 & cp) != 55296:
                result.append(((cp >> 14) & 15) | 144)
                result.append((cp >> 7) & 127)
                result.append(cp & 127)
        return result

    def make_key(self, key_str):
        big_int_add = 0
        for char in key_str:
            cp = ord(char)
            i9_bit = 32768
            for _ in range(16):
                if (i9_bit & cp) != 0:
                    break
                i9_bit >>= 1
            big_int_add = (big_int_add * (i9_bit << 1)) + cp
        return big_int_add

    def _internal_i(self, base_table, remainder, encode_size, current_sb):
        j8_count = 0
        for k in range(len(base_table)):
            char = base_table[k]
            if char not in current_sb:
                if j8_count == remainder:
                    return char
                j8_count += 1
        return ' '

    def make_encode_table(self, num, encode_size, base_table):
        sb = ""
        temp_num = num
        for i in range(encode_size):
            j8_divisor = encode_size - i
            remainder = temp_num % j8_divisor
            char = self._internal_i(base_table, remainder, len(base_table), sb)
            sb += char
            temp_num //= j8_divisor
        return sb

    def encode_normal_be(self, data_str, table, i8=161, i9=30, i10=2):
        list_data = self.string2xA1s(data_str)
        sb, i_arr = [], [0] * (i10 + 1)
        idx, size = 0, len(list_data) % i10
        size2 = len(list_data) - size
        while idx < size2:
            val = 0
            for _ in range(i10):
                val = (val * i8) + list_data[idx]
                idx += 1
            for i in range(i10 + 1):
                i_arr[i] = val % i9
                val //= i9
            for i in range(i10, -1, -1):
                sb.append(table[i_arr[i]])
        if size > 0:
            val = 0
            for _ in range(size):
                val = (val * i8) + list_data[idx]
                idx += 1
            for i in range(size + 1):
                i_arr[i] = val % i9
                val //= i9
            while size >= 0:
                sb.append(table[i_arr[size]])
                size -= 1
        return "".join(sb)

    def generate_token(self, device_id, ts, rand):
        plaintext = (
            f"ai={self.APP_ID}&di={device_id}&as={self.AS_VALUE}&"
            f"su=false&dbg=false&emu=false&hk=false&it={self.app_start_ts}&"
            f"ts={ts}&rt=0&os=13&dm={self.DEVICE_MODEL}&st={self.OS_TYPE}&sv={self.SDK_VERSION}"
        )
        dyn_key = f"v1+{rand}+{ts}"
        key_enc = self.encode_normal_be(dyn_key, self.TABLE, self.I8, self.I9, self.I10)
        big_key = self.make_key(dyn_key)
        custom_table = self.make_encode_table(big_key, self.I9, self.TABLE)
        body_enc = self.encode_normal_be(plaintext, custom_table, self.I8, self.I9, self.I10)
        return f"bEeEP{self.TABLE[len(key_enc)]}{key_enc}{body_enc}"


class NetFunnelHelper:
    def __init__(self):
        self._session = requests.session()
        self._session.headers.update(NetFunnelConfig.HEADERS)
        self._cached_key = None
        self._last_fetch_time = 0

    def run(self) -> str:
        current_time = time.time()
        if self._is_cache_valid(current_time):
            return self._cached_key
        try:
            status, self._cached_key, nwait = self._start()
            self._last_fetch_time = current_time
            while status == NetFunnelConfig.WAIT_STATUS_FAIL:
                logger.debug("NetFunnel 대기: %s명", nwait)
                time.sleep(1)
                status, self._cached_key, nwait = self._check()
            status, _, _ = self._complete()
            if status in (NetFunnelConfig.WAIT_STATUS_PASS, NetFunnelConfig.ALREADY_COMPLETED):
                return self._cached_key
            self.clear()
            raise NetFunnelError("Failed to complete NetFunnel")
        except NetFunnelError:
            raise
        except Exception as ex:
            self.clear()
            raise NetFunnelError(str(ex))

    def clear(self):
        self._cached_key = None
        self._last_fetch_time = 0

    def _start(self):
        return self._make_request("getTidchkEnter")

    def _check(self):
        return self._make_request("chkEnter")

    def _complete(self):
        return self._make_request("setComplete")

    def _make_request(self, opcode: str):
        params = self._build_params(NetFunnelConfig.OP_CODE[opcode])
        r = self._session.get(NetFunnelConfig.URL, params=params)
        logger.debug("NetFunnel %s 전체응답: %s", opcode, r.text)
        response = self._parse(r.text)
        return response.get("status"), response.get("key"), response.get("nwait")

    def _build_params(self, opcode: str) -> dict:
        params = {"opcode": opcode}
        if opcode in (NetFunnelConfig.OP_CODE["getTidchkEnter"], NetFunnelConfig.OP_CODE["chkEnter"]):
            params.update({"sid": "service_1", "aid": "act_8"})
            if opcode == NetFunnelConfig.OP_CODE["chkEnter"]:
                params.update({"key": self._cached_key, "ttl": "1"})
        elif opcode == NetFunnelConfig.OP_CODE["setComplete"]:
            params["key"] = self._cached_key
        return params

    def _parse(self, response: str) -> dict:
        status, params_str = response.split(":", 1)
        if not params_str:
            raise NetFunnelError("Failed to parse NetFunnel response")
        params = dict(
            param.split("=", 1) for param in params_str.split("&") if "=" in param
        )
        params["status"] = status
        return params

    def _is_cache_valid(self, current_time: float) -> bool:
        return bool(
            self._cached_key
            and (current_time - self._last_fetch_time) < NetFunnelConfig.CACHE_TTL
        )


class Korail(AbstractRail):
    """Korail(KTX) API 클라이언트."""

    _sid_key = b"2485dd54d9deaa36"

    def __init__(self, korail_id: str, korail_pw: str, auto_login: bool = True, verbose: bool = False):
        if HAS_TLS_CLIENT:
            self._session = tls_client.Session(
                client_identifier="okhttp4_android_13",
                random_tls_extension_order=False,
            )
            logger.debug("TLS 세션: tls-client okhttp4_android_13")
        else:
            self._session = requests.Session()
            logger.debug("TLS 세션: requests")
        self._session.headers.clear()
        self._session.headers.update(DEFAULT_HEADERS)
        self._device = DEVICE
        self._version = VERSION
        self._key = KEY
        self._idx = None
        self.korail_id = korail_id
        self.korail_pw = korail_pw
        self._logined = False
        self.membership_number = None
        self.name = None
        self.email = None
        self.phone_number = None
        self._device_id = get_or_create_device_id("KTX")
        self._netfunnel = NetFunnelHelper()
        self._engine = DynaPathMasterEngine()

        if auto_login:
            self.login(korail_id, korail_pw)

    def _generate_sid(self, ts: int) -> str:
        plaintext = f"{self._device}{ts}".encode("utf-8")
        cipher = AES.new(self._sid_key, AES.MODE_CBC, iv=self._sid_key)
        return base64.b64encode(cipher.encrypt(pad(plaintext, 16))).decode("utf-8") + "\n"

    def _get_auth_headers_and_sid(self, url: str) -> tuple[dict, str | None]:
        if not any(path in url for path in DYNAPATH_PATHS):
            return {}, None
        ts = int(time.time() * 1000)
        rand = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
        token = self._engine.generate_token(self._device_id, ts, rand)
        sid = self._generate_sid(ts)
        return {"x-dynapath-m-token": token}, sid

    @property
    def is_login(self) -> bool:
        return self._logined

    def _get(self, url: str, params: dict, headers: dict | None = None) -> str:
        logger.debug("GET %s params=%s", url, params)
        r = self._session.get(url, params=params, headers=headers or {})
        logger.debug("응답 status=%s body=%s", r.status_code, r.text[:500])
        return r.text

    def _post(self, url: str, data: dict, headers: dict | None = None) -> str:
        logger.debug("POST %s data=%s", url, data)
        r = self._session.post(url, data=data, headers=headers or {})
        logger.debug("응답 status=%s body=%s", r.status_code, r.text[:500])
        return r.text

    def __enc_password(self, password: str) -> str | bool:
        raw = self._post(API_ENDPOINTS["code"], {"code": "app.login.cphd"})
        j = json.loads(raw)
        if j["strResult"] == "SUCC" and j.get("app.login.cphd"):
            self._idx = j["app.login.cphd"]["idx"]
            key = j["app.login.cphd"]["key"]
            encrypt_key = key.encode("utf-8")
            iv = key[:16].encode("utf-8")
            cipher = AES.new(encrypt_key, AES.MODE_CBC, iv)
            padded_data = pad(password.encode("utf-8"), AES.block_size)
            return base64.b64encode(
                base64.b64encode(cipher.encrypt(padded_data))
            ).decode("utf-8")
        return False

    def login(self, user_id: str, password: str) -> bool:
        logger.info("Korail 로그인 시도: user_id=%s", user_id)
        self.korail_id = user_id
        self.korail_pw = password

        txt_input_flg = (
            "5" if EMAIL_REGEX.match(self.korail_id)
            else "4" if PHONE_NUMBER_REGEX.match(self.korail_id)
            else "2"
        )

        netfunnel_key = self._netfunnel.run()
        auth_headers, sid = self._get_auth_headers_and_sid(API_ENDPOINTS["login"])
        data = {
            "Device": self._device,
            "Version": self._version,
            "Key": self._key,
            "NetFunnelKey": netfunnel_key,
            "txtMemberNo": self.korail_id,
            "txtPwd": self.__enc_password(self.korail_pw),
            "txtInputFlg": txt_input_flg,
            "idx": self._idx,
        }
        if sid:
            data["Sid"] = sid

        raw = self._post(API_ENDPOINTS["login"], data, headers=auth_headers)
        j = json.loads(raw)

        if j["strResult"] == "SUCC" and j.get("strMbCrdNo"):
            self.membership_number = j["strMbCrdNo"]
            self.name = j["strCustNm"]
            self.email = j["strEmailAdr"]
            self.phone_number = j["strCpNo"]
            self._logined = True
            logger.info(
                "Korail 로그인 성공: name=%s membership=%s phone=%s",
                self.name, self.membership_number, self.phone_number,
            )
            return True

        self._logined = False
        logger.warning("Korail 로그인 실패")
        return False

    def logout(self) -> bool:
        self._session.get(API_ENDPOINTS["logout"])
        self._logined = False
        logger.info("Korail 로그아웃")
        return True

    def search_train(
        self,
        dep: str,
        arr: str,
        date: str | None = None,
        time: str | None = None,
        train_type: str = "109",
        passengers: list | None = None,
        include_no_seats: bool = False,
        include_waiting_list: bool = False,
    ) -> list[Train]:
        kst_now = datetime.now() + timedelta(hours=9)
        date = date or kst_now.strftime("%Y%m%d")
        time = time or kst_now.strftime("%H%M%S")
        passengers = passengers or [AdultPassenger()]
        passengers = Passenger.reduce(passengers)

        counts = {
            "adult": sum(p.count for p in passengers if isinstance(p, AdultPassenger)),
            "child": sum(p.count for p in passengers if isinstance(p, type(p) and p.typecode == "3" and p.discount_type == "000")),
            "senior": sum(p.count for p in passengers if p.discount_type == "131"),
            "disability1to3": sum(p.count for p in passengers if p.discount_type == "111"),
            "disability4to6": sum(p.count for p in passengers if p.discount_type == "112"),
        }
        total_child_toddler = sum(p.count for p in passengers if p.typecode == "3")

        logger.info("열차 검색: %s→%s %s %s", dep, arr, date, time)

        auth_headers, sid = self._get_auth_headers_and_sid(API_ENDPOINTS["search_schedule"])
        data = {
            "Device": self._device,
            "Version": self._version,
            "Sid": sid or "",
            "txtMenuId": "11",
            "radJobId": "1",
            "selGoTrain": train_type,
            "txtTrnGpCd": train_type,
            "txtGoStart": dep,
            "txtGoEnd": arr,
            "txtGoAbrdDt": date,
            "txtGoHour": time,
            "txtPsgFlg_1": counts["adult"],
            "txtPsgFlg_2": total_child_toddler,
            "txtPsgFlg_3": counts["senior"],
            "txtPsgFlg_4": counts["disability1to3"],
            "txtPsgFlg_5": counts["disability4to6"],
            "txtSeatAttCd_2": "000",
            "txtSeatAttCd_3": "000",
            "txtSeatAttCd_4": "015",
            "ebizCrossCheck": "N",
            "srtCheckYn": "N",
            "rtYn": "N",
            "adjStnScdlOfrFlg": "N",
            "mbCrdNo": self.membership_number,
        }

        raw = self._get(API_ENDPOINTS["search_schedule"], data, headers=auth_headers)
        trains = parse_trains(raw, include_no_seats=include_no_seats, include_waiting_list=include_waiting_list)
        logger.info("열차 검색 결과: %d편", len(trains))
        return trains

    def reserve(
        self,
        train: Train,
        passengers: list | None = None,
        option: str = ReserveOption.GENERAL_FIRST,
    ) -> Reservation:
        reserving_seat = train.has_seat() or train.wait_reserve_flag < 0
        if reserving_seat:
            is_special_seat = {
                ReserveOption.GENERAL_ONLY: False,
                ReserveOption.SPECIAL_ONLY: True,
                ReserveOption.GENERAL_FIRST: not train.has_general_seat(),
                ReserveOption.SPECIAL_FIRST: train.has_special_seat(),
            }[option]
        else:
            is_special_seat = {
                ReserveOption.GENERAL_ONLY: False,
                ReserveOption.SPECIAL_ONLY: True,
                ReserveOption.GENERAL_FIRST: False,
                ReserveOption.SPECIAL_FIRST: True,
            }[option]

        passengers = passengers or [AdultPassenger()]
        passengers = Passenger.reduce(passengers)
        cnt = sum(p.count for p in passengers)

        auth_headers, sid = self._get_auth_headers_and_sid(API_ENDPOINTS["reserve"])
        data = {
            "Device": self._device,
            "Version": self._version,
            "Key": self._key,
            "txtMenuId": "11",
            "txtJobId": "1101" if reserving_seat else "1102",
            "txtGdNo": "",
            "hidFreeFlg": "N",
            "txtTotPsgCnt": cnt,
            "txtSeatAttCd1": "000",
            "txtSeatAttCd2": "000",
            "txtSeatAttCd3": "000",
            "txtSeatAttCd4": "015",
            "txtSeatAttCd5": "000",
            "txtStndFlg": "N",
            "txtSrcarCnt": "0",
            "txtJrnyCnt": "1",
            "txtJrnySqno1": "001",
            "txtJrnyTpCd1": "11",
            "txtDptDt1": train.dep_date,
            "txtDptRsStnCd1": train.dep_code,
            "txtDptTm1": train.dep_time,
            "txtArvRsStnCd1": train.arr_code,
            "txtTrnNo1": train.train_no,
            "txtRunDt1": train.run_date,
            "txtTrnClsfCd1": train.train_type,
            "txtTrnGpCd1": train.train_group,
            "txtPsrmClCd1": "2" if is_special_seat else "1",
            "txtChgFlg1": "",
            "txtJrnySqno2": "", "txtJrnyTpCd2": "", "txtDptDt2": "",
            "txtDptRsStnCd2": "", "txtDptTm2": "", "txtArvRsStnCd2": "",
            "txtTrnNo2": "", "txtRunDt2": "", "txtTrnClsfCd2": "",
            "txtPsrmClCd2": "", "txtChgFlg2": "",
        }
        for i, psg in enumerate(passengers, 1):
            data.update(psg.get_dict(i))

        logger.info("예약 요청: train=%s option=%s", train.train_no, option)
        raw = self._get(API_ENDPOINTS["reserve"], data, headers=auth_headers)
        rsv_id = get_reservation_id(raw)
        reservation = self._get_reservation_by_id(rsv_id)
        if reservation:
            logger.info("예약 성공: %s", reservation)
            return reservation
        raise SoldOutError()

    def _get_reservation_by_id(self, rsv_id: str) -> Reservation | None:
        raw = self._get(API_ENDPOINTS["myreservationview"], {
            "Device": self._device, "Version": self._version, "Key": self._key,
        })
        reservations = parse_reservations(raw)
        for rsv in reservations:
            if rsv.rsv_id == rsv_id:
                seats, wct_no = self._ticket_info(rsv_id)
                rsv.tickets = seats
                rsv.wct_no = wct_no
                return rsv
        return None

    def get_reservations(self) -> list[Reservation]:
        logger.debug("예약 목록 조회")
        raw = self._get(API_ENDPOINTS["myreservationview"], {
            "Device": self._device, "Version": self._version, "Key": self._key,
        })
        reservations = parse_reservations(raw)
        for rsv in reservations:
            seats, wct_no = self._ticket_info(rsv.rsv_id)
            rsv.tickets = seats
            rsv.wct_no = wct_no
        return reservations

    def get_tickets(self) -> list[Ticket]:
        logger.debug("티켓 목록 조회")
        raw = self._get(API_ENDPOINTS["myticketlist"], {
            "Device": self._device,
            "Version": self._version,
            "Key": self._key,
            "txtDeviceId": "",
            "txtIndex": "1",
            "h_page_no": "1",
            "h_abrd_dt_from": "",
            "h_abrd_dt_to": "",
            "hiduserYn": "Y",
        })
        tickets = parse_tickets(raw)

        for ticket in tickets:
            seat_raw = self._get(API_ENDPOINTS["myticketseat"], {
                "Device": self._device,
                "Version": self._version,
                "Key": self._key,
                "h_orgtk_wct_no": ticket.sale_info1,
                "h_orgtk_ret_sale_dt": ticket.sale_info2,
                "h_orgtk_sale_sqno": ticket.sale_info3,
                "h_orgtk_ret_pwd": ticket.sale_info4,
            })
            seat_j = json.loads(seat_raw)
            try:
                check_result(seat_j)
                seat = (
                    seat_j.get("ticket_infos", {})
                    .get("ticket_info", [{}])[0]
                    .get("tk_seat_info", [{}])[0]
                )
                ticket.seat_no = seat.get("h_seat_no")
                ticket.seat_no_end = None
            except NoResultsError:
                pass
        return tickets

    def _ticket_info(self, rsv_id: str) -> tuple:
        raw = self._get(API_ENDPOINTS["myreservationlist"], {
            "Device": self._device, "Version": self._version,
            "Key": self._key, "hidPnrNo": rsv_id,
        })
        return parse_seats(raw)

    def ticket_info(self, rsv_id: str) -> tuple:
        return self._ticket_info(rsv_id)

    def pay_with_card(self, rsv: Reservation, card_info: dict) -> bool:
        """card_info 키: number, password, birthday, expire"""
        if not isinstance(rsv, Reservation):
            raise TypeError("rsv must be a Reservation instance")

        data = {
            "Device": self._device,
            "Version": self._version,
            "Key": self._key,
            "hidPnrNo": rsv.rsv_id,
            "hidWctNo": rsv.wct_no,
            "hidTmpJobSqno1": "000000",
            "hidTmpJobSqno2": "000000",
            "hidRsvChgNo": "000",
            "hidInrecmnsGridcnt": "1",
            "hidStlMnsSqno1": "1",
            "hidStlMnsCd1": "02",
            "hidMnsStlAmt1": str(rsv.price),
            "hidCrdInpWayCd1": "@",
            "hidStlCrCrdNo1": card_info["number"],
            "hidVanPwd1": card_info["password"],
            "hidCrdVlidTrm1": card_info["expire"],
            "hidIsmtMnthNum1": 0,
            "hidAthnDvCd1": "J" if len(card_info["birthday"]) == 6 else "S",
            "hidAthnVal1": card_info["birthday"],
            "hiduserYn": "Y",
        }

        raw = self._post(API_ENDPOINTS["pay"], data)
        j = json.loads(raw)
        check_result(j)
        logger.info("Korail 카드 결제 성공: rsv_id=%s", rsv.rsv_id)
        return True

    def cancel(self, rsv: Reservation) -> bool:
        if not isinstance(rsv, Reservation):
            raise TypeError("rsv must be a Reservation instance")
        data = {
            "Device": self._device, "Version": self._version, "Key": self._key,
            "txtPnrNo": rsv.rsv_id,
            "txtJrnySqno": rsv.journey_no,
            "txtJrnyCnt": rsv.journey_cnt,
            "hidRsvChgNo": rsv.rsv_chg_no,
        }
        raw = self._post(API_ENDPOINTS["cancel"], data)
        j = json.loads(raw)
        check_result(j)
        logger.info("예약 취소: %s", rsv.rsv_id)
        return True

    def refund(self, ticket: Ticket) -> bool:
        data = {
            "Device": self._device, "Version": self._version, "Key": self._key,
            "txtPrnNo": ticket.pnr_no,
            "h_orgtk_sale_dt": ticket.sale_info2,
            "h_orgtk_sale_wct_no": ticket.sale_info1,
            "h_orgtk_sale_sqno": ticket.sale_info3,
            "h_orgtk_ret_pwd": ticket.sale_info4,
            "h_mlg_stl": "N",
            "tk_ret_tms_dv_cd": "21",
            "trnNo": ticket.train_no,
            "pbpAcepTgtFlg": "N",
            "latitude": "",
            "longitude": "",
        }
        raw = self._post(API_ENDPOINTS["refund"], data)
        j = json.loads(raw)
        check_result(j)
        logger.info("Korail 환불 성공: %s", ticket.pnr_no)
        return True
