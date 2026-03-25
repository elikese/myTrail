"""SRT HTTP 클라이언트 — AbstractRail 구현체."""

import logging
import re
import time
from datetime import datetime

try:
    import curl_cffi
    HAS_CURL_CFFI = True
except ImportError:
    import requests
    HAS_CURL_CFFI = False

from ..base import AbstractRail
from .constants import (
    API_ENDPOINTS, DEFAULT_HEADERS, EMAIL_REGEX, PHONE_NUMBER_REGEX,
    RESERVE_JOBID, STATION_CODE, NetFunnelConfig,
)
from .models import (
    Adult, Passenger, SeatType,
    SRTError, SRTLoginError, SRTNetFunnelError,
    SRTNotLoggedInError, SRTResponseError, SRTTrain, SRTReservation,
)
from .parser import (
    check_success, get_full_json, get_message, get_reservation_number,
    parse_response, parse_tickets, parse_reservations, parse_trains,
)

logger = logging.getLogger(__name__)


class NetFunnelHelper:
    def __init__(self, debug: bool = False):
        if HAS_CURL_CFFI:
            self._session = curl_cffi.Session(impersonate="chrome")
        else:
            self._session = requests.session()
        self._session.headers.update(NetFunnelConfig.HEADERS)
        self._cached_key = None
        self._last_fetch_time = 0
        self.debug = debug

    def run(self) -> str:
        current_time = time.time()
        if self._is_cache_valid(current_time):
            return self._cached_key
        try:
            status, self._cached_key, nwait, ip = self._start()
            self._last_fetch_time = current_time
            while status == NetFunnelConfig.WAIT_STATUS_FAIL:
                logger.debug("NetFunnel 대기: %s명", nwait)
                time.sleep(1)
                status, self._cached_key, nwait, ip = self._check(ip)
            status, *_ = self._complete(ip)
            if status in (NetFunnelConfig.WAIT_STATUS_PASS, NetFunnelConfig.ALREADY_COMPLETED):
                return self._cached_key
            self.clear()
            raise SRTNetFunnelError("Failed to complete NetFunnel")
        except SRTNetFunnelError:
            raise
        except Exception as ex:
            self.clear()
            raise SRTNetFunnelError(str(ex))

    def clear(self):
        self._cached_key = None
        self._last_fetch_time = 0

    def _start(self):
        return self._make_request("getTidchkEnter")

    def _check(self, ip: str | None = None):
        return self._make_request("chkEnter", ip)

    def _complete(self, ip: str | None = None):
        return self._make_request("setComplete", ip)

    def _make_request(self, opcode: str, ip: str | None = None):
        url = f"https://{ip or NetFunnelConfig.URL_HOST}/ts.wseq"
        params = self._build_params(NetFunnelConfig.OP_CODE[opcode])
        r = self._session.get(url, params=params, verify=False)
        logger.debug("NetFunnel %s: %s", opcode, r.text[:100])
        response = self._parse(r.text)
        return map(response.get, ("status", "key", "nwait", "ip"))

    def _build_params(self, opcode: str) -> dict:
        params = {
            "opcode": opcode,
            "nfid": "0",
            "prefix": f"NetFunnel.gRtype={opcode};",
            "js": "true",
            str(int(time.time() * 1000)): "",
        }
        if opcode in (NetFunnelConfig.OP_CODE["getTidchkEnter"], NetFunnelConfig.OP_CODE["chkEnter"]):
            params.update({"sid": "service_1", "aid": "act_10"})
            if opcode == NetFunnelConfig.OP_CODE["chkEnter"]:
                params.update({"key": self._cached_key, "ttl": "1"})
        elif opcode == NetFunnelConfig.OP_CODE["setComplete"]:
            params["key"] = self._cached_key
        return params

    def _parse(self, response: str) -> dict:
        result_match = re.search(r"NetFunnel\.gControl\.result='([^']+)'", response)
        if not result_match:
            raise SRTNetFunnelError("Failed to parse NetFunnel response")
        code, status, params_str = result_match.group(1).split(":", 2)
        if not params_str:
            raise SRTNetFunnelError("Failed to parse NetFunnel response")
        params = dict(
            param.split("=", 1) for param in params_str.split("&") if "=" in param
        )
        params.update({"code": code, "status": status})
        return params

    def _is_cache_valid(self, current_time: float) -> bool:
        return bool(
            self._cached_key
            and (current_time - self._last_fetch_time) < NetFunnelConfig.CACHE_TTL
        )


