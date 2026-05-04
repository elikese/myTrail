import logging
import re

CARD_NUMBER_PATTERN = re.compile(r"\d{4}-?\d{4}-?\d{4}-?\d{4}")
PASSWORD_PATTERN = re.compile(
    r"(password|pw|passwd|hmpgPwdCphd|txtPwd|vanPwd\d*|hidVanPwd\d*)=['\"]?[^\s'\"&]+",
    re.IGNORECASE,
)


class SensitiveDataFilter(logging.Filter):
    """카드번호·비밀번호 패턴을 ****로 마스킹.

    args를 stringify하지 않고 메시지 렌더 후 결과 문자열에만 마스킹을 적용한다.
    이렇게 해야 %d/%f 같은 숫자 포매터가 깨지지 않고, float 표현이 우연히
    16자리 숫자처럼 보여 카드번호로 오인되는 일도 막을 수 있다.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            rendered = record.getMessage()
        except Exception:
            return True   # 포매팅 자체가 깨졌다면 stdlib 로깅 핸들러가 보고
        record.msg = self._mask(rendered)
        record.args = ()
        return True

    def _mask(self, text: str) -> str:
        text = CARD_NUMBER_PATTERN.sub(
            lambda m: m.group()[:4] + "-****-****-" + m.group()[-4:], text
        )
        text = PASSWORD_PATTERN.sub(
            lambda m: m.group().split("=")[0] + "=***", text
        )
        return text
