# AI漫剧管理器 - CLI 指令手册

> 供 Agent 或用户调用的完整命令参考

## 前置条件

```powershell
# Windows: drama.exe 在 Python Scripts 目录，首次使用需加入 PATH
$env:PATH += ";<PYTHON_SCRIPTS>"

# 或直接用完整路径
<PYTHON_SCRIPTS>\drama.exe <command>

# 切换到项目目录
cd <REPO_ROOT>\06_项目作品集\03_AI漫剧管理器
```

以下示例均使用 `drama` 短命令（已加 PATH 前提下）。

---

## 一、项目管理

### 1.1 创建项目

```bash
drama init "<项目名称>"
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | str | 是 | 项目名称，如 "妹妹人生" |

**副作用**: 创建 `data/projects/{id}/` 目录及所有 JSON 文件，初始化 git 仓库

---

### 1.2 列出所有项目

```bash
drama list
```

**输出**: 表格展示所有项目的 ID、名称、创建时间

---

### 1.3 查看当前项目信息

```bash
drama info
```

**输出**: 项目名称、分镜数、人物/场景/道具数

---

### 1.4 切换当前活动项目

```bash
drama use <项目ID或名称>
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| project_id | str | 是 | 项目 ID（支持前缀）或完整名称 |

当前活动项目持久化在 `data/.active`，所有命令默认作用于该项目。
`drama list` 中带 `*` 的即为当前活动项目。

**示例**:
```bash
drama use d3e991dd
drama use 妹妹人生
drama use d3e        # ID 前缀，唯一匹配即可
```

---

### 1.5 查看操作日志

```bash
drama log [--n <条数>]
```

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| --n | int | 否 | 30 | 显示最近 N 条 |

所有写操作（import/split/convert/extract/bind/infer/edit 等）都会记录到
`operations.jsonl`，按时间倒序展示。

**示例**:
```bash
drama log
drama log --n 10
```

---

## 二、小说管理

### 2.1 导入小说

```bash
drama novel import "<文件路径>"
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| file | str | 是 | 小说文件路径，支持 .txt .md .text .markdown |

**副作用**: 将小说全文写入 `project.json` 的 `source_text` 字段，git commit

**示例**:
```bash
drama novel import "<NOVEL_DIR>\妹妹人生.md"
```

---

### 2.2 交互式分集（长篇专用）

```bash
drama novel split --file "<文件路径>" [--max-chars <字数>]
```

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| --file | str | 是 | - | 小说文件路径 |
| --max-chars | int | 否 | 300000 | 字数硬上限，超过则中止 |

**流程**（全程把完整原文喂给 LLM，信息不遗漏，需长上下文模型）:
1. 全文喂 LLM 生成全篇大纲
2. 全文 + 大纲喂 LLM 提分集方案（交互式确认）
3. 输入反馈调整，满意后输入 "可以了" / "ok" / "确认" 确认
4. 执行切分：全文喂 LLM，LLM 只返回切割点（比例 + 边界原句），
   Python 据此在原文精确切割（不让 LLM 重吐内容，省 token、防出错）
5. 结果存入 `episodes.json`（index=0 为大纲，1 起为正式分集）

**副作用**: 写入 `episodes.json`，`variables.json` 存分集方案 proposal，git commit

**字数上限**: 默认 30 万字。超过即中止并提示，请改用 `import-episodes` 人工分集（见 2.3）。
30 万字以内全文喂依赖模型长上下文能力（建议 1M 上下文模型，如 Gemini）。

**示例**:
```bash
drama novel split --file "<NOVEL_DIR>\妹妹人生.md"
drama novel split --file "<NOVEL_DIR>\短篇.txt" --max-chars 200000
```

---

### 2.3 导入人工分集（超长文本专用）

```bash
drama novel import-episodes --folder "<文件夹>" [--outline "<大纲文件>"] [--pattern "*.txt"]
```

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| --folder | str | 是 | - | 存放各集文本的文件夹 |
| --outline | str | 否 | 空 | 大纲文件路径，作为 index=0 |
| --pattern | str | 否 | *.txt | 文件匹配模式 |

**适用场景**: 数十万字超长小说，AI 自动分集精度不够，自己手动切好各集更可靠。

**用法**: 把切好的各集文本按**文件名排序**放进一个文件夹，文件名带序号保证顺序，
每个文件成为一集，文件名（去扩展名）作标题。

**示例**:
```
<NOVEL_DIR>\episodes\
  ├── 01-初遇.txt
  ├── 02-离别.txt
  └── 03-重逢.txt
