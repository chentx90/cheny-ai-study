# AI漫剧管理器（重启版）

小说原文 → 设定库 → 分集/场景 → 剧本/分镜 → 视频提示词，端到端受控 Agent 管线。

每个阶段 LLM 只做 schema→schema 的约束变换，状态住在结构化 JSON 里，随时可手动介入、断点续跑、人工检查。

---

## 快速开始

```bash
pip install -e ".[dev]"

# 1. 创建作品
manga init "妹妹人生"

# 2. 导入原文
manga source import 小说.txt

# 3. 切分集/场景（人工检查点①）
manga segment --episodes 8

# 4. 提取设定库（人工检查点②）
manga bible -j 8

# 5. 生成滚动摘要
manga summary

# 6. 生成分镜剧本
manga screenplay -j 8

# 7. 角色绑定
manga continuity

# 8. 生成视频提示词（第一集前 6 场）
manga video-prompt -e 0 -n 6 --reset -j 1

# 继续生成第一集第 7 到第 20 场（0-based：6 到 19）
manga video-prompt -e 0 --from-scene 6 --to-scene 19 --reset -j 1
```

---

## 管线阶段

```
原文导入
  ↓
S1 Segmenter     — 切集/场景（LLM 识别边界, Python 精确切割）
  ↓  [人工检查点①]
S2 BibleBuilder  — 提取实体/关系设定库（增量去重, 集内并发）
  ↓  [人工检查点②]
S3 Summarizer    — 逐集生成 rolling_summary（前情提要压缩）
  ↓
S4 Screenwriter  — 场景→Shot[]（叙事层, 反思环≤2轮）
  ↓
S5 Continuity    — 角色称呼→entity_id + 精确 variant_label（纯确定性，保留幼年妹妹/幼年妹等称呼）
  ↓
S6 PromptComposer— 原文片段 + Shot[]→视频提示词（三段式, ≤15s/段）
```

---

## 项目结构

```
src/manga_manager/
├── agents/
│   ├── segmenter.py        # S1: 切点识别
│   ├── bible_builder.py    # S2: 实体提取
│   ├── summarizer.py       # S3: 滚动摘要
│   ├── screenwriter.py     # S4: 分镜生成（含反思环）
│   ├── continuity.py       # S5: 确定性角色绑定
│   └── prompt_composer.py  # S6: 视频提示词（系统提示词 + 原文对齐规则）
├── pipeline/
│   ├── s1_segment.py
│   ├── s2_bible.py
│   ├── s3_summary.py
│   ├── s4_screenplay.py
│   ├── s5_continuity.py
│   └── s6_prompt.py
├── models.py               # 全量 Pydantic schema
├── store.py                # JSON 存储层（原子写 + 写锁）
├── context.py              # 上下文组装器（token 预算保护）
├── config.py               # 配置读取
├── llm/client.py           # LLM 客户端封装
└── cli.py                  # Typer CLI 入口

tests/
├── test_m0_store.py        # 3 个测试
├── test_m1_segment.py      # 18 个测试
├── test_m2_bible.py        # 23 个测试
├── test_m3_summary.py      # 23 个测试
├── test_m4_screenplay.py   # 19 个测试
└── test_m5_continuity.py   # 34 个测试

data/works/{work_id}/
├── source.txt              # 唯一原文副本
├── work.json               # 作品元数据
├── style_guide.json        # 风格指南
├── run_state.json          # 当前阶段 + 断点游标
├── index.json              # 实体/场景/镜头索引
├── episodes/               # 集/场景数据 (0000.json …)
├── entities/               # 设定库 (characters / locations / props / relations)
├── summaries/              # 滚动摘要 (0000.json …)
├── shots/                  # 分镜数据 ({scene_id}.json)
├── bindings/               # 角色绑定 ({scene_id}.json)
├── video_prompts/          # 视频提示词 ({scene_id}.txt)
├── assets/                 # 参考媒体 ({entity_id}/{variant_label}[.png|.mp3|.mp4])
├── generated_videos/       # Pippit 下载的视频产物
├── pippit_runs/            # Pippit thread/run 与媒体收集记录
└── operations.jsonl        # 操作日志
```

