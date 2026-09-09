def safe_divide(a: float, b: float) -> tuple[bool, (float | str)]:
    """安全除法，处理除零和类型错误。

    Args:
        a: 被除数
        b: 除数

    Returns:
        (success, result_or_error_msg)
        - success=True 时 result 是计算结果
        - success=False 时是错误说明
    """

    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)) or type(a)=="bool" or type(b)=="bool":   # bool是int的子类型，bool能通过判断

        return False, f"类型错误: a={a!r}({type(a).__name__}), b={b!r}({type(b).__name__})"
    elif b == 0:
        return False, "除数不能为0"
    else :
        result = round(a / b, 4)
        return True, result

if __name__ == "__main__":
    print(safe_divide(10, 3))
    print(safe_divide(10, 0))
    print(safe_divide("a", 3))
    print(safe_divide(10, 2))
    print(safe_divide(0, 5))
    print(safe_divide("a", 0))