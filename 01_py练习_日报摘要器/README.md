# 日报摘要器 V1

把工作日报文字提取成结构化 JSON 的 CLI 工具。

## 功能

- 输入：一段日报文字（命令行直接传，或从 .txt 文件读）
- 输出：归类到 4 个类别的 JSON
  - **完成项**：今天/这周已经做完的事
  - **进行中**：正在进行但未完成的事
  - **计划项**：明天/下周打算做的事
  - **风险点**：阻塞/问题/需要支持的事
- 自动保存历史到 `history/` 目录

## 项目结构

```
01_日报摘要器/
├── main.py             # CLI 主入口
├── llm_client.py       # OpenAI 兼容协议封装（基础设施）
├── prompts.py          # Prompt 集中管理
├── sample_report.txt   # 测试样本
├── history/            # 调用历史（按时间戳命名）
└── README.md
```

## 用法

```bash
# 直接传字符串
python main.py --text "今天完成了订单接口，明天要修支付 bug"

# 从文件读
python main.py --input sample_report.txt

# 指定输出路径
python main.py --input sample_report.txt --output result.json
```

## 配置

需要在项目根目录的 `.env` 里配置：

```
LLM_BASE_URL=http://localhost:3000
LLM_API_KEY=sk-xxx
LLM_MODEL=deepseek-chat
LLM_TIMEOUT=30
```

## 已知限制（V1）

- 不支持流式输出（V2 加）
- 不支持批量处理多个文件（V2 加）
- LLM 返回非合法 JSON 时只能失败（无降级解析）
- response_format 参数依赖模型支持，部分模型可能忽略

## 后续路线

- V2：流式输出 + 批量处理 + 解析降级
- V3：多模型对比（同一日报跑多个模型看输出差异）

## 技术栈

- Python 3.11+
- requests · python-dotenv · argparse
- OpenAI 兼容协议（通过 NewAPI 聚合）