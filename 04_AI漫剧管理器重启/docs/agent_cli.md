# CLI-TOOL-NAME: manga

- **核心功能**: 将小说原文按受控管线转换为 episode、entities、shots、bindings、video prompts，并可调用 Pippit 生成视频。
- **适用场景**: 仅用于当前 AI 漫剧项目管理、阶段生成、实体媒体绑定、Pippit 提交与结果归档；禁止用于任意 JSON 数据库式 CRUD。
- **依赖环境**: Python >= 3.11；必须在 `<REPO_ROOT>\06_项目作品集\04_AI漫剧管理器重启` 运行，或确保 `PYTHONPATH` 指向 `src`；Pippit 功能需要 `pippit-tool-cli` 在 `$PATH` 中。
- **副作用**: 读写 `data/works/<work_id>/`；LLM 阶段会调用外部模型；Pippit 阶段会调用小云雀/Pippit 并可能产生费用。
- **超时建议**: 普通查询 30s；S2/S4/S6 建议 10-30 分钟；`pippit-video` 默认 timeout 3600s。
- **Agent 输出原则**: 当前普通业务命令不支持 `--json`。Agent 必须先调用 `python -m manga_manager.cli --agent-docs` 获取机器可读元数据；解析普通输出时必须检查 exit code，并优先直接读取结构化 JSON 文件验证结果。

## 精确命令语法 (MUST follow this exact pattern)

全局入口：

```bash
python -m manga_manager.cli [GLOBAL_OPTIONS] COMMAND [COMMAND_OPTIONS] [ARGS]
manga [GLOBAL_OPTIONS] COMMAND [COMMAND_OPTIONS] [ARGS]
```

规则：

- `COMMAND` 必须是 `init`, `use`, `list`, `info`, `log`, `validate`, `source`, `segment`, `bible`, `bind`, `bind-media`, `assets`, `pippit-video`, `summary`, `screenplay`, `continuity`, `video-prompt`, `clear` 之一。
- `GLOBAL_OPTIONS` 必须位于 `COMMAND` 之前；当前唯一 Agent 全局选项是 `--agent-docs`。
- `COMMAND_OPTIONS` 必须位于对应 `COMMAND` 之后。
- `--work <work_id>` / `-w <work_id>` 必须显式传给需要定位作品的命令，除非 Agent 已确认当前活动作品正确。
- 禁止直接编辑 `data/works/<work_id>/` 下的 JSON 来绕过 schema；必须使用 CLI、经 `pydantic` schema 校验的脚本，或先备份再迁移。

## 参数逻辑矩阵

