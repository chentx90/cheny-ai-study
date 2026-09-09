# 代码 Review 与各模块修改方案

> **【历史归档 · 2026-07-06】** 本文记录早期 MVP 断链问题，**不代表当前代码状态**。  
> 现状请看：`README.md`、`docs/00_项目结构.md`、`docs/09`、`docs/11`、`docs/10`。

**Review 日期**: 2026-07-06
**Review 范围**: `src/ai_video_manager/` 全部后端代码、`tests/`、`frontend/src/main.jsx`
**结论**: MVP 骨架已成型，模型层和策略层设计合理，但存在 **2 个致命缺陷（P0）**、多个功能性缺陷（P1）和若干与流程设计（canvas v2）不一致的缺失能力（P2）。当前状态下 CLI 无法运行、前端无法与后端联通。

---

## 问题分级总览

| 级别 | 数量 | 说明 |
|------|------|------|
| P0 致命 | 2 | 程序无法运行 / 前后端断链 |
| P1 缺陷 | 9 | 功能错误、数据丢失风险、安全问题 |
| P2 缺失 | 8 | canvas 设计中有、代码中未实现的能力 |

---

## P0-1: `storage.py` 不存在，CLI 完全不可用

`cli.py:9` 引用了不存在的模块：

```python
from .storage import SQLiteStore, model_to_dict   # ModuleNotFoundError
```

`ai-video-manager init` / `ingest` 全部崩溃。

**修改方案**：新建 `src/ai_video_manager/storage.py`，实现最小可用的 SQLiteStore：

```python
class SQLiteStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # 必须实现（cli.py 已引用）
    def save_project(self, project: Project) -> Project: ...
    def save_document(self, document: Document) -> Document: ...
    def save_segments(self, segments: list[Segment]) -> None: ...
    # cli.py 转换了 scripts 却没保存 —— 补上
    def save_scripts(self, scripts: list[Script]) -> None: ...
    # API 层需要
    def get_project(self, project_id: str) -> Project | None: ...
    def list_projects(self) -> list[Project]: ...
    def save_workspace(self, project_id: str, data: dict) -> None: ...
    def load_workspace(self, project_id: str) -> dict: ...
    def save_template(self, template: PromptTemplate) -> None: ...
    def list_templates(self) -> list[PromptTemplate]: ...
    def save_checkpoint(self, checkpoint: Checkpoint) -> None: ...

def model_to_dict(obj) -> dict:
    return asdict(obj)   # dataclasses.asdict + enum/datetime 序列化
```

表结构直接采用 `docs/02_技术架构设计.md` 中已定义的 schema，另加 `workspaces(project_id TEXT PRIMARY KEY, data TEXT)` 表支撑前端工作区持久化。

同时修复 `cli.py`：`init` 命令要真正建库（当前只打印 JSON 什么都不做）；`ingest` 补 `store.save_scripts(scripts)`。

## P0-2: 后端 API 未实现，前端全部调用悬空

`api/__init__.py` 只有一行 docstring。前端 `main.jsx` 依赖以下 10 个端点，全部 404：

```
GET  /api/health
GET  /api/projects            POST /api/projects
GET  /api/projects/{id}       GET/PUT /api/projects/{id}/workspace
POST /api/documents/split     POST /api/segments/convert
POST /api/entities/extract    GET/POST /api/prompts/templates
POST /api/prompts/render      POST /api/videos/generate
GET/PUT /api/config/apis
```

**修改方案**：新建 `api/app.py`，用 FastAPI 组装现有模块（模块层代码是可用的，只缺胶水层）：

```python
def create_app(store: SQLiteStore | None = None) -> FastAPI:
    app = FastAPI(title="ai-video-manager")
    app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5173"], ...)
    store = store or SQLiteStore("database/app.db")
    processor = DocumentProcessor()
    entity_manager = EntityManager()
    prompt_engine = PromptEngine(store.list_templates() or None)
    video_engine = VideoGenerationEngine()
    # ... 按上表逐个实现路由，全部走 Pydantic request/response model
```

要点：
- 所有请求体用 Pydantic 模型定义（当前 pyproject 已有 pydantic 依赖）。
- `/api/config/apis` 的 GET **绝不能回传 apiKey 明文**（见 P1-8）。
- `/api/videos/generate` 内部走 `WorkflowEngine.can_jump_to` 校验前置条件，保证"前置信息足够才能从任意节点往下走"的规则在服务端强制执行，而不是只靠前端判断。
- 补 `uvicorn ai_video_manager.api.app:app` 的启动说明和 `[project.scripts]` 入口。

---

## P1 各模块缺陷与修改方案

### P1-1 document_processor: 章节切分丢失首章之前的内容

`ChapterSplitStrategy.split` 从第一个章节标题的 `match.start()` 开始取片段，**第一个章节标记之前的序言/引子会被静默丢弃**。

