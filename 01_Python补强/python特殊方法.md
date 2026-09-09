
| 分类         | 方法名                                          | 功能描述                                      |
| ---------- | -------------------------------------------- | ----------------------------------------- |
| **对象生命周期** | `__new__(cls[, ...])`                        | 创建实例时最先调用的静态方法，负责返回实例对象                   |
|            | `__init__(self[, ...])`                      | 实例初始化方法，在 `__new__` 之后调用，无返回值             |
|            | `__del__(self)`                              | 析构方法，实例被垃圾回收前调用                           |
| **字符串表示**  | `__repr__(self)`                             | 返回对象的“官方”字符串表示，通常用于调试，应能被 `eval()` 重建     |
|            | `__str__(self)`                              | 返回对象的“非正式”字符串表示，被 `str()` 和 `print()` 调用  |
|            | `__bytes__(self)`                            | 返回对象的字节串表示，被 `bytes()` 调用                 |
|            | `__format__(self, format_spec)`              | 返回对象按指定格式的字符串表示，被 `format()` 调用           |
| **属性访问**   | `__getattr__(self, name)`                    | 在常规属性查找失败时调用（属性不存在时）                      |
|            | `__getattribute__(self, name)`               | 无条件在每次属性访问时调用（需谨慎使用，避免无限递归）               |
|            | `__setattr__(self, name, value)`             | 设置属性时调用                                   |
|            | `__delattr__(self, name)`                    | 删除属性时调用                                   |
|            | `__dir__(self)`                              | 返回对象属性列表，被 `dir()` 调用                     |
| **描述符协议**  | `__get__(self, instance, owner)`             | 描述符获取属性值时调用                               |
|            | `__set__(self, instance, value)`             | 描述符设置属性值时调用                               |
|            | `__delete__(self, instance)`                 | 描述符删除属性值时调用                               |
|            | `__set_name__(self, owner, name)`            | 在描述符被赋值给类属性时调用（Python 3.6+）               |
| **容器与序列**  | `__len__(self)`                              | 返回容器长度，被 `len()` 调用                       |
|            | `__getitem__(self, key)`                     | 通过键或索引获取元素，被 `self[key]` 调用               |
|            | `__setitem__(self, key, value)`              | 设置元素值，被 `self[key] = value` 调用            |
|            | `__delitem__(self, key)`                     | 删除元素，被 `del self[key]` 调用                 |
|            | `__iter__(self)`                             | 返回迭代器对象，被 `iter()` 调用                     |
|            | `__reversed__(self)`                         | 返回反向迭代器，被 `reversed()` 调用                 |
|            | `__contains__(self, item)`                   | 检查成员关系，被 `in` 操作符调用                       |
|            | `__missing__(self, key)`                     | 当字典中键不存在时被 `__getitem__` 调用（用于 `dict` 子类） |
| **数值运算**   | `__add__(self, other)`                       | 加法 `+`                                    |
|            | `__sub__(self, other)`                       | 减法 `-`                                    |
|            | `__mul__(self, other)`                       | 乘法 `*`                                    |
|            | `__matmul__(self, other)`                    | 矩阵乘法 `@` (Python 3.5+)                    |
|            | `__truediv__(self, other)`                   | 真除法 `/`                                   |
|            | `__floordiv__(self, other)`                  | 整数除法 `//`                                 |
|            | `__mod__(self, other)`                       | 取模 `%`                                    |
|            | `__divmod__(self, other)`                    | 返回商和余数元组，被 `divmod()` 调用                  |
|            | `__pow__(self, other[, mod])`                | 幂运算 `**` 或 `pow()`                        |
|            | `__lshift__(self, other)`                    | 左移位 `<<`                                  |
|            | `__rshift__(self, other)`                    | 右移位 `>>`                                  |
|            | `__and__(self, other)`                       | 按位与 `&`                                   |
|            | `__or__(self, other)`                        | 按位或 `\|`                                  |
|            | `__xor__(self, other)`                       | 按位异或 `^`                                  |
|            | `__neg__(self)`                              | 一元负号 `-`                                  |
|            | `__pos__(self)`                              | 一元正号 `+`                                  |
|            | `__abs__(self)`                              | 绝对值 `abs()`                               |
|            | `__invert__(self)`                           | 按位取反 `~`                                  |
|            | `__complex__(self)`                          | 转换为复数 `complex()`                         |
|            | `__int__(self)`                              | 转换为整数 `int()`                             |
|            | `__float__(self)`                            | 转换为浮点数 `float()`                          |
|            | `__index__(self)`                            | 用于 `hex()`, `oct()` 等，或作为切片索引时转换为整数       |
|            | `__round__(self[, ndigits])`                 | 四舍五入 `round()`                            |
|            | `__trunc__(self)`                            | 截断为整数，被 `math.trunc()` 调用                 |
|            | `__floor__(self)`                            | 向下取整，被 `math.floor()` 调用                  |
|            | `__ceil__(self)`                             | 向上取整，被 `math.ceil()` 调用                   |
| **反射运算符**  | `__radd__(self, other)`                      | 反射加法（当左操作数不支持相应操作时调用）                     |
|            | `__rsub__(self, other)`                      | 反射减法                                      |
|            | `__rmul__(self, other)`                      | 反射乘法                                      |
|            | `__rmatmul__(self, other)`                   | 反射矩阵乘法                                    |
|            | ... （其他类似，不再重复）                              | 所有二元运算符均有对应的反射版本，命名规则为 `__r`+运算符名         |
| **增量赋值**   | `__iadd__(self, other)`                      | 增量加法 `+=`                                 |
|            | `__isub__(self, other)`                      | 增量减法 `-=`                                 |
|            | ... （类似，命名规则 `__i`+运算符名）                     | 其他增量赋值操作                                  |
| **比较运算**   | `__lt__(self, other)`                        | 小于 `<`                                    |
|            | `__le__(self, other)`                        | 小于等于 `<=`                                 |
|            | `__eq__(self, other)`                        | 等于 `==`                                   |
|            | `__ne__(self, other)`                        | 不等于 `!=`                                  |
|            | `__gt__(self, other)`                        | 大于 `>`                                    |
|            | `__ge__(self, other)`                        | 大于等于 `>=`                                 |
| **可调用对象**  | `__call__(self[, ...])`                      | 使实例可以像函数一样被调用                             |
| **上下文管理器** | `__enter__(self)`                            | 进入上下文时调用，返回值赋给 `as` 子句的变量                 |
|            | `__exit__(self, exc_type, exc_val, exc_tb)`  | 退出上下文时调用，处理异常                             |
| **迭代器**    | `__iter__(self)`                             | 返回迭代器对象自身（迭代器协议）                          |
|            | `__next__(self)`                             | 返回下一个元素，无元素时抛出 `StopIteration`            |
| **异步相关**   | `__await__(self)`                            | 返回一个迭代器，用于 `await` 对象                     |
|            | `__aiter__(self)`                            | 返回异步迭代器，用于 `async for`                    |
|            | `__anext__(self)`                            | 返回异步迭代器的下一个值，返回一个 `awaitable`             |
|            | `__aenter__(self)`                           | 异步上下文管理器进入方法                              |
|            | `__aexit__(self, exc_type, exc_val, exc_tb)` | 异步上下文管理器退出方法                              |
| **其他**     | `__hash__(self)`                             | 返回对象的哈希值，被 `hash()` 调用，用于字典键等             |
|            | `__bool__(self)`                             | 返回布尔值，被 `bool()` 调用，如果未定义则调用 `__len__()`  |
|            | `__copy__(self)`                             | 浅拷贝协议（`copy.copy` 相关）                     |
|            | `__deepcopy__(self, memo)`                   | 深拷贝协议（`copy.deepcopy` 相关）                 |
|            | `__getnewargs__(self)`                       | 用于 pickle 序列化，控制 `__new__` 的参数            |
|            | `__getstate__(self)`                         | 用于 pickle，返回对象的可序列化状态                     |
|            | `__setstate__(self, state)`                  | 用于 pickle，从状态恢复对象                         |
|            | `__reduce__(self)`                           | 用于 pickle，控制序列化行为                         |
|            | `__reduce_ex__(self, protocol)`              | 带协议版本的 `__reduce__`                       |