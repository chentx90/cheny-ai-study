# W21_Python_03 · Logger 类

## 题目

实现一个 `Logger` 类，支持三级日志：

- `info(msg)`：普通信息
- `warn(msg)`：警告
- `error(msg)`：错误

每条日志自动带：
- 时间戳（精确到秒）
- 级别标签（INFO / WARN / ERROR）
- 消息正文

输出有两种模式：**控制台** 和 **文件**，可同时启用、可独立关闭。

## 约束

- 必须用 OOP 写，不许用全局函数
- 必须有类型注解
- 必须有完整 docstring（类级 + 方法级）
- 必须实现 `__repr__`（不写就扣分，养成习惯）
- 文件输出必须用 `with` 上下文 + `encoding="utf-8"` + `pathlib.Path`
- 文件路径不存在时**自动创建父目录**
- 至少 3 个测试用例（同时控制台 / 只文件 / 只控制台）

## 验收标准

- [x] 三级方法都能正常调用，输出格式一致
- [x] 文件输出和控制台输出格式一致（除了一个有颜色一个没有）
- [x] 调用 `repr(logger)` 能看到有意义的描述
- [x] 创建 `Logger("logs/app.log")` 时如果 logs 目录不存在，能自动创建
- [x] 至少 3 个测试用例都跑通，stdout / 文件双重可见

## 进阶（选做）

- [x] 控制台输出加颜色：INFO 默认 / WARN 黄 / ERROR 红（用 ANSI escape 或 colorama）
- [x] 加日志级别过滤：`Logger(level="WARN")` 时不输出 INFO
- [x] 文件按日期切分：每天一个 log 文件

---

## 你的思路（先写思路再写代码）

> 必答 4 题，写完贴给我看，我审过你才能动代码。

1. **类的属性有哪些？**（数据层面）
   - 实例属性（__init__ 接收的配置）：
      - file_path: Path | None  ← 文件路径，None 表示不写文件
      - to_console: bool        ← 是否输出到控制台

      类常量：
      - LEVELS = ("INFO", "WARN", "ERROR")

      每条日志的"时间戳"和"消息正文"不是属性，是 _log 方法里的局部变量/参数。

2. **方法划分怎么设计？**
   提示：info/warn/error 三个方法显然有重复逻辑（都要时间戳+格式化+输出），怎么避免重复？想想"私有方法"。
   - 配置好一个类变量，所有实列info/warn/error共享
    ```python
    def info(self, msg):
        self._log("INFO", msg)        # ← 调私有方法，传级别
    
    def warn(self, msg):
        self._log("WARN", msg)
    
    def error(self, msg):
        self._log("ERROR", msg)
    
    def _log(self, level, msg):
        """所有重复逻辑都集中在这里：拼时间戳、格式化、写出"""
        # 1. 生成时间戳
        # 2. 拼接最终字符串：[时间] [级别] msg
        # 3. 决定写到哪儿（控制台？文件？）
        # 4. 写出
    ```

3. **如何同时支持控制台 + 文件？两个输出目标怎么解耦？**
   提示：考虑参数化"输出方式"。
   - 用配置参数进行判断，每个动作前加if检查，如if file_path:Path is not None:和if to_console:bool :
   - 控制台 + 文件解耦：
      __init__ 里两个参数 file_path 和 to_console。
      _log 方法里两个独立的 if 判断：
        - if self.to_console: print(line)
        - if self.file_path is not None: 写文件
      两个开关互不干扰，可以同时开、同时关、只开一个。

4. **错误处理放哪里？**
   提示：文件写不进去（路径错误 / 权限不足）应该怎么办？崩还是降级到控制台？
   - 根据情况选择，
   - 1崩（重大错误不能继续）
   - 2吞掉异常降级到控制台（防止日志影响主程序）
   - 3吞掉异常改自己状态自我熔断（长期运行的程序，第一次失败后不再反复尝试）


---

## 你的实现

文件：`01_Python补强/logger.py`

## 自测（至少 3 个用例）

- [x] 用例 1：控制台 + 文件双输出，分别测试 info/warn/error
- [x] 用例 2：只文件输出（控制台关闭）
- [x] 用例 3：只控制台输出（不传文件路径）
- [x] 用例 4（选）：log 路径父目录不存在，自动创建
- [x] 用例 5（选）：`repr(logger)` 输出

## 卡点

-

## 导师反馈

待提交后填写。