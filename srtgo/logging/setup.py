import logging
import logging.handlers
from pathlib import Path

from .filters import SensitiveDataFilter
from .formatters import ConsoleFormatter, FileFormatter


def setup_logging(debug: bool = False) -> None:
    log_dir = Path.home() / ".srtgo" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger("srtgo")
    root_logger.setLevel(logging.DEBUG)

    # 중복 핸들러 방지
    if root_logger.handlers:
        return

    # 콘솔: debug 모드면 DEBUG, 아니면 WARNING
    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if debug else logging.WARNING)
    console.setFormatter(ConsoleFormatter())

    # 파일: DEBUG 이상, 5MB × 3 롤링
    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "srtgo.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(FileFormatter())
    file_handler.addFilter(SensitiveDataFilter())

    root_logger.addHandler(console)
    root_logger.addHandler(file_handler)
