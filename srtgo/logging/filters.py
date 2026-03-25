import logging
import re

CARD_NUMBER_PATTERN = re.compile(r"\d{4}-?\d{4}-?\d{4}-?\d{4}")
PASSWORD_PATTERN = re.compile(
    r"(password|pw|passwd|hmpgPwdCphd|txtPwd|vanPwd\d*|hidVanPwd\d*)=['\"]?[^\s'\"&]+",
    re.IGNORECASE,
)


class SensitiveDataFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._mask(str(record.msg))
        if record.args:
            record.args = tuple(self._mask(str(a)) for a in record.args)
        return True

    def _mask(self, text: str) -> str:
        text = CARD_NUMBER_PATTERN.sub(
            lambda m: m.group()[:4] + "-****-****-" + m.group()[-4:], text
        )
        text = PASSWORD_PATTERN.sub(
            lambda m: m.group().split("=")[0] + "=***", text
        )
        return text
