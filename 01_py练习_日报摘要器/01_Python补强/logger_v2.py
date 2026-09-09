from pathlib import Path
from datetime import datetime
from colorama import Fore, Style, init
from typing import Optional

init(autoreset=True)


class Logger:

    LEVEL_VALUES = {
        "info": 1,
        "warn": 2,
        "error": 3,
    }
    DEFAULT_LOG_PATH = Path(__file__).parent / "logs" / "app.log"

    def __init__(self, file_path: Optional[Path] = DEFAULT_LOG_PATH, level: str = "info", to_console: bool = True) -> None:
        self.file_path = file_path
        self.to_console = to_console
        self.level_value = self.LEVEL_VALUES.get(level.lower(), 1)

        if file_path:
            self.file_path = Path(file_path) if not isinstance(file_path, Path) else file_path
            # 确保日志目录存在
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            self.file_path = None

    def _should_log(self, level: str) -> bool:
        level_value = self.LEVEL_VALUES.get(level, 1)
        return level_value >= self.level_value

    def info(self, msg: str) -> None:
        if not self._should_log("info"):
            return
        msg = f"{Fore.GREEN}{msg}{Style.RESET_ALL}"
        self._log(level="info", msg=msg)
    def warn(self, msg: str) -> None:
        if not self._should_log("warn"):
            return
        msg = f"{Fore.YELLOW}{msg}{Style.RESET_ALL}"
        self._log(level="warn", msg=msg)
    def error(self, msg: str) -> None:
        if not self._should_log("error"):
            return
        msg = f"{Fore.RED}{msg}{Style.RESET_ALL}"
        self._log(level="error", msg=msg)

    def _log(self, level: str, msg: str) -> None:
        now = datetime.now()
        timestamp = now.strftime('%Y-%m-%d %H:%M:%S')
        today = now.strftime('%Y-%m-%d')
        log_path = self.file_path.parent / f"{self.file_path.stem}_{today}{self.file_path.suffix}"
        line = f"[{timestamp}] [{level.upper()}] {msg}"
        if self.to_console:
            print(f"{line}")
        try:
            with open(log_path, mode="a", encoding="utf-8") as f:
                f.write(line+"\n")
        except OSError as e:
            print(f"[logger]写文件失败：{e}")
            if not self.to_console:
                print(line)

    def __repr__(self):
        return f"Logger(file_path={self.file_path!r}, to_console={self.to_console})"


if __name__ == "__main__":
    log1 = Logger(file_path=Path("logs/app.log"))
    log1.info("用户登录")
    log1.warn("API 限流")
    log1.error("数据库连接失败")
    print(repr(log1))