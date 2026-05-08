"""SRT 역명 별칭(alias) 매핑 검증.

자연어 입력("울산", "여수", "김천")이 정식 STATION_CODE 키
("울산(통도사)", "여수EXPO", "김천(구미)")로 정규화되는지 검증한다.
"""

from srtgo.rail.srt.constants import (
    STATION_ALIAS, STATION_CODE, normalize_station,
)


def test_alias_targets_exist_in_station_code():
    """모든 별칭의 매핑 대상은 STATION_CODE의 정식 키여야 한다."""
    for alias, target in STATION_ALIAS.items():
        assert target in STATION_CODE, (
            f'별칭 {alias!r} → {target!r} (STATION_CODE에 없음)'
        )


def test_alias_keys_dont_shadow_canonical_names():
    """별칭 키는 정식 역명과 겹치면 안 된다 (불필요·혼란 방지)."""
    for alias in STATION_ALIAS:
        assert alias not in STATION_CODE, (
            f'{alias!r}는 이미 정식 역명 — 별칭 불필요'
        )


def test_normalize_station_maps_known_alias():
    assert normalize_station("울산") == "울산(통도사)"
    assert normalize_station("통도사") == "울산(통도사)"
    assert normalize_station("여수") == "여수EXPO"
    assert normalize_station("김천") == "김천(구미)"
    assert normalize_station("구미") == "김천(구미)"
    assert normalize_station("광주") == "광주송정"


def test_normalize_station_passthrough_for_canonical():
    """정식 역명은 그대로 통과."""
    assert normalize_station("부산") == "부산"
    assert normalize_station("수서") == "수서"
    assert normalize_station("울산(통도사)") == "울산(통도사)"
    assert normalize_station("동대구") == "동대구"


def test_normalize_station_passthrough_for_unknown():
    """모르는 역명은 그대로 — 검증은 search_train의 STATION_CODE 체크에 위임."""
    assert normalize_station("서울") == "서울"
    assert normalize_station("없는역") == "없는역"
