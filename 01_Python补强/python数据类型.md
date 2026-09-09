
Python 中常见数据类型的分类、特性、常用方法及属性的汇总表格：

| 数据类型         | 分类    | 特性                                | 常用方法及属性                                                                                                  |
| ------------ | ----- | --------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `int`        | 数字类型  | 不可变、可哈希、任意精度整数                    | `bit_length()`, `to_bytes()`, `from_bytes()`, <br>`as_integer_ratio()`；属性：`real`, `imag`                 |
| `float`      | 数字类型  | 不可变、可哈希、双精度浮点数                    | `as_integer_ratio()`, `is_integer()`, `hex()`, <br>`fromhex()`；属性：`real`, `imag`                         |
| `complex`    | 数字类型  | 不可变、可哈希、实部和虚部均为 `float`           | `conjugate()`；属性：`real`, `imag`                                                                          |
| `bool`       | 数字类型  | `int` 的子类，只有 `True` 和 `False`，可哈希 | 继承 `int` 的方法，无特有方法；属性：无                                                                                  |
| `str`        | 序列类型  | 不可变、可哈希、有序、Unicode 字符序列           | `upper()`, `lower()`, `strip()`, `split()`, <br>`join()`, `replace()`, `find()`, `format()`, `encode()`  |
| `list`       | 序列类型  | 可变、不可哈希、有序、元素类型任意                 | `append()`, `extend()`, `insert()`, `remove()`, <br>`pop()`, `index()`, `sort()`, `reverse()`, `copy()`  |
| `tuple`      | 序列类型  | 不可变、可哈希（元素可哈希时）、有序、元素类型任意         | `count()`, `index()`                                                                                     |
| `range`      | 序列类型  | 不可变、可哈希、有序、表示整数等差数列               | `count()`, `index()`；属性：`start`, `stop`, `step`                                                          |
| `set`        | 集合类型  | 可变、不可哈希、无序、元素必须可哈希                | `add()`, `remove()`, `discard()`, `pop()`, `union()`, <br>`intersection()`, `difference()`, `issubset()` |
| `frozenset`  | 集合类型  | 不可变、可哈希、无序、元素必须可哈希                | 同 `set` 但无修改方法（如 `union`, `intersection`,<br>`copy` 等只读操作）                                               |
| `dict`       | 映射类型  | 可变、不可哈希、键必须可哈希、Python 3.7+ 保持插入顺序 | `keys()`, `values()`, `items()`, `get()`, <br>`setdefault()`, `pop()`, `update()`, `copy()`              |
| `bytes`      | 二进制序列 | 不可变、可哈希、有序、元素为 0~255 的整数          | `decode()`, `hex()`, `fromhex()`, `replace()`, <br>`find()`, `split()`, `count()`, `startswith()`        |
| `bytearray`  | 二进制序列 | 可变、不可哈希、有序、元素为 0~255 的整数          | 类似 `bytes` 的读写方法，并增加 `append()`, `extend()`, `insert()`, `pop()`, `remove()`, `reverse()`                |
| `memoryview` | 二进制序列 | 缓冲区视图，可变性取决于原对象、不可哈希、支持内存直接访问     | `tolist()`, `tobytes()`, `cast()`, `release()`；属性：`obj`, `nbytes`, `readonly`, `format`, `shape`         |
| `NoneType`   | 其他    | 单例对象 `None`，不可变、可哈希               | 无常用方法；属性：无                                                                                               |

Python 常见数据类型的方法属性及其作用解释的对应表格：

