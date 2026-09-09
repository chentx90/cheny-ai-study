# W21_Python_04 · 调天气 API

## 题目

写一个脚本 `weather_api.py`：

1. 调用 wttr.in 的免费天气 API：`https://wttr.in/{城市}?format=j1`
2. 解析返回的 JSON，提取以下字段并格式化输出：
   - 城市名
   - 当前温度（℃）
   - 体感温度（℃）
   - 天气描述（中英文都可）
   - 湿度（%）
   - 风速

3. 把结果**同时**：
   - 打印到控制台（人类可读格式）
   - 保存到 `weather.json`（结构化）

4. 必须处理 4 类异常：
   - 网络连不上（ConnectionError）
   - 超时（Timeout）
   - HTTP 错误（HTTPError，比如 404 城市不存在）
   - JSON 解析失败（如果响应不是合法 JSON）

## 约束

- 必须用 `requests` 库
- 必须设置 `timeout=10`
- 必须用上一题写的 `Logger` 类记录日志（**关键：体验跨文件 import**）
- 必须用类型注解
- 必须用 `pathlib.Path` 处理文件路径
- 必须有 `if __name__ == "__main__":`
- 至少 3 个测试用例（正常城市 / 不存在城市 / 网络异常模拟）

## 验收标准

- [x] 调用 `weather("Beijing")` 能正常返回数据
- [x] 控制台输出格式美观（不是裸 print 一坨字典）
- [x] `weather.json` 文件生成，内容是结构化字段
- [x] Logger 记录了至少 1 条 info 和 1 条 error 级别日志
- [x] 网络断开 / 城市不存在时不崩，输出友好错误

## 进阶（选做）

- [x] 支持中文城市名（用 urllib.parse.quote 编码）
- [x] 把多个城市的结果存成列表
- [x] 加个简单的内存缓存（同一城市 5 分钟内不重复请求）

---

## 你的思路（必答 4 题）

> 写完贴给我看，我审过你才能动代码。这次试试**不抄模板，自己写**。
> 写不出来就写"卡"，我给提示。

1. **请求函数和解析函数要不要分开？**
   提示：`requests.get(...)` 是带副作用的（依赖网络），解析 JSON 是纯计算。回想昨天 line_stats 的"纯函数 vs 带副作用"原则。
   - 分开请求是对外的有副作用，解析是内部的
2. **Logger 实例放在哪儿？模块顶层创建一个，还是每次调用 weather() 时创建？**
   提示：思考"每次都创建"和"全局共享一个"的代价。
   - 全局共享一个
3. **wttr.in 返回的 JSON 结构你打算怎么探查？**
   提示：先在浏览器打开 URL 看一眼结构，记住关键字段路径。
   - 用json工具网站方便看结构
4. **4 类异常你打算放在哪一层处理？**
   提示：a) 都在 weather() 函数里捕获 + 返回 None；b) weather() 抛异常，main 函数统一捕获；c) 混合策略。
   - a
(在这里写)

---

## 你的实现

文件：`01_Python补强/weather_api.py`

## 自测（至少 3 个用例）

- [x] 用例 1：weather("Beijing") 正常城市
- [x] 用例 2：weather("ZZZZZ") 不存在的城市（看返回什么）
- [x] 用例 3：断网测试（断 wifi 跑一次）

## 卡点

- json结构找的麻烦，可以借用工具网站
- 错误类型不熟悉
- ZZZZZ 不存在	拿到 Ernestinental（API 模糊匹配行为）

## 导师反馈

待提交后填写。

##  笔记


### 学到
- OOP：__init__ / 公开方法 / 私有方法 / __repr__ / 类常量
- requests：get / timeout=10 / raise_for_status / 4 类异常
- 跨文件 import：from logger import Logger
- pathlib：parent.mkdir(parents=True, exist_ok=True)
- urllib.parse.quote：URL 里凡是用户输入永远 quote

### 直觉
- HTTP 200 ≠ 业务正确（wttr.in 模糊匹配 ZZZZZ → Ernestinental）
- 缓存只存不删 = 过期条目堆积（不算泄漏但是逻辑不完整）
- 人看的（日志）和机器看的（URL）要分开

### 下次注意
- city = quote(city) 这种"原变量被覆盖"是代码气味