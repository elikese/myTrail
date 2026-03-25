# keyring 직접 호출은 이 파일에서만 허용
import secrets

import keyring
import keyring.errors


def _configure_keyring_backend() -> None:
    """헤드리스 환경(Ubuntu/Termux proot)에서 keyrings.alt로 자동 폴백."""
    try:
        keyring.set_password("_srtgo_probe", "_k", "_v")
        result = keyring.get_password("_srtgo_probe", "_k")
        if result == "_v":
            try:
                keyring.delete_password("_srtgo_probe", "_k")
            except Exception:
                pass
            return  # 정상 동작하는 백엔드 있음
    except Exception:
        pass

    # GUI 키링 없음 → keyrings.alt 파일 기반으로 폴백
    try:
        from keyrings.alt.file import PlaintextKeyring
        keyring.set_keyring(PlaintextKeyring())
    except ImportError:
        pass  # keyrings.alt 미설치 시 keyring 오류는 런타임에 발생


_configure_keyring_backend()


def get_setting(service: str, key: str) -> str | None:
    return keyring.get_password(service, key)


def set_setting(service: str, key: str, value: str) -> None:
    keyring.set_password(service, key, value)


def delete_setting(service: str, key: str) -> None:
    try:
        keyring.delete_password(service, key)
    except keyring.errors.PasswordDeleteError:
        pass


# --- 기기 식별자 ---

def get_or_create_device_id(rail_type: str) -> str:
    device_id = get_setting(rail_type, "device_id")
    if not device_id:
        device_id = secrets.token_hex(8)
        set_setting(rail_type, "device_id", device_id)
    return device_id


# --- Rail 자격증명 ---

def get_rail_credential(rail_type: str) -> tuple[str | None, str | None]:
    return get_setting(rail_type, "id"), get_setting(rail_type, "pass")


def set_rail_credential(rail_type: str, user_id: str, password: str) -> None:
    set_setting(rail_type, "id", user_id)
    set_setting(rail_type, "pass", password)
    set_setting(rail_type, "ok", "1")


def delete_rail_credential(rail_type: str) -> None:
    delete_setting(rail_type, "ok")


def is_rail_credential_set(rail_type: str) -> bool:
    return bool(get_setting(rail_type, "ok"))


# --- 역 설정 ---

def get_station_setting(rail_type: str) -> str | None:
    return get_setting(rail_type, "station")


def set_station_setting(rail_type: str, stations_csv: str) -> None:
    set_setting(rail_type, "station", stations_csv)


# --- 예매 옵션 ---

def get_options() -> list[str]:
    options = get_setting("SRT", "options") or ""
    return options.split(",") if options else []


def set_options(options: list[str]) -> None:
    set_setting("SRT", "options", ",".join(options))


# --- 예매 기본값 (출발/도착/날짜/시간/승객수) ---

def get_reserve_defaults(rail_type: str) -> dict:
    keys = ["departure", "arrival", "date", "time", "adult",
            "child", "senior", "disability1to3", "disability4to6"]
    return {k: get_setting(rail_type, k) for k in keys}


def set_reserve_default(rail_type: str, key: str, value: str) -> None:
    set_setting(rail_type, key, value)


# --- 카드 정보 ---

def get_card_info() -> dict | None:
    if not get_setting("card", "ok"):
        return None
    return {
        "number": get_setting("card", "number"),
        "password": get_setting("card", "password"),
        "birthday": get_setting("card", "birthday"),
        "expire": get_setting("card", "expire"),
    }


def set_card_info(number: str, password: str, birthday: str, expire: str) -> None:
    set_setting("card", "number", number)
    set_setting("card", "password", password)
    set_setting("card", "birthday", birthday)
    set_setting("card", "expire", expire)
    set_setting("card", "ok", "1")


# --- 텔레그램 설정 ---

def get_telegram_config() -> tuple[str | None, str | None]:
    return get_setting("telegram", "token"), get_setting("telegram", "chat_id")


def set_telegram_config(token: str, chat_id: str) -> None:
    set_setting("telegram", "ok", "1")
    set_setting("telegram", "token", token)
    set_setting("telegram", "chat_id", chat_id)


def delete_telegram_config() -> None:
    delete_setting("telegram", "ok")