```
```bash
drama novel import-episodes --folder "<NOVEL_DIR>\episodes"
drama novel import-episodes --folder "<NOVEL_DIR>\episodes" --outline "<NOVEL_DIR>\大纲.txt"
```

导入后直接进入 `drama novel convert` 逐集转分镜，跳过 AI 分集。

---

### 2.4 查看分集列表

```bash
drama novel episodes                  # 显示分集列表（index/标题/字数/摘要）
drama novel episodes --show 0         # 显示 index=0 大纲全文
drama novel episodes --show 1         # 显示第1集原文内容
```

---

### 2.5 AI 转换为分镜剧本

```bash
drama novel convert                          # 有分集时按集逐集转换（自动跳过 index=0 大纲）
drama novel convert --episode 2             # 只转换第2集
drama novel convert --file "<NOVEL_DIR>\仙剑.txt"  # 直接传文件（无分集场景）
```

---

## 三、分镜管理

### 3.1 列出分镜

```bash
drama panel list
```

**输出**: 表格展示所有分镜的序号、文案预览、是否有图片/视频提示词

---

### 3.2 查看分镜详情

```bash
drama panel show <分镜序号>
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| index | int | 是 | 分镜序号（从1开始） |

```bash
drama panel show 3
```

---

### 3.3 编辑分镜

