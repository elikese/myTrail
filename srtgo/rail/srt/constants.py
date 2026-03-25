import re

# --- 정규식 ---
EMAIL_REGEX = re.compile(r"[^@]+@[^@]+\.[^@]+")
PHONE_NUMBER_REGEX = re.compile(r"(\d{3})-(\d{3,4})-(\d{4})")

# --- HTTP ---
SRT_MOBILE = "https://app.srail.or.kr:443"

API_ENDPOINTS = {
    "main": f"{SRT_MOBILE}/main/main.do",
    "login": f"{SRT_MOBILE}/apb/selectListApb01080_n.do",
    "logout": f"{SRT_MOBILE}/login/loginOut.do",
    "search_schedule": f"{SRT_MOBILE}/ara/selectListAra10007_n.do",
    "reserve": f"{SRT_MOBILE}/arc/selectListArc05013_n.do",
    "tickets": f"{SRT_MOBILE}/atc/selectListAtc14016_n.do",
    "ticket_info": f"{SRT_MOBILE}/ard/selectListArd02019_n.do",
    "cancel": f"{SRT_MOBILE}/ard/selectListArd02045_n.do",
    "standby_option": f"{SRT_MOBILE}/ata/selectListAta01135_n.do",
    "payment": f"{SRT_MOBILE}/ata/selectListAta09036_n.do",
    "reserve_info": f"{SRT_MOBILE}/atc/getListAtc14087.do",
    "reserve_info_referer": f"{SRT_MOBILE}/common/ATC/ATC0201L/view.do?pnrNo=",
    "refund": f"{SRT_MOBILE}/atc/selectListAtc02063_n.do",
}

USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 15; SM-S912N Build/AP3A.240905.015.A2; wv) AppleWebKit/537.36"
    "(KHTML, like Gecko) Version/4.0 Chrome/136.0.7103.125 Mobile Safari/537.36SRT-APP-Android V.2.0.38"
)

DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json",
}

# --- 예약 job ID ---
RESERVE_JOBID = {
    "PERSONAL": "1101",
    "STANDBY": "1102",
}

# --- 역 코드 ---
STATION_CODE = {
    "수서": "0551",
    "동탄": "0552",
    "평택지제": "0553",
    "경주": "0508",
    "곡성": "0049",
    "공주": "0514",
    "광주송정": "0036",
    "구례구": "0050",
    "김천(구미)": "0507",
    "나주": "0037",
    "남원": "0048",
    "대전": "0010",
    "동대구": "0015",
    "마산": "0059",
    "목포": "0041",
    "밀양": "0017",
    "부산": "0020",
    "서대구": "0506",
    "순천": "0051",
    "여수EXPO": "0053",
    "여천": "0139",
    "오송": "0297",
    "울산(통도사)": "0509",
    "익산": "0030",
    "전주": "0045",
    "정읍": "0033",
    "진영": "0056",
    "진주": "0063",
    "창원": "0057",
    "창원중앙": "0512",
    "천안아산": "0502",
    "포항": "0515",
}

STATION_NAME = {code: name for name, code in STATION_CODE.items()}

# --- 열차 이름 코드 ---
TRAIN_NAME = {
    "00": "KTX",
    "02": "무궁화",
    "03": "통근열차",
    "04": "누리로",
    "05": "전체",
    "07": "KTX-산천",
    "08": "ITX-새마을",
    "09": "ITX-청춘",
    "10": "KTX-산천",
    "17": "SRT",
    "18": "ITX-마음",
}

# --- 창가석 코드 ---
WINDOW_SEAT = {None: "000", True: "012", False: "013"}

# --- NetFunnel 설정 ---
class NetFunnelConfig:
    URL_HOST = "nf.letskorail.com"
    WAIT_STATUS_PASS = "200"
    WAIT_STATUS_FAIL = "201"
    ALREADY_COMPLETED = "502"
    CACHE_TTL = 48  # seconds

    OP_CODE = {
        "getTidchkEnter": "5101",
        "chkEnter": "5002",
        "setComplete": "5004",
    }

    HEADERS = {
        "Host": "nf.letskorail.com",
        "Connection": "keep-alive",
        "Pragma": "no-cache",
        "Cache-Control": "no-cache",
        "sec-ch-ua-platform": "Android",
        "User-Agent": USER_AGENT,
        "sec-ch-ua": '"Chromium";v="136", "Android WebView";v="136", "Not=A/Brand";v="99"',
        "sec-ch-ua-mobile": "?1",
        "Accept": "*/*",
        "X-Requested-With": "kr.co.srail.newapp",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-Mode": "no-cors",
        "Sec-Fetch-Dest": "script",
        "Sec-Fetch-Storage-Access": "active",
        "Referer": "https://app.srail.or.kr/",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "en-US,en;q=0.9,ko-KR;q=0.8,ko;q=0.7",
    }
