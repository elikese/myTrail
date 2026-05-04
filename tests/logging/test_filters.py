"""SensitiveDataFilter 회귀 테스트.

원래 필터는 모든 record.args를 str()로 바꿔서 %d/%.2f 같은 숫자 포매터가 깨지고,
float 문자열이 카드번호 패턴에 오탐되는 버그가 있었음. 아래 테스트가 그 회귀 방지.
"""

import io
import logging

import pytest


@pytest.fixture
def captured_logger():
    """SensitiveDataFilter가 적용된 임시 로거."""
    from srtgo.logging.filters import SensitiveDataFilter

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.addFilter(SensitiveDataFilter())

    logger = logging.getLogger("srtgo._test_sensitive_filter")
    logger.handlers = [handler]
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    yield logger, stream

    logger.handlers = []


def test_int_arg_with_d_format_does_not_break(captured_logger):
    logger, stream = captured_logger
    logger.info("count: %d", 5)
    assert "count: 5" in stream.getvalue()


def test_float_arg_with_f_format_does_not_break(captured_logger):
    logger, stream = captured_logger
    logger.debug("sleep: %.2fs", 0.7435710536546112)
    out = stream.getvalue()
    assert "sleep: 0.74s" in out
    # float이 카드번호로 오탐되지 않아야 함
    assert "****" not in out


def test_card_number_in_message_is_masked(captured_logger):
    logger, stream = captured_logger
    logger.info("payment: 1234-5678-9012-3456")
    assert "1234-****-****-3456" in stream.getvalue()


def test_card_number_in_string_arg_is_masked(captured_logger):
    logger, stream = captured_logger
    logger.info("card=%s", "1234567890123456")
    assert "1234-****-****-3456" in stream.getvalue()


def test_password_in_message_is_masked(captured_logger):
    logger, stream = captured_logger
    logger.info("login: password=secretpw123")
    out = stream.getvalue()
    assert "secretpw123" not in out
    assert "password=***" in out


def test_multiple_args_mixed_types(captured_logger):
    logger, stream = captured_logger
    logger.debug("attempt #%d (elapsed: %.0fs) for %s", 147, 239.5, "user1")
    out = stream.getvalue()
    assert "attempt #147" in out
    assert "elapsed: 240s" in out  # %.0f rounds
    assert "for user1" in out
