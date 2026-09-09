"""
Git 版本管理封装。

设计思路:
  一个项目 = 一个 git 仓库。
  每次 AI 操作 (转换/提取/推理等) 完成后自动 commit，
  用户可以随时通过 git log 查看历史，通过 git checkout 回滚。

所有 git 操作通过 subprocess 调用系统 git 命令实现，
无需安装额外的 git Python 库。
"""
import subprocess
from pathlib import Path


class ProjectVCS:
    """
    项目版本控制类 (基于 Git)。

    每个 ProjectVCS 实例绑定一个项目目录，
    所有 git 操作都在该目录下执行。

    使用示例:
        vcs = ProjectVCS(Path("data/projects/a1b2c3d4"))
        vcs.init()                          # 初始化仓库
        vcs.commit("convert: 小说转剧本")    # 自动提交
        commits = vcs.log()                 # 查看历史
        vcs.checkout_all(commit_hash)       # 回滚
    """

    def __init__(self, project_dir: Path):
        """
        Args:
            project_dir: 项目仓库目录路径 (必须已存在)
        """
        self.dir = project_dir

    def _run(self, *args: str) -> str:
        """
        执行 git 命令并返回 stdout 输出。

        这是一个内部辅助方法，所有 git 操作都通过它执行。
        如果命令失败，返回空字符串 (不抛异常)。

        Args:
            *args: git 子命令和参数 (如 "log", "--format=%H")

        Returns:
            命令的 stdout 输出字符串，失败时返回空字符串
        """
        result = subprocess.run(
            ["git"] + list(args),
            cwd=str(self.dir),           # 在项目目录下执行
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return result.stdout.strip()

    def _run_ok(self, *args: str) -> bool:
        """
        执行 git 命令并返回是否成功 (exit code == 0)。

        用于需要判断命令是否成功的场景 (如 commit、init)。

        Args:
            *args: git 子命令和参数

        Returns:
            True 如果命令成功 (exit code 0)，否则 False
        """
        result = subprocess.run(
            ["git"] + list(args),
            cwd=str(self.dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return result.returncode == 0

    def init(self):
        """
        初始化 git 仓库并创建 .gitignore。

        执行步骤:
        1. git init (创建 .git 目录)
        2. 写入 .gitignore (忽略 media/、*.db 等大文件/临时文件)
        3. 首次提交 .gitignore

        .gitignore 内容:
            media/        # 媒体文件 (图片/音频/视频) 通常很大，不纳入 git
            *.db          # SQLite 数据库文件
            __pycache__/  # Python 缓存
        """
        self._run("init")

        # 写入 .gitignore
        gitignore = self.dir / ".gitignore"
        gitignore.write_text(
            "media/\n*.db\n__pycache__/\n*.pyc\n",
            encoding="utf-8",
        )

        # 提交 .gitignore 作为初始提交
        self._run("add", ".gitignore")
        self._run("commit", "-m", "init: 初始化项目")
        return True

    def commit(self, message: str) -> bool:
        """
        暂存所有变更并提交。

        这是最常用的版本管理操作，每次 AI 操作完成后调用。
        使用 git add -A 暂存所有变更 (新增/修改/删除的文件)。

        commit message 命名约定:
        - "init: 创建项目 {name}"
        - "import: 导入小说 xxx.txt (12345字)"
        - "convert: 小说转剧本, 45个分镜"
        - "extract: 提取8个人物, 12个场景, 5个道具"
        - "bind: 绑定实体到分镜"
        - "infer: 为45个分镜生成提示词"
        - "edit: 修改分镜#3 paperwork"
        - "revert: 回滚到 xxxxxxxx"
        - "agent: 完整工作流执行"

        Args:
            message: 提交信息 (建议遵循上述命名约定)

        Returns:
            True 如果提交成功，否则 False
        """
        self._run("add", "-A")
        return self._run_ok("commit", "-m", message, "--allow-empty")

    def log(self, n: int = 20) -> list[dict]:
        """
        查看提交历史 (类似 git log)。

        返回最近 n 条提交的摘要信息。
        按时间倒序排列 (最新提交在前)。

        Args:
            n: 返回的最大提交数 (默认 20)

        Returns:
            提交列表，每个元素为 dict:
            {
                "hash": str,     # 完整 commit hash (40位)
                "date": str,     # 提交时间 (ISO 格式)
                "message": str,  # 提交信息
            }
        """
        fmt = "%H|%ai|%s"     # hash|日期|提交信息，用 | 分隔
        raw = self._run("log", f"--format={fmt}", f"-{n}")
        if not raw:
            return []         # 没有任何提交 (空仓库)
        commits = []
        for line in raw.splitlines():
            parts = line.split("|", 2)
            if len(parts) == 3:
                commits.append({
                    "hash": parts[0],        # 完整 hash
                    "date": parts[1],        # 提交时间
                    "message": parts[2],     # 提交信息
                })
        return commits

    def diff(self, commit_hash: str = "HEAD~1") -> str:
        """
        查看与指定版本之间的差异。

        默认对比上一个提交 (HEAD~1)，即查看最近一次变更了什么。

        Args:
            commit_hash: 要对比的版本 hash (默认 "HEAD~1" = 上一个提交)

        Returns:
            diff 输出文本 (unified diff 格式)，无差异返回空字符串
        """
        return self._run("diff", commit_hash)

    def has_commits(self) -> bool:
        """
        检查仓库是否有任何提交。

        用于判断仓库是否已初始化 (init 后至少有一个提交)。

        Returns:
            True 如果有至少一个提交，否则 False
        """
        return self._run_ok("rev-parse", "HEAD")

    def checkout_all(self, commit_hash: str):
        """
        回滚到指定版本 (恢复所有文件到该版本的状态)。

        执行: git checkout <hash> -- .
        这会将工作区所有文件恢复到指定提交时的状态，
        但不会改变 HEAD 指针 (保留后续提交历史)。

        注意: 这是一个破坏性操作，当前未提交的修改会丢失。
        建议在调用前先 commit 当前状态。

        Args:
            commit_hash: 目标版本的 commit hash
        """
        self._run("checkout", commit_hash, "--", ".")

    def current_hash(self) -> str:
        """
        获取当前 HEAD 的 commit hash。

        Returns:
            当前 commit 的完整 hash 字符串
        """
        return self._run("rev-parse", "HEAD")
