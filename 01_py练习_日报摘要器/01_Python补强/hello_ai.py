"""
W21 启动验证脚本
作者：cheny
日期：2026-05-18
目的：确认 Python 环境就绪，给大脑一个"我开始了"的锚点
"""

import sys
import platform
from datetime import datetime


def main() -> None:
    """打印环境信息和启动宣言。"""
    print("=" * 50)
    print("  AI 应用方向换岗学习 · 启程")
    print("=" * 50)
    print(f"  时间   : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Python : {sys.version.split()[0]}")
    print(f"  系统   : {platform.system()} {platform.release()}")
    print(f"  目标   : 3-6 个月换岗到 AI 应用岗")
    print("-" * 50)
    print("  Hello, AI 之路。")
    print("=" * 50)


if __name__ == "__main__":
    main()