```python
# 修复：保留 preamble
matches = list(self.chapter_pattern.finditer(text))
if not matches:
    return [text]
segments = []
preamble = text[: matches[0].start()].strip()
if preamble:
    segments.append(preamble)
# ... 其余不变
```

### P1-2 document_processor: LengthSplitStrategy 硬切断句子

超长段落按 `max_chars` 硬切，会把句子从中间截断，直接影响后续剧本转换质量。改为按句子边界切分：

```python
sentence_pattern = re.compile(r"(?<=[。！？!?])")
# 超长段落先按句子切，再拼装到 max_chars，仅当单句超长才硬切
```

### P1-3 document_processor: `convert_to_script` 是伪转换

当前实现只是把第一行当【场景】、其余全部塞进一句"旁白"，不是真正的剧本转换，也没有 canvas 流程中的"转换合格判断→不合格重转"环路。

**修改方案**（分两步走）：
1. 引入 `LLMClient` 协议 + `MockLLMClient`（离线可测试），`convert_to_script(segment, template)` 走 PromptEngine 的 `SCRIPT_CONVERT` 模板调用 LLM；
2. 增加 `validate_script(script) -> ScriptValidation`，校验产出是否包含【场景】【动作】【对白】结构，不合格返回原因供 UI 展示与重转。当前的规则式实现保留为 `MockLLMClient` 的行为，保证无 API Key 时流程可跑通。

### P1-4 entity_manager: 正则提取覆盖率极低，与设计不符

三个问题：
- `prop_pattern` 是 13 个道具的硬编码白名单，白名单外的道具全部漏提；
- `action_name_pattern` 只识别 7 个动词后缀的人名；
- `_infer_state` 的"新"字匹配过宽（"新闻"、"重新"都会误判为"崭新"）。

**修改方案**：与 P1-3 同构 —— 主路径走 LLM（`ENTITY_EXTRACT` 提示词模板 + JSON 输出解析 + 失败重试一次），现有正则实现降级为 `RegexEntityExtractor` 兜底/离线方案。`_infer_state` 修正为词表精确匹配：`("崭新", "全新", "新的")`，去掉裸"新"。另外把 `dialogue_pattern` 的名字长度上限 12 和 `_looks_like_character` 的上限 6 统一（建议统一为 2-6）。

### P1-5 prompt_engine: `str.format` 渲染在模板含字面花括号时崩溃

模板里一旦出现 `{"style": ...}` 这类 JSON 示例就抛 KeyError/IndexError。且 `variables` 字段声明了但渲染时不用（实际靠解析模板），两者可能不一致。

**修改方案**：
- 保持轻量不引入 Jinja2 的话，改用 `string.Template`（`$script` 语法，`safe_substitute` + 显式缺变量检查）；或规定模板转义 `{{`/`}}` 并在 `add_template` 时校验。
- `add_template` 时校验"解析出的占位符 == 声明的 variables"，不一致直接拒绝，把错误暴露在录入时而不是渲染时。

### P1-6 prompt_engine: 默认模板 ID 每次启动重新生成

`DEFAULT_TEMPLATES` 是模块级构造，每次进程重启 `tpl_xxx` ID 变化，前端/工作区里存过的模板引用全部失效。

**修改方案**：默认模板给固定 ID（如 `tpl_default_script_convert`）；用户新建模板经 storage 持久化，PromptEngine 启动时从 SQLite 加载。

### P1-7 workflow: 前置条件过松，可跳过视频生成直达"已完成"

`prerequisites` 中 `VIDEO_GENERATING` 和 `VIDEO_COMPLETED` 都只要求 `has_prompts`，意味着可以从未生成任何视频的状态直接 `jump_to(VIDEO_COMPLETED)`。且 `ASSETS_CONFIRMED` 没有任何确认门槛，"质量优先、每步人工确认"的核心需求在状态机层面没有落地。

**修改方案**：
```python
# Project 增加字段
assets_confirmed: bool = False
has_completed_video: bool = False

prerequisites = {
    ...
    WorkflowState.ASSETS_CONFIRMED: ("has_prompts",),
    WorkflowState.VIDEO_GENERATING: ("has_prompts", "assets_confirmed"),
    WorkflowState.VIDEO_COMPLETED: ("has_completed_video",),
}
```
`assets_confirmed` 只能由两个来源置 True：用户在 UI 明确点击确认，或全局配置 `autoApprove=True`（对应 canvas 的"默认自动同意开关"）。这样付费生成前的确认闸门是服务端强制的。

### P1-8 【安全】API Key 明文往返

前端 `SettingsView` 把 `llmApiKey`/`videoApiKey` 明文 PUT 到 `/api/config/apis`，并期望 GET 时原样返回填充到表单。密钥出现在浏览器内存、network 面板和后端响应里。

**修改方案**：
- 后端 GET 只返回掩码（`sk-***abcd`）和 `hasKey: true`；
- PUT 时空值表示"不修改"，仅显式提交才覆盖；
- 密钥存储位置从 workspace JSON 挪到独立 config 文件/表，本地静态加密（如 Fernet + 机器绑定 key），至少不进项目工作区数据。

