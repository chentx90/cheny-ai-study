from datetime import datetime
from pathlib import Path


class Logger:
    """三级日志记录器，支持控制台和文件双输出。

    Args:
        file_path:Path | None ,log的输出位置
        to_console:Bool ，是否输出到控制台的开关
    """

    LEVELS = ("INFO", "WARN", "ERROR")

    def __init__(self, file_path: Path | None = None, to_console=True):
        self.to_console = to_console
        self.file_path = file_path
        if file_path is not None:
            if not isinstance(self.file_path, Path):
                self.file_path = Path(self.file_path)
            parent_dir = self.file_path.parent
            if not parent_dir.exists():
                parent_dir.mkdir(parents=True, exist_ok=True)

        # ← 1. 类型注解：file_path 应该是什么类型？to_console 呢？
        # ← 2. 把传进来的参数存为实例属性
        # ← 3. 文件路径的父目录如果不存在，要自动创建（用 pathlib）
        ...

    def info(self, msg: str) -> None:
        """记录普通信息。"""
        self._log(level="INFO", msg=msg)
        # ← 一行，调 _log
        ...

    def warn(self, msg: str) -> None:
        """记录警告。"""
        self._log(level="WARN", msg=msg)
        # ← 一行，调 _log
        ...

    def error(self, msg: str) -> None:
        """记录错误。"""
        self._log(level="ERROR", msg=msg)
        # ← 一行，调 _log
        ...

    def _log(self, level: str, msg: str) -> None:
        """所有日志的核心逻辑都在这里。"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] [{level}] {msg}"
        if self.to_console:
            print(line)
        try:
            if self.file_path is not None:
                with open(self.file_path.as_posix(), "a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except (IOError, OSError) as e:
            print(f"[logger]写文件失败：{e}" )
            if not self.to_console:
                   print(line)


        # ← 1. 生成时间戳：datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # ← 2. 拼接成最终字符串：[时间] [级别] msg
        # ← 3. 如果 to_console 开着，print 出来
        # ← 4. 如果 file_path 不是 None，用 with open 追加写文件
        #    （注意：这一步用 try/except 包住，失败时降级到控制台）
        ...

    def __repr__(self) -> str:
        """实例的字符串表示。"""
        return f"Logger(file_path={self.file_path!r}, to_console={self.to_console})"
        # ← 返回一个有用的描述，比如 Logger(file_path=..., to_console=...)
        ...


if __name__ == "__main__":
    # 测试用例 1：控制台 + 文件双输出
    log1 = Logger(file_path=Path("logs/app.log"))
    log1.info("用户登录")
    log1.warn("API 限流")
    log1.error("数据库连接失败")
    print(repr(log1))

    # 测试用例 2：只文件输出
    # ← 自己写
    log2 = Logger(file_path=Path("logs/app.log"), to_console=False)
    log2.info("用户登录")
    log2.warn("API 限流")
    log2.error("数据库连接失败")
    print(repr(log2))

    # 测试用例 3：只控制台输出
    # ← 自己写
    log3 = Logger()
    log3.info("用户登录")
    log3.warn("API 限流")
    log3.error("数据库连接失败")
    print(repr(log3))

    log4 = Logger(to_console=False)
    log4.info("用户登录")
    print(repr(log4))