| 参数 | 类型 | 必填 | 约束/可选值 | 联动逻辑 |
|---|---:|---:|---|---|
| `--work`, `-w` | String | 条件必填 | 作品 ID、ID 前缀或标题 | 所有读写作品的命令必须显式指定，除非 `manga use <work_id>` 已设置当前活动作品。 |
| `--agent-docs` | Boolean | 否 | 隐藏全局选项 | 只输出 CLI 元数据 JSON；不调用业务命令；不依赖当前作品。 |
| `--yes`, `-y` | Boolean | 否 | true/false | 跳过人工确认；不能跳过 schema error、Pippit API 失败、缺失文件等硬错误。 |
| `--dry-run` | Boolean | 否 | true/false | 仅 `pippit-video` 使用；只打印将提交给 Pippit 的命令；不提交、不下载、不写 run 记录。 |
| `--fix-index` | Boolean | 否 | true/false | 仅 `validate` 使用；会重建 `index.json`；执行前必须备份目标作品。 |
| `--refresh` | Boolean | 否 | true/false | 仅 `summary` 使用；会删除已有 `summaries/*.json` 后重跑；执行前必须备份。 |
| `--reset` | Boolean | 否 | true/false | 仅 `video-prompt` 使用；忽略 S6 游标并覆盖已有提示词；执行前必须备份。 |
| `--episode`, `-e` | Int | 条件必填 | 0-based 集号 | `--from-scene` / `--to-scene` 必须与 `-e` 同时使用。 |
| `--from-scene` | Int | 否 | >= 0 | 必须小于等于 `--to-scene`；必须和 `-e` 同时使用。 |
| `--to-scene` | Int | 否 | >= 0 | 必须大于等于 `--from-scene`；必须和 `-e` 同时使用。 |
| `--workers`, `-j` | Int | 否 | >= 1 | 控制 LLM 并发；失败时降低并发重试。 |
| `--limit`, `-n` | Int | 否 | > 0 | 仅测试/小范围 S6 使用；限制生成场景数。 |
| `--kind` | String | 必填 | `image`, `audio`, `video` | 仅 `bind-media` 使用；后缀必须匹配媒体类型。 |
| `--prompt` | String | 条件必填 | 非空 | 覆盖默认 `video_prompts/<scene_id>.txt`。 |
| `--prompt-file`, `-p` | Path | 条件必填 | 必须存在且可读 | 与 `--prompt` 二选一；未指定时读取 `video_prompts/<scene_id>.txt`。 |
| `--output-dir`, `-o` | Path | 否 | 合法目录 | 未指定时写入 `data/works/<work_id>/generated_videos/<scene_id>`。 |
| `--duration` | Int | 否 | > 0 | 传给 `pippit-tool-cli generate-video`。 |
| `--ratio` | String | 否 | 如 `9:16` | 默认 `9:16`。 |
| `--model` | String | 否 | Pippit 支持模型 | 默认 `Seedance_2.0_mini_lite`。 |
| `--resolution` | String | 否 | Pippit 支持分辨率 | 默认 `720p`。 |
| `--poll-interval` | Float | 否 | > 0 | 默认 15s。 |
| `--timeout` | Float | 否 | > 0 | 默认 3600s；超时 exit code 2。 |
| `--download` / `--no-download` | Boolean | 否 | true/false | 默认 true；false 时只提交并写 run 记录，不轮询下载。 |
| `--include-images` / `--no-images` | Boolean | 否 | true/false | 默认 true；控制是否携带场景实体图片。 |
| `--include-audios` / `--no-audios` | Boolean | 否 | true/false | 默认 true；控制是否携带场景实体音频。 |
| `--include-videos` / `--no-videos` | Boolean | 否 | true/false | 默认 true；控制是否携带场景实体视频。 |

## 输入/输出契约

### 成功输出 (Exit Code 0)

- **Human Mode**: 默认输出 Rich 表格、Panel 或纯文本。
- **Agent Mode (RECOMMENDED for metadata)**: 必须使用：
  ```bash
  python -m manga_manager.cli --agent-docs
  ```
  返回 JSON 元数据，包含 tool、commands、data_flow、safety_rules、env、working_directory。
- **结构化数据验证**: 普通命令执行后，Agent 必须直接读取对应 JSON/TXT 文件验证，而不是只依赖控制台摘要。

### 失败输出 (Exit Code 非 0)

| Code | 含义 | 修复建议 |
|---:|---|---|
| 1 | 参数错误、文件缺失、schema 校验失败、LLM 阶段失败、Pippit 结果失败 | 读取 stderr/控制台错误；检查 `--work`、文件路径、schema、前置阶段。 |
| 2 | Pippit 等待结果超时、Typer 命令缺失 | `pippit-video` 超时后不要盲目重试；先用 `thread_id/run_id` 查询或检查网络/key。 |
| 非 0 | `pippit-tool-cli` 自身失败 | 读取 Pippit stderr；检查 `XYQ_ACCESS_KEY`、媒体路径、文件后缀、数量限制。 |

### 普通命令输出限制

当前 CLI 不提供 `--json` 业务输出。Agent 必须遵守：

1. 执行命令后检查 exit code。
2. 对 JSON 阶段产物，直接读取 `data/works/<work_id>/...` 下文件。
3. 对 Pippit 结果，读取 `pippit_runs/<scene_id>.json` 和 `generated_videos/<scene_id>/`。
4. 不把彩色表格作为唯一事实来源。

## 执行逻辑决策流 (Agent Decision Flow)

1. 如果 Agent 不知道工作目录，必须声明并使用：
   ```bash
   cd <REPO_ROOT>\06_项目作品集\04_AI漫剧管理器重启
   ```
2. 如果 Agent 不知道作品 ID，必须先运行：
   ```bash
   python -m manga_manager.cli list
   ```
3. 如果命令会读写作品，必须优先加：
   ```bash
   --work <完整 work_id>
   ```
4. 如果命令会修改结构数据，必须先备份目标文件到：
   ```text
   data/works/<work_id>/export/_backups/<timestamp>/
   ```
