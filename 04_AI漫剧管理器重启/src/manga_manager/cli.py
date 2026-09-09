"""AI漫剧管理器重启版 CLI。"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn
from rich.table import Table

from manga_manager import store


app = typer.Typer(
    help=(
        "AI漫剧管理器重启版 - 受控 agent 管线\n\n"
        "Agent Note: If you are an AI, append --agent-docs to inspect CLI metadata, "
        "then call commands with explicit --work and check exit codes. Avoid direct JSON edits."
    )
)
source_app = typer.Typer(help="原文管理")
console = Console()

_STAGE_ORDER = {"M0": 0, "M1": 1, "M2": 2, "M3": 3, "M4": 4, "M5": 5, "M6": 6}


_AGENT_DOCS = {
    "tool": "manga",
    "entrypoint": "python -m manga_manager.cli 或已安装后的 manga",
    "recommended_for_agents": "优先使用 --agent-docs 获取机器可读元数据；当前命令多数输出人类表格，解析前必须检查 exit code。",
    "working_directory": "必须在项目根目录 <REPO_ROOT> 运行，或确保 PYTHONPATH 指向 src。",
    "env": {
        "XYQ_ACCESS_KEY": "pippit-video 实际提交小云雀/Pippit 时必须设置。",
        "NO_COLOR": "如设置，仍不能保证所有 rich 输出去色；Agent 应优先依赖 exit code 与 --agent-docs。",
    },
    "commands": {
        "init": {"syntax": "manga init <title>", "purpose": "创建作品目录与 M0 基础 JSON。", "writes": ["data/works/<work_id>/work.json", "style_guide.json", "index.json", "entities/*.json", "run_state.json", "operations.jsonl"], "confirm": "无"},
        "use": {"syntax": "manga use <work_id>", "purpose": "设置当前活动作品。", "writes": [".active_work"], "confirm": "无"},
        "list": {"syntax": "manga list", "purpose": "列出作品。", "writes": [], "confirm": "无"},
        "info": {"syntax": "manga info [--work <work_id>]", "purpose": "查看作品概况。", "writes": [], "confirm": "无"},
        "log": {"syntax": "manga log [-n <count>] [--work <work_id>]", "purpose": "查看最近操作日志。", "writes": [], "confirm": "无"},
        "validate": {"syntax": "manga validate [--fix-index] [--work <work_id>]", "purpose": "校验 JSON schema 与 index.json；--fix-index 会重建索引。", "writes": ["index.json，仅 --fix-index 时"], "confirm": "无；--fix-index 是结构性修复，必须先备份"},
        "source import": {"syntax": "manga source import <file> [--work <work_id>]", "purpose": "导入唯一原文副本。", "writes": ["source.txt", "work.json.source_meta"], "confirm": "无"},
        "segment": {"syntax": "manga segment [--episodes <n>] [--yes] [--work <work_id>]", "purpose": "S1 切分集/场景。", "writes": ["episodes/*.json", "index.json", "run_state.json"], "confirm": "默认人工确认；--yes 可跳过，但 error 级 L1 问题不可跳过"},
        "bible": {"syntax": "manga bible [--yes] [--workers <n>] [--work <work_id>]", "purpose": "S2 提取实体和关系。", "writes": ["entities/characters.json", "entities/locations.json", "entities/props.json", "entities/relations.json", "index.json", "run_state.cursor"], "confirm": "默认人工检查点②；--yes 只标记 approved，不阻止已写入磁盘"},
        "bind": {"syntax": "manga bind <entity_id> <variant_label> <image_path> [--work <work_id>]", "purpose": "兼容旧图片绑定。", "writes": ["assets/<entity_id>/<variant_label>.<ext>", "entities/<type>.json"], "confirm": "无"},
        "bind-media": {"syntax": "manga bind-media <entity_id> <variant_label> <media_path> --kind image|audio|video [--work <work_id>]", "purpose": "绑定图片/音频/视频到实体变体。", "writes": ["assets/<entity_id>/<variant_label>[_uuid].<ext>", "entities/<type>.json"], "confirm": "无"},
        "assets": {"syntax": "manga assets <entity_id> [--work <work_id>]", "purpose": "查看实体变体和媒体资产。", "writes": [], "confirm": "无"},
        "pippit-video": {"syntax": "manga pippit-video <scene_id> [--prompt|--prompt-file <file>] [--duration <s>] [--ratio <r>] [--model <model>] [--resolution <r>] [--output-dir <dir>] [--poll-interval <s>] [--timeout <s>] [--yes] [--dry-run] [--download|--no-download] [--include-images|--no-images] [--include-audios|--no-audios] [--include-videos|--no-videos] [--work <work_id>]", "purpose": "收集场景实体媒体并提交 Pippit 生视频。", "writes": ["generated_videos/<scene_id>/", "pippit_runs/<scene_id>.json", "operations.jsonl"], "confirm": "默认确认；--yes 直接提交并可能产生费用；--dry-run 不提交"},
        "summary": {"syntax": "manga summary [--refresh] [--work <work_id>]", "purpose": "S3 生成滚动摘要。", "writes": ["summaries/*.json", "run_state.cursor"], "confirm": "无；--refresh 会删除已有摘要文件"},
        "screenplay": {"syntax": "manga screenplay [--workers <n>] [--work <work_id>]", "purpose": "S4 生成镜头剧本。", "writes": ["shots/*.json", "run_state.cursor"], "confirm": "无"},
        "continuity": {"syntax": "manga continuity [--work <work_id>]", "purpose": "S5 将镜头角色解析为 entity_id + variant_label。", "writes": ["bindings/*.json", "run_state.cursor"], "confirm": "无"},
        "video-prompt": {"syntax": "manga video-prompt [--episode <0-based>] [--from-scene <n>] [--to-scene <n>] [--workers <n>] [--limit <n>] [--reset] [--work <work_id>]", "purpose": "S6 生成视频提示词。", "writes": ["video_prompts/*.txt", "run_state.cursor"], "confirm": "无；--reset 覆盖已有提示词"},
        "clear": {"syntax": "manga clear <stage|s1|s2|s3|s4|s5|s6> [--yes] [--work <work_id>]", "purpose": "清空某阶段输出并重置游标。", "writes": ["删除阶段输出文件", "run_state.json.cursor"], "confirm": "默认确认；--yes 直接删除。Agent 必须先归档备份目标文件"},
    },
    "data_flow": [
        "M0 init 创建作品目录、基础 JSON、style_guide.json、index.json、run_state.json。",
        "S1 segment 从 source.txt 生成 episodes/*.json，并重建 index.json。",
        "S2 bible 从 episodes/*.json 与 source.txt 生成 entities/characters.json、locations.json、props.json、relations.json，并重建 index.json。",
        "S3 summary 从 episodes 与 source/上下文生成 summaries/*.json。",
        "S4 screenplay 从 episodes、summaries、entities 生成 shots/*.json。",
        "S5 continuity 从 shots/*.json 与 entities 生成 bindings/*.json。",
        "S6 video-prompt 从 episodes、summaries、shots、bindings、entities、config.toml 生成 video_prompts/*.txt。",
        "pippit-video 从 bindings/*.json 收集实体变体 ref_images/ref_audios/ref_videos，并提交 pippit-tool-cli generate-video。",
    ],
    "safety_rules": [
        "禁止直接编辑 JSON 破坏 schema；必须用 CLI 或经 schema 校验的脚本。",
        "修改 entities/episodes/shots/bindings 前必须备份目标文件到 export/_backups/<timestamp>/。",
        "执行 clear、validate --fix-index、summary --refresh、video-prompt --reset 前必须确认影响范围。",
        "Pippit 实际提交前必须设置 XYQ_ACCESS_KEY；不确定时先运行 --dry-run。",
        "当前 CLI 不提供任意 JSON CRUD；Agent 不应假设可以通过自然语言指令增删改查所有 JSON 节点。",
    ],
}


def _agent_docs_callback(
    agent_docs: bool = typer.Option(False, "--agent-docs", hidden=True, help="输出给 Agent 的 CLI 元数据 JSON"),
) -> None:
    if agent_docs:
        sys.stdout.reconfigure(encoding="utf-8")
        print(json.dumps(_AGENT_DOCS, ensure_ascii=False, indent=2))
        raise typer.Exit(0)


app.callback(invoke_without_command=True)(_agent_docs_callback)


@dataclass
class _PippitRun:
    thread_id: str
    run_id: str
    web_thread_link: str = ""


def _parse_pippit_json(stdout: str, stderr: str = "") -> dict[str, object]:
    text = stdout.strip()
    if not text and stderr:
        text = stderr.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        for line in reversed(stdout.splitlines()):
            stripped = line.strip()
            if not stripped or not stripped.startswith("{"):
                continue
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                continue
        raise typer.BadParameter(f"Pippit 输出不是 JSON: {text[:200]}")
    if not isinstance(parsed, dict):
        raise typer.BadParameter("Pippit 输出不是 JSON 对象")
    return parsed


def _stage_gte(current: str, minimum: str) -> bool:
    """当前阶段 >= 最低要求阶段时返回 True（允许从任意更高阶段重跑早期步骤）。"""
    return _STAGE_ORDER.get(current, 0) >= _STAGE_ORDER.get(minimum, 0)


def _filter_episodes_by_scene_range(episodes, scene_start: int | None, scene_end: int | None):
    if scene_start is None and scene_end is None:
        return episodes

    filtered = []
    for ep in episodes:
        scenes = ep.scenes
        if scene_start is not None:
            scenes = [s for s in scenes if s.idx >= scene_start]
        if scene_end is not None:
            scenes = [s for s in scenes if s.idx <= scene_end]
        filtered.append(ep.model_copy(update={"scenes": scenes}))
    return filtered


def _resolve_work_id(work_id: str | None = None) -> str:
    if work_id:
        matches = [w for w in store.list_works() if w.id == work_id or w.id.startswith(work_id) or w.title == work_id]
        if len(matches) == 1:
            return matches[0].id
        if len(matches) > 1:
            console.print(f"[yellow]匹配到多个作品，请使用完整 ID: {work_id}[/yellow]")
            raise typer.Exit(1)
        console.print(f"[red]作品不存在: {work_id}[/red]")
        raise typer.Exit(1)
    active = store.get_active_work_id()
    if active:
        return active
    works = store.list_works()
    if not works:
        console.print("[red]没有作品，请先运行: manga init <标题>[/red]")
        raise typer.Exit(1)
    store.set_active_work_id(works[0].id)
    return works[0].id


@app.command()
def init(title: str):
    """创建作品目录与 M0 基础文件。"""

    meta = store.create_work(title)
    console.print(Panel(f"{meta.title}\n{meta.id}", title="OK", border_style="green"))


@app.command("use")
def use_work(work_id: str):
    """切换当前活动作品。"""

    resolved = _resolve_work_id(work_id)
    store.set_active_work_id(resolved)
    meta = store.get_work(resolved)
    console.print(f"[green]当前作品: {meta.title} ({meta.id})[/green]")


@app.command("list")
def list_works():
    """列出作品。"""

    works = store.list_works()
    if not works:
        console.print("[yellow]暂无作品[/yellow]")
        return
    active = store.get_active_work_id()
    table = Table(title="作品列表")
    table.add_column("", width=2)
    table.add_column("ID", style="cyan")
    table.add_column("标题", style="bold")
    table.add_column("状态")
    table.add_column("创建时间")
    for work in works:
        table.add_row("*" if work.id == active else "", work.id, work.title, work.status, work.created_at)
    console.print(table)


@app.command()
def info(work_id: str = typer.Option(None, "--work", "-w", help="作品 ID/标题，默认当前作品")):
    """查看作品概况。"""

    resolved = _resolve_work_id(work_id)
    meta = store.get_work(resolved)
    episodes = store.load_episodes(resolved)
    scenes = sum(len(ep.scenes) for ep in episodes)
    shots = store.load_shots(resolved)
    entities = store.load_entities(resolved)
    console.print(
        Panel(
            "\n".join(
                [
                    f"标题: {meta.title}",
                    f"ID: {meta.id}",
                    f"状态: {meta.status}",
                    f"原文字数: {meta.source_meta.get('chars', 0)}",
                    f"分集/场景/镜头: {len(episodes)} / {scenes} / {len(shots)}",
                    f"实体: {len(entities)}",
                ]
            ),
            title="作品信息",
        )
    )


@app.command("log")
def show_log(
    n: int = typer.Option(30, help="显示最近 N 条"),
    work_id: str = typer.Option(None, "--work", "-w", help="作品 ID/标题，默认当前作品"),
):
    """查看操作日志。"""

    resolved = _resolve_work_id(work_id)
    records = store.load_operations(resolved, limit=n)
    if not records:
        console.print("[yellow]暂无操作日志[/yellow]")
        return
    table = Table(title="操作日志")
    table.add_column("时间", style="cyan")
    table.add_column("命令", style="bold")
    table.add_column("详情")
    for record in records:
        table.add_row(record.time, record.command, record.detail)
    console.print(table)


@app.command()
def validate(
    work_id: str = typer.Option(None, "--work", "-w", help="作品 ID/标题，默认当前作品"),
    fix_index: bool = typer.Option(False, "--fix-index", help="index.json 不一致时重建索引"),
):
    """校验结构化 JSON schema 与 index.json 一致性。"""

    resolved = _resolve_work_id(work_id)
    report = store.validate_work(resolved, fix_index=fix_index)
    if report.ok:
        console.print(f"[green]OK[/green] {resolved}")
        return
    table = Table(title="校验问题")
    table.add_column("级别", style="red")
    table.add_column("路径")
    table.add_column("问题")
    for issue in report.issues:
        table.add_row(issue.severity, issue.path, issue.message)
    console.print(table)
    raise typer.Exit(1)


@source_app.command("import")
def import_source(
    file: str,
    work_id: str = typer.Option(None, "--work", "-w", help="作品 ID/标题，默认当前作品"),
):
    """导入原文到 source.txt（唯一原文副本）。"""

    resolved = _resolve_work_id(work_id)
    meta = store.import_source(resolved, Path(file))
    console.print(f"[green]已导入[/green] {meta.source_meta.get('chars', 0):,} 字 -> {resolved}/source.txt")


@app.command()
def segment(
    work_id: str = typer.Option(None, "--work", "-w", help="作品 ID/标题，默认当前作品"),
    episodes: int = typer.Option(12, "--episodes", "-n", help="目标集数（软约束，LLM 参考）"),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过人工确认，直接写入"),
):
    """S1 切分：调用 LLM 识别集/场景切点，Python 精确切分，人工确认后写入。

    这是人工检查点①：预览结果后按 y 确认写入，按 n 放弃。
    """
    from manga_manager.agents.segmenter import SegmenterError
    from manga_manager.pipeline.s1_segment import run_s1

    resolved = _resolve_work_id(work_id)
    meta = store.get_work(resolved)
    console.print(f"[bold]S1 切分[/bold] — 作品: {meta.title} ({meta.id})")
    console.print(f"目标集数: {episodes}，正在调用 LLM...\n")

    try:
        result = run_s1(resolved, target_episodes=episodes)
    except SegmenterError as exc:
        console.print(f"[red]切分失败: {exc}[/red]")
        raise typer.Exit(1)

    # ── 空结果保护 ────────────────────────────────────────────────────────
    if not result.episodes:
        console.print("[red]切分结果为空（LLM 未返回有效集数据），已中止，未写入任何数据。[/red]")
        raise typer.Exit(1)

    # ── 预览 ──────────────────────────────────────────────────────────────
    table = Table(title="切分预览", show_lines=True)
    table.add_column("集", style="cyan", width=4)
    table.add_column("标题", style="bold")
    table.add_column("场景数", justify="right")
    table.add_column("字数", justify="right")
    table.add_column("首场景摘要")
    for ep in result.episodes:
        ep_chars = (ep.raw_span.end - ep.raw_span.start) if ep.raw_span else 0
        first_summary = ep.scenes[0].summary[:30] if ep.scenes else "—"
        table.add_row(str(ep.idx), ep.title, str(len(ep.scenes)), str(ep_chars), first_summary)
    console.print(table)

    # ── L1 校验结果 ───────────────────────────────────────────────────────
    if result.ok:
        console.print("[green]L1 校验通过[/green]")
    else:
        console.print("[yellow]L1 校验发现问题（仍可手动确认写入）：[/yellow]")
        for issue in result.report.issues:
            console.print(f"  [{issue.severity}] {issue.path}: {issue.message}")

    # ── 人工检查点①（interrupt 等价，CLI 确认） ────────────────────────────
    # --yes 模式下，error 级 L1 问题仍不可绕过（warning 级允许穿透）
    if yes and not result.ok:
        error_issues = [i for i in result.report.issues if i.severity == "error"]
        if error_issues:
            console.print("[red]L1 存在 error 级问题，--yes 不可跳过，请修复切分结果后重试：[/red]")
            for issue in error_issues:
                console.print(f"  [red][error][/red] {issue.path}: {issue.message}")
            raise typer.Exit(1)

    if not yes:
        confirm = typer.confirm("\n确认写入？(y=写入, n=放弃)", default=False)
        if not confirm:
            console.print("[yellow]已放弃，未写入。[/yellow]")
            raise typer.Exit(0)

    store.save_episodes(resolved, result.episodes)
    store.log_operation(resolved, "s1.human_approved", f"{len(result.episodes)} episodes confirmed")
    console.print(
        Panel(
            f"已写入 {len(result.episodes)} 集 / {sum(len(ep.scenes) for ep in result.episodes)} 场景",
            title="OK",
            border_style="green",
        )
    )


@app.command()
def bible(
    work_id: str = typer.Option(None, "--work", "-w", help="作品 ID/标题，默认当前作品"),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过人工检查点②，直接写入"),
    workers: int = typer.Option(4, "--workers", "-j", help="并发 LLM 调用数（默认 4）"),
):
    """S2 设定库提取：逐场景从原文中提取人物/地点/道具实体及关系。

    这是人工检查点②：预览设定库后按 y 确认，按 n 放弃（数据不写回 final state）。
    集内场景并行调 LLM，合并阶段串行（保证去重正确性）。
    """
    from manga_manager.agents.bible_builder import BibleBuilderError
    from manga_manager.models import RunState
    from manga_manager.pipeline.s2_bible import run_s2

    resolved = _resolve_work_id(work_id)
    meta = store.get_work(resolved)

    episodes = store.load_episodes(resolved)
    total_scenes = sum(len(ep.scenes) for ep in episodes)
    if total_scenes == 0:
        console.print("[red]尚无分集数据，请先运行: manga segment[/red]")
        raise typer.Exit(1)

    existing_entities = store.load_entities(resolved)
    root = store.work_dir(resolved)
    rs = store.read_model(root / "run_state.json", RunState)
    done_count = len(rs.cursor.get("done_scenes") or [])
    remaining = total_scenes - done_count

    console.print(
        Panel(
            f"{meta.title} ({meta.id})\n"
            f"场景: {total_scenes}"
            + (f"（已处理 {done_count}，待处理 {remaining}）" if done_count else "")
            + f"\n实体: {len(existing_entities)} | 并发: {workers}",
            title="S2 设定库提取",
            border_style="cyan",
        )
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
    ) as progress:
        task = progress.add_task("提取实体…", total=total_scenes)
        if done_count:
            progress.update(task, completed=done_count)

        def _cb(done: int, total: int, scene_id: str) -> None:
            progress.update(task, completed=done)

        try:
            result = run_s2(
                resolved,
                max_workers=max(1, workers),
                on_scene_progress=_cb,
                resume=True,
            )
        except BibleBuilderError as exc:
            console.print(f"[red]设定提取失败: {exc}[/red]")
            raise typer.Exit(1)

    if result.stats.errors:
        console.print(f"[yellow]处理中有 {len(result.stats.errors)} 个场景出错：[/yellow]")
        for scene_id, msg in result.stats.errors[:10]:
            console.print(f"  {scene_id}: {msg}")

    entities = result.entities
    chars = [e for e in entities if e.type == "character"]
    locs = [e for e in entities if e.type == "location"]
    props = [e for e in entities if e.type == "prop"]
    major = [e for e in entities if e.importance == "major"]

    table = Table(title="设定库摘要")
    table.add_column("类型", style="cyan")
    table.add_column("总数", justify="right")
    table.add_row("人物", str(len(chars)))
    table.add_row("地点", str(len(locs)))
    table.add_row("道具", str(len(props)))
    table.add_row("合计", str(len(entities)))
    table.add_row("核心实体", f"{len(major)} / {len(entities)}")
    table.add_row("关系", str(len(result.relations)))
    console.print(table)

    if major:
        console.print("\n[bold]核心实体（major）:[/bold]")
        for ent in major[:30]:
            aliases_str = f"[{', '.join(ent.aliases[:4])}]" if ent.aliases else ""
            console.print(f"  {ent.id} | {ent.name} {aliases_str} | {ent.type}")
        if len(major) > 30:
            console.print(f"  ...（共 {len(major)} 个，仅展示前 30 个）")

    if result.ok:
        console.print("\n[green]S2 完成，数据已按集写入 entities/ 与 index.json[/green]")
    else:
        console.print("\n[yellow]S2 完成（存在错误），数据已写入[/yellow]")

    if not yes:
        console.print(
            "\n[bold cyan]人工检查点②[/bold cyan] "
            "请打开 data/works/" + resolved + "/entities/ 查看设定库。\n"
            "确认无误后按 y 标记为 approved，按 n 放弃本次运行。"
        )
        confirm = typer.confirm("确认设定库？", default=False)
        if confirm:
            store.log_operation(resolved, "s2.human_approved", f"{len(entities)} entities, {len(result.relations)} relations")
            console.print("[green]设定库已 confirmed（human_approved）[/green]")
        else:
            console.print("[yellow]用户放弃（数据已按集写入磁盘，可手动回退）[/yellow]")


@app.command()
def bind(
    entity_id: str,
    variant_label: str,
    image_path: Path,
    work_id: str = typer.Option(None, "--work", "-w", help="作品 ID/标题，默认当前作品"),
):
    """绑定参考图片到实体的某个变体。

    示例: manga bind e001 "幼年哥哥" ~/ref_images/child_brother.png
    """
    resolved = _resolve_work_id(work_id)

    if not image_path.exists():
        console.print(f"[red]图片文件不存在: {image_path}[/red]")
        raise typer.Exit(1)

    try:
        entity = store.bind_ref_image(resolved, entity_id, variant_label, image_path)
        console.print(
            Panel(
                f"实体: {entity.name} ({entity.id})\n"
                f"变体: {variant_label}\n"
                f"资产数: {len(entity.variants)}",
                title="绑定成功",
                border_style="green",
            )
        )
    except ValueError as exc:
        console.print(f"[red]绑定失败: {exc}[/red]")
        raise typer.Exit(1)


@app.command("bind-media")
def bind_media(
    entity_id: str,
    variant_label: str,
    media_path: Path,
    kind: str = typer.Option(..., "--kind", help="媒体类型: image/audio/video"),
    work_id: str = typer.Option(None, "--work", "-w", help="作品 ID/标题，默认当前作品"),
):
    """绑定图片/音频/视频到实体的某个变体。

    示例: manga bind-media e001 "幼年哥哥" ref.wav --kind audio
    """
    resolved = _resolve_work_id(work_id)

    try:
        entity = store.bind_ref_media(resolved, entity_id, variant_label, media_path, kind)
        console.print(
            Panel(
                f"实体: {entity.name} ({entity.id})\n"
                f"变体: {variant_label}\n"
                f"类型: {kind}\n"
                f"资产数: {len(entity.variants)}",
                title="媒体绑定成功",
                border_style="green",
            )
        )
    except ValueError as exc:
        console.print(f"[red]媒体绑定失败: {exc}[/red]")
        raise typer.Exit(1)


@app.command()
def assets(
    entity_id: str,
    work_id: str = typer.Option(None, "--work", "-w", help="作品 ID/标题，默认当前作品"),
):
    """列出实体的资产文件。

    示例: manga assets e001
    """
    resolved = _resolve_work_id(work_id)
    entities = store.load_entities(resolved)

    target = None
    for ent in entities:
        if ent.id == entity_id:
            target = ent
            break

    if not target:
        console.print(f"[red]实体不存在: {entity_id}[/red]")
        raise typer.Exit(1)

    asset_map = store.load_entity_assets(resolved, entity_id)
    media_map = store.load_entity_media(resolved, entity_id)

    if not asset_map and not target.variants:
        console.print(f"[yellow]{target.name} 无变体、无绑定资产[/yellow]")
        return

    console.print(
        Panel(
            f"实体: {target.name} ({target.id})\n类型: {target.type}",
            title="资产列表",
            border_style="cyan",
        )
    )

    if target.variants:
        table = Table(title="变体")
        table.add_column("标签", style="bold")
        table.add_column("时间", style="dim")
        table.add_column("外观", max_width=50)
        table.add_column("图片", justify="right")
        table.add_column("音频", justify="right")
        table.add_column("视频", justify="right")

        for v in target.variants:
            table.add_row(
                v.label,
                v.time_desc or "-",
                v.appearance[:50] if v.appearance else "-",
                str(len(v.ref_images)),
                str(len(v.ref_audios)),
                str(len(v.ref_videos)),
            )
        console.print(table)

    if media_map:
        console.print("\n[bold]媒体资产:[/bold]")
        for kind, by_variant in media_map.items():
            label = {"image": "图片", "audio": "音频", "video": "视频"}[kind]
            if not by_variant:
                continue
            console.print(f"  [cyan]{label}[/cyan]")
            for variant_label, paths in by_variant.items():
                console.print(f"    {variant_label}:")
                for p in paths:
                    console.print(f"      {p}")


def _pippit_executable() -> str:
    executable = shutil.which("pippit-tool-cli")
    if not executable:
        raise RuntimeError("未找到 pippit-tool-cli；请先安装 @pippit-dev/cli")
    return executable


def _run_pippit(args: list[str]) -> tuple[int, str, str]:
    completed = subprocess.run(
        [_pippit_executable(), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode, completed.stdout, completed.stderr


def _pippit_generate_video(args: list[str]) -> _PippitRun:
    code, stdout, stderr = _run_pippit(args)
    if code != 0:
        console.print(f"[red]Pippit 提交失败（exit {code}）[/red]")
        if stderr.strip():
            console.print(stderr.strip())
        raise typer.Exit(code)

    data = _parse_pippit_json(stdout, stderr)
    thread_id = str(data.get("thread_id") or "").strip()
    run_id = str(data.get("run_id") or "").strip()
    if not thread_id or not run_id:
        raise typer.BadParameter(f"Pippit 输出缺少 thread_id/run_id: {data}")

    return _PippitRun(
        thread_id=thread_id,
        run_id=run_id,
        web_thread_link=str(data.get("web_thread_link") or ""),
    )


def _pippit_query_result(thread_id: str, run_id: str, download_dir: Path) -> dict[str, object]:
    args = [
        "query-result",
        "--thread-id",
        thread_id,
        "--run-id",
        run_id,
        "--download-dir",
        str(download_dir),
    ]
    code, stdout, stderr = _run_pippit(args)
    try:
        data = _parse_pippit_json(stdout, stderr)
    except typer.BadParameter:
        if stderr.strip():
            console.print(stderr.strip())
        raise typer.Exit(code or 1)
    if code != 0:
        error_message = data.get("error_message") or stderr.strip()
        console.print(f"[red]Pippit 查询失败（exit {code}）[/red]")
        if error_message:
            console.print(error_message)
        raise typer.Exit(code)
    return data


def _write_pippit_run_record(
    work_id: str,
    scene_id: str,
    prompt_file: Path,
    prompt: str,
    bundle: store.SceneMediaBundle,
    command: list[str],
    run: _PippitRun,
    query_result: dict[str, object] | None,
    output_dir: Path,
) -> Path:
    record_dir = store.work_dir(work_id) / "pippit_runs"
    record_path = record_dir / f"{scene_id}.json"
    store.write_json_atomic(
        record_path,
        {
            "scene_id": scene_id,
            "prompt_file": str(prompt_file),
            "prompt_chars": len(prompt),
            "media_counts": bundle.counts(),
            "skipped": bundle.skipped,
            "command": command,
            "run": asdict(run),
            "query_result": query_result or {},
            "output_dir": str(output_dir),
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        },
    )
    return record_path


@app.command("pippit-video")
def pippit_video(
    scene_id: str,
    prompt: str | None = typer.Option(None, "--prompt", help="覆盖 prompt 文件内容"),
    prompt_file: Path | None = typer.Option(None, "--prompt-file", "-p", help="默认读取 video_prompts/{scene_id}.txt"),
    work_id: str = typer.Option(None, "--work", "-w", help="作品 ID/标题，默认当前作品"),
    output_dir: Path | None = typer.Option(
        None,
        "--output-dir",
        "-o",
        help="默认写入 data/works/{work_id}/generated_videos/{scene_id}",
    ),
    duration: int | None = typer.Option(None, "--duration", help="Pippit 视频时长秒数"),
    ratio: str = typer.Option("9:16", "--ratio", help="视频比例"),
    model: str = typer.Option("Seedance_2.0_mini_lite", "--model", help="Pippit 视频模型"),
    resolution: str = typer.Option("720p", "--resolution", help="Pippit 视频分辨率"),
    poll_interval: float = typer.Option(15.0, "--poll-interval", help="查询完成状态间隔秒数"),
    timeout: float = typer.Option(3600.0, "--timeout", help="最长等待秒数"),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过确认直接提交 Pippit"),
    dry_run: bool = typer.Option(False, "--dry-run", help="只打印将传给 Pippit 的参数，不提交"),
    download: bool = typer.Option(True, "--download/--no-download", help="提交后轮询并下载结果"),
    include_images: bool = typer.Option(True, "--include-images/--no-images", help="携带场景实体参考图片"),
    include_audios: bool = typer.Option(True, "--include-audios/--no-audios", help="携带场景实体参考音频"),
    include_videos: bool = typer.Option(True, "--include-videos/--no-videos", help="携带场景实体参考视频"),
):
    """用 Pippit 根据场景提示词和实体媒体资产生成视频。

    会先从 bindings/{scene_id}.json 找到场景实体变体，再收集实体变体上的
    ref_images/ref_audios/ref_videos，传给 pippit-tool-cli generate-video。
    """
    resolved = _resolve_work_id(work_id)
    root = store.work_dir(resolved)

    if prompt_file is None:
        prompt_file = root / "video_prompts" / f"{scene_id}.txt"
    else:
        prompt_file = prompt_file.expanduser()

    if prompt is None:
        if not prompt_file.exists():
            console.print(f"[red]提示词文件不存在: {prompt_file}[/red]")
            raise typer.Exit(1)
        prompt = prompt_file.read_text(encoding="utf-8").strip()

    if not prompt:
        console.print("[red]Pippit prompt 不能为空[/red]")
        raise typer.Exit(1)

    bundle = store.collect_scene_media(resolved, scene_id)
    images = bundle.images if include_images else []
    audios = bundle.audios if include_audios else []
    videos = bundle.videos if include_videos else []

    args = ["generate-video", "--prompt", prompt]
    for path in images:
        args.extend(["--image", str(path)])
    for path in videos:
        args.extend(["--video", str(path)])
    for path in audios:
        args.extend(["--audio", str(path)])
    if duration is not None:
        args.extend(["--duration", str(duration)])
    args.extend(["--ratio", ratio, "--model", model, "--resolution", resolution])

    console.print(
        Panel(
            f"场景: {scene_id}\n"
            f"图片: {len(images)} / 9\n"
            f"视频: {len(videos)} / 3\n"
            f"音频: {len(audios)} / 3\n"
            f"提示词: {prompt_file}",
            title="Pippit 生视频",
            border_style="cyan",
        )
    )

    if bundle.skipped:
        console.print("[yellow]媒体跳过项:[/yellow]")
        for item in bundle.skipped[:20]:
            console.print(f"  - {item}")
        if len(bundle.skipped) > 20:
            console.print(f"  ...还有 {len(bundle.skipped) - 20} 条")

    if dry_run:
        console.print("[yellow]Dry run：未提交 Pippit[/yellow]")
        executable = shutil.which("pippit-tool-cli") or "pippit-tool-cli"
        console.print("命令:")
        console.print(" ".join([executable, *args]))
        return

    if not yes:
        confirm = typer.confirm("确认提交到 Pippit？该操作可能产生 API 调用费用。", default=False)
        if not confirm:
            console.print("[yellow]已取消，未提交 Pippit。[/yellow]")
            raise typer.Exit(0)

    run = _pippit_generate_video(args)
    output_dir = (output_dir.expanduser() if output_dir else root / "generated_videos" / scene_id)
    output_dir.mkdir(parents=True, exist_ok=True)

    query_result: dict[str, object] | None = None
    if download:
        deadline = time.monotonic() + timeout
        while True:
            query_result = _pippit_query_result(run.thread_id, run.run_id, output_dir)
            if query_result.get("completed") is True:
                break
            if time.monotonic() >= deadline:
                console.print(f"[red]等待 Pippit 结果超时（{timeout} 秒）[/red]")
                console.print(f"thread_id: {run.thread_id}")
                console.print(f"run_id: {run.run_id}")
                raise typer.Exit(2)
            console.print(f"[yellow]Pippit 仍在运行，{poll_interval} 秒后重试...[/yellow]")
            time.sleep(poll_interval)

    record_path = _write_pippit_run_record(
        resolved,
        scene_id,
        prompt_file,
        prompt,
        bundle,
        args,
        run,
        query_result,
        output_dir,
    )
    store.log_operation(
        resolved,
        "pippit.generate_video",
        detail=f"scene={scene_id}, thread={run.thread_id}, run={run.run_id}",
    )

    if run.web_thread_link:
        console.print(f"Web thread: {run.web_thread_link}")
    console.print(f"Run 记录: {record_path}")

    if query_result:
        error_message = query_result.get("error_message")
        if error_message:
            console.print(f"[red]Pippit 结果失败: {error_message}[/red]")
            raise typer.Exit(1)
        videos_result = query_result.get("videos") or []
        if videos_result:
            console.print("[green]视频已下载:[/green]")
            for video in videos_result:
                if isinstance(video, dict):
                    console.print(f"  - {video.get('output_path')}")
        else:
            console.print("[yellow]Pippit 已完成，但未返回可下载视频。[/yellow]")


app.add_typer(source_app, name="source")


@app.command()
def summary(
    work_id: str = typer.Option(None, "--work", "-w", help="作品 ID/标题，默认当前作品"),
    refresh: bool = typer.Option(False, "--refresh", "-r", help="重新生成，忽略已有摘要"),
):
    """S3 滚动摘要：为每集生成 episode_summary + rolling_summary（前情提要）。

    逐集顺序处理，每集完成即 checkpoint；断点续跑自动跳过已处理集。
    rolling_summary 供下游 S4/S5/S6 作为剧情上下文，压缩 token 开销。
    """
    from manga_manager.agents.summarizer import SummarizerError
    from manga_manager.models import RunState
    from manga_manager.pipeline.s3_summary import run_s3

    resolved = _resolve_work_id(work_id)
    meta = store.get_work(resolved)

    episodes = store.load_episodes(resolved)
    if not episodes:
        console.print("[red]尚无分集数据，请先运行: manga segment[/red]")
        raise typer.Exit(1)

    existing_summaries = store.load_summaries(resolved)
    done_count = len(existing_summaries)
    total = len(episodes)
    remaining = total - (done_count if not refresh else 0)

    root = store.work_dir(resolved)
    rs = store.read_model(root / "run_state.json", RunState)

    if refresh and existing_summaries:
        console.print("[yellow]--refresh 模式：将重新生成所有集摘要[/yellow]")
        for s in existing_summaries:
            summary_path = root / "summaries" / f"{s.episode_idx:04d}.json"
            summary_path.unlink(missing_ok=True)
        done_count = 0
        remaining = total

    console.print(
        Panel(
            f"{meta.title} ({meta.id})\n"
            f"集数: {total}"
            + (f"（已处理 {done_count}，待处理 {remaining}）" if done_count else "")
            + "\n当前阶段: " + rs.stage,
            title="S3 滚动摘要",
            border_style="cyan",
        )
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
    ) as progress:
        task_widget = progress.add_task("生成摘要…", total=total)
        if done_count:
            progress.update(task_widget, completed=done_count)

        def _cb(done: int, t: int, ep_idx: int) -> None:
            progress.update(task_widget, completed=done)

        try:
            result = run_s3(
                resolved,
                on_episode_progress=_cb,
                resume=not refresh,
            )
        except SummarizerError as exc:
            console.print(f"[red]摘要生成失败: {exc}[/red]")
            raise typer.Exit(1)

    if result.stats.errors:
        console.print(f"[yellow]处理中有 {len(result.stats.errors)} 集出错：[/yellow]")
        for ep_idx, msg in result.stats.errors:
            console.print(f"  第 {ep_idx} 集: {msg}")

    table = Table(title="摘要情况")
    table.add_column("集", style="cyan", justify="right")
    table.add_column("episode_summary", justify="right")
    table.add_column("rolling_summary", justify="right")
    table.add_column("token 估算", justify="right")

    for s in sorted(result.summaries, key=lambda x: x.episode_idx):
        table.add_row(
            str(s.episode_idx),
            str(len(s.episode_summary)),
            str(len(s.rolling_summary)),
            f"~{s.token_estimate}",
        )
    console.print(table)

    if result.ok:
        console.print("[green]S3 完成，所有集摘要已写入 summaries/[/green]")
    else:
        console.print("[yellow]S3 完成（存在错误），部分摘要未生成[/yellow]")


@app.command()
def screenplay(
    work_id: str = typer.Option(None, "--work", "-w", help="作品 ID/标题，默认当前作品"),
    workers: int = typer.Option(4, "--workers", "-j", help="集内并L场景数（默认 4）"),
):
    """S4 编剧/分镜：从场景生成 Shot 列表（叙事层：景别/动作/情绪/对话）。

    集内场景并行调 LLM，反思环最多 2 轮修订。
    断点续跑：跳过已有 shots 文件的场景。
    """
    from manga_manager.agents.screenwriter import ScreenwriterError
    from manga_manager.models import RunState
    from manga_manager.pipeline.s4_screenplay import run_s4

    resolved = _resolve_work_id(work_id)
    meta = store.get_work(resolved)

    episodes = store.load_episodes(resolved)
    if not episodes:
        console.print("[red]尚无分集数据，请先运行: manga segment[/red]")
        raise typer.Exit(1)

    root = store.work_dir(resolved)
    rs = store.read_model(root / "run_state.json", RunState)
    if not _stage_gte(rs.stage, "M3"):
        console.print("[red]S3 尚未完成，请先运行: manga summary[/red]")
        raise typer.Exit(1)

    total_scenes = sum(len(ep.scenes) for ep in episodes)
    done_screenplay = len(rs.cursor.get("done_screenplay_scenes") or [])
    remaining = total_scenes - done_screenplay

    existing_shots = store.load_shots(resolved)

    console.print(
        Panel(
            f"{meta.title} ({meta.id})\n"
            f"场景: {total_scenes}"
            + (f"（已处理 {done_screenplay}，待处理 {remaining}）" if done_screenplay else "")
            + f"\n已有镜头: {len(existing_shots)} | 并发: {workers}",
            title="S4 编剧/分镜",
            border_style="cyan",
        )
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
    ) as progress:
        task = progress.add_task("生成镜头…", total=total_scenes)
        if done_screenplay:
            progress.update(task, completed=done_screenplay)

        def _cb(done: int, total: int, scene_id: str) -> None:
            progress.update(task, completed=done)

        try:
            result = run_s4(
                resolved,
                max_workers=max(1, workers),
                on_scene_progress=_cb,
                resume=True,
            )
        except ScreenwriterError as exc:
            console.print(f"[red]编剧失败: {exc}[/red]")
            raise typer.Exit(1)

    if result.stats.errors:
        console.print(f"[yellow]{len(result.stats.errors)} 个场景出错：[/yellow]")
        for scene_id, msg in result.stats.errors[:10]:
            console.print(f"  {scene_id}: {msg}")

    table = Table(title="S4 结果")
    table.add_column("指标", style="cyan")
    table.add_column("值", justify="right")
    table.add_row("处理场景", f"{result.stats.scenes_processed}/{result.stats.total_scenes}")
    table.add_row("新建镜头", str(result.stats.shots_created))
    table.add_row("错误", str(len(result.stats.errors)))
    table.add_row("镜头总数", str(result.stats.final_shot_count))
    console.print(table)

    if result.ok:
        console.print("[green]S4 完成，所有场景镜头已写入 shots/[/green]")
    else:
        console.print("[yellow]S4 完成（存在错误）[/yellow]")


@app.command()
def continuity(
    work_id: str = typer.Option(None, "--work", "-w", help="作品 ID/标题，默认当前作品"),
):
    """S5 角色/实体绑定：把 Shot.characters 解析为 entity_id + variant_label。

    纯确定性流程，无 LLM 调用。按场景处理，断点续跑。
    完成后做跨场景一致性检查并报告 issues。
    """
    from manga_manager.models import RunState
    from manga_manager.pipeline.s5_continuity import run_s5

    resolved = _resolve_work_id(work_id)
    meta = store.get_work(resolved)

    episodes = store.load_episodes(resolved)
    if not episodes:
        console.print("[red]尚无分集数据，请先运行: manga segment[/red]")
        raise typer.Exit(1)

    root = store.work_dir(resolved)
    rs = store.read_model(root / "run_state.json", RunState)
    if not _stage_gte(rs.stage, "M4"):
        console.print("[red]S4 尚未完成，请先运行: manga screenplay[/red]")
        raise typer.Exit(1)

    total_scenes = sum(len(ep.scenes) for ep in episodes)
    done_count = len(rs.cursor.get("done_binding_scenes") or [])
    remaining = total_scenes - done_count

    console.print(
        Panel(
            f"{meta.title} ({meta.id})\n"
            f"场景: {total_scenes}"
            + (f"（已处理 {done_count}，待处理 {remaining}）" if done_count else "")
            + f"\n当前阶段: {rs.stage}",
            title="S5 角色/实体绑定",
            border_style="cyan",
        )
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
    ) as progress:
        task = progress.add_task("绑定实体…", total=total_scenes)
        if done_count:
            progress.update(task, completed=done_count)

        def _cb(done: int, total: int, scene_id: str) -> None:
            progress.update(task, completed=done)

        try:
            result = run_s5(
                resolved,
                on_scene_progress=_cb,
                resume=True,
            )
        except Exception as exc:
            console.print(f"[red]绑定失败: {exc}[/red]")
            raise typer.Exit(1)

    if result.stats.errors:
        console.print(f"[yellow]{len(result.stats.errors)} 个场景解析失败：[/yellow]")
        for scene_id, msg in result.stats.errors[:10]:
            console.print(f"  {scene_id}: {msg}")

    table = Table(title="S5 结果")
    table.add_column("指标", style="cyan")
    table.add_column("值", justify="right")
    table.add_row("处理场景", f"{result.stats.scenes_processed}/{result.stats.total_scenes}")
    table.add_row("绑定镜头", str(result.stats.total_bindings))
    table.add_row("解析失败", str(len(result.stats.errors)))
    table.add_row("一致性 issues", str(len(result.stats.consistency_issues)))
    console.print(table)

    if result.stats.consistency_issues:
        console.print("\n[bold yellow]跨场景一致性 issues：[/bold yellow]")
        for issue in result.stats.consistency_issues[:10]:
            console.print(f"  ! {issue}")
        if len(result.stats.consistency_issues) > 10:
            console.print(f"  …还有 {len(result.stats.consistency_issues) - 10} 条")

    if result.ok:
        console.print("\n[green]S5 完成，所有场景绑定已写入 bindings/[/green]")
    else:
        console.print("\n[yellow]S5 完成（存在错误）[/yellow]")


@app.command("video-prompt")
def video_prompt(
    work_id: str = typer.Option(None, "--work", "-w"),
    episode: int = typer.Option(None, "--episode", "-e", help="只处理某一集（0-based）"),
    workers: int = typer.Option(4, "--workers", "-j"),
    limit: int = typer.Option(None, "--limit", "-n", help="最多生成 N 个场景（测试用）"),
    reset: bool = typer.Option(False, "--reset", help="忽略 S6 游标，重新生成/覆盖"),
    scene_start: int | None = typer.Option(
        None,
        "--from-scene",
        "--scene-start",
        help="只处理某集内场景起点（0-based，含；必须和 -e 一起使用）",
    ),
    scene_end: int | None = typer.Option(
        None,
        "--to-scene",
        "--scene-end",
        help="只处理某集内场景终点（0-based，含；必须和 -e 一起使用）",
    ),
):
    """S6 视频提示词：为每个场景生成三段式视频生成提示词，输出 video_prompts/{scene_id}.txt。

    系统提示词：src/manga_manager/agents/prompt_composer.py 的 _SYSTEM_PROMPT
    风格约束：config.toml [video_prompt] style_contract（改此处全局生效）
    """
    from manga_manager.pipeline.s6_prompt import run_s6

    resolved = _resolve_work_id(work_id)
    meta = store.get_work(resolved)
    episodes = store.load_episodes(resolved)
    if not episodes:
        console.print("[red]尚无分集数据，请先运行: manga segment[/red]")
        raise typer.Exit(1)

    if (scene_start is not None or scene_end is not None) and episode is None:
        console.print("[red]--from-scene/--to-scene 必须和 -e/--episode 一起使用[/red]")
        raise typer.Exit(1)

    if scene_start is not None and scene_start < 0:
        console.print("[red]--from-scene 不能小于 0[/red]")
        raise typer.Exit(1)
    if scene_end is not None and scene_end < 0:
        console.print("[red]--to-scene 不能小于 0[/red]")
        raise typer.Exit(1)
    if scene_start is not None and scene_end is not None and scene_start > scene_end:
        console.print("[red]--from-scene 不能大于 --to-scene[/red]")
        raise typer.Exit(1)

    target_eps = [ep for ep in episodes if ep.idx == episode] if episode is not None else episodes
    target_eps = _filter_episodes_by_scene_range(target_eps, scene_start, scene_end)
    if not target_eps or not sum(len(ep.scenes) for ep in target_eps):
        console.print("[red]筛选后没有可处理的场景[/red]")
        raise typer.Exit(1)

    total = sum(len(ep.scenes) for ep in target_eps)
    if limit is not None:
        total = min(total, limit)

    root = store.work_dir(resolved)
    done_ids = set()
    vp_dir = root / "video_prompts"
    if vp_dir.exists():
        done_ids = {p.stem for p in vp_dir.glob("*.txt")}
    done = sum(1 for ep in target_eps for s in ep.scenes if s.id in done_ids)

    console.print(
        Panel(
            f"{meta.title} ({resolved})\n"
            f"目标集: {'第'+str(episode)+'集' if episode is not None else '全集'} / "
            f"场景: {total}"
            + (f"（已生成 {done}，待处理 {total-done}）" if done else "")
            + (f"\n限制: 最多 {limit} 个场景" if limit is not None else ""),
            title="S6 视频提示词", border_style="cyan",
        )
    )

    with Progress(SpinnerColumn(), TextColumn("{task.description}"),
                  BarColumn(), TextColumn("{task.percentage:>3.0f}%"),
                  console=console) as progress:
        task = progress.add_task("生成提示词…", total=total)
        if done:
            progress.update(task, completed=done)

        def _cb(d: int, t: int, _sid: str) -> None:
            progress.update(task, completed=d)

        try:
            result = run_s6(
                resolved,
                target_episode_idx=episode,
                max_workers=max(1, workers),
                on_scene_progress=_cb,
                resume=True,
                limit=limit,
                reset=reset,
                scene_start=scene_start,
                scene_end=scene_end,
            )
        except Exception as exc:
            console.print(f"[red]生成失败: {exc}[/red]")
            raise typer.Exit(1)

    if result.stats.errors:
        console.print(f"[yellow]{len(result.stats.errors)} 个场景失败：[/yellow]")
        for sid, msg in result.stats.errors[:5]:
            console.print(f"  {sid}: {msg[:80]}")

    table = Table(title="S6 结果")
    table.add_column("指标", style="cyan")
    table.add_column("值", justify="right")
    table.add_row("处理场景", f"{result.stats.scenes_processed}/{result.stats.total_scenes}")
    table.add_row("生成段落", str(result.stats.total_segments))
    table.add_row("错误",     str(len(result.stats.errors)))
    console.print(table)

    if result.ok:
        console.print(f"[green]S6 完成，提示词已写入 data/works/{resolved}/video_prompts/[/green]")
    else:
        console.print("[yellow]S6 完成（存在错误）[/yellow]")


# ── 阶段元数据 ────────────────────────────────────────────────────────────────
_STAGE_META: dict[str, dict] = {
    "segment": {
        "alias": ["s1", "seg"],
        "dirs": ["episodes"],
        "cursor_keys": ["done_scenes"],
        "desc": "集/场景切分",
    },
    "bible": {
        "alias": ["s2"],
        "dirs": [],
        "files": [
            "entities/characters.json",
            "entities/locations.json",
            "entities/props.json",
            "entities/relations.json",
        ],
        "cursor_keys": ["done_scenes"],
        "desc": "设定库提取",
    },
    "summary": {
        "alias": ["s3"],
        "dirs": ["summaries"],
        "cursor_keys": ["done_episodes"],
        "desc": "滚动摘要",
    },
    "screenplay": {
        "alias": ["s4"],
        "dirs": ["shots"],
        "cursor_keys": ["done_screenplay_scenes"],
        "desc": "分镜剧本",
    },
    "continuity": {
        "alias": ["s5"],
        "dirs": ["bindings"],
        "cursor_keys": ["done_binding_scenes"],
        "desc": "角色绑定",
    },
    "video-prompt": {
        "alias": ["s6", "vp"],
        "dirs": ["video_prompts"],
        "cursor_keys": ["done_video_prompt_scenes"],
        "desc": "视频提示词",
    },
}


def _resolve_stage(name: str) -> tuple[str, dict]:
    """把别名/简写解析为规范名 + 元数据。"""
    key = name.lower()
    if key in _STAGE_META:
        return key, _STAGE_META[key]
    for canonical, meta in _STAGE_META.items():
        if key in meta.get("alias", []):
            return canonical, meta
    raise typer.BadParameter(f"未知阶段 '{name}'，可选: {', '.join(list(_STAGE_META.keys()))}")


@app.command()
def clear(
    stage: str = typer.Argument(help="要清空的阶段: segment/bible/summary/screenplay/continuity/video-prompt (可用别名 s1-s6)"),
    work_id: str = typer.Option(None, "--work", "-w"),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过确认直接执行"),
):
    """清空某阶段的输出文件并重置断点游标，以便重新生成。

    \b
    阶段别名:
      s1 / segment      集/场景切分
      s2 / bible        设定库提取
      s3 / summary      滚动摘要
      s4 / screenplay   分镜剧本
      s5 / continuity   角色绑定
      s6 / vp / video-prompt  视频提示词

    示例:
      manga clear s6           清空视频提示词（询问确认）
      manga clear s6 -y        直接清空，不询问
      manga clear s4 -e 0      清空第0集的分镜（尚未支持）
    """
    from manga_manager.models import RunState

    resolved = _resolve_work_id(work_id)
    canonical, meta = _resolve_stage(stage)
    root = store.work_dir(resolved)

    # 统计将要删除的文件
    to_delete: list[Path] = []
    for d in meta.get("dirs", []):
        target_dir = root / d
        if target_dir.exists():
            to_delete.extend(target_dir.iterdir())
    for f in meta.get("files", []):
        p = root / f
        if p.exists():
            to_delete.append(p)

    # 过滤掉子目录（只删文件）
    to_delete = [p for p in to_delete if p.is_file()]

    if not to_delete and not meta.get("cursor_keys"):
        console.print(f"[yellow]{meta['desc']} 没有可清空的输出[/yellow]")
        return

    # 预览
    console.print(
        Panel(
            f"阶段: [bold]{canonical}[/bold]（{meta['desc']}）\n"
            f"将删除文件: [red]{len(to_delete)} 个[/red]\n"
            f"将重置 cursor: {meta.get('cursor_keys', [])}",
            title="清空确认",
            border_style="red",
        )
    )

    if not yes:
        confirm = typer.confirm("确认清空？(y=执行, n=取消)", default=False)
        if not confirm:
            console.print("[yellow]已取消[/yellow]")
            raise typer.Exit(0)

    # 执行删除
    deleted = 0
    for p in to_delete:
        p.unlink(missing_ok=True)
        deleted += 1

    # 重置 cursor
    rs_path = root / "run_state.json"
    if rs_path.exists():
        rs = store.read_model(rs_path, RunState)
        for key in meta.get("cursor_keys", []):
            rs.cursor.pop(key, None)
        rs.updated_at = __import__("datetime").datetime.now().isoformat(timespec="seconds")
        store.write_json_atomic(rs_path, rs)

    store.log_operation(resolved, f"clear.{canonical}", f"deleted {deleted} files, reset cursor {meta.get('cursor_keys', [])}")

    console.print(
        Panel(
            f"已删除 [red]{deleted}[/red] 个文件\n"
            f"已重置 cursor: {meta.get('cursor_keys', [])}\n\n"
            f"重新生成: [bold]manga {canonical}[/bold]",
            title="清空完成",
            border_style="green",
        )
    )


if __name__ == "__main__":
    app()