```bash
drama panel edit <分镜序号> --field "<字段名>" --value "<新值>"
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| index | int | 是 | 分镜序号 |
| --field | str | 是 | 字段名: paperwork / prompt / video_prompt / dialogue |
| --value | str | 是 | 新值 |

```bash
drama panel edit 3 --field prompt --value "一位穿白衣的女子站在桃花树下"
drama panel edit 1 --field dialogue --value "张三: 你好"
```

---

### 3.4 手动添加分镜

```bash
drama panel add --paperwork "<分镜文案>"
```

```bash
drama panel add --paperwork "【外景·日·山道】少年骑马奔驰在山间小路上"
```

---

### 3.5 删除分镜

```bash
drama panel delete <分镜序号>
```

---

## 四、实体管理（人物/场景/道具）

### 4.1 列出实体

```bash
drama entity list [--type "<类型>"]
```

| --type 值 | 说明 |
|-----------|------|
| 空（默认） | 全部 |
| character | 只看人物 |
| location  | 只看场景 |
| item      | 只看道具 |

```bash
drama entity list
drama entity list --type character
```

---

### 4.2 查看实体详情

```bash
drama entity show "<实体名称>"
```

```bash
drama entity show "李逍遥"
```

---

### 4.3 手动添加实体

```bash
drama entity add "<名称>" --type "<类型>" --description "<描述>" --aliases "<别名>"
```

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| name | str | 是 | - | 实体名称 |
| --type | str | 否 | character | character / location / item |
| --description | str | 否 | 空 | 形象描述（用于生图提示词） |
| --aliases | str | 否 | 空 | 别名，逗号分隔 |
| --importance | str | 否 | major | major（核心，需锚定）/ minor（次要，泛称） |

```bash
drama entity add "赵灵儿" --type character --description "16岁女性，黑色长发，白色仙裙" --aliases "灵儿"
drama entity add "青云大殿" --type location --description "中式古代殿堂，红色立柱" --aliases "大殿"
drama entity add "路人甲" --type character --importance minor
```

---

### 4.4 AI 提取实体

```bash
drama entity extract              # 提取全部分镜的实体，按 name 去重
drama entity extract --episode 1  # 只提取第1集分镜的实体
drama entity extract --replace    # 清空现有实体和绑定后重新提取
```

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| --episode | int | 否 | -1 | 只提取指定集 index，-1=全部分镜 |
| --replace | flag | 否 | false | 清空旧实体/绑定后重新提取 |

**前置条件**: 必须先有分镜（novel convert 或 panel add）
**特性**:
- 自动判定每个实体的 `importance`（major/minor）
- 同一角色不同年龄段会拆为独立实体（如"妹妹(6岁)"、"妹妹(20岁)"）
- 增量模式按 name 去重，已存在的同名实体跳过（保留旧实体的绑定和参考图）
- 配合 `--episode` 可逐集提取，边转边补

**副作用**: 写入 `entities.json`，git commit

---

### 4.5 编辑实体字段

```bash
drama entity edit <名称> --field <字段> --value <新值>
```

| 字段 | 说明 |
|------|------|
| description | 形象描述 |
| aliases | 别名 |
| importance | major / minor |

```bash
drama entity edit "妹妹(6岁)" --field importance --value major
drama entity edit "哥哥" --field description --value "20岁男性，黑色短发，休闲装"
```

---

### 4.6 绑定参考图/音频

为重要实体绑定自制设定图或音色样本，infer 时会在提示词中追加 `<ref:名称>` 占位标记。

```bash
drama entity set-media <名称> [--image <图片路径>] [--audio <音频路径>]
```

```bash
drama entity set-media "妹妹(20岁)" --image "<ASSETS_DIR>\妹妹设定图.png"
drama entity set-media "哥哥" --image "<ASSETS_DIR>\哥哥.png" --audio "<ASSETS_DIR>\哥哥音色.wav"
```

---

### 4.7 LLM 精确绑定实体到分镜

```bash
drama entity bind               # 绑定全部（按集分批调用 LLM）
drama entity bind --episode 1   # 只绑定第1集
```

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| --episode | int | 否 | -1 | 指定集 index，-1=全部 |

**说明**: 每集所有分镜 + 实体表一次性传给 LLM，由 LLM 判断每个分镜真正出现的实体，
准确率远高于字符串匹配。5 集 = 5 次 LLM 调用。
**副作用**: 写入 `bindings.json`（`{panel_id: [entity_id]}`），git commit

---

## 五、提示词推理

```bash
drama prompt infer [--episode <集>] [--range <区间>] [--only-empty] [--panel-index <序号>]
```

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| --episode | int | 否 | -1 | 只推理指定集 index 的分镜，-1=不按集过滤 |
| --range | str | 否 | 空 | 分镜序号区间，如 `1-30`（按 sort_order），可与 episode 叠加 |
| --only-empty | flag | 否 | false | 只推理还没提示词的分镜（断点续跑，跳过已完成）|
| --panel-index | int | 否 | 0 | 0 = 全部；指定序号则只推理该分镜 |

**特性**:
- 多分镜并发调用 LLM（限流到 8），100+ 分镜也较快
- 按实体 `importance` 注入锚定标记：核心实体强调外观一致性，次要实体用泛称
- 配了参考图的核心实体，提示词追加 `<ref:名称>` 占位符
- 过滤优先级：episode → panel-index，再叠加 range，最后 only-empty

**副作用**: 更新 `panels.json` 中的 prompt 和 video_prompt，git commit

**分批推理（分镜多时推荐）**:
```bash
# 一集 140 个分镜，分批跑，每批 30 个
drama prompt infer --range 1-30
drama prompt infer --range 31-60
drama prompt infer --range 61-90

# 断点续跑：只补还没生成的，反复跑直到全部完成（不重复花钱）
drama prompt infer --only-empty
drama prompt infer --episode 1 --only-empty   # 限定第1集