5. 如果命令是 `validate --fix-index`、`clear`、`summary --refresh`、`video-prompt --reset`，必须先确认影响范围；默认不得自动执行。
6. 如果命令是 `segment` 或 `bible`，默认必须等待人工确认；除非用户明确要求 `--yes`。
7. 如果命令是 `pippit-video`：
   - 未设置 `XYQ_ACCESS_KEY` 时不得实际提交。
   - 首次调用必须使用 `--dry-run`。
   - 未明确确认费用风险时不得加 `--yes`。
8. 如果输出 exit code 非 0，Agent 不应重复执行同一命令；必须先修复错误原因。
9. 如果需要增删改查任意 JSON 节点，当前 CLI 不完整；必须使用 schema 校验脚本或新增 typed CRUD 命令，禁止自然语言直接改 JSON。

## 数据流转

| 阶段 | 命令 | 输入 | 输出 | 是否断点续跑 | 是否人工确认 |
|---|---|---|---|---|---|
| M0 | `init` | 标题 | `work.json`, `style_guide.json`, `index.json`, `entities/*.json`, `run_state.json` | 否 | 否 |
| Source | `source import` | 原文文件 | `source.txt`, `work.json.source_meta` | 否 | 否 |
| S1 | `segment` | `source.txt` | `episodes/*.json`, `index.json`, `run_state.cursor.done_scenes` | 是 | 是，除非 `--yes` |
| S2 | `bible` | `source.txt`, `episodes/*.json` | `entities/characters.json`, `locations.json`, `props.json`, `relations.json`, `index.json` | 是 | 是，除非 `--yes` |
| S3 | `summary` | `episodes`, `source`, 上下文 | `summaries/*.json`, `run_state.cursor.done_episodes` | 是 | 否 |
| S4 | `screenplay` | `episodes`, `summaries`, `entities` | `shots/*.json`, `run_state.cursor.done_screenplay_scenes` | 是 | 否 |
| S5 | `continuity` | `shots/*.json`, `entities` | `bindings/*.json`, `run_state.cursor.done_binding_scenes` | 是 | 否 |
| S6 | `video-prompt` | `episodes`, `summaries`, `shots`, `bindings`, `entities`, `config.toml` | `video_prompts/*.txt`, `run_state.cursor.done_video_prompt_scenes` | 是 | 否 |
| Pippit | `pippit-video` | `bindings/*.json`, 实体媒体, `video_prompts/*.txt` | `generated_videos/<scene_id>/`, `pippit_runs/<scene_id>.json` | 否 | 是，除非 `--yes` |

## 文件保存与结构保护

- 所有 JSON 写入必须走 `store.write_json_atomic()`：先写临时文件，再 `os.replace()` 原子替换。
- 所有结构写入必须通过 `store.write_lock()` 获取单写者锁，防止并发写坏 `index.json`。
- `save_entities()` 必须按类型写回：
  - `entities/characters.json`
  - `entities/locations.json`
  - `entities/props.json`
  - 并重建 `index.json`
- `validate()` 必须校验：
  - `work.json`
  - `style_guide.json`
  - `index.json`
  - `run_state.json`
  - `entities/*.json`
  - `episodes/*.json`
  - `shots/*.json`
  - `bindings/*.json`
  - `summaries/*.json`
- `index.json` 只能由 `build_index()` / `rebuild_index()` 生成；禁止手写。
- 媒体绑定必须复制到 `assets/<entity_id>/`，JSON 只保存相对路径。
- 绑定路径必须以 `assets/` 开头，且文件必须存在。

## 人工确认时机

| 命令 | 默认行为 | 跳过确认 | 禁止跳过 |
|---|---|---|---|
| `segment` | 预览后询问 `y/n` | `--yes` | error 级 L1 问题不可跳过 |
| `bible` | 写入后要求确认设定库 | `--yes` 只记录 approved | 不阻止数据已写入磁盘 |
| `pippit-video` | 提交前询问费用风险 | `--yes` | 未设置 `XYQ_ACCESS_KEY` 时不得提交 |
| `clear` | 删除前询问 | `--yes` | 未备份前不得自动执行 |
| `validate --fix-index` | 无确认 | 无 | 执行前必须备份 |
| `summary --refresh` | 无确认 | 无 | 执行前必须备份 |
| `video-prompt --reset` | 无确认 | 无 | 执行前必须备份 |

## 受影响的 ENV

