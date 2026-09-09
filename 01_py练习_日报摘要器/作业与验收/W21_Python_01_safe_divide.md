# W21_Python_01 · safe_divide

## 题目

实现一个 `safe_divide(a, b)` 函数，处理三种情况：

1. **除零**：b 为 0 时不能崩，要给出有意义的反馈
2. **类型错误**：a 或 b 不是数字（比如传入字符串、列表）时不能崩
3. **浮点精度**：返回值如果是浮点数，控制精度（比如保留 4 位小数）

## 约束

- 必须有类型注解（type hints）
- 必须有 docstring 说明用法
- 不许使用 try/except 包住整个函数体当万能盾牌，要明确处理每类问题
- 函数返回值要"信息完整"：调用者不仅要知道结果，还要知道是否成功

## 验收标准

- [x] `safe_divide(10, 3)` → 正常返回 3.3333（4 位小数）
- [x] `safe_divide(10, 0)` → 不抛异常，返回能体现"除零"的结果
- [x] `safe_divide("a", 3)` → 不抛异常，返回能体现"类型错误"的结果
- [x] `safe_divide(10, 2)` → 返回 5.0（整数除整数也要稳定）
- [x] 代码长度控制在 30 行以内（含 docstring）

---

## 你的思路（先写思路再写代码）

> 在动手写代码之前，先在这里用中文回答 3 个问题：
>
> 1. 函数的返回值你打算用什么结构？（单值？元组？字典？）为什么？
> 2. 检测"类型错误"你打算用什么方法？isinstance？type？还是其他？
> 3. 三种异常情况，你打算用同一种返回结构表达，还是分别用不同方式？

> 1、组元,因为判断和结果/错误打包，解包就能获得，安全
> 2、isinstance能够判断子类，且判断多个类型
> 3、好处，错误有同一False标签；坏处，结果需要解包，result类型不纯，python习惯正确出结果，错误出报错

---

## 你的实现

```python
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

```

## 自测

- [x] `safe_divide(10, 3)` → (True, 3.3333)
- [x] `safe_divide(10, 0)` → (False, '除数不能为0')
- [x] `safe_divide("a", 3)` → (False, "类型错误: a='a'(str), b=3(int)")
- [x] `safe_divide(10, 2)` → (True, 5.0)
- [x] `safe_divide(0, 5)` → (True, 0.0)（思考题：0/5 算成功还是失败？）
- 成功，0 是合法被除数

## 卡点

-

## 导师反馈

待提交后填写。