---

## CLI 命令速查

| 命令 | 阶段 | 说明 |
|---|---|---|
| `manga init <标题>` | M0 | 创建作品 |
| `manga source import <文件>` | M0 | 导入原文 |
| `manga list` | — | 列出所有作品 |
| `manga info` | — | 当前作品概况 |
| `manga segment [-n 集数]` | S1 | 切分集/场景，人工确认 |
| `manga bible [-j 并发]` | S2 | 提取设定库，人工确认 |
| `manga summary` | S3 | 生成滚动摘要 |
| `manga screenplay [-j 并发]` | S4 | 生成分镜 Shot 列表 |
| `manga continuity` | S5 | 角色绑定 |
| `manga video-prompt [-e 集] [-j 并发]` | S6 | 生成视频提示词 |
| `manga video-prompt -e 0 -n 6 --reset -j 1` | S6 | 重置并生成第 0 集前 6 场 |
| `manga video-prompt -e 0 --from-scene 6 --to-scene 19 --reset -j 1` | S6 | 只生成第 0 集第 7 到第 20 场 |
| `manga bind <entity_id> <变体> <图片>` | — | 绑定参考图到实体变体（兼容旧命令） |
| `manga bind-media <entity_id> <变体> <媒体> --kind image\|audio\|video` | — | 绑定图片/音频/视频到实体变体 |
| `manga assets <entity_id>` | — | 查看实体变体与图片/音频/视频资产 |
| `manga pippit-video <scene_id>` | — | 用 Pippit 根据场景提示词和实体媒体生成视频 |
| `manga validate [--fix-index]` | — | 校验数据完整性 |
| `manga log` | — | 查看操作日志 |
| `manga clear <阶段> [-y]` | — | 清空阶段输出 + 重置游标（可用别名 s1-s6） |

所有管线命令均支持断点续跑（默认 `resume=True`）。S6 额外支持范围生成：`--from-scene` / `--to-scene` 为 0-based 闭区间，且必须配合 `-e/--episode` 使用。

## Pippit 生视频

实体变体现在可绑定三类媒体：

- `ref_images`：参考图片，最多 9 张
- `ref_videos`：参考视频，最多 3 个
- `ref_audios`：参考音频，最多 3 个

绑定示例：

```bash
manga bind-media eb50c3b34 "幼年妹妹" refs/sister.png --kind image
manga bind-media eb50c3b34 "幼年妹妹" refs/sister_voice.mp3 --kind audio
manga bind-media eb50c3b34 "幼年妹妹" refs/sister_pose.mp4 --kind video
manga assets eb50c3b34
```

生成视频前，`manga pippit-video <scene_id>` 会从 `bindings/{scene_id}.json` 找到场景实体变体，再收集对应实体 JSON 中的 `ref_images/ref_audios/ref_videos`，传给 `pippit-tool-cli generate-video`。默认读取 `video_prompts/{scene_id}.txt`：

```powershell
$env:XYQ_ACCESS_KEY="你的小云雀 access key"

manga pippit-video s00000_dbd4 --duration 13 --ratio "9:16" --model "Seedance_2.0_mini_lite" --resolution "720p"
```

常用参数：

- `--prompt`：覆盖默认 prompt 文件内容
- `--prompt-file`：指定 prompt 文件
- `--output-dir` / `-o`：下载目录，默认 `data/works/{work_id}/generated_videos/{scene_id}`
- `--dry-run`：只打印将传给 Pippit 的参数，不提交
- `--no-download`：只提交生成任务，不轮询下载
- `--no-images` / `--no-audios` / `--no-videos`：禁用某类实体媒体

提交记录会写入 `data/works/{work_id}/pippit_runs/{scene_id}.json`。

**重新生成工作流：**