# 按集 + 区间组合
drama prompt infer --episode 1 --range 1-40
```

```bash
drama prompt infer              # 全部
drama prompt infer --episode 1  # 只推理第1集
drama prompt infer --panel-index 3  # 只推理第3个
```

---

### 5.1 导出提示词（图片/视频分开）

图片提示词和视频提示词通常要喂给**不同的服务端**（生图服务 / 生视频服务），
`export` 把两类提示词分别导出成独立文件。

```bash
drama export [--out-dir <目录>] [--fmt jsonl|txt]
```

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| --out-dir | str | 否 | 项目目录/export/ | 导出目录 |
| --fmt | str | 否 | jsonl | jsonl（带序号，推荐）/ txt（每行一条） |

**产出两个文件**:
- `image_prompts.{jsonl\|txt}` — 图片提示词
- `video_prompts.{jsonl\|txt}` — 视频提示词

**jsonl 格式**（每条带 `sort_order`，服务端可按分镜序号对应回填）:
```json
{"sort_order": 1, "prompt": "一个少年站在山路上，中景，黄昏"}
{"sort_order": 2, "prompt": "女孩回头微笑，近景"}
```

**txt 格式**（每行一条纯提示词，直接逐行喂服务）:
```
一个少年站在山路上，中景，黄昏
女孩回头微笑，近景
```

空提示词的分镜自动跳过。

**示例**:
```bash
drama export                              # 导出到项目 export/ 目录，jsonl
drama export --fmt txt                    # 纯文本格式
drama export --out-dir "<OUTPUT_DIR>\prompts"  # 指定目录
```

---

## 六、变量管理

```bash
drama variable list                                    # 列出所有变量
drama variable set "<键>" "<值>" [--category "<分类>"] # 设置变量
drama variable get "<键>"                              # 获取变量
```

| category 值 | 说明 |
|-------------|------|
| style       | 画风变量（可选覆盖；默认画风见第十章 STYLE 常量） |
| negative    | 负面提示词 |
| split       | 分集方案（系统写入，不建议手动改） |
| custom      | 自定义（默认） |

> 注：项目默认画风现由 `prompts.py` 的 `STYLE` 常量统一管理（见 10.1）。
> 这里的 `style` 变量仅作临时覆盖用途，一般无需设置。

```bash
drama variable set style "赛博朋克" --category style
drama variable set neg_default "低清晰度，畸形" --category negative
drama variable get style
```

---

## 七、一键全流程（Agent 模式）

```bash
drama agent run [--file "<文件路径>"] [--threshold <字数>]
```

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| --file | str | 否 | 空 | 小说文件路径，不填则用已导入文本 |
| --threshold | int | 否 | 100000 | 分集字数阈值，低于此值不分集 |

**完整流程**: split → convert → extract → bind → infer

> 注意: agent run 的 split 节点为**非交互式**自动分集，适合短篇。
> 长篇需要用户确认分集方案时，请先单独运行 `drama novel split`，再分步执行后续命令。

```bash
drama agent run --file "<NOVEL_DIR>\短篇.txt"
drama agent run                              # 用已导入文本
```

---

## 八、Git 版本管理

```bash
drama git log [--n <条数>]          # 版本历史（默认20条）
drama git diff [--commit "<hash>"]  # 版本差异（默认对比 HEAD~1）
drama git revert "<commit hash>"    # 回滚到指定版本
```

```bash
drama git log
drama git log --n 5
drama git diff
drama git diff --commit abc12345
drama git revert abc12345
```

---

## 九、典型工作流

### 短篇一键生成（<10万字）

```bash
drama init "测试项目"
drama agent run --file "<NOVEL_DIR>\短篇.txt"
drama panel list
```

### 长篇分步操作（>10万字）

```bash
drama init "妹妹人生"
# 第一步: 交互式分集确认
drama novel split --file "<NOVEL_DIR>\[入间人间].妹妹人生.上.md"
# 输入反馈，满意后输入 "可以了" 确认
drama novel episodes              # 确认分集结果

