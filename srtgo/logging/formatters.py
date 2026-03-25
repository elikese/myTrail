import logging


class FileFormatter(logging.Formatter):
    """파일용: 타임스탬프, 레벨, 모듈, 함수명, 라인번호, 메시지"""

    fmt = "%(asctime)s.%(msecs)03d | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    def __init__(self):
        super().__init__(fmt=self.fmt, datefmt=self.datefmt)


class ConsoleFormatter(logging.Formatter):
    """콘솔용: 시간, 레벨 심볼, 메시지만"""

    LEVEL_SYMBOL = {
        logging.WARNING: "!",
        logging.ERROR: "x",
        logging.CRITICAL: "!!",
    }

    def format(self, record: logging.LogRecord) -> str:
        symbol = self.LEVEL_SYMBOL.get(record.levelno, "")
        t = self.formatTime(record, "%H:%M:%S")
        prefix = f"[{symbol}] " if symbol else ""
        return f"[{t}] {prefix}{record.getMessage()}"
