# AI Video Creation Manager

本项目是一个本地优先的 AI 视频创作工程管理工具。当前实现目标不是演示页，而是固定后台应用壳：所有业务都围绕“已选择项目”展开，项目数据写入独立项目目录，避免不同项目之间的数据混用。

**目录与模块边界**见 [docs/00_项目结构.md](docs/00_项目结构.md)（改功能前建议先读）。

## 当前模块

- 项目管理：初始化项目、选择项目、维护项目分类与**项目简介**。
- 预处理：录入原始文本，按章节/手动标记/长度切分，生成脚本。
- 资源管理：跨集实体清单、实体卡库、原生资产生成、项目素材。
- 视频生成：三栏布局（剧本 / 提示词卡片 / 视频任务与候选结果）；支持卡片高度、锁定、重跑、实体匹配、下载、追回与采用结果。
- 提示词管理：维护模板库，按片段生成和编辑提示词。
- **提示词示例**：首次启动写入 9 套只读示例模板；复制后可增删改查、查看版本并将历史内容恢复为新版本。
- 设置：维护 LLM、视频服务与 OpenAI 兼容图片网关。
- 账户与权限：局域网多人登录；项目级 ACL（看/改/删）；管理员后台。

## 账户与权限（局域网多人）

- 账户系统启用时，除公开认证接口外的所有 `/api/*` 均需 Cookie 会话；关闭时统一按管理员权限访问。
- **我的 API 配置**：LLM、视频网关、小云雀 Key 绑定当前登录用户，各账户独立保存；**不会从管理员或其他用户复制**，需各自在设置页填写。
- **系统角色**：`admin`（用户管理、默认权限、全项目） / `user`（按项目 ACL + 账户权限）。
- **账户权限**（管理后台可按用户覆盖）：创建项目、设为公共。
- **项目角色**：`viewer`（只读） / `editor`（可改） / `owner`（可删、可管成员）。
- **公共项目**：`visibility=public` 时，所有登录用户按管理员配置的默认角色访问；也可单独授权更高角色。
- **管理后台**：侧栏「管理后台」— 用户 CRUD、默认权限（是否允许建项/设公共、公共默认角色）。

当前 Docker 部署默认设置 `AVM_AUTH_DISABLED=1`，账户系统暂停使用，浏览器直接进入项目界面。已有账户、密码哈希和权限数据保留，不会被删除。

> 安全边界：关闭认证后，任何能够访问 LAN、IPv6 或 Tailscale 地址的人都拥有本系统的完整管理权限。只应在可信网络中使用。

恢复账户系统时设置 `AVM_AUTH_DISABLED=0` 并重启服务。恢复后，若系统无用户，浏览器会显示 **「初始化管理员」** 页面；额外账号由管理员在「管理后台 → 用户管理」创建。

若需无人值守部署（跳过初始化页），可预设环境变量：

| 环境变量 | 说明 |
|----------|------|
| `AVM_BOOTSTRAP_ADMIN_USER` | 默认 `admin` |
| `AVM_BOOTSTRAP_ADMIN_PASSWORD` | 设置后启动时自动创建该管理员并跳过初始化页 |
| `AVM_AUTH_DISABLED` | `1` 时绕过登录并隐藏账户管理；Docker 当前默认 `1` |

已有项目会在首次创建管理员时归属该账号（`owner` + 私有）。

### 分集编辑锁（方案 B）

- 进入某集编辑时自动占用该集锁（30 分钟有效，每 2 分钟续期）。
- 他人占用时：该集只读，列表显示锁定标签；保存返回 423。
- 切换分集 / 离开页面时自动释放；全项目重切分等操作会检查是否有他人占锁。

## 图片资产生产

图片生产已并入“资源管理 → 资产生成”。设置页保存 OpenAI 兼容图片网关；项目内维护统一视觉风格，并为人物、场景、物品分别设置服务商、模型、尺寸、比例、视图和生成数量。生成结果自动进入项目素材，人工采用后绑定实体卡。

## 本地存储