- `MANGA_DATA_DIR`: 如果设置，作品目录从该目录读取；否则默认使用当前项目 `data/works/`。
- `XYQ_ACCESS_KEY`: `pippit-video` 实际提交小云雀/Pippit 时必须设置。
- `LLM_API_KEY`: LLM 阶段必须设置，或使用 `config.toml` 中的 `llm.api_key`。
- `LLM_MODEL`: 覆盖 `config.toml` 的 `llm.model`。
- `LLM_BASE_URL`: 覆盖 `config.toml` 的 `llm.base_url`。
- `MANGA_CONTEXT_MAX_TOKENS`: 覆盖 `config.toml` 的上下文 token 预算。
- `NO_COLOR`: 可减少部分终端颜色干扰；普通命令仍可能包含 Rich 表格，Agent 必须检查 exit code。

## 错误处理规则

1. 文件不存在：
   - 命令必须停止。
   - Agent 必须检查路径、`--work`、当前工作目录。
2. JSON schema 错误：
   - 命令必须停止。
   - Agent 必须读取错误路径并修复 schema，不得继续下游阶段。
3. `index.json` 不一致：
   - `validate` 默认只报告错误。
   - 只有明确执行 `--fix-index` 才重建索引。
   - `--fix-index` 前必须备份。
4. LLM 阶段失败：
   - `segment`, `bible`, `summary`, `screenplay`, `video-prompt` 必须报告失败场景/集。
   - Agent 必须降低 `--workers` 或修复输入后重试失败范围。
5. Pippit 提交失败：
   - 不得自动重试同一 prompt/media 组合，除非错误明确是网络瞬断。
   - 必须检查 `XYQ_ACCESS_KEY`、媒体后缀、媒体数量、文件是否存在。
6. Pippit 查询超时：
   - exit code 2。
   - Agent 必须保留 `thread_id/run_id`，不得丢失 run 记录。

## 标准调用示例

### 示例 1：获取 Agent 元数据并检查 exit code

**意图**: 获取机器可读 CLI 元数据。

```bash
python -m manga_manager.cli --agent-docs
```

**期望 STDOUT**:

```json
{
  "tool": "manga",
  "commands": {
    "init": {"syntax": "manga init <title>"}
  },
  "safety_rules": []
}
```

**注意**: 普通业务命令当前不支持 `--json`；`--agent-docs` 只输出元数据，不输出业务数据。

### 示例 2：完整 S6 到 Pippit dry-run

**意图**: 为作品 `w42302f6a` 生成第 0 集第 0 场视频提示词，并预览 Pippit 将使用的媒体。

```bash
python -m manga_manager.cli video-prompt -e 0 --from-scene 0 --to-scene 0 --workers 1 --work w42302f6a
python -m manga_manager.cli pippit-video s00000_dbd4 --dry-run --work w42302f6a
```

**期望 STDOUT 关键信息**:

```text
场景: s00000_dbd4
图片: <n> / 9
视频: <n> / 3
音频: <n> / 3
提示词: data/works/w42302f6a/video_prompts/s00000_dbd4.txt
Dry run：未提交 Pippit
```

**注意**: dry-run 不设置 `XYQ_ACCESS_KEY`，不提交 Pippit，不产生费用。

### 示例 3：安全清空 S6 后重跑

**意图**: 删除旧视频提示词并重新生成，必须先备份。

```bash
python -m manga_manager.cli validate --work w42302f6a
# 手动或脚本备份 data/works/w42302f6a/video_prompts/*.txt 到 export/_backups/<timestamp>/
python -m manga_manager.cli clear s6 --work w42302f6a
python -m manga_manager.cli video-prompt -e 0 --reset --workers 1 --work w42302f6a
```

**注意**: `clear s6 -y` 会直接删除文件；Agent 默认不得自动使用 `-y`。

## 当前数据查询/修改能力评估

- 当前 CLI 支持：`list`, `info`, `log`, `assets`, `validate`，以及阶段产物文件直接读取。
- 当前 CLI 不支持：任意 JSON 节点的 create/read/update/delete。
- 当前 CLI 不支持：普通业务命令 `--json` 输出。
- 当前 CLI 支持：`--agent-docs` 输出工具元数据 JSON。
- 结论：当前数据查询指令不完整。Agent 不得假设可以通过自然语言指令增删改查所有 JSON 文件；必须使用 CLI、schema 校验脚本，或先实现 typed CRUD 命令。