### P1-9 video_generation: 状态只查一次、批量无并发无错误隔离

- `generate_*` 调 `generate()` 后立刻 `check_status()` 一次就返回，真实视频 API 是长任务，这里永远拿到 processing；
- `batch_generate` 串行 await，且任何一个任务抛异常整批中断；
- `download_result` 定义了但从未被调用，`task.result_path` 永远为 None。

**修改方案**：
```python
async def wait_until_done(self, task, timeout=600, interval=5):
    while elapsed < timeout:
        status = await self.api_client.check_status(task.api_task_id)
        if status in (COMPLETED, FAILED): break
        await asyncio.sleep(interval)
    if status is COMPLETED:
        task.result_path = self._archive_path(task)
        await self.api_client.download_result(task.api_task_id, task.result_path)

async def batch_generate(self, tasks, concurrency=2):
    sem = asyncio.Semaphore(concurrency)   # 付费 API 控制并发上限
    results = await asyncio.gather(*(self._run_one(sem, t) for t in tasks),
                                   return_exceptions=True)
    # 单任务失败标记 FAILED，不影响其他任务
```

---

## P2 与 canvas v2 流程设计的差距（按优先级排序）

| # | canvas 设计能力 | 当前状态 | 落地建议 |
|---|----------------|---------|---------|
| 1 | 检查点持久化、可从任意检查点重启 | CheckpointManager 纯内存，重启即失 | Checkpoint 写入 SQLite（storage.py 已规划表），API 补 `GET /api/checkpoints/{project_id}` 和 `POST /api/checkpoints/load` |
| 2 | 实体库管理界面（实体·状态卡片 + 素材绑定） | EntityCard 模型有了，但无持久化、无 API、无 UI | storage 增 entity_cards 表；API 增 CRUD + `POST /api/entities/smart-bind`（smart_bind 代码已有，只缺暴露） |
| 3 | 默认自动同意开关贯穿全流程 | 前端有 checkbox，后端无任何消费方 | 见 P1-7，配置进入 WorkflowEngine 判定 |
| 4 | 按剧情时长切分（默认 2min） | 只有按字符数 | 增 `DurationSplitStrategy(minutes=2)`：中文按 ~300 字/分钟估算映射为字符预算，复用句子边界切分 |
| 5 | AI 智能切分建议 | 无 | `POST /api/documents/split/suggest`：返回三种策略的预览结果（片段数+首行摘要），前端做方案对比选择，本身不需要 LLM 也能先做 |
| 6 | 视频归档 + 回溯重发 | VideoTask 无归档目录结构、无重发 | 归档路径 `projects/{id}/generated/{segment}/{v1,v2...}`；`POST /api/videos/tasks/{id}/retry` 复制参数新建任务，旧任务保留 |
| 7 | 版本管理（模板 A/B 结果对比） | 无 | 先做最小版：VideoTask 保留全部历史 + 按 segment 分组展示，即可满足"对比不同提示词的产出"；完整 Version 表放后期 |
| 8 | 流程进度追踪面板 | 无 | `GET /api/projects/{id}/state` 返回 current_state + 各 has_* 标志，前端渲染步骤条即可，成本很低 |

---

## 测试现状与补齐要求

现有测试仅 9 个用例，全部 happy-path。按 docs/03 的 TDD 规范，修复以上问题时必须同步补：

1. **回归用例（先写，红→绿）**：
   - `test_chapter_split_keeps_preamble`（P1-1）
   - `test_length_split_does_not_break_sentences`（P1-2）
   - `test_render_prompt_with_literal_braces`（P1-5）
   - `test_cannot_jump_to_video_completed_without_video`（P1-7）
   - `test_batch_generate_isolates_failures`（P1-9）
2. **API 层测试**：httpx 依赖已在 dev extras 里，用 `TestClient` 对 10 个端点各写至少一条正常 + 一条 422/400 用例。
3. **storage 测试**：用 `:memory:` SQLite 跑全部 CRUD 往返。

## 建议执行顺序

1. **第 1 步（解阻塞）**: storage.py + api/app.py + CORS —— 让系统先能跑通端到端（P0）。
2. **第 2 步（改正确性）**: P1-1/2/5/6/7 —— 纯本地逻辑，改动小收益大，先行合并。
3. **第 3 步（安全）**: P1-8 密钥处理。
4. **第 4 步（真实生成链路）**: P1-3/4/9 —— 引入 LLMClient 抽象与轮询下载。
5. **第 5 步（补齐设计）**: P2 按表中顺序推进，1/2/3 优先（检查点、实体库、自动同意开关是 canvas 的核心差异化能力）。

---

**关联文档**: [05_前端设计逻辑.md](05_前端设计逻辑.md)（本次 review 中前端问题及重构方案单独成文）
