from pathlib import Path
import json
from datetime import datetime

def open_file(input_file: Path) -> list:
    """读取文件内容，返回行列表"""
    try:
        input_file.suffix ==".txt"
    except Exception as e:
        print(f"zb文件类型错误：{e}")
        return []
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