class SRT(AbstractRail):
    """SRT API 클라이언트."""

    def __init__(self, srt_id: str, srt_pw: str, auto_login: bool = True, verbose: bool = False):
        if HAS_CURL_CFFI:
            self._session = curl_cffi.Session(impersonate="chrome")
        else:
            self._session = requests.session()
        self._session.headers.update(DEFAULT_HEADERS)
        self._netfunnel = NetFunnelHelper(debug=verbose)
        self.srt_id = srt_id
        self.srt_pw = srt_pw
        self._is_login = False
        self.membership_number = None
        self.membership_name = None
        self.phone_number = None

        if auto_login:
            self.login(srt_id, srt_pw)

    @property
    def is_login(self) -> bool:
        return self._is_login

    def _post(self, url: str, data: dict) -> str:
        logger.debug("POST %s params=%s", url, data)
        r = self._session.post(url=url, data=data)
        logger.debug("응답 status=%s body=%s", r.status_code, r.text[:500])
        return r.text

    def login(self, user_id: str, password: str) -> bool:
        logger.info("SRT 로그인 시도: user_id=%s", user_id)
        login_type = (
            "2" if EMAIL_REGEX.match(user_id)
            else ("3" if PHONE_NUMBER_REGEX.match(user_id) else "1")
        )
        if login_type == "3":
            user_id = re.sub("-", "", user_id)

        data = {
            "auto": "Y",
            "check": "Y",
            "page": "menu",
            "deviceKey": "-",
            "customerYn": "",
            "login_referer": API_ENDPOINTS["main"],
            "srchDvCd": login_type,
            "srchDvNm": user_id,
            "hmpgPwdCphd": password,
        }

        raw = self._post(API_ENDPOINTS["login"], data)

        if "존재하지않는 회원입니다" in raw:
            raise SRTLoginError(get_full_json(raw)["MSG"])
        if "비밀번호 오류" in raw:
            raise SRTLoginError(get_full_json(raw)["MSG"])
        if "Your IP Address Blocked" in raw:
            raise SRTLoginError(raw.strip())

        self._is_login = True
        user_info = get_full_json(raw)["userMap"]
        self.membership_number = user_info["MB_CRD_NO"]
        self.membership_name = user_info["CUST_NM"]
        self.phone_number = user_info["MBL_PHONE"]
        logger.info(
            "SRT 로그인 성공: name=%s membership=%s phone=%s",
            self.membership_name, self.membership_number, self.phone_number,
        )
        return True

    def logout(self) -> bool:
        if not self._is_login:
            return True
        raw = self._post(API_ENDPOINTS["logout"], {})
        self._is_login = False
        self.membership_number = None
        logger.info("SRT 로그아웃")
        return True

    def search_train(
        self,
        dep: str,
        arr: str,
        date: str | None = None,
        time: str | None = None,
        time_limit: str | None = None,
        passengers: list | None = None,
        available_only: bool = True,
        include_no_seats: bool = False,
    ) -> list[SRTTrain]:
        if dep not in STATION_CODE or arr not in STATION_CODE:
            raise ValueError(f'Invalid station: "{dep}" or "{arr}"')

        now = datetime.now()
        today = now.strftime("%Y%m%d")
        date = date or today

        if date < today:
            raise ValueError("Date cannot be before today")

        time = (
            max(time or "000000", now.strftime("%H%M%S"))
            if date == today
            else time or "000000"
        )

        passengers = Passenger.combine(passengers or [Adult()])
        logger.info("열차 검색: %s→%s %s %s", dep, arr, date, time)

        data = {
            "chtnDvCd": "1",
            "dptDt": date,
            "dptTm": time,
            "dptDt1": date,
            "dptTm1": time[:2] + "0000",
            "dptRsStnCd": STATION_CODE[dep],
            "arvRsStnCd": STATION_CODE[arr],
            "stlbTrnClsfCd": "05",
            "trnGpCd": 109,
            "trnNo": "",
            "psgNum": str(Passenger.total_count(passengers)),
            "seatAttCd": "015",
            "arriveTime": "N",
            "tkDptDt": "",
            "tkDptTm": "",
            "tkTrnNo": "",
            "tkTripChgFlg": "",
            "dlayTnumAplFlg": "Y",
            "netfunnelKey": self._netfunnel.run(),
        }

        raw = self._post(API_ENDPOINTS["search_schedule"], data)
        trains = parse_trains(raw)

        if time_limit:
            trains = [t for t in trains if t.dep_time <= time_limit]
        if available_only and not include_no_seats:
            trains = [t for t in trains if t.seat_available()]

        logger.info("열차 검색 결과: %d편", len(trains))
        return trains

    def reserve(
        self,
        train: SRTTrain,
        passengers: list | None = None,
        option: SeatType = SeatType.GENERAL_FIRST,
        window_seat: bool | None = None,
    ) -> SRTReservation:
        if not train.seat_available() and train.reserve_standby_available():
            reservation = self.reserve_standby(train, passengers, option=option, mblPhone=self.phone_number)
            if self.phone_number:
                agree_class_change = option in (SeatType.SPECIAL_FIRST, SeatType.GENERAL_FIRST)
                self.reserve_standby_option_settings(
                    reservation,
                    isAgreeSMS=True,
                    isAgreeClassChange=agree_class_change,
                    telNo=self.phone_number,
                )
            return reservation
        return self._reserve(RESERVE_JOBID["PERSONAL"], train, passengers, option, window_seat=window_seat)

    def reserve_standby(
        self,
        train: SRTTrain,
        passengers: list | None = None,
        option: SeatType = SeatType.GENERAL_FIRST,
        mblPhone: str | None = None,
    ) -> SRTReservation:
        if option == SeatType.SPECIAL_FIRST:
            option = SeatType.SPECIAL_ONLY
        elif option == SeatType.GENERAL_FIRST:
            option = SeatType.GENERAL_ONLY
        return self._reserve(RESERVE_JOBID["STANDBY"], train, passengers, option, mblPhone=mblPhone)

    def _reserve(
        self,
        jobid: str,
        train: SRTTrain,
        passengers: list | None = None,
        option: SeatType = SeatType.GENERAL_FIRST,
        mblPhone: str | None = None,
        window_seat: bool | None = None,
    ) -> SRTReservation:
        if not self._is_login:
            raise SRTNotLoggedInError()
        if not isinstance(train, SRTTrain):
            raise TypeError('"train" must be SRTTrain instance')
        if train.train_name != "SRT":
            raise ValueError(f'Expected "SRT" train, got {train.train_name}')

        passengers = Passenger.combine(passengers or [Adult()])
        is_special_seat = {
            SeatType.GENERAL_ONLY: False,
            SeatType.SPECIAL_ONLY: True,
            SeatType.GENERAL_FIRST: not train.general_seat_available(),
            SeatType.SPECIAL_FIRST: train.special_seat_available(),
        }[option]

        data = {
            "jobId": jobid,
            "jrnyCnt": "1",
            "jrnyTpCd": "11",
            "jrnySqno1": "001",
            "stndFlg": "N",
            "trnGpCd1": "300",
            "trnGpCd": "109",
            "grpDv": "0",
            "rtnDv": "0",
            "stlbTrnClsfCd1": train.train_code,
            "dptRsStnCd1": train.dep_station_code,
            "dptRsStnCdNm1": train.dep_station_name,
            "arvRsStnCd1": train.arr_station_code,
            "arvRsStnCdNm1": train.arr_station_name,
            "dptDt1": train.dep_date,
            "dptTm1": train.dep_time,
            "arvTm1": train.arr_time,
            "trnNo1": f"{int(train.train_number):05d}",
            "runDt1": train.dep_date,
            "dptStnConsOrdr1": train.dep_station_constitution_order,
            "arvStnConsOrdr1": train.arr_station_constitution_order,
            "dptStnRunOrdr1": train.dep_station_run_order,
            "arvStnRunOrdr1": train.arr_station_run_order,
            "mblPhone": mblPhone,
            "netfunnelKey": self._netfunnel.run(),
        }
        if jobid == RESERVE_JOBID["PERSONAL"]:
            data["reserveType"] = "11"
        data.update(Passenger.get_passenger_dict(passengers, special_seat=is_special_seat, window_seat=window_seat))

        logger.info("예약 요청: train=%s option=%s", train.train_number, option)
        raw = self._post(API_ENDPOINTS["reserve"], data)
        reservation_number = get_reservation_number(raw)

        for rsv in self.get_reservations():
            if rsv.reservation_number == reservation_number:
                logger.info("예약 성공: %s", rsv)
                return rsv
        raise SRTError("Ticket not found: check reservation status")

    def reserve_standby_option_settings(
        self,
        reservation: SRTReservation | int,
        isAgreeSMS: bool,
        isAgreeClassChange: bool,
        telNo: str | None = None,
    ) -> bool:
        if not self._is_login:
            raise SRTNotLoggedInError()
        reservation_number = getattr(reservation, "reservation_number", reservation)
        data = {
            "pnrNo": reservation_number,
            "psrmClChgFlg": "Y" if isAgreeClassChange else "N",
            "smsSndFlg": "Y" if isAgreeSMS else "N",
            "telNo": telNo if isAgreeSMS else "",
        }
        raw = self._post(API_ENDPOINTS["standby_option"], data)
        return True

    def get_reservations(self, paid_only: bool = False) -> list[SRTReservation]:
        if not self._is_login:
            raise SRTNotLoggedInError()
        logger.debug("예약 목록 조회")
        raw = self._post(API_ENDPOINTS["tickets"], {"pageNo": "0"})
        reservations = parse_reservations(raw, self.ticket_info)
        if paid_only:
            reservations = [r for r in reservations if r.paid]
        return reservations

    def get_tickets(self) -> list[SRTReservation]:
        """결제 완료된 예약 반환 (AbstractRail 인터페이스)."""
        return self.get_reservations(paid_only=True)

    def ticket_info(self, reservation: SRTReservation | int | str) -> list:
        if not self._is_login:
            raise SRTNotLoggedInError()
        reservation_number = getattr(reservation, "reservation_number", reservation)
        raw = self._post(
            API_ENDPOINTS["ticket_info"],
            {"pnrNo": reservation_number, "jrnySqno": "1"},
        )
        return parse_tickets(raw)

    def cancel(self, reservation: SRTReservation | int) -> bool:
        if not self._is_login:
            raise SRTNotLoggedInError()
        reservation_number = getattr(reservation, "reservation_number", reservation)
        data = {"pnrNo": reservation_number, "jrnyCnt": "1", "rsvChgTno": "0"}
        raw = self._post(API_ENDPOINTS["cancel"], data)
        status = parse_response(raw)
        if not check_success(status):
            raise SRTResponseError(get_message(status))
        logger.info("예약 취소: %s", reservation_number)
        return True

    def pay_with_card(self, reservation: SRTReservation, card_info: dict) -> bool:
        """card_info 키: number, password, birthday, expire"""
        if not self._is_login:
            raise SRTNotLoggedInError()

        number = card_info["number"]
        password = card_info["password"]
        birthday = card_info["birthday"]
        expire = card_info["expire"]
        card_type = "J" if len(birthday) == 6 else "S"

        data = {
            "stlDmnDt": datetime.now().strftime("%Y%m%d"),
            "mbCrdNo": self.membership_number,
            "stlMnsSqno1": "1",
            "ststlGridcnt": "1",
            "totNewStlAmt": reservation.total_cost,
            "athnDvCd1": card_type,
            "vanPwd1": password,
            "crdVlidTrm1": expire,
            "stlMnsCd1": "02",
            "rsvChgTno": "0",
            "chgMcs": "0",
            "ismtMnthNum1": 0,
            "ctlDvCd": "3102",
            "cgPsId": "korail",
            "pnrNo": reservation.reservation_number,
            "totPrnb": reservation.seat_count,
            "mnsStlAmt1": reservation.total_cost,
            "crdInpWayCd1": "@",
            "athnVal1": birthday,
            "stlCrCrdNo1": number,
            "jrnyCnt": "1",
            "strJobId": "3102",
            "inrecmnsGridcnt": "1",
            "dptTm": reservation.dep_time,
            "arvTm": reservation.arr_time,
            "dptStnConsOrdr2": "000000",
            "arvStnConsOrdr2": "000000",
            "trnGpCd": "300",
            "pageNo": "-",
            "rowCnt": "-",
            "pageUrl": "",
        }

        raw = self._post(API_ENDPOINTS["payment"], data)
        j = get_full_json(raw)
        if j["outDataSets"]["dsOutput0"][0]["strResult"] == "FAIL":
            raise SRTResponseError(j["outDataSets"]["dsOutput0"][0]["msgTxt"])
        logger.info("SRT 카드 결제 성공: pnrNo=%s", reservation.reservation_number)
        return True

    def reserve_info(self, reservation: SRTReservation) -> dict:
        referer = API_ENDPOINTS["reserve_info_referer"] + reservation.reservation_number
        self._session.headers.update({"Referer": referer})
        raw = self._post(API_ENDPOINTS["reserve_info"], {})
        j = get_full_json(raw)
        if j.get("ErrorCode") == "0" and j.get("ErrorMsg") == "":
            return j.get("outDataSets").get("dsOutput1")[0]
        raise SRTResponseError(j.get("ErrorMsg"))

    def refund(self, reservation: SRTReservation) -> bool:
        info = self.reserve_info(reservation)
        data = {
            "pnr_no": info.get("pnrNo"),
            "cnc_dmn_cont": "승차권 환불로 취소",
            "saleDt": info.get("ogtkSaleDt"),
            "saleWctNo": info.get("ogtkSaleWctNo"),
            "saleSqno": info.get("ogtkSaleSqno"),
            "tkRetPwd": info.get("ogtkRetPwd"),
            "psgNm": info.get("buyPsNm"),
        }
        raw = self._post(API_ENDPOINTS["refund"], data)
        status = parse_response(raw)
        if not check_success(status):
            raise SRTResponseError(get_message(status))
        logger.info("SRT 환불 성공: %s", reservation.reservation_number)
        return True

    def clear(self):
        logger.debug("NetFunnel 캐시 초기화")
        self._netfunnel.clear()
