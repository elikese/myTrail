"""srtgo.bot.tools — 도구 스키마 + DISPATCH 정합성."""


def test_dispatch_matches_tools():
    """DISPATCH 키와 TOOLS 이름 집합이 정확히 일치 (드리프트 가드)."""
    from srtgo.bot import tools
    assert set(tools.DISPATCH) == {t["name"] for t in tools.TOOLS}


def test_expected_tool_set():
    from srtgo.bot import tools
    assert set(tools.DISPATCH) == {
        "search_trains", "start_booking", "get_booking_progress", "cancel_booking",
        "list_cards", "delete_card", "pay_pending_reservation", "get_account_status",
        "start_card_registration", "start_credential_setup",
    }


def test_all_schemas_closed_objects():
    from srtgo.bot import tools
    for t in tools.TOOLS:
        schema = t["input_schema"]
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False


def test_each_tool_has_required_fields():
    from srtgo.bot import tools
    for t in tools.TOOLS:
        assert {"name", "description", "input_schema"} <= set(t)
        assert t["description"].strip()


def test_dispatch_values_callable():
    from srtgo.bot import tools
    assert all(callable(fn) for fn in tools.DISPATCH.values())


def test_model_is_haiku():
    from srtgo.bot import tools
    assert tools.MODEL == "claude-haiku-4-5-20251001"


def test_system_prompt_formats_today():
    from srtgo.bot import tools
    assert "{today}" in tools.SYSTEM_PROMPT
    out = tools.SYSTEM_PROMPT.format(today="2026-06-01")
    assert "2026-06-01" in out


def test_search_trains_schema_requires_core_fields():
    from srtgo.bot import tools
    schema = next(t["input_schema"] for t in tools.TOOLS if t["name"] == "search_trains")
    assert set(schema["required"]) == {"rail", "dep", "arr", "date", "time"}


def test_delete_card_requires_card_id():
    from srtgo.bot import tools
    schema = next(t["input_schema"] for t in tools.TOOLS if t["name"] == "delete_card")
    assert schema["required"] == ["card_id"]