```bash
# 对当前结果不满意，清空 S6 重新生成
manga clear s6 -y
manga video-prompt -e 0

# 修改了系统提示词后，清空整级重跑
manga clear video-prompt -y   # 等价于 clear s6
manga video-prompt

# 从 S4 往后全部重跑（需按顺序清空）
manga clear s4 -y && manga clear s5 -y && manga clear s6 -y
manga screenplay -j 8
manga continuity
manga video-prompt

# S6 分范围重跑：第 0 集第 7 到第 20 场（0-based：6 到 19）
manga video-prompt -e 0 --from-scene 6 --to-scene 19 --reset -j 1
```

---

## 配置

`config.toml`（项目根目录）：

```toml
[llm]
model    = "deepseek-v4-flash"       # 任何 OpenAI 兼容模型
api_key  = "sk-..."
base_url = "http://localhost:3000/v1" # 本地 NewAPI 中转或直连

[video_prompt]
# 全局风格约束前缀——改这里，下次生成即生效
style_contract = """动画风格，参照山田尚子（《莉兹与青鸟》…"""

# 每段视频最大时长（秒）
max_segment_duration = 15.0
```

---

## 人工微调入口

| 需要微调 | 位置 |
|---|---|
| 视频风格约束（山田尚子/新海诚/…） | `config.toml` → `[video_prompt] style_contract` |
| 提示词结构（分段规则、动作链写法） | `agents/prompt_composer.py` → `_SYSTEM_PROMPT_TEMPLATE` |
| 原文参考规则（source_text 对齐） | `agents/prompt_composer.py` → `_SYSTEM_PROMPT_TEMPLATE` 的“原文参考规则” |
| 单场景提示词 | 直接编辑 `video_prompts/{scene_id}.txt` |
| 最大分段时长 | `config.toml` → `max_segment_duration` |
| 实体设定（人物/地点/变体外观） | 直接编辑 `entities/characters.json` |
| 实体参考媒体（图片/音频/视频） | `manga bind-media <entity_id> <变体> <文件> --kind image\|audio\|video` |
| 叙事风格 | `style_guide.json` → `narrative_style` |

修改文件后，删除对应的输出文件，或用 S6 的 `--reset` 覆盖对应场景后重跑对应阶段即可。

---

## 设计原则

- **原文优先对齐**，S6 会把该场景 `source.txt` 片段传入 LLM，用于校正称呼、关系、动作顺序和台词
- **精确称呼保留**，`幼年妹妹 / 幼年妹 / 国中生妹妹 / 高中生妹妹` 等 variant label 不被合并，直接用于多媒体资产绑定
- **LLM 只做约束变换**，不决策流程走向，不做自由生成
- **状态住在 JSON**，不用数据库，随时手改、随时备份
- **断点续跑**，每阶段完成即 checkpoint，中断后从 `run_state.cursor` 续跑
- **两处反思环**（S4 分镜 / S6 提示词），`generate → critique → revise`，上限 2 轮
- **三个人工检查点**（S1 分集确认 / S2 设定库确认 / S5 高严重度问题），把人放在最高杠杆的对齐点

---

## 运行测试

```bash
python -m pytest tests/ -v
# 120 passed（M0=3, M1=18, M2=23, M3=23, M4=19, M5=34）
```

---

## 实测规模（妹妹人生，184,024 字）

| 阶段 | 产物 |
|---|---|
| S1 切分 | 8 集 / 95 场景 |
| S2 设定库 | 11 实体（char 4 / loc 4 / prop 2）/ 78 变体 |
| S3 摘要 | rolling_summary 最终 ~1518 字 / ~379 tokens |
| S4 分镜 | 1245 镜头（平均 13 镜/场景）|
| S5 绑定 | 1675 次绑定（覆盖率 96.9%）|
| S6 提示词 | 第一集 6 场景 / 36 段 |

---

## 依赖

- Python ≥ 3.11
- LangChain + LangChain-OpenAI
- Pydantic v2
- Typer + Rich
- 任何 OpenAI 兼容接口（DeepSeek / 本地 Ollama / OpenAI 直连均可）