# 第二步: 逐集转换分镜（可先单集验证）
drama novel convert --episode 1
drama panel list                  # 看第1集效果
drama novel convert               # 没问题则转换全部

# 第三步: 提取实体（自动判定 major/minor）
drama entity extract
drama entity list --type character

# 第四步（可选）: 为核心角色绑定自制设定图
drama entity set-media "妹妹(20岁)" --image "<ASSETS_DIR>\妹妹.png"
drama entity edit "路人" --field importance --value minor

# 第五步: LLM 精确绑定实体到分镜
drama entity bind

# 第六步: 推理提示词（并发 + 锚定）
drama prompt infer

# 查看结果
drama panel show 1
drama git log
```

### 手动微调

```bash
drama panel edit 3 --field prompt --value "新提示词内容"
drama entity add "新角色" --type character --description "描述"
drama entity edit "新角色" --field importance --value major
drama variable set style "水墨风" --category style
drama prompt infer --panel-index 3  # 重新推理该分镜
```

---

## 十、自定义提示词

每个项目在 `drama init` 时会自动复制一份提示词模板到项目目录：

```
data/projects/{项目ID}/prompts.py
```

所有 AI 步骤（split/convert/extract/bind/infer）运行时**优先读取项目自己的 `prompts.py`**，
没有副本才回退到默认模板。因此你可以：

1. 用任意编辑器打开 `data/projects/{项目ID}/prompts.py`
2. 修改其中的提示词常量（如 `CONVERT_USER`、`INFER_USER`），可写 Python 注释
3. 保存后直接重新运行对应命令，新提示词立即生效

### 10.1 设置画风（STYLE 常量）

画风统一由项目 `prompts.py` 顶部的 `STYLE` 常量控制，convert 和 infer 都引用它：

```python
# data/projects/{项目ID}/prompts.py
STYLE = "电影感动画：写实光影、细腻情绪、强画面叙事"  # 改这里换画风
```

改一处，分镜叙事基调和绘图提示词同时生效。例如换成日系治愈：

```python
STYLE = "日系治愈动画：柔和色调、清新光线、温暖氛围"
```

```bash
# 改完直接重跑，无需重新 init
drama novel convert
drama prompt infer
```

**特点**:
- 按项目特化：不同项目可用不同提示词，互不影响
- 不污染初始模板：改副本不影响 `src/drama_manager/llm/prompts.py`
- 占位符要保留：如 `{text}`、`{outline}`、`{style}` 等，删了会报错

**主要提示词常量**:

| 常量 | 用途 | 关键占位符 |
|------|------|-----------|
| `OUTLINE_USER` | 生成全篇大纲 | `{text}` |
| `SPLIT_DISCUSS_USER` | 分集方案讨论 | `{char_count}` `{outline}` |
| `SPLIT_EXECUTE_USER` | 执行分集 | `{plan}` `{outline}` `{char_count}` `{samples}` |
| `CONVERT_USER` | 小说→分镜 | `{outline}` `{prev_summary}` `{next_summary}` `{style}` `{text}` |
| `EXTRACT_USER` | 提取实体 | `{panels_text}` `{existing}` |
| `BIND_USER` | 绑定实体到分镜 | `{entities_text}` `{panels_text}` |
| `INFER_USER` | 生成图片/视频提示词 | `{paperwork}` `{entities_block}` `{style}` |

**示例**: 想让分镜文案更偏向某种风格，编辑该项目的 `prompts.py`：

```python
# data/projects/d3e991dd/prompts.py
CONVERT_SYSTEM = "你是擅长日系治愈风格的影视分镜编剧。"  # 改这里
```

```bash
# 改完直接重跑，无需重新 init
drama novel convert --episode 1
```
