# W21_Python_02 · 行字数统计

## 题目

写一个脚本 `line_stats.py`：

1. 读取一个 txt 文件（路径作为参数或写死都行）
2. 统计每行的字数（不计算换行符）
3. 把结果写入同目录的 `stats.json`，结构如下：

```json
{
  "source_file": "input.txt",
  "total_lines": 5,
  "total_chars": 123,
  "lines": [
    {"line_no": 1, "chars": 30, "preview": "前 20 个字符..."},
    {"line_no": 2, "chars": 45, "preview": "..."}
  ],
  "generated_at": "2026-05-19 14:30:00"
}
```

## 约束

- 必须用 `with` 上下文管理文件，不许裸 open
- 必须处理：文件不存在 / 不是 txt / 编码错误 三种异常
- 用 `pathlib.Path`，不许用字符串拼路径
- 输出 JSON 要 indent=2 + ensure_ascii=False（中文不转码）

## 验收标准

- [x] 输入存在的 txt → 正确生成 stats.json
- [x] 输入不存在的文件 → 友好报错（不是 traceback 一片红）
- [x] 输入空文件 → 不崩，total_lines=0
- [x] 输入有中文的 txt → JSON 里中文正常显示
- [x] preview 字段超过 20 字符要截断并加 "..."

---

## 你的思路

> 1. 这个脚本你打算分几个函数？每个函数职责是什么？
> 2. 异常处理你打算放在哪一层？（main 里？还是各个函数里？）
> 3. 编码错误怎么处理？用什么编码读？

（在这里写）
1. 3个，数据导入、计算、格式化输出
2. 各个函数里
3. UnicodeDecodeError，用utf-8
---

## 你的实现

```python
from pathlib import Path
import json
from datetime import datetime

def open_file(input_file: Path) -> list:
    """读取文件内容，返回行列表"""
    try:
        with open(input_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
            return lines
    except FileNotFoundError:
        print(f"文件不存在: {input_file}")
        return []
    except UnicodeDecodeError:
        print(f"编码错误，文件可能不是 UTF-8: {input_file}")
        return []
    except Exception as e:
        print(f"未预期错误：{e}")
        return []

def lines_count(lines: list) -> tuple:
    """
    统计行数信息

    Args:
        lines: 文件行列表

    Returns:
        (total_lines, total_chars, lines_info) 元组
    """
    total_lines = len(lines)
    total_chars = 0
    lines_info = []  # 存储每行信息的列表
    for i, line in enumerate(lines, 1):
        chars = len(line.rstrip())
        total_chars += chars
        stripped = line.rstrip()
        preview = stripped if len(stripped) <= 20 else stripped[:20] + "..."
        line_info = {"line_no": i, "chars": chars, "preview": preview}
        lines_info.append(line_info)
    return (total_lines, total_chars, lines_info)


def out_json(result: tuple, output_file: Path) -> dict:
    """
    将结果保存为 JSON 文件

    Args:
        result: (total_lines, total_chars, lines_info) 元组
        output_file: 输出文件路径
    """
    total_lines, total_chars, lines_info = result

    data = {
        "source_file": "sample.txt",
        "total_lines": total_lines,
        "total_chars": total_chars,
        "lines": lines_info,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    # 确保目录存在
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # 写入 JSON 文件
    try:
        with output_file.open('w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"✅ 成功保存到: {output_file}")
    except Exception as e:
        print(f"❌ 保存失败: {e}")
        return {}

    return data


def main():
    file_path = Path(__file__).parent
    input_file = file_path / "sample.txt"
    output_file = file_path / "stats.json"

    lines = open_file(input_file)
    result = lines_count(lines)
    out_json(result, output_file)


if __name__ == "__main__":
    main()
```

## 测试用的输入文件

请同时在 `01_Python补强/` 下创建一个 `sample.txt`，内容自定（建议混合中英文，4-5 行）

## 自测

- [x] 正常 txt 测试通过
- [x] 不存在的文件测试通过
- [x] 空文件测试通过
- [x] 中文显示正常

## 卡点

- Path用法不清楚
- enumerate返回行号现查，原来用的i手动计数
- 函数return和变量赋值位置不合适
- with output_file.open('w', encoding='utf-8') as f：
with open(input_file, "r", encoding="utf-8") as f:
两种用法文件在内和在外都可以

特性	Path.open()	open()

调用对象	Path 对象的方法	内置函数

路径类型	只能处理 Path 对象	可处理 str 和 Path 对象

风格	面向对象（OOP）	函数式

推荐度	✅ 现代 Python（推荐）	传统方式

## 导师反馈

待提交后填写。