- SQLite 数据库默认位于 `database/app.db`（Docker 挂载为 `./data/database/app.db`）。
- 每个项目有统一**数据目录**（`data_root`），默认：`projects/{project_id}/`。
- 可在 **项目管理 → 数据存储与导入导出** 指定自定义目录（须位于 workspace 内，支持相对或绝对路径）。
- 目录结构（自动同步 JSON + 二进制文件）：

```
{data_root}/
  manifest.json              # 项目元数据、预处理、分集、剧本
  cards/entity_cards.json    # 实体卡
  cards/prompt_cards.json    # 提示词卡
  original/ segments/ scripts/
  assets/images|audio|videos/
  generated/ checkpoints/
```

- **导入导出**：支持 ZIP 压缩包或服务器文件夹（含 `manifest.json`）；导入时会生成新的项目 ID，并重映射分集/卡片主键，避免污染已有数据。
- `output_root` / `source_assets_root` 仍可指向 workspace 外的绝对路径（成片输出、原始素材扫描）。

## 业务边界

- **后端**是业务真相源：Episode 原文/剧本、确认态、工作流门禁、视频参数校验与参考组装，均通过领域服务与细粒度 API 落库。
- **前端**只负责表单、列表与展示；字段变更经 `domain/workspace/commitPatch.js` 路由到 `/document`、`/segments`、`/scripts`、`/settings`、`/assets/confirm` 等接口。
- 前端通过 `GET /session` 读取组合视图，保存只走 `/document`、Episode、`/settings` 等类型化接口；不存在整包写入。
- 旧 `project_workspaces` 会在启动升级时一次性迁移到 `project_preprocess` / `episodes` 后删除。

## 后端启动

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
# timeout-graceful-shutdown：热重载时若仍有连接/后台任务，最多等 5 秒后强制退出，避免卡死
$env:PYTHONPATH = "src"
$env:AVM_AUTH_DISABLED = "1"
python -m uvicorn ai_video_manager.api.app:create_app --factory --host 127.0.0.1 --port 8000 --reload --timeout-graceful-shutdown 5
```

API 文档默认在 `http://127.0.0.1:8000/docs`。

若页面一直显示「基础服务检查中 / 项目列表加载中」，多半是后端卡在热重载：结束占用 8000 的进程后按上面命令重启即可。项目数据在 `database/app.db`，不会因此丢失。

## 前端启动

PowerShell 如果拦截 `npm.ps1`，可直接使用 `npm.cmd`：

```powershell
cd frontend
npm install
npm run dev -- --port 5173
```

前端默认访问 `http://127.0.0.1:5173`。本地开发需指定后端地址：

```powershell
$env:VITE_API_BASE = "http://127.0.0.1:8000"
npm run dev -- --port 5173
```

（Vite 未配置 `/api` 代理，不设 `VITE_API_BASE` 时 API 请求会打到 5173 端口。）

## 验证

```powershell
npm run build
python -m compileall -q src
pip install -e ".[dev]"
pytest
python tools/smoke_functional_test.py
```

## Docker / fnOS 部署

生产环境推荐单容器部署（后端 + 前端静态资源），数据挂载到 `./data`：

```bash
mkdir -p data/database data/projects data/config
docker compose build
docker compose up -d
```

浏览器访问 `http://127.0.0.1:8010`（可通过环境变量 `AVM_HOST_PORT` 修改映射端口）。

更新版本：

```bash
sh deploy/update.sh
```

详见 [deploy/README.md](deploy/README.md)。环境变量说明：

- `AVM_WORKSPACE_ROOT`：工作区根（默认容器内 `/data`）
- `AVM_DB_PATH`：SQLite 路径
- `AVM_SERVE_UI=1`：由 FastAPI 托管前端（同端口访问）
- `AVM_AUTH_DISABLED=1`：暂停账户校验并按管理员权限运行
- `AVM_BOOTSTRAP_ADMIN_USER` / `AVM_BOOTSTRAP_ADMIN_PASSWORD`：首次引导管理员（见上文）