| 数据类型           | 方法/属性                           | 作用解释                              |
| -------------- | ------------------------------- | --------------------------------- |
| **int**        | `bit_length()`                  | 返回表示该整数所需的二进制位数（不包括符号位）           |
|                | `to_bytes(length, byteorder)`   | 将整数转换为指定长度的字节串                    |
|                | `from_bytes(bytes, byteorder)`  | 从字节串创建整数（类方法）                     |
|                | `as_integer_ratio()`            | 返回整数对应的(分子, 分母)元组，分母为1            |
|                | `.real`                         | 返回整数的实部（即自身）                      |
|                | `.imag`                         | 返回整数的虚部（恒为0）                      |
| **float**      | `as_integer_ratio()`            | 返回浮点数精确表示的分数(分子, 分母)              |
|                | `is_integer()`                  | 判断浮点数是否为整数值（如3.0为True，3.14为False） |
|                | `hex()`                         | 返回浮点数的十六进制字符串表示                   |
|                | `fromhex(s)`                    | 从十六进制字符串创建浮点数（类方法）                |
|                | `.real`                         | 返回浮点数的实部（即自身）                     |
|                | `.imag`                         | 返回浮点数的虚部（恒为0）                     |
| **complex**    | `conjugate()`                   | 返回复数的共轭复数                         |
|                | `.real`                         | 返回复数的实部                           |
|                | `.imag`                         | 返回复数的虚部                           |
| **str**        | `upper()`                       | 将字符串全部转换为大写                       |
|                | `lower()`                       | 将字符串全部转换为小写                       |
|                | `strip([chars])`                | 移除字符串首尾指定的字符（默认空格）                |
|                | `split([sep])`                  | 按指定分隔符分割字符串，返回列表                  |
|                | `join(iterable)`                | 用字符串连接可迭代对象中的元素                   |
|                | `replace(old, new[, count])`    | 替换字符串中的子串                         |
|                | `find(sub[, start[, end]])`     | 查找子串首次出现的位置，返回索引或-1               |
|                | `format(*args, **kwargs)`       | 格式化字符串                            |
|                | `encode(encoding='utf-8')`      | 将字符串编码为字节串                        |
|                | `count(sub[, start[, end]])`    | 统计子串出现的次数                         |
|                | `startswith(prefix)`            | 判断字符串是否以指定前缀开头                    |
|                | `endswith(suffix)`              | 判断字符串是否以指定后缀结尾                    |
| **list**       | `append(x)`                     | 在列表末尾添加元素                         |
|                | `extend(iterable)`              | 用可迭代对象扩展列表                        |
|                | `insert(i, x)`                  | 在指定位置插入元素                         |
|                | `remove(x)`                     | 移除列表中第一个值为x的元素                    |
|                | `pop([i])`                      | 移除并返回指定位置的元素（默认末尾）                |
|                | `index(x[, start[, end]])`      | 返回元素首次出现的索引                       |
|                | `count(x)`                      | 统计元素出现的次数                         |
|                | `sort(key=None, reverse=False)` | 对列表进行原地排序                         |
|                | `reverse()`                     | 原地反转列表                            |
|                | `copy()`                        | 返回列表的浅拷贝                          |
|                | `clear()`                       | 移除列表所有元素                          |
| **tuple**      | `count(x)`                      | 统计元素出现的次数                         |
|                | `index(x[, start[, end]])`      | 返回元素首次出现的索引                       |
| **range**      | `count(x)`                      | 判断x是否在range中，返回1或0                |
|                | `index(x)`                      | 返回x在range中的索引，不存在则报错              |
|                | `.start`                        | range的起始值（属性）                     |
|                | `.stop`                         | range的结束值（属性）                     |
|                | `.step`                         | range的步长（属性）                      |
| **set**        | `add(x)`                        | 向集合添加元素                           |
|                | `remove(x)`                     | 移除指定元素，不存在则报错                     |
|                | `discard(x)`                    | 移除指定元素，不存在也不报错                    |
|                | `pop()`                         | 随机移除并返回一个元素                       |
|                | `clear()`                       | 清空集合                              |
|                | `union(set)`                    | 返回并集（也可用`\|`）                     |
|                | `intersection(set)`             | 返回交集（也可用`&`）                      |
|                | `difference(set)`               | 返回差集（也可用`-`）                      |
|                | `symmetric_difference(set)`     | 返回对称差集（也可用`^`）                    |
|                | `issubset(set)`                 | 判断是否为子集                           |
|                | `issuperset(set)`               | 判断是否为超集                           |
|                | `isdisjoint(set)`               | 判断是否无交集                           |
|                | `copy()`                        | 返回集合的浅拷贝                          |
| **frozenset**  | `union(set)`                    | 返回并集                              |
|                | `intersection(set)`             | 返回交集                              |
|                | `difference(set)`               | 返回差集                              |
|                | `symmetric_difference(set)`     | 返回对称差集                            |
|                | `issubset(set)`                 | 判断是否为子集                           |
|                | `issuperset(set)`               | 判断是否为超集                           |
|                | `isdisjoint(set)`               | 判断是否无交集                           |
|                | `copy()`                        | 返回frozenset的浅拷贝                   |
| **dict**       | `keys()`                        | 返回所有键的视图                          |
|                | `values()`                      | 返回所有值的视图                          |
|                | `items()`                       | 返回所有(键,值)对的视图                     |
|                | `get(key[, default])`           | 获取键的值，不存在返回默认值                    |
|                | `setdefault(key[, default])`    | 获取键的值，不存在则设置默认值                   |
|                | `pop(key[, default])`           | 移除并返回键的值                          |
|                | `popitem()`                     | 移除并返回最后一个(键,值)对                   |
|                | `update([other])`               | 用另一个字典更新当前字典                      |
|                | `clear()`                       | 清空字典                              |
|                | `copy()`                        | 返回字典的浅拷贝                          |
|                | `fromkeys(iterable[, value])`   | 从可迭代对象创建新字典（类方法）                  |
| **bytes**      | `decode(encoding='utf-8')`      | 将字节串解码为字符串                        |
|                | `hex()`                         | 返回字节串的十六进制表示                      |
|                | `fromhex(string)`               | 从十六进制字符串创建字节串（类方法）                |
|                | `replace(old, new)`             | 替换字节子串                            |
|                | `find(sub[, start[, end]])`     | 查找子串位置                            |
|                | `split([sep])`                  | 分割字节串                             |
|                | `count(sub)`                    | 统计子串出现次数                          |
|                | `startswith(prefix)`            | 判断是否以指定前缀开头                       |
|                | `endswith(suffix)`              | 判断是否以指定后缀结尾                       |
| **bytearray**  | `append(x)`                     | 在末尾添加一个字节                         |
|                | `extend(iterable)`              | 扩展字节数组                            |
|                | `insert(i, x)`                  | 在指定位置插入字节                         |
|                | `pop([i])`                      | 移除并返回指定位置的字节                      |
|                | `remove(x)`                     | 移除第一个值为x的字节                       |
|                | `reverse()`                     | 原地反转字节数组                          |
|                | `decode(encoding='utf-8')`      | 解码为字符串                            |
|                | `hex()`                         | 返回十六进制表示                          |
| **memoryview** | `tolist()`                      | 返回缓冲区数据的列表表示                      |
|                | `tobytes()`                     | 返回缓冲区数据的字节串                       |
|                | `cast(format[, shape])`         | 将内存视图转换为新的格式或形状                   |
|                | `release()`                     | 释放内存视图的缓冲区                        |
|                | `.obj`                          | 内存视图引用的底层对象（属性）                   |
|                | `.nbytes`                       | 缓冲区总字节数（属性）                       |
|                | `.readonly`                     | 缓冲区是否只读（属性）                       |
|                | `.format`                       | 缓冲区中元素的格式描述（属性）                   |
|                | `.shape`                        | 缓冲区形状的元组（属性）                      |
|                | `.strides`                      | 缓冲区步长的元组（属性）                      |